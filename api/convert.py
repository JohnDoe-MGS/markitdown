"""Vercel Python serverless function: convert an uploaded file to Markdown.

The browser POSTs the raw file bytes with the original name in the
`X-Filename` header. We hand the bytes to MarkItDown and return JSON.
"""

from http.server import BaseHTTPRequestHandler
import io
import json
import os

from markitdown import MarkItDown, StreamInfo

# One shared instance is fine across warm invocations.
_md = MarkItDown(enable_plugins=False)


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length <= 0:
                return self._send(400, {"error": "Empty request body."})

            data = self.rfile.read(length)
            filename = self.headers.get("X-Filename", "upload")
            extension = os.path.splitext(filename)[1] or None

            result = _md.convert_stream(
                io.BytesIO(data),
                stream_info=StreamInfo(filename=filename, extension=extension),
            )
            self._send(200, {"markdown": result.markdown, "title": result.title})
        except Exception as exc:  # noqa: BLE001 - surface any conversion error
            self._send(400, {"error": str(exc)})

    def do_GET(self):
        self._send(200, {"status": "ok", "usage": "POST a file with X-Filename header"})
