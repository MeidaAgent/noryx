"""WSGI adapter for the Noryx API on Vercel.

The local development server remains ``serve_noryx.py``. Vercel discovers the
``app`` WSGI callable and invokes it for each request.
"""

from email.message import Message
from io import BytesIO
from http import HTTPStatus

from backend_server import NoryxHandler, init_database


class _VercelHandler(NoryxHandler):
    def __init__(self, environ):
        self.command = environ["REQUEST_METHOD"]
        path = environ.get("PATH_INFO", "/")
        query = environ.get("QUERY_STRING", "")
        self.path = f"{path}?{query}" if query else path
        self.headers = Message()
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                self.headers[key[5:].replace("_", "-")] = value
        if environ.get("CONTENT_LENGTH"):
            self.headers["content-length"] = environ["CONTENT_LENGTH"]
        if environ.get("CONTENT_TYPE"):
            self.headers["content-type"] = environ["CONTENT_TYPE"]
        self.rfile = environ["wsgi.input"]
        self.wfile = BytesIO()
        self._status = 500
        self._response_headers = []

    def send_response(self, code, message=None):
        self._status = code

    def send_header(self, keyword, value):
        self._response_headers.append((keyword, value))

    def end_headers(self):
        return

    def log_message(self, format, *args):
        return


def app(environ, start_response):
    init_database()
    request = _VercelHandler(environ)
    method = getattr(request, f"do_{request.command}", None)
    if method is None:
        request.send_json(405, {"error": "method_not_allowed"})
    else:
        method()
    headers = [(key, value) for key, value in request._response_headers]
    if not any(key.lower() == "content-length" for key, _ in headers):
        headers.append(("content-length", str(request.wfile.tell())))
    start_response(f"{request._status} {HTTPStatus(request._status).phrase}", headers)
    return [request.wfile.getvalue()]
