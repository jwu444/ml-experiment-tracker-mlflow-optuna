import app.routes.datasets as datasets_route
import pytest
from app.loop import LoopResult

_CSV = "ticker,quarter_end,revenue,revenue_next\nAAPL,2015-03-31,100,150\nMSFT,2015-06-30,200,250\n"


def _fake_loop(monkeypatch, text="Revenue is right-skewed across both tickers.") -> None:
    def fake_run_loop(datasets, dfs, prior_messages, question, *, client=None):
        # The route must hand the loop the dataset it was asked about, profiled.
        assert len(datasets) == 1
        assert datasets[0]["profile"]["columns"]
        return LoopResult(interpretation=text, pass_count=2, judge_score=85)

    monkeypatch.setattr(datasets_route, "run_loop", fake_run_loop)


def _upload(client) -> str:
    return client.post("/datasets", files={"file": ("panel.csv", _CSV, "text/csv")}).json()["id"]


def test_eda_creates_a_draft_finding(client, monkeypatch) -> None:
    _fake_loop(monkeypatch)
    dataset_id = _upload(client)
    resp = client.post(f"/datasets/{dataset_id}/eda")
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "draft"
    assert body["source_type"] == "eda"
    assert body["source_id"] == dataset_id
    assert body["text"] == "Revenue is right-skewed across both tickers."


def test_eda_finding_is_readable_through_the_findings_api(client, monkeypatch) -> None:
    _fake_loop(monkeypatch)
    dataset_id = _upload(client)
    finding_id = client.post(f"/datasets/{dataset_id}/eda").json()["finding_id"]
    listed = client.get("/findings?source_type=eda").json()
    assert [f["id"] for f in listed] == [finding_id]
    assert listed[0]["original_text"] == listed[0]["text"]


def test_eda_on_an_unknown_dataset_is_404(client, monkeypatch) -> None:
    _fake_loop(monkeypatch)
    resp = client.post("/datasets/no-such-id/eda")
    assert resp.status_code == 404


def test_eda_writes_no_finding_when_the_loop_fails(client, monkeypatch) -> None:
    """A loop failure surfaces exactly as it does on /chats — unwrapped. The
    guarantee this test pins is the other half: no partial finding is written,
    because `create_finding` is only reached after the loop returns."""

    def boom(datasets, dfs, prior_messages, question, *, client=None):
        raise RuntimeError("anthropic exploded")

    monkeypatch.setattr(datasets_route, "run_loop", boom)
    dataset_id = _upload(client)
    with pytest.raises(RuntimeError):
        client.post(f"/datasets/{dataset_id}/eda")
    assert client.get("/findings").json() == []


def test_eda_never_inserts_the_dataset_twice(client, monkeypatch) -> None:
    """D13: the EDA path reads `datasets`, it does not write to it."""
    _fake_loop(monkeypatch)
    dataset_id = _upload(client)
    client.post(f"/datasets/{dataset_id}/eda")
    assert len(client.get("/datasets").json()) == 1
