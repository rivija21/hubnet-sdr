#!/usr/bin/env python3
"""Run the generated r7 flowgraph (bpsk_mac_pluto.py) with no radio.

bpsk_zmq_node.py runs the node block in a minimal headless flowgraph. This
runs the real GRC-generated flowgraph - Qt sinks, edit box, parameters and
all - and replaces only the two IIO Pluto blocks with ZMQ stand-ins that talk
to bpsk_zmq_air.py, including retuning:

    python3 bpsk_zmq_air.py --nodes 2 &
    python3 bpsk_zmq_bench.py --index 0 -- --my-addr 1 --http-port 8088
    python3 bpsk_zmq_node.py  --index 1 --my-addr 2 --http-port 8089

Everything after `--` goes to the flowgraph unchanged. --headless runs Qt
offscreen with no browser.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--index', type=int, required=True)
    ap.add_argument('--base', type=int, default=5600)
    ap.add_argument('--headless', action='store_true')
    ap.add_argument('flowgraph_args', nargs=argparse.REMAINDER)
    args = ap.parse_args()
    fg_args = args.flowgraph_args
    if fg_args and fg_args[0] == '--':
        fg_args = fg_args[1:]
    if args.headless:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        os.environ['BROWSER'] = 'true'

    import zmq
    from gnuradio import gr, iio, zeromq

    ctx = zmq.Context()
    ctl = ctx.socket(zmq.PUSH)
    ctl.connect('tcp://127.0.0.1:%d' % (args.base - 1))

    def report(key, hz):
        ctl.send(json.dumps({'id': args.index, key: float(hz)}).encode())

    class ZmqSink(gr.hier_block2):
        """Stands in for iio.fmcomms2_sink_fc32."""

        def __init__(self, *_):
            gr.hier_block2.__init__(self, 'zmq_pluto_sink',
                                    gr.io_signature(1, 1, gr.sizeof_gr_complex),
                                    gr.io_signature(0, 0, 0))
            self.pub = zeromq.pub_sink(
                gr.sizeof_gr_complex, 1,
                'tcp://127.0.0.1:%d' % (args.base + 2 * args.index),
                100, False, -1, '', False, True)
            self.connect(self, self.pub)

        def set_frequency(self, hz):
            report('tx', hz)

        def set_len_tag_key(self, *_): pass
        def set_bandwidth(self, *_): pass
        def set_samplerate(self, *_): pass
        def set_attenuation(self, *_): pass
        def set_filter_params(self, *_): pass

    class ZmqSource(gr.hier_block2):
        """Stands in for iio.fmcomms2_source_fc32."""

        def __init__(self, *_):
            gr.hier_block2.__init__(self, 'zmq_pluto_source',
                                    gr.io_signature(0, 0, 0),
                                    gr.io_signature(1, 1, gr.sizeof_gr_complex))
            self.sub = zeromq.sub_source(
                gr.sizeof_gr_complex, 1,
                'tcp://127.0.0.1:%d' % (args.base + 2 * args.index + 1),
                100, False, -1, '', False)
            self.connect(self.sub, self)

        def set_frequency(self, hz):
            report('rx', hz)

        def set_len_tag_key(self, *_): pass
        def set_samplerate(self, *_): pass
        def set_gain_mode(self, *_): pass
        def set_gain(self, *_): pass
        def set_quadrature(self, *_): pass
        def set_rfdc(self, *_): pass
        def set_bbdc(self, *_): pass
        def set_filter_params(self, *_): pass

    iio.fmcomms2_sink_fc32 = ZmqSink
    iio.fmcomms2_source_fc32 = ZmqSource

    import bpsk_mac_pluto as fg
    options = fg.argument_parser().parse_args(fg_args)
    print('[bench] Pluto blocks replaced by ZMQ (air index %d, base %d)'
          % (args.index, args.base), flush=True)
    fg.main(options=options)


if __name__ == '__main__':
    main()
