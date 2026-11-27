class ChatServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, app):
        ThreadingHTTPServer.__init__(self, addr, _Handler)
        self.app = app
        self.stopping = False
