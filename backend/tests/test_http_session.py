import socket
import threading

import pytest
import requests

from http_session import reliable_session


class OddServer:
    """A tiny server whose first connection(s) are closed without an answer, as an idle one would be."""

    def __init__(self, drop_first, hang=False):
        self.drop_first, self.hang = drop_first, hang
        self.connections = 0
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        self.sock.settimeout(0.2)
        held = []
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            self.connections += 1
            conn.recv(4096)
            if self.hang:
                held.append(conn)  # never answers
            elif self.connections <= self.drop_first:
                conn.close()  # closed before any answer
            else:
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
                conn.close()

    def close(self):
        self.stop.set()
        self.sock.close()


@pytest.fixture
def server(request):
    odd = OddServer(**getattr(request, "param", {"drop_first": 1}))
    yield odd
    odd.close()


def test_a_connection_closed_before_any_answer_is_retried_once(server):
    response = reliable_session().get(f"http://127.0.0.1:{server.port}/", timeout=3)

    assert response.status_code == 200 and response.text == "ok"
    assert server.connections == 2


def test_a_plain_session_would_have_failed_on_that_connection(server):
    with pytest.raises(requests.exceptions.ConnectionError):
        requests.Session().get(f"http://127.0.0.1:{server.port}/", timeout=3)


@pytest.mark.parametrize("server", [{"drop_first": 5}], indirect=True)
def test_it_gives_up_after_one_retry(server):
    with pytest.raises(requests.exceptions.ConnectionError):
        reliable_session().get(f"http://127.0.0.1:{server.port}/", timeout=3)
    assert server.connections == 2


@pytest.mark.parametrize("server", [{"drop_first": 0, "hang": True}], indirect=True)
def test_a_timeout_is_never_retried(server):
    # A busy server may be working on the request: repeating it could spend another search credit.
    with pytest.raises(requests.exceptions.ReadTimeout):
        reliable_session().get(f"http://127.0.0.1:{server.port}/", timeout=0.5)
    assert server.connections == 1


def test_the_search_providers_use_the_reliable_session(monkeypatch):
    import image_shopping_service, llm_query_parser, text_shopping_service
    from http_session import RetryOnClosedConnection

    monkeypatch.undo()  # the other tests swap these sessions for mocks; look at the real ones

    for module, name in ((image_shopping_service, "_api_session"), (text_shopping_service, "_session"),
                         (llm_query_parser, "_session")):
        adapter = getattr(module, name).get_adapter("https://example.com")
        assert isinstance(adapter, RetryOnClosedConnection), (module.__name__, name)
