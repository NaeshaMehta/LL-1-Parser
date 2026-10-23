# parser.py - predictive LL(1) parser driver with panic-mode error recovery
from grammar import END, EPS
from lexer import KEYWORDS

# Statement starters used to re-anchor parser at statement boundaries during recovery
STMT_START = {"int", "float", "id", "if", "while", "for", "switch", "break", "{", "}"}
EXTRA_SYNC = STMT_START | {";", END}


class Node:
    """A parse tree node representing a non-terminal, terminal, or epsilon."""
    def __init__(self, label, children=None, token=None):
        self.label = label
        self.children = children if children is not None else []
        self.token = token
        self.text = token.text if token else None
        self.line = token.line if token else None
        self.col = token.col if token else None

    def __repr__(self):
        if self.token:
            return f"Node({self.label}, text={self.text!r})"
        return f"Node({self.label}, {len(self.children)} children)"


def render_tree_text(node):
    """
    Renders the derivation tree as plain text with ASCII branches (|-- and \\--).
    Terminals are displayed as 'id (x)', 'intlit (5)', 'floatlit (2.5)', or literal token text (';').
    Epsilon productions are displayed as 'ε'.
    """
    if node is None:
        return ""

    lines = []

    def _format_label(n):
        if n.token is not None:
            if n.token.type in ("id", "intlit", "floatlit"):
                return f"{n.token.type} ({n.token.text})"
            return f"{n.token.text}"
        return n.label

    def _build(curr, prefix="", is_last=True, is_root=True):
        if is_root:
            lines.append(_format_label(curr))
        else:
            branch = "\\-- " if is_last else "|-- "
            lines.append(f"{prefix}{branch}{_format_label(curr)}")

        new_prefix = prefix + ("    " if is_last else "|   ") if not is_root else ""
        child_count = len(curr.children)
        for idx, child in enumerate(curr.children):
            _build(child, new_prefix, idx == child_count - 1, False)

    _build(node)
    return "\n".join(lines)


class ParseResult:
    """Represents the outcome of parsing, usable both as a boolean and for inspection."""
    def __init__(self, ok, error_count, errors, tree=None, trace=None):
        self.ok = ok
        self.error_count = error_count
        self.errors = errors
        self.tree = tree
        self.trace = trace if trace is not None else []

    def __bool__(self):
        return self.ok

    def __eq__(self, other):
        if isinstance(other, bool):
            return self.ok == other
        return super().__eq__(other)

    def __repr__(self):
        status = "Accepted" if self.ok else "Rejected"
        return f"<ParseResult: {status}, errors={self.error_count}>"


def format_expected(expected, verbose=False):
    """
    Formats the list of expected tokens for syntax error diagnostics.
    If verbose is True, prints the full raw list of expected terminals.
    Otherwise, groups them into friendly categories ('an expression',
    'a statement', 'a relational operator', 'an arithmetic operator', etc.)
    and summarizes cleanly.
    """
    if verbose:
        return ", ".join(sorted(expected))

    exp_set = set(expected)

    RELATIONAL_OPS = {"<", ">", "<=", ">=", "==", "!="}
    ARITHMETIC_OPS = {"+", "-", "*", "/"}
    EXPR_TOKENS = {"intlit", "floatlit", "id", "("}
    STMT_TOKENS = {"int", "float", "id", "if", "while", "for", "switch", "break", "{"}

    # If the set directly matches a known category, use it immediately
    if exp_set == RELATIONAL_OPS:
        return "a relational operator"
    if exp_set == EXPR_TOKENS:
        return "an expression"
    if exp_set == STMT_TOKENS:
        return "a statement"
    if exp_set == ARITHMETIC_OPS:
        return "an arithmetic operator"

    def quote_sym(s):
        if s in {";", ",", ")", "(", ":", "{", "}", "=", "+", "-", "*", "/", "<", ">", "<=", ">=", "==", "!="}:
            return f"'{s}'"
        return s

    # If exactly 1 expected token, keep clean unquoted display (e.g. 'expected ;')
    if len(expected) == 1:
        return expected[0] if expected[0] != END else "end of input"

    # Rule of thumb: show exact tokens when there are 3 or fewer (with $ as 'end of input')
    if len(expected) <= 3:
        formatted = ["end of input" if t == END else quote_sym(t) for t in sorted(expected)]
        return ", ".join(formatted)

    # Group categories for larger sets
    items = []
    rem = set(exp_set)

    if STMT_TOKENS.issubset(rem):
        rem -= STMT_TOKENS
        items.append("a statement")

    if EXPR_TOKENS.issubset(rem):
        rem -= EXPR_TOKENS
        items.append("an expression")

    if RELATIONAL_OPS.issubset(rem):
        rem -= RELATIONAL_OPS
        items.append("a relational operator")

    if ARITHMETIC_OPS.issubset(rem):
        rem -= ARITHMETIC_OPS
        items.append("an arithmetic operator")
    elif {"+", "-"}.issubset(rem):
        rem -= {"+", "-"}
        items.append("an arithmetic operator")
    elif {"*", "/"}.issubset(rem):
        rem -= {"*", "/"}
        items.append("an arithmetic operator")

    # Specific common delimiters listed individually in natural order with quotes for readability
    punctuation_order = [";", ",", ")", ":", "{", "}", "else", "case", "default"]
    delims = []
    for p in punctuation_order:
        if p in rem:
            delims.append(quote_sym(p))
            rem.remove(p)

    items = delims + items

    for t in sorted(rem):
        if t == END:
            items.append("end of input")
        else:
            items.append(quote_sym(t))

    # If still more than 5 items, show first 4 plus 'or N more'
    if len(items) > 5:
        first_4 = items[:4]
        more_count = len(items) - 4
        return f"{', '.join(first_4)}, or {more_count} more"

    return ", ".join(items)



def parse(tokens, table, start="Program", trace=False, follow=None, first_error=False, max_errors=20, verbose_expected=False):
    """
    LL(1) table-driven predictive parser with panic-mode error recovery.

    Recovery Strategy (Panic Mode with FOLLOW-based Sync Sets):
    1. Terminal mismatch: When the top of the stack is a terminal that doesn't match
       the current input token, the parser reports the error:
       - If the expected terminal was a literal/identifier and the input is another
         value/keyword token (token substitution, e.g. 'case y:' or 'int if = 1;'),
         the invalid token is consumed and the expected terminal popped.
       - If top is EOF ($) and input has extra tokens, the extra tokens are consumed.
       - Otherwise, the terminal is popped from the stack (treated as inserted/missing,
         e.g. missing ';', ')', ':', '{').
    2. Non-terminal mismatch: When M[A, token] is empty, the parser reports the error
       and skips input tokens until reaching a token in A's synchronizing set.
       The sync set consists of FOLLOW(A), plus statement-start tokens (int, float, id,
       if, while, for, switch, break, '{', '}') and ';' to safely re-anchor at statement
       boundaries. If the non-terminal cannot expand on the sync token reached, it is
       popped from the stack.
    3. Error suppression: To prevent cascading false errors, subsequent errors are
       suppressed after recovery until at least one terminal token is successfully matched.
    4. Progress & Termination: Every recovery step either consumes an input token or
       pops a stack symbol. Reaching EOF ($) terminates cleanly.
    """
    if follow is None:
        from grammar import GRAMMAR, compute_first, compute_follow
        f = compute_first(GRAMMAR)
        follow = compute_follow(GRAMMAR, f, start)

    nonterminals = {nt for nt, _ in table}

    stack = [END, start]
    root = Node(start)
    node_stack = [None, root]

    ip = 0
    step = 1

    errors = []
    error_count = 0
    suppressed = False
    trace_records = []

    if trace:
        print(f"{'Step':<5} {'Stack':<35} {'Input':<25} {'Action'}")
        print("-" * 80)

    while stack:
        top = stack[-1]
        tok = tokens[ip]

        cur_stack = " ".join(stack)
        cur_input = " ".join(t.text for t in tokens[ip:])

        # 1. Accept condition: stack has $ and input token is $
        if top == END and tok.type == END:
            action = "accept"
            if trace:
                print(f"{step:<5} {cur_stack:<35} {cur_input:<25} {action}")
            trace_records.append({"step": step, "stack": cur_stack, "input": cur_input, "action": action})
            stack.pop()
            node_stack.pop()
            break

        # 2. Terminal match: top of stack matches current input token
        if top == tok.type:
            action = f"match {tok.text}"
            if trace:
                print(f"{step:<5} {cur_stack:<35} {cur_input:<25} {action}")
            trace_records.append({"step": step, "stack": cur_stack, "input": cur_input, "action": action})

            # Hook point: terminal matched, attach token to leaf node
            top_node = node_stack.pop()
            if top_node is not None:
                top_node.token = tok
                top_node.text = tok.text
                top_node.line = tok.line
                top_node.col = tok.col

            stack.pop()
            ip += 1
            step += 1
            # Once a terminal token matches, clear error suppression
            suppressed = False
            continue

        # 3. Nonterminal expansion: apply production from M[top, tok.type]
        if top in nonterminals:
            cell = (top, tok.type)
            if cell in table:
                prod = table[cell]
                action = f"{top} -> {' '.join(prod)}"
                if trace:
                    print(f"{step:<5} {cur_stack:<35} {cur_input:<25} {action}")
                trace_records.append({"step": step, "stack": cur_stack, "input": cur_input, "action": action})

                stack.pop()
                top_node = node_stack.pop()

                # Hook point: production applied, attach children
                if top_node is not None:
                    if prod == [EPS]:
                        top_node.children = [Node(EPS)]
                    else:
                        children = [Node(sym) for sym in prod]
                        top_node.children = children
                        for child in reversed(children):
                            node_stack.append(child)

                for sym in reversed(prod):
                    if sym != EPS:
                        stack.append(sym)
                step += 1
                continue
            else:
                # Non-terminal mismatch: panic-mode recovery
                expected = sorted([term for nt, term in table if nt == top])
                if not suppressed:
                    error_count += 1
                    err_info = _report_error(tok, expected, verbose=verbose_expected)
                    errors.append(err_info)
                    suppressed = True

                if first_error:
                    return ParseResult(False, error_count, errors, tree=None, trace=trace_records)

                if error_count >= max_errors:
                    print(f"Error limit reached ({max_errors} errors); stopping parse.")
                    break

                # Synchronizing set: FOLLOW(top) + statement anchors + ; + $
                sync_set = follow.get(top, set()) | EXTRA_SYNC

                # Skip input tokens until reaching a synchronizing token or EOF ($)
                while ip < len(tokens) and tokens[ip].type not in sync_set:
                    skip_action = f"panic: skip token '{tokens[ip].text}'"
                    if trace:
                        print(f"{step:<5} {cur_stack:<35} {' '.join(t.text for t in tokens[ip:]):<25} {skip_action}")
                    trace_records.append({"step": step, "stack": cur_stack, "input": ' '.join(t.text for t in tokens[ip:]), "action": skip_action})
                    ip += 1

                # If the nonterminal still cannot transition on the sync token reached, pop it
                if (top, tokens[ip].type) not in table:
                    pop_action = f"panic: pop non-terminal '{top}'"
                    if trace:
                        print(f"{step:<5} {cur_stack:<35} {' '.join(t.text for t in tokens[ip:]):<25} {pop_action}")
                    trace_records.append({"step": step, "stack": cur_stack, "input": ' '.join(t.text for t in tokens[ip:]), "action": pop_action})
                    stack.pop()
                    node_stack.pop()

                step += 1
                continue

        # 4. Terminal mismatch: top of stack is a terminal that doesn't match tok.type
        expected = [top]
        if not suppressed:
            error_count += 1
            err_info = _report_error(tok, expected, verbose=verbose_expected)
            errors.append(err_info)
            suppressed = True

        if first_error:
            return ParseResult(False, error_count, errors, tree=None, trace=trace_records)

        if error_count >= max_errors:
            print(f"Error limit reached ({max_errors} errors); stopping parse.")
            break

        # Extra tokens after the complete program was parsed (top is $, but tokens remain)
        if top == END and tok.type != END:
            extra_action = f"panic: skip extra token '{tok.text}'"
            if trace:
                print(f"{step:<5} {cur_stack:<35} {cur_input:<25} {extra_action}")
            trace_records.append({"step": step, "stack": cur_stack, "input": cur_input, "action": extra_action})
            ip += 1
            step += 1
            continue

        # Substituted literal or identifier token (e.g. keyword used as id, or id used as case label)
        if top in {"id", "intlit", "floatlit"} and tok.type in ({"id", "intlit", "floatlit"} | KEYWORDS):
            sub_action = f"panic: replace invalid token '{tok.text}' with '{top}'"
            if trace:
                print(f"{step:<5} {cur_stack:<35} {cur_input:<25} {sub_action}")
            trace_records.append({"step": step, "stack": cur_stack, "input": cur_input, "action": sub_action})
            stack.pop()
            node_stack.pop()
            ip += 1
            step += 1
            continue

        # Treat the expected terminal as inserted / missing; pop it and continue
        term_action = f"panic: pop terminal '{top}' (assumed inserted)"
        if trace:
            print(f"{step:<5} {cur_stack:<35} {cur_input:<25} {term_action}")
        trace_records.append({"step": step, "stack": cur_stack, "input": cur_input, "action": term_action})
        stack.pop()
        node_stack.pop()
        step += 1
        continue

    # Final summary and return status
    tree_result = root if error_count == 0 else None
    if error_count == 0:
        print("Accepted")
        return ParseResult(True, 0, errors, tree=tree_result, trace=trace_records)
    else:
        print(f"Parsing finished with {error_count} syntax error(s)")
        print("Rejected")
        return ParseResult(False, error_count, errors, tree=tree_result, trace=trace_records)


def _compute_hint(tok, expected, exp_str):
    """Computes a helpful diagnostic hint based on current token and expected set."""
    closing_map = {"}": "{", ")": "("}
    if tok.type == END and any(c in closing_map for c in expected):
        for c in expected:
            if c in closing_map:
                return f"unclosed '{closing_map[c]}'"

    if expected == [END]:
        return f"unexpected '{tok.text}' after program end (unmatched closing brace)"

    if tok.text in KEYWORDS and expected == ["id"]:
        return f"keyword '{tok.text}' cannot be used as an identifier"

    if expected == ["intlit"] and tok.type in {"id", "floatlit"}:
        return f"case label must be an integer literal, found '{tok.text}'"

    if tok.text == "if" and expected == ["{"]:
        return "'else if' is not supported; use 'else { if (...) { ... } }'"

    if tok.text == "else":
        return "'else' without matching 'if'"

    if tok.text == "-" and {"(", "floatlit", "id", "intlit"}.issubset(set(expected)):
        return "unary '-' is not supported; expression operand expected"

    if len(expected) == 1:
        return f"missing '{expected[0]}' before '{tok.text}'"

    if ")" in expected and tok.type in {"{", ";"}:
        return f"missing ')' before '{tok.text}'"

    if ";" in expected and tok.type in STMT_START:
        return f"missing ';' before '{tok.text}'"

    if set(expected) == {"!=", "<", "<=", "==", ">", ">="}:
        return "missing relational operator (e.g. '==', '<', '!=')"

    if any(op in expected for op in {"==", "!=", "<", ">", "<=", ">="}) and tok.type in {"intlit", "floatlit", "id", "("}:
        return f"missing relational operator before '{tok.text}'"

    if set(expected) == {"int", "float"}:
        return "expected type name ('int' or 'float')"

    if set(expected) == {"(", "floatlit", "id", "intlit"}:
        return f"expected expression or operand before '{tok.text}'"

    if set(expected) == {"break", "float", "for", "id", "if", "int", "switch", "while", "{"}:
        return f"expected statement before '{tok.text}'"

    if set(expected) == {"case", "default", "}"}:
        return "expected 'case', 'default', or '}'"

    return f"expected one of: {exp_str}"


def format_diagnostic(err):
    """Formats a single diagnostic dictionary into terminal message string."""
    return (
        f"Syntax error at line {err['line']}, col {err['col']}: found '{err['found']}', expected {err['expected_text']}\n"
        f"Hint: {err['hint']}"
    )


def _report_error(tok, expected, verbose=False):
    """Formats, prints, and returns a detailed syntax error record."""
    exp_str = format_expected(expected, verbose=verbose)
    hint = _compute_hint(tok, expected, exp_str)
    err = {
        "line": tok.line,
        "col": tok.col,
        "found": tok.text,
        "expected": expected,
        "expected_text": exp_str,
        "hint": hint,
    }
    print(format_diagnostic(err))
    return err

