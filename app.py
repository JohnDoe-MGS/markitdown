"""MarkItDown web wrapper — a single ASGI app for Vercel's Python runtime.

GET  /            -> upload page
POST /api/convert -> raw file bytes (with X-Filename header) -> Markdown JSON
"""

import io
import os

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from markitdown import MarkItDown, StreamInfo

_md = MarkItDown(enable_plugins=False)

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
    border: 2px dashed #888; border-radius: 12px; padding: 2.5rem 1rem;
    text-align: center; cursor: pointer; transition: border-color .15s, background .15s;
  }
  #drop.hover { border-color: #4f8cff; background: rgba(79,140,255,.08); }
  #drop input { display: none; }
  .muted { opacity: .65; font-size: .9rem; }
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
    <div class="muted">PDF · DOCX · PPTX · XLSX · HTML · CSV · JSON · images …</div>
  </label>

  <div class="row">
    <button id="go" disabled>Convert</button>
    <button id="copy" disabled>Copy Markdown</button>
    <span id="status" class="muted"></span>
  </div>

  <div id="error" class="err"></div>
  <textarea id="out" placeholder="Markdown output appears here…" spellcheck="false"></textarea>

<script>
  const fileInput = document.getElementById('file');
  const drop = document.getElementById('drop');
  const label = document.getElementById('label');
  const go = document.getElementById('go');
  const copy = document.getElementById('copy');
  const out = document.getElementById('out');
  const statusEl = document.getElementById('status');
  const errEl = document.getElementById('error');
  let current = null;

  function pick(f) {
    current = f;
    label.textContent = f ? f.name : 'Click to choose a file — or drop one here';
    go.disabled = !f;
  }

  fileInput.addEventListener('change', () => pick(fileInput.files[0]));
  ['dragover', 'dragenter'].forEach(e => drop.addEventListener(e, ev => {
    ev.preventDefault(); drop.classList.add('hover');
  }));
  ['dragleave', 'drop'].forEach(e => drop.addEventListener(e, ev => {
    ev.preventDefault(); drop.classList.remove('hover');
  }));
  drop.addEventListener('drop', ev => { if (ev.dataTransfer.files[0]) pick(ev.dataTransfer.files[0]); });

  go.addEventListener('click', async () => {
    if (!current) return;
    errEl.textContent = ''; out.value = ''; copy.disabled = true;
    go.disabled = true; statusEl.textContent = 'Converting…';
    try {
      const res = await fetch('/api/convert', {
        method: 'POST',
        headers: { 'X-Filename': current.name, 'Content-Type': 'application/octet-stream' },
        body: current,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
      out.value = data.markdown || '';
      copy.disabled = !out.value;
      statusEl.textContent = data.title ? ('Title: ' + data.title) : 'Done.';
    } catch (e) {
      errEl.textContent = 'Error: ' + e.message;
      statusEl.textContent = '';
    } finally {
      go.disabled = false;
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
    data = await request.body()
    if not data:
        return JSONResponse({"error": "Empty request body."}, status_code=400)
    filename = request.headers.get("x-filename", "upload")
    extension = os.path.splitext(filename)[1] or None
    try:
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
    ]
)
