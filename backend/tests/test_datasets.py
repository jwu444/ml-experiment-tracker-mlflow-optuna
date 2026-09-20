import datetime as dt
import io


def _csv_bytes() -> bytes:
    return b"age,income,city\n20,100,NY\n30,200,NY\n40,300,LA\n"


def test_upload_csv_persists_and_profiles(client):
    files = {"file": ("sales.csv", io.BytesIO(_csv_bytes()), "text/csv")}
    response = client.post("/datasets", files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "sales.csv"
    assert body["n_rows"] == 3
    assert body["n_cols"] == 3
    assert body["id"]


def test_get_dataset_by_id(client):
    files = {"file": ("sales.csv", io.BytesIO(_csv_bytes()), "text/csv")}
    created = client.post("/datasets", files=files).json()
    fetched = client.get(f"/datasets/{created['id']}").json()
    assert fetched["id"] == created["id"]
    assert fetched["name"] == "sales.csv"


def test_get_missing_dataset_404(client):
    assert client.get("/datasets/does-not-exist").status_code == 404


def test_reject_non_csv(client):
    files = {"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")}
    response = client.post("/datasets", files=files)
    assert response.status_code == 400


def test_reject_empty_csv(client):
    files = {"file": ("empty.csv", io.BytesIO(b"a,b\n"), "text/csv")}
    response = client.post("/datasets", files=files)
    assert response.status_code == 400


def test_upload_populates_dataset_columns(client) -> None:
    csv = "age,city\n30,NYC\n,LA\n"
    resp = client.post(
        "/datasets",
        files={"file": ("people.csv", csv, "text/csv")},
    )
    assert resp.status_code == 200
    dataset_id = resp.json()["id"]

    from app.db import get_session
    from app.models import DatasetColumn

    session = next(client.app.dependency_overrides[get_session]())
    rows = (
        session.query(DatasetColumn)
        .filter(DatasetColumn.dataset_id == dataset_id)
        .order_by(DatasetColumn.ordinal_position)
        .all()
    )
    assert [r.name for r in rows] == ["age", "city"]
    assert [r.ordinal_position for r in rows] == [0, 1]
    assert rows[0].null_count == 1  # "age" has one missing value
    assert rows[0].inferred_type  # non-empty dtype string


def test_duplicate_upload_returns_same_id(client):
    """Uploading the same file twice should return the same id."""
    files1 = {"file": ("sales.csv", io.BytesIO(_csv_bytes()), "text/csv")}
    response1 = client.post("/datasets", files=files1)
    assert response1.status_code == 200
    id1 = response1.json()["id"]

    files2 = {"file": ("sales.csv", io.BytesIO(_csv_bytes()), "text/csv")}
    response2 = client.post("/datasets", files=files2)
    assert response2.status_code == 200
    id2 = response2.json()["id"]

    assert id1 == id2


def test_same_filename_different_content_distinct_ids(client):
    """Same filename but different content should return different ids."""
    csv1 = b"age,income,city\n20,100,NY\n30,200,NY\n40,300,LA\n"
    files1 = {"file": ("data.csv", io.BytesIO(csv1), "text/csv")}
    response1 = client.post("/datasets", files=files1)
    assert response1.status_code == 200
    id1 = response1.json()["id"]

    csv2 = b"age,income,city\n25,150,SF\n35,250,LA\n45,350,NYC\n"
    files2 = {"file": ("data.csv", io.BytesIO(csv2), "text/csv")}
    response2 = client.post("/datasets", files=files2)
    assert response2.status_code == 200
    id2 = response2.json()["id"]

    assert id1 != id2


def test_same_content_different_filename_collapses(client):
    """Byte-identical content under different filenames collapses to one id —
    the hash is over content only, not filename."""
    content = b"a,b\n1,2\n"
    files1 = {"file": ("first.csv", io.BytesIO(content), "text/csv")}
    files2 = {"file": ("second.csv", io.BytesIO(content), "text/csv")}
    first = client.post("/datasets", files=files1)
    second = client.post("/datasets", files=files2)
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_duplicate_race_returns_existing(client, monkeypatch):
    """A lost race (pre-check misses, insert hits the unique constraint) still
    returns the winner via the flush -> IntegrityError -> rollback -> re-query path."""
    files = {"file": ("s.csv", io.BytesIO(_csv_bytes()), "text/csv")}
    first = client.post("/datasets", files=files).json()

    from app.routes import datasets as datasets_module

    real = datasets_module._find_by_hash
    calls = {"n": 0}

    def flaky(session, content_hash):
        calls["n"] += 1
        # First call is the pre-insert dedup check: force a miss so the INSERT
        # proceeds and trips uq_datasets_content_hash at flush().
        return None if calls["n"] == 1 else real(session, content_hash)

    monkeypatch.setattr(datasets_module, "_find_by_hash", flaky)
    files = {"file": ("s.csv", io.BytesIO(_csv_bytes()), "text/csv")}
    second = client.post("/datasets", files=files)
    assert second.status_code == 200
    assert second.json()["id"] == first["id"]


def test_list_datasets_empty(client):
    """GET /datasets with no datasets returns an empty list."""
    response = client.get("/datasets")
    assert response.status_code == 200
    assert response.json() == []


def test_list_datasets_newest_first_and_shape(client):
    """GET /datasets returns datasets ordered by created_at DESC (newest first).
    Response shape contains id, name, n_rows, n_cols but NOT content_hash."""
    from app.db import get_session
    from app.models import Dataset

    # Override session to insert datasets with explicit created_at values
    session = next(client.app.dependency_overrides[get_session]())
    d1 = Dataset(
        id="d1",
        name="first.csv",
        n_rows=10,
        n_cols=2,
        profile_json={"columns": []},
        data_csv="a,b\n1,2\n",
        content_hash="hash1",
        created_at=dt.datetime(2020, 1, 1, 10, 0, 0),
    )
    d2 = Dataset(
        id="d2",
        name="second.csv",
        n_rows=20,
        n_cols=3,
        profile_json={"columns": []},
        data_csv="a,b,c\n1,2,3\n",
        content_hash="hash2",
        created_at=dt.datetime(2020, 1, 2, 10, 0, 0),
    )
    d3 = Dataset(
        id="d3",
        name="third.csv",
        n_rows=30,
        n_cols=4,
        profile_json={"columns": []},
        data_csv="a,b,c,d\n1,2,3,4\n",
        content_hash="hash3",
        created_at=dt.datetime(2020, 1, 3, 10, 0, 0),
    )
    session.add_all([d1, d2, d3])
    session.commit()

    response = client.get("/datasets")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    # Verify newest-first ordering (d3, d2, d1)
    assert body[0]["id"] == "d3"
    assert body[1]["id"] == "d2"
    assert body[2]["id"] == "d1"
    # Verify shape: should have id, name, n_rows, n_cols but NOT content_hash
    for dataset in body:
        assert set(dataset.keys()) == {"id", "name", "n_rows", "n_cols"}
        assert "content_hash" not in dataset


def test_get_dataset_returns_columns(client):
    csv = b"ticker,revenue\nNVDA,1000\nAMD,500\n"
    upload = client.post("/datasets", files={"file": ("d.csv", io.BytesIO(csv), "text/csv")})
    dataset_id = upload.json()["id"]

    resp = client.get(f"/datasets/{dataset_id}")

    assert resp.status_code == 200
    body = resp.json()
    names = {c["name"] for c in body["columns"]}
    assert names == {"ticker", "revenue"}
    # every column reports a type and a null count, not just a name
    assert all("inferred_type" in c and "null_count" in c for c in body["columns"])
    # ordered as they appeared in the CSV, not by name or insertion luck
    assert [c["name"] for c in body["columns"]] == ["ticker", "revenue"]
