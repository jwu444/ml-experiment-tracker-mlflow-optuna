"""Runner wiring. Offline: search_runs is monkeypatched, so no Voyage and no
Postgres. What is tested here is the plumbing between retrieval and metrics —
the metric arithmetic itself is pinned in test_eval_metrics.py."""

import pytest
from eval import runner
from eval.runner import GoldenQuery, load_golden_set, render_report, run_eval


def _hit(source_type, source_id, score):
    class _H:
        pass

    h = _H()
    h.source_type, h.source_id, h.score = source_type, source_id, score
    h.snippet, h.run_id, h.experiment_id, h.dataset_id = "…", None, None, None
    return h


def test_load_reads_queries_and_freezes_their_relevant_sets(tmp_path):
    path = tmp_path / "g.yaml"
    path.write_text(
        "- id: q1\n"
        "  query: which model won?\n"
        "  relevant:\n"
        "    - [note, abc]\n"
        "    - [eda, def]\n"
        "  notes: from the leaderboard only\n"
    )
    queries = load_golden_set(path)
    assert len(queries) == 1
    assert queries[0].id == "q1"
    assert queries[0].relevant == frozenset({("note", "abc"), ("eda", "def")})


def test_load_rejects_a_query_with_no_relevant_sources(tmp_path):
    """Unanswerable, and scoring it 0.0 would drag the mean down for a
    data-entry bug."""
    path = tmp_path / "g.yaml"
    path.write_text("- id: q1\n  query: hm?\n  relevant: []\n  notes: x\n")
    with pytest.raises(ValueError, match="q1"):
        load_golden_set(path)


def test_load_rejects_duplicate_ids(tmp_path):
    """paired_mrr_delta pairs by position and id; duplicates make the pairing
    ambiguous and the sweep's comparison meaningless."""
    path = tmp_path / "g.yaml"
    path.write_text(
        "- id: q1\n  query: a\n  relevant: [[note, x]]\n  notes: ''\n"
        "- id: q1\n  query: b\n  relevant: [[note, y]]\n  notes: ''\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_golden_set(path)


def test_run_eval_ranks_sources_in_the_order_search_returned_them(monkeypatch):
    """MRR depends entirely on position, so a reordering here would be a
    silent, systematic scoring error."""
    monkeypatch.setattr(
        runner.retrieval,
        "search_runs",
        lambda session, query, **kw: (
            [_hit("eda", "c", 0.9), _hit("note", "a", 0.8), _hit("note", "b", 0.7)],
            [],
        ),
    )
    queries = [GoldenQuery("q1", "which model won?", frozenset({("note", "a")}), "")]
    scores = run_eval(session=None, queries=queries, client=None, k=8)
    assert scores[0].rr == pytest.approx(1 / 2)
    assert scores[0].precision[3] == pytest.approx(1 / 3)


def test_run_eval_passes_the_cache_client_through(monkeypatch):
    """If the client is dropped, every run pays the 3 RPM tax and the sweep is
    unusable — with no symptom except slowness."""
    seen = {}

    def _fake(session, query, **kw):
        seen.update(kw)
        return ([_hit("note", "a", 0.9)], [])

    monkeypatch.setattr(runner.retrieval, "search_runs", _fake)
    sentinel = object()
    run_eval(
        session=None,
        queries=[GoldenQuery("q1", "x", frozenset({("note", "a")}), "")],
        client=sentinel,
        k=8,
    )
    assert seen["client"] is sentinel
    assert seen["k"] == 8


def test_run_eval_scores_a_query_that_retrieved_nothing(monkeypatch):
    """An empty result is a real outcome — 0.0 across the board, not a crash."""
    monkeypatch.setattr(runner.retrieval, "search_runs", lambda *a, **k: ([], []))
    scores = run_eval(
        session=None,
        queries=[GoldenQuery("q1", "x", frozenset({("note", "a")}), "")],
        client=None,
        k=8,
    )
    assert scores[0].rr == 0.0
    assert scores[0].recall[8] == 0.0


def test_the_report_names_the_configuration_it_measured(monkeypatch):
    """A results file that does not say which config produced it cannot be
    compared to another one, which is the entire point of the sweep (D46)."""
    from eval.metrics import aggregate, score_query

    scores = [score_query("q1", [("note", "a")], {("note", "a")}, ks=(3, 5, 8))]
    report = render_report(
        scores,
        aggregate(scores),
        label="baseline",
        config={"chunk_max_chars": 1000, "chunk_overfetch": 4},
    )
    assert "chunk_max_chars" in report and "1000" in report
    assert "chunk_overfetch" in report and "4" in report
    assert "q1" in report
    assert "MRR" in report
