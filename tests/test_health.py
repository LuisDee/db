import urllib.request

from dba_agent.health import start_health_server


def test_healthz_endpoint_returns_ok():
    server = start_health_server(host="127.0.0.1", port=0)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
            assert response.status == 200
            assert response.read() == b'{"status":"ok"}'
    finally:
        server.shutdown()
        server.server_close()


def test_unknown_path_returns_404():
    server = start_health_server(host="127.0.0.1", port=0)
    try:
        port = server.server_address[1]
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=2)
            raise AssertionError("expected HTTPError for unknown path")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        server.server_close()
