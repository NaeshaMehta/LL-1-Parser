# main.py - driver for LL(1) parser project
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from grammar import GRAMMAR, START, EPS, compute_first, compute_follow
from parser_table import build_table, print_table, print_conflicts
from lexer import tokenize, LexerError
from parser import parse, render_tree_text


def run_check(g, start=START):
    first = compute_first(g)
    follow = compute_follow(g, first, start)

    print("FIRST sets")
    for nt in g:
        print(f"  FIRST({nt}) = {{ {', '.join(sorted(first[nt]))} }}")

    print("\nFOLLOW sets")
    for nt in g:
        print(f"  FOLLOW({nt}) = {{ {', '.join(sorted(follow[nt]))} }}")

    table, conflicts = build_table(g, first, follow)
    print()
    print_table(table)
    print()
    print_conflicts(conflicts)


def make_dangling_else_grammar():
    bg = {nt: [list(alt) for alt in alts] for nt, alts in GRAMMAR.items()}
    bg["IfStmt"] = [["if", "(", "Cond", ")", "Stmt", "ElsePart"]]
    bg["ElsePart"] = [["else", "Stmt"], [EPS]]
    return bg


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py [--check | --demo-conflict | --run-tests | --serve [port] [--no-browser] | <file> [--trace] [--first-error] [--verbose-expected] [--tree]]")
        sys.exit(0)

    arg = sys.argv[1]

    if arg == "--check":
        run_check(GRAMMAR)
        return

    if arg == "--demo-conflict":
        bg = make_dangling_else_grammar()
        run_check(bg)
        return

    if arg == "--run-tests":
        import run_tests
        sys.exit(run_tests.main())

    if arg == "--serve":
        port = 8000
        no_browser = "--no-browser" in sys.argv[2:]
        for a in sys.argv[2:]:
            if a.isdigit():
                port = int(a)
        import webui
        webui.start_server(port=port, open_browser=not no_browser)
        return

    filename = arg
    trace = "--trace" in sys.argv[2:]
    first_error = "--first-error" in sys.argv[2:]
    verbose_expected = "--verbose-expected" in sys.argv[2:]
    show_tree = "--tree" in sys.argv[2:]
    show_svg = "--svg" in sys.argv[2:]
    svg_out_path = "tree.svg"
    if show_svg:
        idx = sys.argv.index("--svg")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            svg_out_path = sys.argv[idx + 1]

    try:
        with open(filename, "r", encoding="utf-8") as f:
            src = f.read()
    except Exception as e:
        print(f"Error reading file '{filename}': {e}")
        sys.exit(1)

    try:
        tokens = tokenize(src)
    except LexerError as e:
        # Print all detected lexer errors
        for _, _, err_msg in getattr(e, "errors", [(e.line, e.col, str(e))]):
            print(err_msg)
        err_count = len(getattr(e, "errors", [1]))
        if not first_error:
            print(f"Parsing finished with {err_count} syntax error(s)")
            print("Rejected")
        if show_tree:
            print("No parse tree (program rejected)")
        if show_svg:
            print("No parse tree (program rejected)")
        sys.exit(1)
    except SyntaxError as e:
        print(e)
        if not first_error:
            print("Parsing finished with 1 syntax error(s)")
            print("Rejected")
        if show_tree:
            print("No parse tree (program rejected)")
        if show_svg:
            print("No parse tree (program rejected)")
        sys.exit(1)

    first = compute_first(GRAMMAR)
    follow = compute_follow(GRAMMAR, first, START)
    table, _ = build_table(GRAMMAR, first, follow)

    res = parse(tokens, table, START, trace=trace, follow=follow, first_error=first_error, verbose_expected=verbose_expected)

    if show_tree:
        if res.ok and res.tree:
            print(render_tree_text(res.tree))
        else:
            print("No parse tree (program rejected)")

    if show_svg:
        if res.ok and res.tree:
            import treeviz
            svg_content = treeviz.render_tree_svg(res.tree, compact=False)
            with open(svg_out_path, "w", encoding="utf-8") as f:
                f.write(svg_content)
            print(f"Tree SVG written to {svg_out_path}")
        else:
            print("No parse tree (program rejected)")

    if not res:
        sys.exit(1)


if __name__ == "__main__":
    main()
