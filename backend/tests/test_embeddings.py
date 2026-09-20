"""Chunking (D29) and the Voyage boundary (3.3)."""

import pytest
from app import embeddings
from app.config import settings
from app.models import EMBEDDING_DIM, Finding


def test_chunk_text_returns_nothing_for_empty_input():
    assert embeddings.chunk_text("") == []
    assert embeddings.chunk_text("   \n\n  ") == []


def test_a_short_note_stays_one_chunk():
    """Mean run-note length is 693 chars — the common case must not be split."""
    note = "Ridge at alpha=1.0 beat the baseline by 4%. " * 10  # ~430 chars
    assert len(embeddings.chunk_text(note)) == 1


def test_a_long_finding_splits_on_sentence_boundaries():
    """Mean finding length is 2,704-4,022 chars — three or four chunks."""
    sentence = "The residuals are heteroscedastic across the upper quartile of revenue. "
    chunks = embeddings.chunk_text(sentence * 60)  # ~4,300 chars
    assert len(chunks) >= 4
    # No chunk exceeds the budget, and none starts mid-sentence.
    assert all(len(c) <= 1000 for c in chunks)
    assert all(c.startswith("The residuals") for c in chunks)


def test_chunks_do_not_overlap():
    """D29: sentence boundaries already guarantee no sentence is unretrievable,
    so overlap would only duplicate text and inflate Phase 4's recall."""
    text = " ".join(f"Sentence number {i} says something." for i in range(200))
    chunks = embeddings.chunk_text(text)
    rejoined = " ".join(chunks)
    assert rejoined.count("Sentence number 7 says") == 1


def test_a_single_sentence_longer_than_the_budget_is_emitted_whole():
    """Never split mid-sentence: a half-sentence chunk retrieves as nonsense."""
    monster = "x" * 2500 + "."
    assert embeddings.chunk_text(monster) == [monster]


def test_blank_lines_are_chunk_boundaries():
    """Findings are markdown with headed sections; a heading must not be glued to
    the tail of the previous section."""
    text = "## Distribution\n\n" + ("A. " * 200) + "\n\n## Missingness\n\n" + ("B. " * 200)
    chunks = embeddings.chunk_text(text)
    assert any(c.startswith("## Missingness") for c in chunks)


def test_embed_texts_passes_the_document_input_type(fake_voyage):
    vectors = embeddings.embed_texts(["hello"], input_type="document", client=fake_voyage)
    assert len(vectors) == 1
    assert len(vectors[0]) == EMBEDDING_DIM
    assert fake_voyage.calls[0]["input_type"] == "document"
    assert fake_voyage.calls[0]["output_dimension"] == EMBEDDING_DIM


def test_embed_texts_passes_the_query_input_type(fake_voyage):
    """The asymmetry is the whole point: indexing and querying use different
    input types, and omitting it costs recall with no visible symptom."""
    embeddings.embed_texts(["hello"], input_type="query", client=fake_voyage)
    assert fake_voyage.calls[0]["input_type"] == "query"


def test_embed_texts_rejects_an_unknown_input_type(fake_voyage):
    with pytest.raises(ValueError, match="input_type"):
        embeddings.embed_texts(["hello"], input_type="passage", client=fake_voyage)


def test_embed_texts_short_circuits_on_an_empty_list(fake_voyage):
    assert embeddings.embed_texts([], input_type="document", client=fake_voyage) == []
    assert fake_voyage.calls == []


def test_embed_texts_rejects_a_wrong_width_vector(fake_voyage):
    """A provider returning 1024 floats into a VECTOR(512) column fails at INSERT
    with a message about the column, far from the cause."""
    fake_voyage.width = 8
    with pytest.raises(ValueError, match="512"):
        embeddings.embed_texts(["hello"], input_type="document", client=fake_voyage)


def test_embed_texts_sends_the_configured_model(fake_voyage):
    """The model is config, not a literal in the call site: D14 fixes the provider
    and the 512 width, and the model string moved once already (voyage-3.5 ->
    voyage-4) without either of those changing."""
    from app.config import settings

    embeddings.embed_texts(["hello"], input_type="document", client=fake_voyage)
    assert fake_voyage.calls[0]["model"] == settings.voyage_model


def test_a_heading_leads_the_section_beneath_it():
    """A heading alone embeds as almost nothing, and would answer a question
    about missingness with a bare heading and no content."""
    chunks = embeddings.chunk_text("## Missingness\n\nRevenue is null in 4 of 224 rows.")
    assert chunks == ["## Missingness\n\nRevenue is null in 4 of 224 rows."]


def test_a_paragraph_break_ends_a_chunk_even_when_there_is_room():
    """The distinction that matters: a sentence break is where a chunk MAY end,
    a blank line is where it MUST. Packing across one glues a section onto the
    tail of the section above it, which then retrieves as the wrong section."""
    chunks = embeddings.chunk_text("First section text.\n\nSecond section text.")
    assert chunks == ["First section text.", "Second section text."]


def test_a_trailing_heading_is_not_dropped():
    assert embeddings.chunk_text("Body text here.\n\n## Dangling") == [
        "Body text here.",
        "## Dangling",
    ]


class _RateLimitError(Exception):
    """Stands in for voyageai.error.RateLimitError.

    Matched by class NAME, exactly as the real one is: `app.embeddings` defers
    its `voyageai` import into `_default_client()` so a missing package fails at
    call time rather than at app startup, so it cannot name the SDK's exception
    class in an `except` clause.
    """


class _FlakyVoyage:
    """Rate-limits the first `failures` calls, then succeeds."""

    def __init__(self, inner, failures: int, exc: Exception | None = None):
        self._inner = inner
        self._remaining = failures
        self._exc = exc or _RateLimitError("429 Too Many Requests")
        self.calls = 0

    def embed(self, *args, **kwargs):
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise self._exc
        return self._inner.embed(*args, **kwargs)


@pytest.fixture
def no_sleep(monkeypatch):
    """Record the backoff delays instead of serving them — the real ones are
    exponential and would put minutes into the suite."""
    slept: list[float] = []
    monkeypatch.setattr(embeddings, "_sleep", slept.append)
    return slept


def test_a_rate_limited_embed_is_retried(fake_voyage, no_sleep):
    """Voyage's free tier is 3 requests/minute and `make embed` sends one request
    per changed source, so a review session of a dozen notes trips it as a matter
    of course. Unretried, the backfill aborts partway and leaves the index
    half-reconciled — the state 3.3b's reap exists to prevent."""
    client = _FlakyVoyage(fake_voyage, failures=2)
    vectors = embeddings.embed_texts(["hello"], input_type="document", client=client)

    assert len(vectors[0]) == EMBEDDING_DIM
    assert client.calls == 3
    assert no_sleep == [2.0, 4.0]  # exponential, from voyage_retry_base_seconds


def test_retries_are_bounded(fake_voyage, no_sleep):
    """A key that is genuinely over quota must fail, not hang."""
    client = _FlakyVoyage(fake_voyage, failures=99)
    with pytest.raises(_RateLimitError):
        embeddings.embed_texts(["hello"], input_type="document", client=client)
    assert client.calls == 4  # voyage_max_attempts
    assert len(no_sleep) == 3  # no sleep after the final attempt


def test_a_non_rate_limit_error_is_not_retried(fake_voyage, no_sleep):
    """A bad key or a wrong model name fails identically on every attempt, so
    retrying turns an instant, legible error into a slow one."""
    client = _FlakyVoyage(fake_voyage, failures=99, exc=ValueError("invalid api key"))
    with pytest.raises(ValueError):
        embeddings.embed_texts(["hello"], input_type="document", client=client)
    assert client.calls == 1
    assert no_sleep == []


def test_a_429_in_the_message_counts_as_a_rate_limit(fake_voyage, no_sleep):
    """Not every SDK version names the class the same way; the status code in
    the message is the stable signal."""
    client = _FlakyVoyage(fake_voyage, failures=1, exc=RuntimeError("HTTP 429 from voyage"))
    embeddings.embed_texts(["hello"], input_type="document", client=client)
    assert client.calls == 2


def test_chunk_text_reads_its_budget_from_settings(monkeypatch):
    """The budget is resolved at call time, so a settings change takes effect
    without any caller passing it. Task 8's sweep depends on this."""
    text = "One. " * 200  # 1000 characters of short sentences
    monkeypatch.setattr(settings, "chunk_max_chars", 100)
    narrow = embeddings.chunk_text(text)
    monkeypatch.setattr(settings, "chunk_max_chars", 2000)
    wide = embeddings.chunk_text(text)
    assert len(narrow) > len(wide)
    assert all(len(c) <= 100 for c in narrow)


def test_an_explicit_max_chars_still_wins():
    """Tests and callers that pass a budget are unaffected by the setting."""
    text = "One. " * 200
    assert all(len(c) <= 50 for c in embeddings.chunk_text(text, max_chars=50))


def _approve_one_finding(session, *, text: str) -> Finding:
    """An approved Finding is enough to exercise backfill's skip check —
    approved_sources() groups by (source_type, source_id) without joining back
    to datasets/runs, so a fixed source_id needs no real dataset behind it."""
    finding = Finding(
        source_type="eda",
        source_id="dataset-1",
        text=text,
        original_text=text,
        status="approved",
    )
    session.add(finding)
    session.commit()
    return finding


def test_backfill_reindexes_when_the_chunk_budget_changes(db_session, fake_voyage, monkeypatch):
    """The skip check re-chunks with the CURRENT budget, so a budget change is
    detected as an edit. If this regresses, a swept config silently evaluates
    the previous config's index."""
    _approve_one_finding(db_session, text="One. " * 200)

    monkeypatch.setattr(settings, "chunk_max_chars", 1000)
    first = embeddings.backfill(db_session, client=fake_voyage)
    assert first.indexed == 1

    monkeypatch.setattr(settings, "chunk_max_chars", 200)
    second = embeddings.backfill(db_session, client=fake_voyage)
    assert second.reindexed == 1
    assert second.unchanged == 0
