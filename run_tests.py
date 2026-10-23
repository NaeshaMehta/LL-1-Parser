# run_tests.py - automated test runner for LL(1) parser
import os
import sys
import json
import io
import contextlib
import threading
import urllib.request

from grammar import GRAMMAR, START, compute_first, compute_follow
from parser_table import build_table
from lexer import tokenize, LexerError
from parser import parse
import re
import webui
import treeviz


rect_pattern = re.compile(r'<rect[^>]*\bx="([^"]+)"[^>]*\by="([^"]+)"[^>]*\bwidth="([^"]+)"')


def get_terminal_leaves(node):
    """Returns in-order list of terminal leaf tokens from a parse tree."""
    if node is None:
        return []
    if node.token is not None:
        return [node.token]
    if node.label == "ε":
        return []
    leaves = []
    for c in node.children:
        leaves.extend(get_terminal_leaves(c))
    return leaves


def run_single_test(filepath, table, follow, first, start=START):
    """
    Runs parser on a single source file in memory.
    Captures stdout to keep test runs clean while retaining any diagnostics.
    Verifies:
      1. Parse result string ('accepted' or 'rejected') and error count.
      2. Parse tree presence: present for accepted, None for rejected.
      3. For accepted files: leaf tokens read left-to-right match lexer tokens (excluding $).
      4. render_report_body returns non-empty HTML containing 'Accepted'/'Rejected'.
      5. For accepted files: render_tree_svg generates valid SVG without overlaps.
    Returns (result_str, error_count, captured_output, tree_ok, report_ok, svg_ok, tree_err, report_err, svg_err).
    """
    with open(filepath, "r", encoding="utf-8") as f:
        src = f.read()

    buf = io.StringIO()
    lexer_errors = None
    tokens = []
    res = None

    with contextlib.redirect_stdout(buf):
        try:
            tokens = tokenize(src)
        except LexerError as e:
            lexer_errors = getattr(e, "errors", [(e.line, e.col, str(e))])
            act_result = "rejected"
            act_errors = len(lexer_errors)
        except SyntaxError as e:
            lexer_errors = [(1, 1, str(e))]
            act_result = "rejected"
            act_errors = 1
        else:
            try:
                res = parse(tokens, table, start=start, trace=False, follow=follow)
                act_result = "accepted" if res.ok else "rejected"
                act_errors = res.error_count
            except Exception as e:
                return "crashed", 0, str(e), False, False, False, f"Parser crashed: {e}", "", ""

    # Tree check
    tree_ok = True
    tree_err = ""
    if act_result == "accepted":
        if res.tree is None:
            tree_ok = False
            tree_err = "Tree is None for accepted file"
        else:
            leaves = get_terminal_leaves(res.tree)
            expected_tokens = [t for t in tokens if t.type != "$"]
            if len(leaves) != len(expected_tokens):
                tree_ok = False
                tree_err = f"Tree leaf count ({len(leaves)}) != lexer token count ({len(expected_tokens)})"
            else:
                for idx, (l_tok, e_tok) in enumerate(zip(leaves, expected_tokens)):
                    if (l_tok.type != e_tok.type or l_tok.text != e_tok.text or
                            l_tok.line != e_tok.line or l_tok.col != e_tok.col):
                        tree_ok = False
                        tree_err = f"Leaf mismatch at #{idx}: tree={l_tok} vs token={e_tok}"
                        break
    else:
        if res is not None and res.tree is not None:
            tree_ok = False
            tree_err = "Tree is not None for rejected file"

    # Report check
    report_ok = True
    report_err = ""
    try:
        report_html = webui.render_report_body(
            source=src,
            lex_errors=lexer_errors,
            result=res,
            first=first,
            follow=follow,
            table=table
        )
        if not report_html:
            report_ok = False
            report_err = "render_report_body returned empty string"
        elif act_result == "accepted":
            if "Accepted" not in report_html:
                report_ok = False
                report_err = "Report HTML missing 'Accepted' verdict"
            elif "No errors." not in report_html:
                report_ok = False
                report_err = "Valid file report missing 'No errors.'"
            elif "Errors: <strong>0</strong>" not in report_html and "Errors: 0" not in report_html:
                report_ok = False
                report_err = "Valid file report error count is not 0"
            elif report_html.count('<tr class="error-row">') != 0:
                report_ok = False
                report_err = "Valid file report has rows in Errors table"
        elif act_result == "rejected":
            if "Rejected" not in report_html:
                report_ok = False
                report_err = "Report HTML missing 'Rejected' verdict"
            else:
                error_row_count = report_html.count('<tr class="error-row">')
                if error_row_count != act_errors:
                    report_ok = False
                    report_err = f"Report error rows ({error_row_count}) != expected errors ({act_errors})"
                else:
                    # Check that each error's line number appears in a highlighted source line
                    row_lines = re.findall(r'<tr class="error-row">\s*<td>(\d+)</td>', report_html)
                    for r_line in row_lines:
                        pattern = f'<span class="error-line">{int(r_line):3d} |'
                        if pattern not in report_html:
                            report_ok = False
                            report_err = f"Error line {r_line} not highlighted in source block"
                            break
    except Exception as e:
        report_ok = False
        report_err = f"render_report_body raised exception: {e}"

    # SVG check (for accepted files)
    svg_ok = True
    svg_err = ""
    if act_result == "accepted" and res and res.tree:
        try:
            full_svg = treeviz.render_tree_svg(res.tree, compact=False)
            if not full_svg.startswith("<svg"):
                svg_ok = False
                svg_err = "Full SVG does not start with '<svg'"
            else:
                full_nodes = treeviz.count_tree_nodes(res.tree)
                full_rects = full_svg.count('class="node-box')
                if full_rects != full_nodes:
                    svg_ok = False
                    svg_err = f"Full SVG node shapes ({full_rects}) != tree nodes ({full_nodes})"

            if svg_ok:
                compact_svg = treeviz.render_tree_svg(res.tree, compact=True)
                if not compact_svg.startswith("<svg"):
                    svg_ok = False
                    svg_err = "Compact SVG does not start with '<svg'"
                else:
                    compact_rects = compact_svg.count('class="node-box')
                    if compact_rects > full_nodes:
                        svg_ok = False
                        svg_err = f"Compact SVG node shapes ({compact_rects}) > tree nodes ({full_nodes})"
                    elif "ε" in compact_svg:
                        svg_ok = False
                        svg_err = "Compact SVG contains ε"

            if svg_ok:
                for mode_name, svg_content in [("full", full_svg), ("compact", compact_svg)]:
                    matches = rect_pattern.findall(svg_content)
                    by_y = {}
                    for x_str, y_str, w_str in matches:
                        x_val, y_val, w_val = float(x_str), float(y_str), float(w_str)
                        by_y.setdefault(y_val, []).append((x_val, w_val))
                    for y_coord, intervals in by_y.items():
                        intervals.sort(key=lambda item: item[0])
                        for i in range(len(intervals) - 1):
                            x1, w1 = intervals[i]
                            x2, w2 = intervals[i+1]
                            if x1 + w1 > x2 + 1e-5:
                                svg_ok = False
                                svg_err = f"Overlap in {mode_name} SVG at y={y_coord}: [{x1}, {x1+w1}] overlaps with [{x2}, {x2+w2}]"
                                break
                        if not svg_ok:
                            break
                    if not svg_ok:
                        break
        except Exception as e:
            svg_ok = False
            svg_err = f"SVG generation raised exception: {e}"

    return act_result, act_errors, buf.getvalue(), tree_ok, report_ok, svg_ok, tree_err, report_err, svg_err


def run_server_e2e_check():
    """Starts server in background thread on a free port, tests valid/invalid POST /parse and switch E2E, shuts down."""
    server = webui.create_server("127.0.0.1", 0)
    port = server.server_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    passed = 0
    total = 2

    try:
        # 1. Basic valid and invalid POST requests
        req1_data = json.dumps({"source": "int a = 10;"}).encode("utf-8")
        req1 = urllib.request.Request(
            f"http://127.0.0.1:{port}/parse",
            data=req1_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req1) as resp1:
            body1 = resp1.read().decode("utf-8")
            if "Accepted" not in body1:
                return passed, total, "Server valid POST did not return 'Accepted'"

        req2_data = json.dumps({"source": "int a 10;"}).encode("utf-8")
        req2 = urllib.request.Request(
            f"http://127.0.0.1:{port}/parse",
            data=req2_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req2) as resp2:
            body2 = resp2.read().decode("utf-8")
            if "Rejected" not in body2:
                return passed, total, "Server invalid POST did not return 'Rejected'"

        passed += 1

        # 2. POST switch program with syntax errors (reproduction case)
        switch_src = (
            "int x = 1;\n"
            "switch (x) {\n"
            "    case 1\n"
            "        x = 2;\n"
            "        break\n"
            "    case 2:\n"
            "        x = 3;\n"
            "        break;\n"
            "}\n"
        )
        req3_data = json.dumps({"source": switch_src}).encode("utf-8")
        req3 = urllib.request.Request(
            f"http://127.0.0.1:{port}/parse",
            data=req3_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req3) as resp3:
            body3 = resp3.read().decode("utf-8")
            if "Rejected" not in body3:
                return passed, total, "Server switch test did not return 'Rejected'"
            if "Errors: <strong>2</strong>" not in body3 and "Errors: 2" not in body3:
                return passed, total, "Server switch test did not contain 'Errors: 2'"
            if "3" not in body3 or "5" not in body3:
                return passed, total, "Server switch test did not contain error line numbers (3 and 5)"
            if "<td>4</td>" not in body3 or "<td>6</td>" not in body3:
                return passed, total, "Server switch test did not contain error rows for lines 4 and 6"

        passed += 1
        return passed, total, ""
    except Exception as e:
        return passed, total, f"Server E2E check error: {e}"
    finally:
        server.shutdown()
        server.server_close()


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    expected_path = os.path.join(base_dir, "tests", "expected.json")

    if not os.path.exists(expected_path):
        print(f"Error: Expectations file '{expected_path}' not found.")
        return 1

    with open(expected_path, "r", encoding="utf-8") as f:
        expected_data = json.load(f)

    first = compute_first(GRAMMAR)
    follow = compute_follow(GRAMMAR, first, START)
    table, _ = build_table(GRAMMAR, first, follow)

    print("=" * 80)
    print(" LL(1) PARSER AUTOMATED TEST SUITE")
    print("=" * 80)
    print(f"{'Status':<8} {'Test File':<38} {'Expected':<16} {'Actual':<16}")
    print("-" * 80)

    parse_passed = 0
    tree_passed = 0
    report_passed = 0
    svg_passed = 0
    svg_total = 0
    total_files = len(expected_data)

    failures = []

    for rel_path, exp in sorted(expected_data.items()):
        full_path = os.path.join(base_dir, "tests", rel_path.replace("/", os.sep))
        if not os.path.exists(full_path):
            print(f"{'FAIL':<8} {rel_path:<38} (file missing)")
            failures.append((rel_path, "File does not exist"))
            continue

        act_result, act_errors, output, tree_ok, report_ok, svg_ok, tree_err, report_err, svg_err = run_single_test(
            full_path, table, follow, first
        )

        exp_result = exp["result"]
        exp_errors = exp["errors"]

        parse_matched = (act_result == exp_result) and (act_errors == exp_errors)
        if parse_matched:
            parse_passed += 1

        if tree_ok:
            tree_passed += 1
        else:
            failures.append((rel_path, f"Tree check failed: {tree_err}"))

        if report_ok:
            report_passed += 1
        else:
            failures.append((rel_path, f"Report check failed: {report_err}"))

        if exp_result == "accepted":
            svg_total += 1
            if svg_ok:
                svg_passed += 1
            else:
                failures.append((rel_path, f"SVG check failed: {svg_err}"))

        exp_desc = f"{exp_result} ({exp_errors} err)"
        act_desc = f"{act_result} ({act_errors} err)"

        if parse_matched:
            print(f"{'PASS':<8} {rel_path:<38} {exp_desc:<16} {act_desc:<16}")
        else:
            print(f"{'FAIL':<8} {rel_path:<38} {exp_desc:<16} {act_desc:<16}")
            failures.append((rel_path, f"Expected {exp_desc}, got {act_desc}\nOutput:\n{output}"))

    # Server end-to-end checks
    server_passed, server_total, server_err = run_server_e2e_check()
    if server_err:
        failures.append(("Server E2E Check", server_err))

    total_passed = parse_passed + tree_passed + report_passed + svg_passed + server_passed
    total_expected = total_files * 3 + svg_total + server_total
    total_failed = total_expected - total_passed

    print("=" * 80)
    print(f"Parse checks: {parse_passed}/{total_files} | Tree checks: {tree_passed}/{total_files} | Report checks: {report_passed}/{total_files} | SVG checks: {svg_passed}/{svg_total} | Server checks: {server_passed}/{server_total} | TOTAL: {total_passed} passed, {total_failed} failed")
    print("=" * 80)

    if failures:
        print("\nFAILURE DETAILS:")
        for name, reason in failures:
            print(f"--- {name} ---")
            print(reason)
            print("-" * 40)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
