"""TDD tests for replay_html.py."""
import json
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pytest
import persistence
import replay_html
from schemas import AgentResult, NodeState


def _write_mock_session(tmp_path, sid, nodes: list[NodeState], query: str = "test query"):
    import networkx as nx
    session_dir = tmp_path / sid
    session_dir.mkdir(parents=True)
    (session_dir / "query.txt").write_text(query)

    g = nx.DiGraph()
    for ns in nodes:
        g.add_node(ns.node_id, skill=ns.skill, status=ns.status)
    graph_payload = nx.node_link_data(g, edges="edges")
    (session_dir / "graph.json").write_text(json.dumps(graph_payload))

    nodes_dir = session_dir / "nodes"
    nodes_dir.mkdir()
    for ns in nodes:
        idx = ns.node_id.replace("n:", "").zfill(3)
        p = nodes_dir / f"n_{idx}.json"
        p.write_text(ns.model_dump_json())


def _make_browser_node(node_id: str, url: str, content: str,
                       path: str = "a11y", actions=None) -> NodeState:
    result = AgentResult(
        success=True,
        agent_name="browser",
        output={
            "url": url,
            "goal": "extract info",
            "path": path,
            "turns": 2,
            "content": content,
            "actions": actions or [
                {"turn": 1, "action": "navigate", "element": url, "outcome": "ok"},
            ],
        },
    )
    return NodeState(node_id=node_id, skill="browser", status="complete", result=result)


def _make_formatter_node(node_id: str, answer: str = "This is the final answer.") -> NodeState:
    result = AgentResult(
        success=True,
        agent_name="formatter",
        output={"final_answer": answer},
    )
    return NodeState(node_id=node_id, skill="formatter", status="complete", result=result)


def _make_comparator_node(node_id: str) -> NodeState:
    table_md = "| Name | Likes |\n|---|---|\n| model-A | 100 |\n| model-B | 80 |"
    result = AgentResult(
        success=True,
        agent_name="comparator",
        output={"items": [{"name": "model-A"}, {"name": "model-B"}], "table_markdown": table_md},
    )
    return NodeState(node_id=node_id, skill="comparator", status="complete", result=result)


# ─── tests ───────────────────────────────────────────────────────────────────

def test_generate_html_returns_string(tmp_path, monkeypatch):
    sid = "test-01"
    monkeypatch.setattr(persistence, "SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(replay_html, "SESSIONS_ROOT", tmp_path)
    nodes = [_make_browser_node("n:1", "https://example.com", "hello world")]
    _write_mock_session(tmp_path, sid, nodes)
    html = replay_html.generate_html(sid)
    assert isinstance(html, str)
    assert len(html) > 100


def test_html_contains_user_goal(tmp_path, monkeypatch):
    sid = "test-02"
    monkeypatch.setattr(persistence, "SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(replay_html, "SESSIONS_ROOT", tmp_path)
    nodes = [_make_browser_node("n:1", "https://example.com", "content")]
    _write_mock_session(tmp_path, sid, nodes, query="find top 3 models")
    html = replay_html.generate_html(sid)
    assert "find top 3 models" in html


def test_html_contains_all_8_section_headers(tmp_path, monkeypatch):
    sid = "test-03"
    monkeypatch.setattr(persistence, "SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(replay_html, "SESSIONS_ROOT", tmp_path)
    nodes = [
        _make_browser_node("n:1", "https://example.com/list", "list content"),
        _make_browser_node("n:2", "https://example.com/detail", "detail content"),
        _make_comparator_node("n:3"),
        _make_formatter_node("n:4", "Here is the final comparison answer."),
    ]
    _write_mock_session(tmp_path, sid, nodes)
    html = replay_html.generate_html(sid)
    for section in ["User Goal", "Planner DAG", "Browser Path", "Browser Actions",
                    "Screenshots", "Extracted Data", "Comparison Table", "Cost Summary",
                    "Final Answer"]:
        assert section in html, f"Missing section: {section}"


def test_html_contains_browser_actions(tmp_path, monkeypatch):
    sid = "test-04"
    monkeypatch.setattr(persistence, "SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(replay_html, "SESSIONS_ROOT", tmp_path)
    actions = [{"turn": 1, "action": "navigate", "element": "https://example.com", "outcome": "ok"}]
    nodes = [_make_browser_node("n:1", "https://example.com", "content", actions=actions)]
    _write_mock_session(tmp_path, sid, nodes)
    html = replay_html.generate_html(sid)
    assert "navigate" in html


def test_html_contains_comparison_table(tmp_path, monkeypatch):
    sid = "test-05"
    monkeypatch.setattr(persistence, "SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(replay_html, "SESSIONS_ROOT", tmp_path)
    nodes = [
        _make_browser_node("n:1", "https://example.com", "content"),
        _make_comparator_node("n:2"),
    ]
    _write_mock_session(tmp_path, sid, nodes)
    html = replay_html.generate_html(sid)
    assert "model-A" in html
    assert "model-B" in html


def test_markdown_table_to_html(tmp_path, monkeypatch):
    md = "| Name | Likes |\n|---|---|\n| model-A | 100 |"
    html = replay_html._markdown_table_to_html(md)
    assert "<table" in html
    assert "<th>" in html or "<th " in html
    assert "model-A" in html
    assert "100" in html


def test_html_is_self_contained(tmp_path, monkeypatch):
    sid = "test-07"
    monkeypatch.setattr(persistence, "SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(replay_html, "SESSIONS_ROOT", tmp_path)
    nodes = [_make_browser_node("n:1", "https://example.com", "content")]
    _write_mock_session(tmp_path, sid, nodes)
    html = replay_html.generate_html(sid)
    assert "<html" in html
    assert "<style" in html
    assert 'href="http' not in html
    assert 'src="http' not in html


def test_html_contains_cost_summary(tmp_path, monkeypatch):
    sid = "test-08"
    monkeypatch.setattr(persistence, "SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(replay_html, "SESSIONS_ROOT", tmp_path)
    result = AgentResult(success=True, agent_name="browser",
                         output={"url": "u", "goal": "g", "path": "a11y",
                                 "turns": 3, "content": "c", "actions": []},
                         elapsed_s=1.23)
    ns = NodeState(node_id="n:1", skill="browser", status="complete", result=result)
    _write_mock_session(tmp_path, sid, [ns])
    html = replay_html.generate_html(sid)
    assert "Cost Summary" in html or "cost" in html.lower()
    assert "browser" in html.lower()
