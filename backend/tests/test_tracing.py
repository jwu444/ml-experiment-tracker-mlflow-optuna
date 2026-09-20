"""Tracing is off unless asked for, and emits real spans when it is on (3.1)."""

import pytest
from app import tracing


def test_configure_is_a_noop_when_disabled(monkeypatch):
    """The default. `make test` must need no collector, and CI no service."""
    monkeypatch.setattr(tracing.settings, "otel_enabled", False)
    monkeypatch.setattr(tracing, "_configured", False)
    tracing.configure_tracing()
    assert tracing._configured is False


def test_configure_is_idempotent(monkeypatch):
    """create_app() is called per test by the client fixture; installing a second
    exporter per call would leak processors for the life of the process."""
    calls = []
    monkeypatch.setattr(tracing.settings, "otel_enabled", True)
    monkeypatch.setattr(tracing, "_configured", False)
    monkeypatch.setattr(tracing, "_install_exporter", lambda: calls.append(1))
    tracing.configure_tracing()
    tracing.configure_tracing()
    assert calls == [1]


def test_span_is_safe_to_call_with_no_provider_installed():
    """span() is called from library code that must not care whether tracing is on."""
    with tracing.span("unit.test", count=3) as current:
        assert current is not None


def test_span_records_name_and_attributes(spans):
    with tracing.span("unit.test", count=3, label="x", skipped=None):
        pass
    finished = spans.get_finished_spans()
    assert [s.name for s in finished] == ["unit.test"]
    assert finished[0].attributes["count"] == 3
    assert finished[0].attributes["label"] == "x"
    # None-valued attributes are dropped: OTel rejects None and would raise.
    assert "skipped" not in finished[0].attributes


def test_nested_spans_are_parented(spans):
    with tracing.span("outer"):
        with tracing.span("inner"):
            pass
    finished = {s.name: s for s in spans.get_finished_spans()}
    assert finished["inner"].parent.span_id == finished["outer"].context.span_id


def test_span_records_an_exception_and_re_raises(spans):
    with pytest.raises(ValueError):
        with tracing.span("boom"):
            raise ValueError("nope")
    finished = spans.get_finished_spans()
    assert finished[0].status.status_code.name == "ERROR"
