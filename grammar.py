"""
grammar.py - LL(1) grammar for the C-subset language, with FIRST/FOLLOW
computation.

Run:  python grammar.py
"""

EPS = "ε"   # epsilon (empty string)
END = "$"   # end-of-input marker

START = "Program"

# Each nonterminal maps to a list of alternatives; each alternative is a list
# of symbols. Any symbol that is not a key of GRAMMAR is a terminal.
GRAMMAR = {
    "Program":       [["StmtList"]],
    "StmtList":      [["Stmt", "StmtList"], [EPS]],
    "Stmt":          [["Decl"], ["Assign"], ["IfStmt"], ["WhileStmt"], ["Block"], ["ForStmt"], ["SwitchStmt"], ["BreakStmt"]],

    # for loops
    "ForStmt":       [["for", "(", "ForInit", ";", "Cond", ";", "ForStep", ")", "Block"]],
    "ForInit":       [["id", "=", "Expr"], [EPS]],
    "ForStep":       [["id", "=", "Expr"], [EPS]],

    # switch-case
    "SwitchStmt":    [["switch", "(", "Expr", ")", "{", "CaseList", "DefaultPart", "}"]],
    "CaseList":      [["Case", "CaseList"], [EPS]],
    "Case":          [["case", "intlit", ":", "StmtList"]],
    "DefaultPart":   [["default", ":", "StmtList"], [EPS]],
    "BreakStmt":     [["break", ";"]],

    # declarations:  int x;   int a = 1, b;   float f = 2.5;
    "Decl":          [["Type", "DeclList", ";"]],
    "Type":          [["int"], ["float"]],
    "DeclList":      [["Declarator", "DeclListTail"]],
    "DeclListTail":  [[",", "Declarator", "DeclListTail"], [EPS]],
    "Declarator":    [["id", "DeclInit"]],
    "DeclInit":      [["=", "Expr"], [EPS]],

    # assignment:  x = expr;
    "Assign":        [["id", "=", "Expr", ";"]],

    # control flow (braces are mandatory; no 'else if')
    "IfStmt":        [["if", "(", "Cond", ")", "Block", "ElsePart"]],
    "ElsePart":      [["else", "Block"], [EPS]],
    "WhileStmt":     [["while", "(", "Cond", ")", "Block"]],
    "Block":         [["{", "StmtList", "}"]],

    # conditions
    "Cond":          [["Expr", "RelOp", "Expr"]],
    "RelOp":         [["<"], [">"], ["<="], [">="], ["=="], ["!="]],

    # expressions (left recursion removed, no unary minus)
    "Expr":          [["Term", "ExprPrime"]],
    "ExprPrime":     [["+", "Term", "ExprPrime"], ["-", "Term", "ExprPrime"], [EPS]],
    "Term":          [["Factor", "TermPrime"]],
    "TermPrime":     [["*", "Factor", "TermPrime"], ["/", "Factor", "TermPrime"], [EPS]],
    "Factor":        [["(", "Expr", ")"], ["id"], ["intlit"], ["floatlit"]],
}


def first_of_sequence(seq, first, grammar):
    """FIRST of a string of symbols. Contains EPS iff the whole string can vanish."""
    result = set()
    for sym in seq:
        if sym == EPS:
            continue
        if sym not in grammar:            # terminal
            result.add(sym)
            return result
        result |= first[sym] - {EPS}
        if EPS not in first[sym]:
            return result
    result.add(EPS)
    return result


def compute_first(grammar):
    first = {nt: set() for nt in grammar}
    changed = True
    while changed:
        changed = False
        for nt, alts in grammar.items():
            for alt in alts:
                new = first_of_sequence(alt, first, grammar)
                if not new <= first[nt]:
                    first[nt] |= new
                    changed = True
    return first


def compute_follow(grammar, first, start=START):
    follow = {nt: set() for nt in grammar}
    follow[start].add(END)
    changed = True
    while changed:
        changed = False
        for nt, alts in grammar.items():
            for alt in alts:
                for i, sym in enumerate(alt):
                    if sym not in grammar:
                        continue
                    beta_first = first_of_sequence(alt[i + 1:], first, grammar)
                    add = beta_first - {EPS}
                    if EPS in beta_first:       # beta can vanish (or is empty)
                        add |= follow[nt]
                    if not add <= follow[sym]:
                        follow[sym] |= add
                        changed = True
    return follow


def fmt(alt):
    return " ".join(alt)


def print_grammar(grammar):
    print("GRAMMAR")
    width = max(len(nt) for nt in grammar)
    for nt, alts in grammar.items():
        print(f"  {nt:<{width}} -> {' | '.join(fmt(a) for a in alts)}")


def analyse(grammar=GRAMMAR, start=START):
    first = compute_first(grammar)
    follow = compute_follow(grammar, first, start)

    print_grammar(grammar)

    print("\nFIRST sets")
    for nt in grammar:
        print(f"  FIRST({nt}) = {{ {', '.join(sorted(first[nt]))} }}")

    print("\nFOLLOW sets")
    for nt in grammar:
        print(f"  FOLLOW({nt}) = {{ {', '.join(sorted(follow[nt]))} }}")

    return first, follow


if __name__ == "__main__":
    analyse()