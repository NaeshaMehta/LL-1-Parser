# treeviz.py - SVG visualizer for LL(1) parse trees
import html
import sys

# Raise recursion limit for very deep parse trees
try:
    sys.setrecursionlimit(50000)
except Exception:
    pass

from grammar import EPS


class LayoutNode:
    """Represents a laid-out node in the SVG tree."""
    def __init__(self, orig_node, is_terminal, is_epsilon, label, children=None):
        self.orig_node = orig_node
        self.is_terminal = is_terminal
        self.is_epsilon = is_epsilon
        self.label = label
        self.children = children if children is not None else []
        # Monospace width estimation: ~8px per character + padding
        self.width = max(24.0, len(label) * 8.0 + 14.0)
        self.height = 24.0
        self.needed_width = 0.0
        self.x = 0.0
        self.y = 0.0
        self.center_x = 0.0
        self.depth = 0


def format_node_label(node):
    """Formats terminal, non-terminal, or epsilon node label."""
    if node.token is not None:
        if node.token.type in ("id", "intlit", "floatlit"):
            return f"{node.token.type} ({node.token.text})"
        return str(node.token.text)
    if node.label == EPS or node.label == "ε":
        return "ε"
    return str(node.label)


def count_tree_nodes(node):
    """Recursively counts the total number of nodes in a parse tree."""
    if node is None:
        return 0
    return 1 + sum(count_tree_nodes(c) for c in node.children)


def _build_layout_tree(node, compact=False, is_root=True):
    """
    Builds the LayoutNode hierarchy.
    If compact=True, drops every ε leaf together with any non-terminal whose
    only child is ε (or whose remaining children are all dropped).
    """
    if node is None:
        return None

    is_eps = (node.label == EPS or node.label == "ε")
    is_term = (node.token is not None)

    if compact:
        if is_eps:
            return None
        if is_term:
            return LayoutNode(node, is_terminal=True, is_epsilon=False, label=format_node_label(node), children=[])

        # Non-terminal
        valid_children = []
        for c in node.children:
            cl = _build_layout_tree(c, compact=True, is_root=False)
            if cl is not None:
                valid_children.append(cl)

        if not valid_children and not is_root:
            return None

        return LayoutNode(
            node,
            is_terminal=False,
            is_epsilon=False,
            label=format_node_label(node),
            children=valid_children
        )
    else:
        label = format_node_label(node)
        c_nodes = [_build_layout_tree(c, compact=False, is_root=False) for c in node.children]
        return LayoutNode(
            node,
            is_terminal=is_term,
            is_epsilon=is_eps,
            label=label,
            children=c_nodes
        )


def _compute_needed_width(u, gap=12.0):
    """Bottom-up pass: computes minimum horizontal slice needed by node subtree."""
    if not u.children:
        u.needed_width = u.width + gap
        return u.needed_width

    ch_sum = sum(_compute_needed_width(c, gap) for c in u.children)
    u.needed_width = max(u.width + gap, ch_sum)
    return u.needed_width


def _assign_positions(u, start_x, depth=0, margin_y=20.0, level_gap=55.0):
    """
    Top-down pass: assigns horizontal positions and levels.
    Children blocks are laid out consecutively, and parent is centered
    over first and last child.
    """
    u.depth = depth
    u.y = margin_y + depth * level_gap

    if not u.children:
        u.center_x = start_x + u.needed_width / 2.0
        u.x = u.center_x - u.width / 2.0
        return

    ch_needed_sum = sum(c.needed_width for c in u.children)
    extra = u.needed_width - ch_needed_sum
    cur_x = start_x + extra / 2.0

    for c in u.children:
        _assign_positions(c, cur_x, depth + 1, margin_y, level_gap)
        cur_x += c.needed_width

    u.center_x = (u.children[0].center_x + u.children[-1].center_x) / 2.0
    u.x = u.center_x - u.width / 2.0


def _collect_render_elements(u, lines_out, nodes_out, max_depth_ref):
    """Traverses layout tree to collect all lines and node shapes."""
    if u.depth > max_depth_ref[0]:
        max_depth_ref[0] = u.depth

    nodes_out.append(u)

    for c in u.children:
        lines_out.append((u.center_x, u.y + u.height, c.center_x, c.y))
        _collect_render_elements(c, lines_out, nodes_out, max_depth_ref)


def render_tree_svg(root, compact=False):
    """
    Renders the parse tree as a clean, plain SVG string.
    If compact=True, drops every ε leaf together with any non-terminal whose
    only child is ε.
    Guarantees no overlapping node boxes at any depth level.
    """
    if root is None:
        return ""

    layout_root = _build_layout_tree(root, compact=compact, is_root=True)
    if layout_root is None:
        return ""

    gap = 12.0
    margin_x = 20.0
    margin_y = 20.0
    level_gap = 55.0

    _compute_needed_width(layout_root, gap=gap)
    _assign_positions(layout_root, margin_x, depth=0, margin_y=margin_y, level_gap=level_gap)

    lines_out = []
    nodes_out = []
    max_depth_ref = [0]
    _collect_render_elements(layout_root, lines_out, nodes_out, max_depth_ref)

    total_width = int(max(100.0, layout_root.needed_width + margin_x * 2.0))
    total_height = int(max(60.0, (max_depth_ref[0] + 1) * level_gap + margin_y * 2.0))

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_width} {total_height}" '
        f'width="{total_width}" height="{total_height}" style="background: #ffffff; display: block;">',
        '<style>',
        'line { stroke: #000000; stroke-width: 1px; }',
        '.node-box { fill: #ffffff; stroke: #000000; stroke-width: 1px; }',
        '.terminal-box { stroke-dasharray: 3,3; }',
        '.epsilon-box { stroke-dasharray: 3,3; }',
        'text { font-family: monospace; font-size: 12px; fill: #000000; text-anchor: middle; dominant-baseline: central; }',
        '.nt-text { font-weight: bold; }',
        '</style>'
    ]

    # 1. Straight lines from parent bottom to child top
    for x1, y1, x2, y2 in lines_out:
        svg_parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#000000" stroke-width="1" />')

    # 2. Node shapes (solid rect for non-terminals, dashed rect for terminals and epsilon)
    for u in nodes_out:
        if u.is_terminal:
            cls = "node-box terminal-box"
            dash = ' stroke-dasharray="3,3"'
            txt_cls = ""
        elif u.is_epsilon:
            cls = "node-box epsilon-box"
            dash = ' stroke-dasharray="3,3"'
            txt_cls = ""
        else:
            cls = "node-box"
            dash = ""
            txt_cls = ' class="nt-text" font-weight="bold"'

        svg_parts.append(
            f'<rect class="{cls}" x="{u.x:.1f}" y="{u.y:.1f}" width="{u.width:.1f}" height="{u.height:.1f}" '
            f'fill="#ffffff" stroke="#000000" stroke-width="1"{dash} />'
        )
        cy = u.y + u.height / 2.0
        escaped_label = html.escape(u.label)
        svg_parts.append(
            f'<text{txt_cls} x="{u.center_x:.1f}" y="{cy:.1f}" text-anchor="middle" dominant-baseline="central" '
            f'font-family="monospace" font-size="12" fill="#000000">{escaped_label}</text>'
        )

    svg_parts.append('</svg>')
    return "\n".join(svg_parts)
