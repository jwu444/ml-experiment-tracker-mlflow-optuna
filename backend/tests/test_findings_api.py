import uuid

from app import findings
from app.models import Dataset


def _dataset_and_finding(db_session, text="draft text"):
    """Insert through the same DB the `client` fixture's app reads/writes.

    `client` and `db_session` both depend on the (function-scoped) `db_engine`
    fixture, so within one test they share the same SQLite file — see
    conftest.py's `db_session` docstring for the established pattern. The
    brief's original helper reached into `app.main.app.dependency_overrides`,
    but `client` builds its own local `create_app(init_on_startup=False)`
    instance rather than overriding the module-level singleton, so that
    lookup raises KeyError; `db_session` is the fixture already used
    elsewhere in this suite for exactly this "insert a row the route will
    see" need. `content_hash` is unique on `datasets`, so it must vary per
    call — the brief's hardcoded "h1" collides the moment a test creates two
    datasets (test_list_findings_returns_newest_first).
    """
    dataset = Dataset(
        name="d.csv",
        data_csv="a,b\n1,2\n",
        profile_json={},
        content_hash=uuid.uuid4().hex,
        n_rows=1,
        n_cols=2,
    )
    db_session.add(dataset)
    db_session.flush()
    row = findings.create_finding(db_session, "eda", dataset.id, text)
    db_session.commit()
    return dataset.id, row.id


def test_list_findings_returns_newest_first(client, db_session) -> None:
    _dataset_and_finding(db_session, "first")
    _dataset_and_finding(db_session, "second")
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_findings_filters_by_status(client, db_session) -> None:
    _, finding_id = _dataset_and_finding(db_session)
    client.patch(f"/findings/{finding_id}", json={"status": "approved"})
    assert len(client.get("/findings?status=approved").json()) == 1
    assert client.get("/findings?status=draft").json() == []


def test_list_findings_filters_by_source_type(client, db_session) -> None:
    _dataset_and_finding(db_session)
    assert len(client.get("/findings?source_type=eda").json()) == 1
    assert client.get("/findings?source_type=diagnostic").json() == []


def test_list_findings_filters_by_source_id(client, db_session) -> None:
    """Two datasets, so the filter has something to exclude.

    One dataset is the cardinality-1 case every source_id filter passes by
    accident: with a single row in the table, returning everything and
    returning the right thing are the same answer.
    """
    mine, mine_finding = _dataset_and_finding(db_session, "about my dataset")
    theirs, _ = _dataset_and_finding(db_session, "about the other one")

    rows = client.get(f"/findings?source_id={mine}").json()
    assert [r["id"] for r in rows] == [mine_finding]
    assert [r["text"] for r in rows] == ["about my dataset"]

    assert len(client.get(f"/findings?source_id={theirs}").json()) == 1
    assert client.get("/findings?source_id=no-such-id").json() == []


def test_source_id_composes_with_the_other_filters(client, db_session) -> None:
    """The inline panels send source_id AND status together — an approved-only
    view of one dataset must not fall back to every dataset's approved rows."""
    mine, mine_finding = _dataset_and_finding(db_session)
    theirs, theirs_finding = _dataset_and_finding(db_session)
    client.patch(f"/findings/{mine_finding}", json={"status": "approved"})
    client.patch(f"/findings/{theirs_finding}", json={"status": "approved"})

    rows = client.get(f"/findings?source_id={mine}&status=approved").json()
    assert [r["id"] for r in rows] == [mine_finding]
    assert client.get(f"/findings?source_id={mine}&status=draft").json() == []
    assert len(client.get(f"/findings?source_id={theirs}&status=approved").json()) == 1


def test_patch_text_alone_does_not_approve(client, db_session) -> None:
    _, finding_id = _dataset_and_finding(db_session)
    resp = client.patch(f"/findings/{finding_id}", json={"text": "edited"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "edited"
    assert body["status"] == "draft"
    assert body["original_text"] == "draft text"


def test_patch_can_approve_explicitly(client, db_session) -> None:
    _, finding_id = _dataset_and_finding(db_session)
    resp = client.patch(f"/findings/{finding_id}", json={"text": "edited", "status": "approved"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


def test_approving_empty_finding_is_422(client, db_session) -> None:
    _, finding_id = _dataset_and_finding(db_session, text="  ")
    resp = client.patch(f"/findings/{finding_id}", json={"status": "approved"})
    assert resp.status_code == 422


def test_patch_unknown_finding_is_404(client) -> None:
    resp = client.patch("/findings/nope", json={"text": "x"})
    assert resp.status_code == 404
