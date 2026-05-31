"""MarkItDown web wrapper — a single ASGI app for Vercel's Python runtime.

Routes:
  GET  /            -> upload page (file upload + URL conversion)
  POST /api/convert -> convert a file or a remote URL to Markdown (JSON)
  ANY  /mcp         -> MarkItDown MCP server (Streamable HTTP, stateless)

Direct file upload is capped at ~4.5 MB by Vercel's request-body limit.
For large or remote files, use URL conversion: the server fetches the
resource itself (no ingress cap) and converts it.
"""

import contextlib
import io
import json
import os
from collections.abc import AsyncIterator
from urllib.parse import urlparse

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route

from markitdown import MarkItDown, StreamInfo
from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

_md = MarkItDown(enable_plugins=False)

# --- MCP (Streamable HTTP, stateless -> serverless friendly) ----------------
_fastmcp = FastMCP("markitdown")


@_fastmcp.tool()
async def convert_to_markdown(uri: str) -> str:
    """Convert a resource described by an http:, https: or data: URI to markdown."""
    scheme = urlparse(uri).scheme.lower()
    if scheme not in ("http", "https", "data"):
        raise ValueError("Only http(s) and data URIs are allowed.")
    return _md.convert_uri(uri).markdown


_mcp_server = _fastmcp._mcp_server
_session_manager = StreamableHTTPSessionManager(
    app=_mcp_server,
    event_store=None,
    json_response=True,
    stateless=True,
)


async def handle_mcp(scope, receive, send):
    await _session_manager.handle_request(scope, receive, send)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with _session_manager.run():
        yield


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>MarkItDown — File to Markdown</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    margin: 0; padding: 2rem; max-width: 860px; margin-inline: auto; line-height: 1.5;
  }
  h1 { margin: 0 0 .25rem; font-size: 1.6rem; }
  p.sub { margin: 0 0 1.5rem; opacity: .7; }
  #drop {
    border: 2px dashed #888; border-radius: 12px; padding: 2.25rem 1rem;
    text-align: center; cursor: pointer; transition: border-color .15s, background .15s;
  }
  #drop.hover { border-color: #4f8cff; background: rgba(79,140,255,.08); }
  #drop input { display: none; }
  .muted { opacity: .65; font-size: .9rem; }
  .or { text-align: center; margin: 1rem 0 .5rem; opacity: .55; font-size: .85rem; }
  input[type=url] {
    width: 100%; padding: .6rem .75rem; border-radius: 8px;
    border: 1px solid #8884; font-size: 1rem;
  }
  button {
    margin-top: 1rem; padding: .5rem 1rem; border: 0; border-radius: 8px;
    background: #4f8cff; color: #fff; font-size: 1rem; cursor: pointer;
  }
  button:disabled { opacity: .5; cursor: default; }
  textarea {
    width: 100%; min-height: 320px; margin-top: 1.25rem; padding: 1rem;
    border-radius: 10px; border: 1px solid #8884; font-family: ui-monospace, monospace;
    font-size: .9rem; white-space: pre;
  }
  .row { display: flex; gap: .75rem; align-items: center; flex-wrap: wrap; }
  .err { color: #e5484d; margin-top: 1rem; white-space: pre-wrap; }
</style>
</head>
<body>
  <h1>MarkItDown</h1>
  <p class="sub">Convert PDF, Office docs, HTML, images and more to Markdown.</p>

  <label id="drop">
    <input type="file" id="file" />
    <div id="label">Click to choose a file — or drop one here</div>
    <div class="muted">Direct upload up to ~4.5&nbsp;MB · PDF · DOCX · PPTX · XLSX · HTML · CSV · JSON · images …</div>
  </label>

  <div class="or">— or convert from a URL (no size limit) —</div>
  <input type="url" id="url" placeholder="https://example.com/document.pdf" />

  <div class="row">
    <button id="go" disabled>Convert</button>
    <button id="copy" disabled>Copy Markdown</button>
    <span id="status" class="muted"></span>
  </div>

  <div id="error" class="err"></div>
  <textarea id="out" placeholder="Markdown output appears here…" spellcheck="false"></textarea>

<script>
  const fileInput = document.getElementById('file');
  const urlInput = document.getElementById('url');
  const drop = document.getElementById('drop');
  const label = document.getElementById('label');
  const go = document.getElementById('go');
  const copy = document.getElementById('copy');
  const out = document.getElementById('out');
  const statusEl = document.getElementById('status');
  const errEl = document.getElementById('error');
  let current = null;

  function refresh() { go.disabled = !current && !urlInput.value.trim(); }
  function pick(f) {
    current = f;
    label.textContent = f ? f.name : 'Click to choose a file — or drop one here';
    refresh();
  }

  fileInput.addEventListener('change', () => pick(fileInput.files[0]));
  urlInput.addEventListener('input', refresh);
  ['dragover', 'dragenter'].forEach(e => drop.addEventListener(e, ev => {
    ev.preventDefault(); drop.classList.add('hover');
  }));
  ['dragleave', 'drop'].forEach(e => drop.addEventListener(e, ev => {
    ev.preventDefault(); drop.classList.remove('hover');
  }));
  drop.addEventListener('drop', ev => { if (ev.dataTransfer.files[0]) pick(ev.dataTransfer.files[0]); });

  go.addEventListener('click', async () => {
    errEl.textContent = ''; out.value = ''; copy.disabled = true;
    go.disabled = true; statusEl.textContent = 'Converting…';
    try {
      let res;
      const url = urlInput.value.trim();
      if (url) {
        res = await fetch('/api/convert', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });
      } else if (current) {
        res = await fetch('/api/convert', {
          method: 'POST',
          headers: { 'X-Filename': current.name, 'Content-Type': 'application/octet-stream' },
          body: current,
        });
      } else {
        throw new Error('Choose a file or enter a URL.');
      }
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
      out.value = data.markdown || '';
      copy.disabled = !out.value;
      statusEl.textContent = data.title ? ('Title: ' + data.title) : 'Done.';
    } catch (e) {
      errEl.textContent = 'Error: ' + e.message;
      statusEl.textContent = '';
    } finally {
      refresh();
    }
  });

  copy.addEventListener('click', async () => {
    await navigator.clipboard.writeText(out.value);
    statusEl.textContent = 'Copied!';
  });
</script>
</body>
</html>"""


async def index(request):
    return HTMLResponse(PAGE)


async def convert(request):
    content_type = request.headers.get("content-type", "")
    try:
        if content_type.startswith("application/json"):
            payload = json.loads(await request.body() or b"{}")
            url = (payload.get("url") or "").strip()
            if not url:
                return JSONResponse({"error": "Missing 'url'."}, status_code=400)
            scheme = urlparse(url).scheme.lower()
            if scheme not in ("http", "https", "data"):
                return JSONResponse(
                    {"error": "Only http(s) and data URLs are allowed."},
                    status_code=400,
                )
            result = _md.convert_uri(url)
        else:
            data = await request.body()
            if not data:
                return JSONResponse({"error": "Empty request body."}, status_code=400)
            filename = request.headers.get("x-filename", "upload")
            extension = os.path.splitext(filename)[1] or None
            result = _md.convert_stream(
                io.BytesIO(data),
                stream_info=StreamInfo(filename=filename, extension=extension),
            )
        return JSONResponse({"markdown": result.markdown, "title": result.title})
    except Exception as exc:  # noqa: BLE001 - surface any conversion error
        return JSONResponse({"error": str(exc)}, status_code=400)


app = Starlette(
    routes=[
        Route("/", index, methods=["GET"]),
        Route("/api/convert", convert, methods=["POST"]),
        Mount("/mcp", app=handle_mcp),
    ],
    lifespan=lifespan,
)
