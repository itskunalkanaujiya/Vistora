"""
HTTP sessions that reuse connections (skipping a secure-connection set-up on
every call) without being tripped by a connection the server has closed.

A server may close an idle connection at any moment. The next request on that
reused connection then fails at once with "Connection aborted" before any
answer comes back. That is safe to repeat on a fresh connection, so it is
retried once. Timeouts are never retried: the server may be busy working on
the request, and a repeat could use another search credit.
"""

import requests
from requests.adapters import HTTPAdapter


class RetryOnClosedConnection(HTTPAdapter):
    def send(self, request, **kwargs):
        try:
            return super().send(request, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            if isinstance(exc, requests.exceptions.Timeout):
                raise
            return super().send(request, **kwargs)


def reliable_session():
    session = requests.Session()
    session.mount("https://", RetryOnClosedConnection())
    session.mount("http://", RetryOnClosedConnection())
    return session
