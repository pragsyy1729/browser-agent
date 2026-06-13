"""Generate a self-contained HTML replay report for one session.

Usage:
    python replay_html.py <session_id>
    python replay_html.py <session_id> > replay_<sid>.html

All screenshots are embedded as base64 data URIs so the file is
fully portable with no external dependencies.
"""
from __future__ import annotations

import base64
import html as html_lib
import json
import sys
from pathlib import Path

import networkx as nx
import persistence
from persistence import SessionStore
from schemas import NodeState

SESSIONS_ROOT = persistence.SESSIONS_ROOT


# ─── data loading ────────────────────────────────────────────────────────────

def _load_session(sid: str) -> tuple[str, list[NodeState]]:
    store = SessionStore(sid)
    query = store.read_query() or ""
    nodes = store.read_all_nodes()
    return query, nodes


def _find_screenshots(sid: str) -> list[Path]:
    root = SESSIONS_ROOT / sid / "browser"
    if not root.exists():
        return []
    pngs = sorted(root.glob("**/*.png"))
    return pngs


# ─── DAG rendering ───────────────────────────────────────────────────────────

_STATUS_COLOR = {
    "complete": "#2e7d32",   # green
    "failed":   "#c62828",   # red
    "running":  "#1565c0",   # blue
    "skipped":  "#757575",   # grey
    "pending":  "#e0e0e0",   # light grey
}
_STATUS_TEXT_COLOR = {
    "complete": "#fff", "failed": "#fff", "running": "#fff",
    "skipped": "#fff",  "pending": "#333",
}


def _dag_svg(sid: str, nodes: list[NodeState]) -> str:
    """Render the session DAG as an inline SVG with edges and coloured node boxes."""
    # Load graph edges from graph.json
    graph_path = SESSIONS_ROOT / sid / "graph.json"
    edges: list[tuple[str, str]] = []
    if graph_path.exists():
        try:
            payload = json.loads(graph_path.read_text())
            g = nx.node_link_graph(payload, edges="edges", directed=True)
            edges = list(g.edges())
        except Exception:
            pass

    # Build node id → NodeState map
    ns_map = {ns.node_id: ns for ns in nodes}
    all_node_ids = [ns.node_id for ns in sorted(nodes, key=lambda n: n.node_id)]

    if not all_node_ids:
        return "<p>(no nodes)</p>"

    # Assign layers via longest-path ranking (topological generations)
    g_layout = nx.DiGraph()
    g_layout.add_nodes_from(all_node_ids)
    for u, v in edges:
        if u in ns_map and v in ns_map:
            g_layout.add_edge(u, v)

    # Topological generations → assign each node a column (depth) and row
    try:
        gens = list(nx.topological_generations(g_layout))
    except nx.NetworkXUnfeasible:
        gens = [[nid] for nid in all_node_ids]

    BOX_W, BOX_H = 140, 50
    GAP_X, GAP_Y = 60, 30
    PAD = 20

    # Position: column = generation index, row = position within generation
    pos: dict[str, tuple[int, int]] = {}
    for col_idx, gen in enumerate(gens):
        for row_idx, nid in enumerate(sorted(gen)):
            x = PAD + col_idx * (BOX_W + GAP_X)
            y = PAD + row_idx * (BOX_H + GAP_Y)
            pos[nid] = (x, y)

    max_x = max(x + BOX_W for x, _ in pos.values()) + PAD
    max_y = max(y + BOX_H for _, y in pos.values()) + PAD

    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{max_x}" height="{max_y}" style="font-family:sans-serif;font-size:12px">']

    # Arrow marker
    lines.append(
        '<defs><marker id="arr" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">'
        '<polygon points="0 0, 8 3, 0 6" fill="#555"/></marker></defs>'
    )

    # Draw edges
    for u, v in edges:
        if u not in pos or v not in pos:
            continue
        ux, uy = pos[u]
        vx, vy = pos[v]
        x1 = ux + BOX_W
        y1 = uy + BOX_H // 2
        x2 = vx
        y2 = vy + BOX_H // 2
        mx = (x1 + x2) // 2
        lines.append(
            f'<path d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" '
            f'fill="none" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>'
        )

    # Draw nodes
    for nid in all_node_ids:
        ns = ns_map[nid]
        x, y = pos[nid]
        fill  = _STATUS_COLOR.get(ns.status, "#e0e0e0")
        tcolor = _STATUS_TEXT_COLOR.get(ns.status, "#333")
        label1 = html_lib.escape(nid)
        label2 = html_lib.escape(ns.skill)
        icon   = {"complete": "✓", "failed": "✗", "running": "…", "skipped": "–", "pending": "○"}.get(ns.status, "?")
        lines.append(
            f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="6" ry="6" '
            f'fill="{fill}" stroke="#333" stroke-width="1"/>'
        )
        lines.append(
            f'<text x="{x + BOX_W//2}" y="{y + 18}" text-anchor="middle" '
            f'fill="{tcolor}" font-weight="bold">{icon} {label1}</text>'
        )
        lines.append(
            f'<text x="{x + BOX_W//2}" y="{y + 36}" text-anchor="middle" '
            f'fill="{tcolor}">{label2}</text>'
        )

    lines.append("</svg>")

    # Append legend
    legend_parts = []
    for status, color in _STATUS_COLOR.items():
        tc = _STATUS_TEXT_COLOR[status]
        legend_parts.append(
            f'<span style="background:{color};color:{tc};padding:2px 8px;border-radius:4px;'
            f'font-size:.8rem;margin-right:6px">{status}</span>'
        )
    legend = '<div style="margin-top:.5rem">' + "".join(legend_parts) + "</div>"
    return "\n".join(lines) + legend


# ─── table conversion ────────────────────────────────────────────────────────

def _markdown_table_to_html(md: str) -> str:
    lines = [l.strip() for l in md.strip().splitlines() if l.strip()]
    if not lines:
        return ""
    rows = []
    for line in lines:
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows.append(cells)
    if not rows:
        return f"<pre>{html_lib.escape(md)}</pre>"

    out = ["<table>"]
    header_row = rows[0]
    out.append("<thead><tr>")
    for cell in header_row:
        out.append(f"<th>{html_lib.escape(cell)}</th>")
    out.append("</tr></thead>")
    out.append("<tbody>")
    for row in rows[2:]:  # skip separator row (row index 1)
        out.append("<tr>")
        for cell in row:
            out.append(f"<td>{html_lib.escape(cell)}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


# ─── section builders ────────────────────────────────────────────────────────

def _section(title: str, body: str) -> str:
    return (
        f'<section>\n'
        f'<h2>{html_lib.escape(title)}</h2>\n'
        f'{body}\n'
        f'</section>\n'
    )


def _pre(text: str) -> str:
    return f"<pre>{html_lib.escape(text)}</pre>"


def _build_sections(sid: str, query: str, nodes: list[NodeState]) -> list[str]:
    sections: list[str] = []

    # §1 User Goal
    sections.append(_section("§1 User Goal", f"<p>{html_lib.escape(query)}</p>"))

    # §2 Planner DAG
    sections.append(_section("§2 Planner DAG", _dag_svg(sid, nodes)))

    # §3 Browser Paths
    path_lines = []
    for ns in nodes:
        if ns.skill == "browser" and ns.result and ns.result.output:
            out = ns.result.output
            url = out.get("url", "?")
            cascade = out.get("path", "?")
            path_lines.append(f"{ns.node_id}: {url}  →  cascade={cascade}")
    sections.append(_section(
        "§3 Browser Path",
        _pre("\n".join(path_lines) if path_lines else "(no browser nodes)"),
    ))

    # §4 Browser Actions
    action_rows: list[str] = []
    for ns in nodes:
        if ns.skill == "browser" and ns.result and ns.result.output:
            actions = ns.result.output.get("actions") or []
            for act in actions:
                turn    = act.get("turn", "")
                action  = act.get("action", "")
                element = act.get("element", "")
                outcome = act.get("outcome", "")
                action_rows.append(
                    f"<tr><td>{html_lib.escape(ns.node_id)}</td>"
                    f"<td>{html_lib.escape(str(turn))}</td>"
                    f"<td>{html_lib.escape(str(action))}</td>"
                    f"<td>{html_lib.escape(str(element)[:80])}</td>"
                    f"<td>{html_lib.escape(str(outcome))}</td></tr>"
                )
    if action_rows:
        table = (
            "<table><thead><tr><th>Node</th><th>Turn</th><th>Action</th>"
            "<th>Element</th><th>Outcome</th></tr></thead><tbody>"
            + "".join(action_rows)
            + "</tbody></table>"
        )
    else:
        table = "<p>(no browser actions recorded)</p>"
    sections.append(_section("§4 Browser Actions", table))

    # §5 Screenshots
    screenshots = _find_screenshots(sid)
    img_tags: list[str] = []
    for png in screenshots:
        try:
            data = base64.b64encode(png.read_bytes()).decode()
            img_tags.append(
                f'<figure>'
                f'<img src="data:image/png;base64,{data}" alt="{html_lib.escape(png.name)}" style="max-width:100%;border:1px solid #ccc">'
                f'<figcaption>{html_lib.escape(str(png.relative_to(SESSIONS_ROOT / sid)))}</figcaption>'
                f'</figure>'
            )
        except Exception:
            pass
    sections.append(_section(
        "§5 Screenshots",
        "".join(img_tags) if img_tags else "<p>(no screenshots found)</p>",
    ))

    # §6 Extracted Data
    data_parts: list[str] = []
    for ns in nodes:
        if ns.skill == "browser" and ns.result and ns.result.output:
            content = ns.result.output.get("content") or ""
            snippet = content[:500] + ("…" if len(content) > 500 else "")
            url = ns.result.output.get("url", "")
            data_parts.append(
                f"<h3>{html_lib.escape(ns.node_id)} — {html_lib.escape(url)}</h3>"
                + _pre(snippet)
            )
    sections.append(_section(
        "§6 Extracted Data",
        "".join(data_parts) if data_parts else "<p>(no extracted data)</p>",
    ))

    # §7 Comparison Table
    comparison_html = "<p>(no comparator output found)</p>"
    for ns in nodes:
        if ns.skill == "comparator" and ns.result and ns.result.output:
            table_md = ns.result.output.get("table_markdown", "")
            if table_md:
                comparison_html = _markdown_table_to_html(table_md)
                break
            items = ns.result.output.get("items")
            if items:
                comparison_html = _pre(json.dumps(items, indent=2))
                break
    sections.append(_section("§7 Comparison Table", comparison_html))

    # §8 Cost Summary
    summary_rows: list[str] = []
    total_elapsed = 0.0
    for ns in nodes:
        elapsed = (ns.result.elapsed_s if ns.result else 0.0) or 0.0
        total_elapsed += elapsed
        provider = (ns.result.provider if ns.result else "") or ""
        turns = ""
        if ns.skill == "browser" and ns.result and ns.result.output:
            turns = str(ns.result.output.get("turns", ""))
        summary_rows.append(
            f"<tr><td>{html_lib.escape(ns.node_id)}</td>"
            f"<td>{html_lib.escape(ns.skill)}</td>"
            f"<td>{html_lib.escape(ns.status)}</td>"
            f"<td>{elapsed:.2f}s</td>"
            f"<td>{html_lib.escape(provider)}</td>"
            f"<td>{html_lib.escape(turns)}</td></tr>"
        )
    cost_table = (
        "<p><strong>Total nodes:</strong> "
        + str(len(nodes))
        + f"&nbsp;&nbsp;<strong>Total elapsed:</strong> {total_elapsed:.2f}s</p>"
        + "<table><thead><tr><th>Node</th><th>Skill</th><th>Status</th>"
        + "<th>Elapsed</th><th>Provider</th><th>Turns</th></tr></thead><tbody>"
        + "".join(summary_rows)
        + "</tbody></table>"
    )
    sections.append(_section("§8 Cost Summary", cost_table))

    # §9 Final Answer
    final_answer_html = "<p>(no formatter output found)</p>"
    # Walk nodes in reverse so we pick the last completed formatter
    for ns in reversed(nodes):
        if ns.skill == "formatter" and ns.status == "complete" and ns.result and ns.result.output:
            fa = ns.result.output.get("final_answer") or ""
            if fa:
                # Render markdown tables inside the final answer
                lines = fa.split("\n")
                rendered_lines: list[str] = []
                table_buf: list[str] = []
                for line in lines:
                    if line.strip().startswith("|"):
                        table_buf.append(line)
                    else:
                        if table_buf:
                            rendered_lines.append(_markdown_table_to_html("\n".join(table_buf)))
                            table_buf = []
                        rendered_lines.append(f"<p>{html_lib.escape(line)}</p>" if line.strip() else "")
                if table_buf:
                    rendered_lines.append(_markdown_table_to_html("\n".join(table_buf)))
                final_answer_html = (
                    f'<div class="final-answer">{"".join(rendered_lines)}</div>'
                )
                break
    sections.append(_section("§9 Final Answer", final_answer_html))

    return sections


# ─── main assembler ──────────────────────────────────────────────────────────

_CSS = """
body { font-family: sans-serif; margin: 2rem auto; max-width: 960px; color: #222; }
h1   { border-bottom: 2px solid #333; padding-bottom: .4rem; }
h2   { background: #f0f0f0; padding: .4rem .8rem; border-left: 4px solid #666; margin-top: 2rem; }
h3   { color: #555; }
pre  { background: #fafafa; border: 1px solid #ddd; padding: 1rem; overflow-x: auto;
       white-space: pre-wrap; font-size: .85rem; }
table{ border-collapse: collapse; width: 100%; margin: 1rem 0; }
th,td{ border: 1px solid #ccc; padding: .4rem .7rem; text-align: left; font-size: .9rem; }
th   { background: #e8e8e8; }
figure{ margin: 1rem 0; }
figcaption{ font-size: .75rem; color: #888; }
.final-answer { background:#f9fbe7; border:2px solid #aed581; border-radius:6px;
                padding:1.2rem 1.5rem; line-height:1.7; }
.final-answer p { margin:.4rem 0; }
.final-answer table { margin:.8rem 0; }
"""


def generate_html(sid: str) -> str:
    query, nodes = _load_session(sid)
    sections = _build_sections(sid, query, nodes)
    body = "\n".join(sections)
    return (
        "<!DOCTYPE html>\n"
        "<html lang='en'>\n"
        "<head>\n"
        "<meta charset='utf-8'>\n"
        f"<title>Replay — {html_lib.escape(sid)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"<h1>Agent Replay — Session <code>{html_lib.escape(sid)}</code></h1>\n"
        + body
        + "\n</body>\n</html>\n"
    )


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python replay_html.py <session_id>", file=sys.stderr)
        sys.exit(1)
    sid = sys.argv[1]
    out_path = Path(f"replay_{sid}.html")
    html = generate_html(sid)
    out_path.write_text(html, encoding="utf-8")
    print(f"Written: {out_path}")
