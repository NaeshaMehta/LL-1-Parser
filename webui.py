import html
import json
import io
import contextlib
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

from grammar import GRAMMAR, START, EPS, compute_first, compute_follow
from parser_table import build_table
from lexer import tokenize, LexerError
from parser import parse, format_expected
from treeviz import render_tree_svg, count_tree_nodes


# Precomputed tables at module/startup time
GLOBAL_FIRST = compute_first(GRAMMAR)
GLOBAL_FOLLOW = compute_follow(GRAMMAR, GLOBAL_FIRST, START)
GLOBAL_TABLE, GLOBAL_CONFLICTS = build_table(GRAMMAR, GLOBAL_FIRST, GLOBAL_FOLLOW)


def _render_tree_html(node):
    """Renders parse tree as nested details/summary and ul/li elements."""
    if node is None:
        return ""

    if node.token is not None:
        if node.token.type in ("id", "intlit", "floatlit"):
            text = f"{node.token.type} ({node.token.text})"
        else:
            text = node.token.text
        return f"<li><span class=\"mono\">{html.escape(text)}</span></li>"

    if node.label == EPS:
        return f"<li><span class=\"mono\">{EPS}</span></li>"

    if not node.children:
        return f"<li><span class=\"mono\">{html.escape(node.label)}</span></li>"

    inner = "".join(_render_tree_html(c) for c in node.children)
    return (
        f"<li>"
        f"<details open class=\"tree-node\">"
        f"<summary class=\"mono\"><strong>{html.escape(node.label)}</strong></summary>"
        f"<ul class=\"tree-list\">{inner}</ul>"
        f"</details>"
        f"</li>"
    )


def render_report_body(source, lex_errors, result, first=None, follow=None, table=None, conflicts=None, verbose_expected=False):
    """
    Renders the 7 sections of the parse report in exact order:
      1. Result
      2. Source
      3. Errors
      4. Parse tree
      5. Parse trace
      6. FIRST and FOLLOW sets
      7. LL(1) parsing table
    """
    if first is None:
        first = GLOBAL_FIRST
    if follow is None:
        follow = GLOBAL_FOLLOW
    if table is None:
        table = GLOBAL_TABLE
    if conflicts is None:
        conflicts = GLOBAL_CONFLICTS

    # Compile error records
    error_records = []
    error_lines = set()

    if lex_errors:
        for line_num, col_num, msg in lex_errors:
            error_lines.add(line_num)
            char_found = "?"
            if "unknown character" in msg and "'" in msg:
                parts = msg.split("'")
                if len(parts) >= 2:
                    char_found = parts[1]
            error_records.append({
                "line": line_num,
                "col": col_num,
                "found": char_found,
                "expected": "valid token",
                "hint": "unknown character"
            })

    if result is not None and result.errors:
        for err in result.errors:
            error_lines.add(err["line"])
            exp_text = err.get("expected_text")
            if not exp_text:
                exp_text = format_expected(err.get("expected", []), verbose=verbose_expected)
            error_records.append({
                "line": err["line"],
                "col": err["col"],
                "found": err["found"],
                "expected": exp_text,
                "hint": err["hint"]
            })

    # Section 1: Result
    status_str = "Accepted" if (result is not None and result.ok and not lex_errors) else "Rejected"
    total_errors = len(error_records)
    if status_str == "Rejected" and total_errors == 0:
        total_errors = max(1, getattr(result, "error_count", 1) if result is not None else 1)
        if not error_records:
            error_records.append({
                "line": 1,
                "col": 1,
                "found": "?",
                "expected": "valid syntax",
                "hint": "syntax error",
            })
            error_lines.add(1)

    section_result = (
        f"<h2>Result</h2>\n"
        f"<p>\n"
        f"Result: <strong>{status_str}</strong><br>\n"
        f"Errors: <strong>{total_errors}</strong>\n"
        f"</p>"
    )

    # Section 2: Source
    src_lines = source.splitlines()
    if not src_lines:
        src_lines = [""]
    max_line = max(error_lines) if error_lines else len(src_lines)
    while len(src_lines) < max_line:
        src_lines.append("")
    source_html_lines = []
    for idx, line_text in enumerate(src_lines, start=1):
        line_escaped = html.escape(line_text)
        if idx in error_lines:
            source_html_lines.append(
                f"<span class=\"error-line\">{idx:3d} | {line_escaped:<50}  <strong>&lt;-- error</strong></span>"
            )
        else:
            source_html_lines.append(f"{idx:3d} | {line_escaped}")
    source_block = "\n".join(source_html_lines)
    section_source = f"<h2>Source</h2>\n<pre>{source_block}</pre>"

    # Section 3: Errors
    if error_records:
        error_rows = []
        for e in error_records:
            error_rows.append(
                f"<tr class=\"error-row\">"
                f"<td>{e['line']}</td>"
                f"<td>{e['col']}</td>"
                f"<td>{html.escape(str(e['found']))}</td>"
                f"<td>{html.escape(str(e['expected']))}</td>"
                f"<td>{html.escape(str(e['hint']))}</td>"
                f"</tr>"
            )
        section_errors = (
            f"<h2>Errors</h2>\n"
            f"<table>\n"
            f"<thead><tr><th>Line</th><th>Col</th><th>Found</th><th>Expected</th><th>Hint</th></tr></thead>\n"
            f"<tbody>{''.join(error_rows)}</tbody>\n"
            f"</table>"
        )
    else:
        section_errors = "<h2>Errors</h2>\n<p>No errors.</p>"

    # Section 4: Parse tree
    if result is not None and result.ok and not lex_errors and result.tree:
        total_nodes = count_tree_nodes(result.tree)
        large_note = (
            f"<p>Note: Tree is large ({total_nodes} nodes). Use Zoom - to view the full diagram.</p>\n"
            if total_nodes > 1500 else ""
        )
        compact_svg = render_tree_svg(result.tree, compact=True)
        full_svg = render_tree_svg(result.tree, compact=False)

        section_tree = (
            f"<h2>Parse tree</h2>\n"
            f"{large_note}"
            f"<p>\n"
            f"<button type=\"button\" id=\"btn-compact-tree\" onclick=\"showCompactTree()\"><strong>Compact tree</strong></button>\n"
            f"<button type=\"button\" id=\"btn-full-tree\" onclick=\"showFullTree()\">Full tree</button>\n"
            f"&nbsp;&nbsp;\n"
            f"<button type=\"button\" onclick=\"zoomTree(1.25)\">Zoom +</button>\n"
            f"<button type=\"button\" onclick=\"zoomTree(0.8)\">Zoom -</button>\n"
            f"<span id=\"zoom-indicator\" class=\"mono\" style=\"margin-left: 8px;\">100%</span>\n"
            f"</p>\n"
            f"<div id=\"tree-scroll-container\" style=\"overflow: auto; max-height: 600px; border: 1px solid #000000; margin-bottom: 8px; background: #ffffff;\">\n"
            f"<div id=\"tree-compact-container\">{compact_svg}</div>\n"
            f"<div id=\"tree-full-container\" style=\"display: none;\">{full_svg}</div>\n"
            f"</div>\n"
            f"<p><a id=\"download-tree-link\" href=\"#\" onclick=\"downloadTreeSvg(event)\">Download tree as SVG</a></p>"
        )
    else:
        section_tree = "<h2>Parse tree</h2>\n<p>No parse tree (program rejected).</p>"

    # Section 5: Parse trace
    trace_records = result.trace if (result is not None) else []
    if trace_records:
        trace_rows = []
        for r in trace_records:
            trace_rows.append(
                f"<tr>"
                f"<td>{r['step']}</td>"
                f"<td>{html.escape(r['stack'])}</td>"
                f"<td>{html.escape(r['input'])}</td>"
                f"<td>{html.escape(r['action'])}</td>"
                f"</tr>"
            )
        trace_table = (
            f"<table>\n"
            f"<thead><tr><th>Step</th><th>Stack</th><th>Input</th><th>Action</th></tr></thead>\n"
            f"<tbody>{''.join(trace_rows)}</tbody>\n"
            f"</table>"
        )
        if len(trace_records) > 300:
            section_trace = (
                f"<h2>Parse trace</h2>\n"
                f"<details>\n"
                f"<summary>Parse trace ({len(trace_records)} rows - click to expand)</summary>\n"
                f"{trace_table}\n"
                f"</details>"
            )
        else:
            section_trace = f"<h2>Parse trace</h2>\n{trace_table}"
    else:
        section_trace = "<h2>Parse trace</h2>\n<p>No parse trace.</p>"

    # Section 6: FIRST and FOLLOW sets
    ff_rows = []
    for nt in GRAMMAR:
        first_str = f"{{ {', '.join(sorted(first[nt]))} }}"
        follow_str = f"{{ {', '.join(sorted(follow[nt]))} }}"
        ff_rows.append(
            f"<tr>"
            f"<td><strong>{html.escape(nt)}</strong></td>"
            f"<td>{html.escape(first_str)}</td>"
            f"<td>{html.escape(follow_str)}</td>"
            f"</tr>"
        )
    section_ff = (
        f"<h2>FIRST and FOLLOW sets</h2>\n"
        f"<table>\n"
        f"<thead><tr><th>Non-terminal</th><th>FIRST</th><th>FOLLOW</th></tr></thead>\n"
        f"<tbody>{''.join(ff_rows)}</tbody>\n"
        f"</table>"
    )

    # Section 7: LL(1) parsing table
    all_terms = sorted({term for _, term in table})
    matrix_headers = "".join(f"<th>{html.escape(t)}</th>" for t in all_terms)
    matrix_rows = []
    for nt in GRAMMAR:
        cells = []
        for t in all_terms:
            cell_key = (nt, t)
            if cell_key in table:
                prod = table[cell_key]
                cells.append(f"<td>{html.escape(nt)} -&gt; {html.escape(' '.join(prod))}</td>")
            else:
                cells.append("<td></td>")
        matrix_rows.append(
            f"<tr><td><strong>{html.escape(nt)}</strong></td>{''.join(cells)}</tr>"
        )

    conflict_note = f"Table has {len(table)} entries, no conflicts." if not conflicts else f"Table has {len(conflicts)} conflict(s)."
    section_matrix = (
        f"<h2>LL(1) parsing table</h2>\n"
        f"<p>{conflict_note}</p>\n"
        f"<div class=\"table-wrapper\">\n"
        f"<table>\n"
        f"<thead><tr><th>Non-terminal</th>{matrix_headers}</tr></thead>\n"
        f"<tbody>{''.join(matrix_rows)}</tbody>\n"
        f"</table>\n"
        f"</div>"
    )

    return "\n\n".join([
        section_result,
        section_source,
        section_errors,
        section_tree,
        section_trace,
        section_ff,
        section_matrix
    ])


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>LL(1) Parser</title>
<style>
body { font-family: sans-serif; margin: 20px; background: #ffffff; color: #000000; line-height: 1.4; }
h2 { margin-top: 24px; margin-bottom: 8px; font-size: 1.2em; border-bottom: 1px solid #000000; padding-bottom: 4px; }
pre, code, .mono { font-family: monospace; }
pre { background: #ffffff; border: 1px solid #000000; padding: 8px; overflow-x: auto; font-size: 13px; line-height: 1.4; }
textarea { width: 100%; box-sizing: border-box; font-family: monospace; font-size: 13px; padding: 6px; border: 1px solid #000000; }
table { border-collapse: collapse; width: 100%; margin-bottom: 16px; }
th, td { border: 1px solid #000000; padding: 2px 6px; text-align: left; font-size: 13px; font-family: monospace; }
th { background: #ffffff; font-weight: bold; }
.error-line { background-color: #f0f0f0; display: block; }
.error-row { background-color: #f0f0f0; }
.table-wrapper { overflow-x: auto; margin-bottom: 16px; border: 1px solid #000000; }
.table-wrapper table { border: none; margin: 0; width: auto; min-width: 100%; }
button { font-family: sans-serif; font-size: 13px; padding: 4px 12px; cursor: pointer; }
ul.tree-list, ul.tree-list ul { list-style-type: none; margin: 2px 0 2px 16px; padding: 0; font-family: monospace; }
details.tree-node > summary { cursor: pointer; font-family: monospace; }
</style>
</head>
<body>

<h2>LL(1) Parser</h2>

<p>
<textarea id="source" name="source" rows="20" placeholder="Type or paste C-subset source code here..."></textarea>
</p>

<p>
<label><input type="checkbox" id="first_error"> Stop at first error</label>&nbsp;&nbsp;
<label><input type="checkbox" id="verbose_expected"> Show full expected list</label>
</p>

<p>
<button type="button" id="parse-btn" onclick="runParse()">Parse</button>
</p>

<div id="results"></div>

<script>
let currentTreeZoom = 1.0;

function showCompactTree() {
  const c = document.getElementById('tree-compact-container');
  const f = document.getElementById('tree-full-container');
  if (c && f) {
    c.style.display = 'block';
    f.style.display = 'none';
    const btnC = document.getElementById('btn-compact-tree');
    const btnF = document.getElementById('btn-full-tree');
    if (btnC) btnC.innerHTML = '<strong>Compact tree</strong>';
    if (btnF) btnF.innerHTML = 'Full tree';
    applyTreeZoom();
  }
}

function showFullTree() {
  const c = document.getElementById('tree-compact-container');
  const f = document.getElementById('tree-full-container');
  if (c && f) {
    c.style.display = 'none';
    f.style.display = 'block';
    const btnC = document.getElementById('btn-compact-tree');
    const btnF = document.getElementById('btn-full-tree');
    if (btnC) btnC.innerHTML = 'Compact tree';
    if (btnF) btnF.innerHTML = '<strong>Full tree</strong>';
    applyTreeZoom();
  }
}

function zoomTree(factor) {
  let next = currentTreeZoom * factor;
  if (next < 0.25) next = 0.25;
  if (next > 3.0) next = 3.0;
  currentTreeZoom = next;
  applyTreeZoom();
}

function applyTreeZoom() {
  const indicator = document.getElementById('zoom-indicator');
  if (indicator) {
    indicator.textContent = Math.round(currentTreeZoom * 100) + '%';
  }
  const svgs = document.querySelectorAll('#tree-scroll-container svg');
  svgs.forEach(function(s) {
    if (!s.dataset.origWidth) {
      s.dataset.origWidth = s.getAttribute('width');
    }
    const origW = parseFloat(s.dataset.origWidth);
    s.style.width = (origW * currentTreeZoom) + 'px';
    s.style.height = 'auto';
  });
}

function downloadTreeSvg(e) {
  if (e && e.preventDefault) e.preventDefault();
  const compactCont = document.getElementById('tree-compact-container');
  const fullCont = document.getElementById('tree-full-container');
  if (!compactCont || !fullCont) return;
  const isCompact = compactCont.style.display !== 'none';
  const activeCont = isCompact ? compactCont : fullCont;
  const svg = activeCont.querySelector('svg');
  if (!svg) return;
  const svgData = new XMLSerializer().serializeToString(svg);
  const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = isCompact ? 'parse_tree_compact.svg' : 'parse_tree_full.svg';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function runParse() {
  const src = document.getElementById('source').value;
  const firstErr = document.getElementById('first_error').checked;
  const verboseExp = document.getElementById('verbose_expected').checked;
  const resultsDiv = document.getElementById('results');

  resultsDiv.innerHTML = '<p>Parsing...</p>';

  fetch('/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source: src,
      first_error: firstErr,
      verbose_expected: verboseExp
    })
  })
  .then(function(res) {
    return res.text();
  })
  .then(function(html) {
    resultsDiv.innerHTML = html;
    currentTreeZoom = 1.0;
    applyTreeZoom();
  })
  .catch(function(err) {
    resultsDiv.innerHTML = '<p>Error: ' + err.message + '</p>';
  });
}
</script>

</body>
</html>
"""


class LL1Handler(BaseHTTPRequestHandler):
    """HTTP request handler for local LL(1) parser web interface."""

    def log_message(self, format, *args):
        # Silence default request logging to keep console clean
        pass

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
        if self.path == "/parse":
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 100 * 1024:
                    resp_html = "<p>Error: Input exceeds 100 KB limit.</p>"
                    body = resp_html.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                raw_data = self.rfile.read(content_len)
                try:
                    payload = json.loads(raw_data.decode("utf-8", errors="replace"))
                except Exception:
                    payload = {"source": raw_data.decode("utf-8", errors="replace")}

                source = payload.get("source", "")
                first_error = bool(payload.get("first_error", False))
                verbose_expected = bool(payload.get("verbose_expected", False))

                # Handle parsing
                tokens = []
                lexer_errors = None
                parse_res = None

                try:
                    tokens = tokenize(source)
                except LexerError as e:
                    lexer_errors = getattr(e, "errors", [(e.line, e.col, str(e))])
                    if first_error and lexer_errors:
                        lexer_errors = lexer_errors[:1]
                except SyntaxError as e:
                    lexer_errors = [(1, 1, str(e))]
                except Exception as e:
                    resp_html = f"<p>Error during tokenization: {html.escape(str(e))}</p>"
                    body = resp_html.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if not lexer_errors:
                    try:
                        with contextlib.redirect_stdout(io.StringIO()):
                            parse_res = parse(
                                tokens,
                                GLOBAL_TABLE,
                                START,
                                trace=False,
                                follow=GLOBAL_FOLLOW,
                                first_error=first_error,
                                verbose_expected=verbose_expected
                            )
                    except Exception as e:
                        resp_html = f"<p>Error during parsing: {html.escape(str(e))}</p>"
                        body = resp_html.encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return

                report_html = render_report_body(
                    source=source,
                    lex_errors=lexer_errors,
                    result=parse_res,
                    first=GLOBAL_FIRST,
                    follow=GLOBAL_FOLLOW,
                    table=GLOBAL_TABLE,
                    conflicts=GLOBAL_CONFLICTS,
                    verbose_expected=verbose_expected
                )

                body = report_html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            except Exception as e:
                resp_html = f"<p>Unexpected error: {html.escape(str(e))}</p>"
                body = resp_html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not Found")


def create_server(host="127.0.0.1", port=8000):
    """Creates an HTTPServer bound to host and port."""
    return HTTPServer((host, port), LL1Handler)


def start_server(host="127.0.0.1", port=8000, open_browser=True):
    """Starts the local web server and optionally opens the browser."""
    server = create_server(host, port)
    url = f"http://{host}:{port}"
    print(f"Open {url} in your browser (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()
