"""The curation manifest (D45): its selection rule and its applier."""

import apply_curation
import pytest
from apply_curation import apply_manifest, build_manifest, spread_indices


def test_spread_always_takes_the_best_and_the_worst():
    """Outcome diversity is the point (D45). A rule that took the top N would
    delete every failure from the corpus, and failures are what the agent needs
    in order to recommend against repeating them."""
    picks = spread_indices(8, 4)
    assert picks[0] == 0
    assert picks[-1] == 7
    assert len(picks) == 4
    assert picks == sorted(set(picks))


def test_spread_of_two_takes_both_ends():
    assert spread_indices(8, 2) == [0, 7]


def test_spread_takes_everything_when_the_quota_covers_the_stratum():
    assert spread_indices(2, 2) == [0, 1]


def test_a_quota_larger_than_the_stratum_is_not_an_error():
    assert spread_indices(2, 5) == [0, 1]


def test_a_quota_of_one_takes_the_best():
    assert spread_indices(8, 1) == [0]


def test_spread_of_an_empty_stratum_is_empty():
    assert spread_indices(0, 4) == []


def test_the_manifest_covers_every_run_exactly_once():
    """A run missing from the manifest stays a draft forever and is silently
    absent from the corpus — invisible, because nothing errors."""
    runs = [
        {
            "id": f"r{i}",
            "model_type": "ridge",
            "experiment_name": "revenue-nowcast",
            "metrics": {"rmse": float(i)},
        }
        for i in range(8)
    ]
    manifest = build_manifest(runs, findings=[])
    ids = [entry["id"] for entry in manifest["runs"]]
    assert sorted(ids) == sorted(r["id"] for r in runs)
    assert len(ids) == len(set(ids))


def test_the_manifest_approves_the_quota_and_rejects_the_rest():
    runs = [
        {
            "id": f"r{i}",
            "model_type": "ridge",
            "experiment_name": "revenue-nowcast",
            "metrics": {"rmse": float(i)},
        }
        for i in range(8)
    ]
    manifest = build_manifest(runs, findings=[])
    approved = [e for e in manifest["runs"] if e["decision"] == "approved"]
    rejected = [e for e in manifest["runs"] if e["decision"] == "rejected"]
    assert len(approved) == 4  # QUOTAS[("revenue-nowcast", "ridge")]
    assert len(rejected) == 4
    assert all(e["reason"] for e in manifest["runs"])


def test_every_finding_is_approved():
    """All six findings are distinct sources about distinct things, and the
    three eda ones are the only route to dataset-level questions (D30)."""
    manifest = build_manifest([], findings=[{"id": "f1"}, {"id": "f2"}])
    assert [e["decision"] for e in manifest["findings"]] == ["approved", "approved"]


def test_a_run_with_no_metric_is_rejected_not_crashed():
    """A run whose tracking-store record is missing cannot be ranked within its
    stratum. Rejecting it is honest; sorting None would raise."""
    runs = [
        {"id": "r0", "model_type": "ridge", "experiment_name": "revenue-nowcast", "metrics": {}},
    ]
    manifest = build_manifest(runs, findings=[])
    assert manifest["runs"][0]["decision"] == "rejected"


def test_apply_sends_one_patch_per_entry(client):
    """Through the API (D13), so route validation is never bypassed."""
    calls: list[tuple[str, dict]] = []

    class _Recorder:
        def patch(self, url, json):
            calls.append((url, json))
            return type("R", (), {"status_code": 200, "text": ""})()

    manifest = {
        "runs": [{"id": "r1", "decision": "approved", "reason": "x"}],
        "findings": [{"id": "f1", "decision": "approved", "reason": "y"}],
    }
    approved, rejected = apply_manifest(manifest, _Recorder())
    assert approved == 2 and rejected == 0
    assert calls[0] == ("/runs/r1", {"notes_status": "approved"})
    assert calls[1] == ("/findings/f1", {"status": "approved"})


def test_apply_never_sends_note_text(client):
    """Writing text through PATCH /runs is deliberately NOT an approval (D20).
    Sending both would make the curation able to rewrite the corpus it is
    supposed to be selecting from."""
    calls: list[dict] = []

    class _Recorder:
        def patch(self, url, json):
            calls.append(json)
            return type("R", (), {"status_code": 200, "text": ""})()

    apply_manifest({"runs": [{"id": "r1", "decision": "rejected", "reason": "x"}]}, _Recorder())
    assert calls == [{"notes_status": "rejected"}]
    assert all("notes" not in call and "text" not in call for call in calls)


def test_a_failed_patch_raises_rather_than_being_counted(client):
    """A half-applied manifest is a corpus that does not match its own file.
    Failing loudly is the only way that gets noticed."""

    class _Broken:
        def patch(self, url, json):
            return type("R", (), {"status_code": 422, "text": "nope"})()

    with pytest.raises(RuntimeError, match="422"):
        apply_manifest({"runs": [{"id": "r1", "decision": "approved", "reason": "x"}]}, _Broken())


# --- Fix round 1 -------------------------------------------------------------
#
# FIX 1: GET /runs and GET /findings cap `limit` at 200 (Query(..., le=200)), so
# _plan's original limit=500 422s against the real API. FIX 2: build_manifest
# approved runs without ever checking their note text, but PATCH /runs 422s on
# an empty note (D20) — a quota-selected run with no note has to be skipped and
# warned about, not approved (which would abort apply_manifest partway through)
# or silently rejected (which would shrink the corpus without saying so). FIX 3:
# findings weren't sorted, so the manifest could differ byte-for-byte between two
# --plan runs over an identical corpus.


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakePlanClient:
    """Records every GET this fake receives, for asserting on the params
    `_plan` sends — offline, no live server, no network."""

    def __init__(self, experiments=None, runs=None, findings=None):
        self._experiments = experiments if experiments is not None else []
        self._runs = runs if runs is not None else []
        self._findings = findings if findings is not None else []
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        if url == "/experiments":
            return _FakeResponse(self._experiments)
        if url == "/runs":
            return _FakeResponse(self._runs)
        if url == "/findings":
            return _FakeResponse(self._findings)
        raise AssertionError(f"unexpected GET {url}")


def test_plan_requests_the_route_page_cap_not_500(monkeypatch, tmp_path):
    """GET /runs and GET /findings declare `Query(50, ge=1, le=200)`; a
    limit=500 request 422s before _plan ever sees the response body."""
    monkeypatch.setattr(apply_curation, "MANIFEST", tmp_path / "curation.yaml")
    fake = _FakePlanClient()
    apply_curation._plan(fake)
    assert ("/runs", {"limit": 200}) in fake.calls
    assert ("/findings", {"limit": 200}) in fake.calls


def test_plan_raises_when_runs_hits_the_page_cap(capsys):
    """Exactly 200 rows back means more may exist and this fetch may have been
    silently truncated — the same narrowing-with-no-symptom failure other
    parts of this codebase guard against on purpose."""
    runs = [
        {"id": f"r{i}", "model_type": "ridge", "experiment_id": "e1", "metrics": {}}
        for i in range(200)
    ]
    fake = _FakePlanClient(runs=runs)
    with pytest.raises(SystemExit):
        apply_curation._plan(fake)
    captured = capsys.readouterr()
    assert "200" in captured.err
    assert "page" in captured.err


def test_plan_raises_when_findings_hits_the_page_cap(capsys):
    findings = [{"id": f"f{i}"} for i in range(200)]
    fake = _FakePlanClient(findings=findings)
    with pytest.raises(SystemExit):
        apply_curation._plan(fake)
    captured = capsys.readouterr()
    assert "200" in captured.err
    assert "page" in captured.err


def test_build_manifest_skips_only_the_approval_case_for_an_empty_note(capsys):
    """D20 forbids approving an empty note (422 on PATCH /runs), so approving
    one here would abort apply_manifest partway through — that run (position 0,
    an approval pick per spread_indices(8, 4) == {0, 2, 5, 7}) is skipped and
    warned about instead. Rejecting an empty note is fine under D20, so a run
    the quota assigns to REJECTION (position 1, not a pick) keeps its ordinary
    reject decision rather than being skipped too — skipping it as well would
    leave it a draft forever with nothing to resolve it later."""
    runs = [
        {
            "id": f"r{i}",
            "model_type": "ridge",
            "experiment_name": "revenue-nowcast",
            "metrics": {"rmse": float(i)},
            "notes": {0: "", 1: "   \n"}.get(i, "a real note about this run"),
        }
        for i in range(8)
    ]
    manifest = build_manifest(runs, findings=[])
    by_id = {entry["id"]: entry for entry in manifest["runs"]}
    assert "r0" not in by_id  # position 0, an approval pick — skipped, not rejected
    assert by_id["r1"]["decision"] == "rejected"  # position 1, not a pick — rejected normally
    assert len(manifest["runs"]) == 7
    captured = capsys.readouterr()
    assert "r0" in captured.err
    assert "empty" in captured.err
    assert "r1" not in captured.err


def test_a_rejected_run_with_an_empty_note_is_rejected_not_skipped():
    """The newly-distinguished case on its own: an empty note at a
    non-approval position is not a reason to skip. Only approving an empty
    note 422s under D20 — rejecting one is fine — so this run gets an
    ordinary reject decision and the manifest still covers every run."""
    runs = [
        {
            "id": f"r{i}",
            "model_type": "ridge",
            "experiment_name": "revenue-nowcast",
            "metrics": {"rmse": float(i)},
            "notes": "" if i == 1 else "a real note about this run",
        }
        for i in range(8)
    ]
    manifest = build_manifest(runs, findings=[])
    by_id = {entry["id"]: entry for entry in manifest["runs"]}
    assert by_id["r1"]["decision"] == "rejected"
    assert len(manifest["runs"]) == 8  # nobody skipped: r1 sits at a non-pick position


def test_build_manifest_sorts_findings_by_id():
    """The API's return order is not guaranteed stable; an unsorted manifest
    would differ byte-for-byte between two --plan runs over an identical
    corpus (D45's determinism requirement)."""
    findings = [{"id": "f3"}, {"id": "f1"}, {"id": "f2"}]
    manifest = build_manifest([], findings=findings)
    assert [e["id"] for e in manifest["findings"]] == ["f1", "f2", "f3"]
