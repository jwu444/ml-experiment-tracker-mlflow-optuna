"""CORS origins arrive from a host's dashboard as whatever a human typed, and
the field is list-typed, so pydantic-settings JSON-decodes it before validation.
That made a plainly-typed origin an import-time SettingsError — see the comment
on the field. These pin the three shapes that must all boot."""

import pytest
from app.config import Settings
from pydantic import ValidationError

WEB = "https://wavepoint-web.onrender.com"
API = "https://wavepoint-api.onrender.com"


@pytest.mark.parametrize(
    "raw,expected",
    [
        (WEB, [WEB]),
        (f"{WEB},{API}", [WEB, API]),
        (f" {WEB} , {API} ", [WEB, API]),
        (f'["{WEB}"]', [WEB]),
        (f'["{WEB}", "{API}"]', [WEB, API]),
    ],
)
def test_a_bare_origin_a_list_and_json_all_parse(monkeypatch, raw, expected):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", raw)
    assert Settings().cors_allow_origins == expected


def test_the_default_survives_an_unset_variable(monkeypatch):
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    assert Settings().cors_allow_origins == ["http://localhost:5173"]


def test_malformed_json_still_fails_loudly(monkeypatch):
    """Only a value that OPENS as JSON is parsed as JSON. Half a JSON list is a
    typo, and guessing at it would hand the app an origin nobody chose. It raises
    ValidationError rather than the SettingsError the undecorated field raised,
    which is the better error: it names the field and echoes the bad input."""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", f'["{WEB}"')
    with pytest.raises(ValidationError):
        Settings()
