from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx2

import llm.utils


def test_debug_client_closes_real_keepalive_connections(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    transport = httpx2.HTTPTransport()
    monkeypatch.setattr(llm.utils.httpx2, "HTTPTransport", lambda: transport)
    try:
        with llm.utils.logging_client() as client:
            assert client.get(f"http://127.0.0.1:{server.server_port}/").json() == {}
            assert len(transport._pool.connections) == 1
            assert not transport._pool.connections[0].is_closed()
        assert client.is_closed
        assert transport._pool.connections == []
    finally:
        transport.close()
        server.shutdown()
        server.server_close()
        thread.join()
