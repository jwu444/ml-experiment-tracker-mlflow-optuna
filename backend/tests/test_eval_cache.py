"""The eval's query-vector cache. Offline: the inner client is a fake."""

import json

import pytest
from app.embeddings import embed_texts
from app.models import EMBEDDING_DIM
from eval.cache import CachingVoyageClient


class _FakeVoyage:
    """Records every call so the tests can assert on what was NOT sent."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts, *, model, input_type, output_dimension):
        self.calls.append(list(texts))
        return type("R", (), {"embeddings": [[0.5] * output_dimension for _ in texts]})()


def test_a_miss_calls_through_and_a_hit_does_not(tmp_path):
    inner = _FakeVoyage()
    cache = CachingVoyageClient(tmp_path / "c.json", inner=inner)

    first = cache.embed(["ridge"], model="voyage-4", input_type="query", output_dimension=4)
    second = cache.embed(["ridge"], model="voyage-4", input_type="query", output_dimension=4)

    assert first.embeddings == second.embeddings
    assert len(inner.calls) == 1
    assert cache.hits == 1 and cache.misses == 1


def test_only_the_uncached_texts_are_sent(tmp_path):
    """A partially-cached batch must not re-send what it already holds, or the
    rate limit is hit for text the cache already has."""
    inner = _FakeVoyage()
    cache = CachingVoyageClient(tmp_path / "c.json", inner=inner)
    cache.embed(["a"], model="m", input_type="query", output_dimension=2)
    cache.embed(["a", "b"], model="m", input_type="query", output_dimension=2)
    assert inner.calls == [["a"], ["b"]]


def test_results_come_back_in_the_requested_order(tmp_path):
    """Merging cached and freshly-embedded vectors must preserve input order —
    a silent transposition would mislabel every query's vector."""
    inner = _FakeVoyage()
    cache = CachingVoyageClient(tmp_path / "c.json", inner=inner)
    cache.embed(["b"], model="m", input_type="query", output_dimension=2)

    def positional(texts, *, model, input_type, output_dimension):
        inner.calls.append(list(texts))
        return type("R", (), {"embeddings": [[float(len(t))] * output_dimension for t in texts]})()

    inner.embed = positional
    resp = cache.embed(["a", "b", "ccc"], model="m", input_type="query", output_dimension=2)
    assert resp.embeddings[0] == [1.0, 1.0]
    assert resp.embeddings[2] == [3.0, 3.0]


def test_the_model_name_is_part_of_the_key(tmp_path):
    """Two models' vectors are not comparable (D14). Changing the model must
    miss, not serve the previous model's vectors."""
    inner = _FakeVoyage()
    cache = CachingVoyageClient(tmp_path / "c.json", inner=inner)
    cache.embed(["ridge"], model="voyage-4", input_type="query", output_dimension=2)
    cache.embed(["ridge"], model="voyage-3", input_type="query", output_dimension=2)
    assert len(inner.calls) == 2


def test_the_input_type_is_part_of_the_key(tmp_path):
    """Voyage's models are trained with document/query asymmetry (D29); one
    stored under the other's key would cost recall with no symptom."""
    inner = _FakeVoyage()
    cache = CachingVoyageClient(tmp_path / "c.json", inner=inner)
    cache.embed(["ridge"], model="m", input_type="query", output_dimension=2)
    cache.embed(["ridge"], model="m", input_type="document", output_dimension=2)
    assert len(inner.calls) == 2


def test_the_cache_survives_a_reload(tmp_path):
    path = tmp_path / "c.json"
    inner = _FakeVoyage()
    first = CachingVoyageClient(path, inner=inner)
    first.embed(["ridge"], model="m", input_type="query", output_dimension=2)
    first.save()

    second = CachingVoyageClient(path, inner=inner)
    second.embed(["ridge"], model="m", input_type="query", output_dimension=2)
    assert len(inner.calls) == 1
    assert second.hits == 1


def test_a_corrupt_cache_file_is_ignored_not_fatal(tmp_path):
    """A half-written file must cost a slow run, never a crash that looks like
    a retrieval bug."""
    path = tmp_path / "c.json"
    path.write_text("{not json")
    cache = CachingVoyageClient(path, inner=_FakeVoyage())
    resp = cache.embed(["ridge"], model="m", input_type="query", output_dimension=2)
    assert len(resp.embeddings) == 1


def test_save_writes_readable_json(tmp_path):
    path = tmp_path / "c.json"
    cache = CachingVoyageClient(path, inner=_FakeVoyage())
    cache.embed(["ridge"], model="m", input_type="query", output_dimension=2)
    cache.save()
    assert len(json.loads(path.read_text())) == 1


def test_a_crash_after_the_first_call_does_not_lose_it(tmp_path):
    """A cold 20-query run at 3 RPM dies to a transient connection error as a
    matter of course. If the cache only persists at the very end, that crash
    discards every vector already paid for. It must instead save after each
    successful inner call, so a crash on call N still leaves calls 1..N-1 on
    disk for the next attempt to pick up for free."""
    path = tmp_path / "c.json"

    class _FlakyVoyage:
        def __init__(self):
            self.calls = 0

        def embed(self, texts, *, model, input_type, output_dimension):
            self.calls += 1
            if self.calls == 2:
                raise ConnectionError("Connection reset by peer")
            return type("R", (), {"embeddings": [[0.5] * output_dimension for _ in texts]})()

    cache = CachingVoyageClient(path, inner=_FlakyVoyage())
    cache.embed(["ridge"], model="m", input_type="query", output_dimension=2)  # call 1: ok
    with pytest.raises(ConnectionError):
        cache.embed(["lasso"], model="m", input_type="query", output_dimension=2)  # call 2: dies

    # A fresh client re-reading the same path must still have "ridge" cached,
    # without hitting the inner client for it again.
    reloaded_inner = _FlakyVoyage()
    reloaded = CachingVoyageClient(path, inner=reloaded_inner)
    reloaded.embed(["ridge"], model="m", input_type="query", output_dimension=2)
    assert reloaded_inner.calls == 0
    assert reloaded.hits == 1 and reloaded.misses == 0


def test_no_inner_client_and_a_miss_is_a_clear_error(tmp_path):
    """--no-cache-adjacent misuse should name the problem, not fail deep inside
    the Voyage SDK with a None."""
    cache = CachingVoyageClient(tmp_path / "c.json", inner=None)
    with pytest.raises(RuntimeError, match="no inner client"):
        cache.embed(["ridge"], model="m", input_type="query", output_dimension=2)


def test_the_cache_satisfies_the_embed_texts_client_contract(tmp_path):
    """Regression guard for the real call site: `app.embeddings.embed_texts`
    passes `texts` positionally and `model`/`input_type`/`output_dimension` as
    keywords, then reads `.embeddings` off the return value. Every other test
    here calls `.embed()` directly and cannot catch a signature mismatch at
    that call site — this one drives the cache through `embed_texts` itself."""
    inner = _FakeVoyage()
    cache = CachingVoyageClient(tmp_path / "c.json", inner=inner)

    first = embed_texts(["ridge regression"], input_type="query", client=cache)
    assert len(first) == 1
    assert len(first[0]) == EMBEDDING_DIM
    assert len(inner.calls) == 1
    assert cache.hits == 0 and cache.misses == 1

    second = embed_texts(["ridge regression"], input_type="query", client=cache)
    assert second == first
    assert len(inner.calls) == 1
    assert cache.hits == 1 and cache.misses == 1
