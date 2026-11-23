#!/usr/bin/env python3
"""The air between several r7 nodes running in GNU Radio, over ZMQ.

Stands in for the radio channel when no Plutos are attached. Each node
process (bpsk_zmq_node.py) publishes its TX samples and subscribes to its RX
samples; this process, paced by the wall clock at the sample rate:

  * plays every node's TX stream out at exactly fs (a DAC: a node that falls
    behind underflows and is padded with zeros, as a Pluto would);
  * gives every node the sum of the transmitters tuned to its RX frequency,
    each with its own carrier offset and gain, plus AWGN;
  * follows retuning: the node's stand-in Pluto blocks report every
    set_frequency() on the control socket, so hub election is real.

    python3 bpsk_zmq_air.py --nodes 3 --base 5600

Ports: node i (0-based) publishes TX on base+2i (this process subscribes),
and receives RX from base+2i+1 (this process publishes). Control: base-1.

Needs pyzmq and numpy only. A functional test, not a timing one.
"""

import argparse
import json
import random
import time

import numpy as np
import zmq


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--nodes', type=int, default=3)
    ap.add_argument('--base', type=int, default=5600)
    ap.add_argument('--fs', type=float, default=1e6)
    ap.add_argument('--chunk', type=int, default=4096)
    ap.add_argument('--noise', type=float, default=0.02,
                    help='AWGN amplitude at each receiver (signal peak ~0.7)')
    ap.add_argument('--cfo', type=float, default=3000.0,
                    help='each node LO offset uniform in +-cfo Hz')
    ap.add_argument('--prebuffer', type=int, default=16384,
                    help='TX samples a node must have queued before it is '
                         'played (the DAC buffer)')
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    nrng = np.random.default_rng(args.seed)
    ctx = zmq.Context()
    ctl = ctx.socket(zmq.PULL)
    ctl.bind('tcp://127.0.0.1:%d' % (args.base - 1))
    subs, pubs = [], []
    for i in range(args.nodes):
        s = ctx.socket(zmq.SUB)
        s.setsockopt(zmq.SUBSCRIBE, b'')
        s.connect('tcp://127.0.0.1:%d' % (args.base + 2 * i))
        subs.append(s)
        p = ctx.socket(zmq.PUB)
        p.bind('tcp://127.0.0.1:%d' % (args.base + 2 * i + 1))
        pubs.append(p)
    n = args.nodes
    fifo = [[] for _ in range(n)]
    fifo_len = [0] * n
    playing = [False] * n
    f_tx = [None] * n
    f_rx = [None] * n
    cfo = [rng.uniform(-args.cfo, args.cfo) for _ in range(n)]
    under = [0] * n
    N = args.chunk
    t_idx = 0
    start = time.time()
    last_report = start
    print('[air] %d nodes, chunk %d, noise %.3f, LO offsets %s Hz'
          % (n, N, args.noise, [round(c) for c in cfo]), flush=True)

    def take(i):
        """Next N samples node i puts on the air (zeros if it underflows)."""
        if not playing[i]:
            if fifo_len[i] >= args.prebuffer:
                playing[i] = True
            else:
                return None
        if fifo_len[i] < N:
            under[i] += 1
            playing[i] = False
            return None
        out = np.empty(N, np.complex64)
        k = 0
        while k < N:
            head = fifo[i][0]
            m = min(N - k, len(head))
            out[k:k + m] = head[:m]
            k += m
            if m == len(head):
                fifo[i].pop(0)
            else:
                fifo[i][0] = head[m:]
        fifo_len[i] -= N
        return out

    while True:
        while True:
            try:
                msg = json.loads(ctl.recv(zmq.NOBLOCK).decode())
            except zmq.Again:
                break
            i = int(msg['id'])
            if 'tx' in msg:
                f_tx[i] = float(msg['tx'])
            if 'rx' in msg:
                f_rx[i] = float(msg['rx'])
            print('[air] %.2f s: node %d tuned TX %s RX %s'
                  % (t_idx / args.fs, i, f_tx[i], f_rx[i]),
                  flush=True)
        for i, s in enumerate(subs):
            while True:
                try:
                    raw = s.recv(zmq.NOBLOCK)
                except zmq.Again:
                    break
                a = np.frombuffer(raw, np.complex64)
                fifo[i].append(a)
                fifo_len[i] += len(a)
        # pace to the wall clock
        due = start + (t_idx + N) / args.fs
        lag = due - time.time()
        if lag > 0:
            time.sleep(lag)
        tx = [take(i) for i in range(n)]
        t = (t_idx + np.arange(N)) / args.fs
        for i in range(n):
            x = (args.noise / np.sqrt(2)) * (nrng.standard_normal(N)
                                             + 1j * nrng.standard_normal(N))
            x = x.astype(np.complex64)
            for j in range(n):
                if j == i or tx[j] is None or f_tx[j] is None:
                    continue
                if f_tx[j] != f_rx[i]:
                    continue
                x += tx[j] * np.exp(2j * np.pi * (cfo[j] - cfo[i]) * t
                                    ).astype(np.complex64)
            pubs[i].send(x.astype(np.complex64).tobytes())
        t_idx += N
        now = time.time()
        if now - last_report > 10:
            last_report = now
            print('[air] t=%.0f s  lag %.0f ms  queued %s  underflows %s'
                  % (t_idx / args.fs, (now - start - t_idx / args.fs) * 1e3,
                     fifo_len, under), flush=True)


if __name__ == '__main__':
    main()
