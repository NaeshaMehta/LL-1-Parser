# parser_table.py - LL(1) parsing table builder and conflict detection
from grammar import first_of_sequence, EPS

def build_table(grammar, first, follow):
    table = {}
    conflicts = []
    for nt, alts in grammar.items():
        for alt in alts:
            f_seq = first_of_sequence(alt, first, grammar)
            terms = set(f_seq) - {EPS}
            if EPS in f_seq:
                terms |= follow[nt]
            for term in sorted(terms):
                cell = (nt, term)
                if cell in table:
                    existing = table[cell]
                    if existing != alt:
                        conflicts.append((nt, term, existing, alt))
                else:
                    table[cell] = alt
    return table, conflicts

def print_table(table=None):
    if table is None:
        from grammar import GRAMMAR, compute_first, compute_follow, START
        f = compute_first(GRAMMAR)
        fo = compute_follow(GRAMMAR, f, START)
        table, _ = build_table(GRAMMAR, f, fo)
    print("PARSING TABLE")
    for (nt, term), prod in sorted(table.items()):
        print(f"  M[{nt}, {term}] = {nt} -> {' '.join(prod)}")

def print_conflicts(conflicts):
    if not conflicts:
        print("Grammar is LL(1): no conflicts")
        return
    for nt, term, p1, p2 in conflicts:
        print(f"Conflict at M[{nt}, {term}]:")
        print(f"  {nt} -> {' '.join(p1)}")
        print(f"  {nt} -> {' '.join(p2)}")
