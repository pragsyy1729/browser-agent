"""TDD tests for url_extractor helpers in skills.py."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pytest
from skills import _extract_slugs, _build_url_extractor_successors
from schemas import NodeSpec


# ─── _extract_slugs ──────────────────────────────────────────────────────────

HF_PATTERN = r"[A-Za-z0-9_\-\.]+/[A-Za-z0-9_\-\.]+"
HF_DENYLIST = ["pipeline_tag", "sort=", "datasets/", "/spaces/", "/docs/", ".md", ".json"]

SAMPLE_CONTENT = """
Top models by likes:
  meta-llama/Llama-3.1-8B  ★ 95k
  mistralai/Mistral-7B-v0.3  ★ 80k
  google/gemma-2-9b  ★ 60k
  pipeline_tag=text-generation
  datasets/common_crawl
"""


def test_extracts_correct_count():
    slugs = _extract_slugs(SAMPLE_CONTENT, HF_PATTERN, HF_DENYLIST, 3)
    assert len(slugs) == 3


def test_extracts_correct_slugs():
    slugs = _extract_slugs(SAMPLE_CONTENT, HF_PATTERN, HF_DENYLIST, 3)
    assert slugs[0] == "meta-llama/Llama-3.1-8B"
    assert slugs[1] == "mistralai/Mistral-7B-v0.3"
    assert slugs[2] == "google/gemma-2-9b"


def test_denylist_filters_pipeline_tag():
    slugs = _extract_slugs(SAMPLE_CONTENT, HF_PATTERN, HF_DENYLIST, 10)
    assert not any("pipeline_tag" in s for s in slugs)


def test_denylist_filters_datasets():
    slugs = _extract_slugs(SAMPLE_CONTENT, HF_PATTERN, HF_DENYLIST, 10)
    assert not any("datasets" in s for s in slugs)


def test_no_duplicates():
    dup_content = "meta-llama/Llama-3 meta-llama/Llama-3 other-org/model-B"
    slugs = _extract_slugs(dup_content, HF_PATTERN, [], 10)
    assert len(slugs) == len(set(slugs))


def test_returns_fewer_when_content_sparse():
    slugs = _extract_slugs("nothing here at all", HF_PATTERN, HF_DENYLIST, 3)
    assert slugs == []


def test_count_cap_respected():
    big_content = "\n".join(f"org{i}/model-{i}" for i in range(20))
    slugs = _extract_slugs(big_content, HF_PATTERN, [], 5)
    assert len(slugs) == 5


def test_empty_denylist_passes_all():
    slugs = _extract_slugs("a/b c/d e/f", HF_PATTERN, [], 10)
    assert set(slugs) == {"a/b", "c/d", "e/f"}


# ─── _build_url_extractor_successors ─────────────────────────────────────────

META = {
    "url_template": "https://huggingface.co/{slug}",
    "detail_goal": "Extract name, likes, license.",
    "next_skill": "comparator",
}

SLUGS = ["meta-llama/Llama-3.1-8B", "mistralai/Mistral-7B-v0.3", "google/gemma-2-9b"]


def _get_successors(slugs=SLUGS, meta=META):
    return _build_url_extractor_successors(slugs, meta)


def test_successor_total_count():
    succ = _get_successors()
    # N detail browsers + 1 comparator + 1 formatter
    assert len(succ) == len(SLUGS) + 2


def test_detail_nodes_are_browser_skill():
    succ = _get_successors()
    detail_nodes = succ[: len(SLUGS)]
    assert all(s.skill == "browser" for s in detail_nodes)


def test_detail_urls_built_from_template():
    succ = _get_successors()
    urls = [s.metadata.get("url") for s in succ[: len(SLUGS)]]
    assert urls[0] == "https://huggingface.co/meta-llama/Llama-3.1-8B"
    assert urls[1] == "https://huggingface.co/mistralai/Mistral-7B-v0.3"


def test_detail_labels_are_unique():
    succ = _get_successors()
    labels = [s.metadata.get("label") for s in succ[: len(SLUGS)]]
    assert len(labels) == len(set(labels))


def test_comparator_inputs_reference_all_details():
    succ = _get_successors()
    compare_node = succ[len(SLUGS)]
    assert compare_node.skill == "comparator"
    detail_labels = [s.metadata.get("label") for s in succ[: len(SLUGS)]]
    for lbl in detail_labels:
        assert f"n:{lbl}" in compare_node.inputs


def test_formatter_inputs_include_query_and_compare():
    succ = _get_successors()
    formatter = succ[-1]
    assert formatter.skill == "formatter"
    assert "USER_QUERY" in formatter.inputs
    assert "n:compare" in formatter.inputs


def test_next_skill_override():
    meta = {**META, "next_skill": "summariser"}
    succ = _build_url_extractor_successors(SLUGS, meta)
    compare_node = succ[len(SLUGS)]
    assert compare_node.skill == "summariser"
