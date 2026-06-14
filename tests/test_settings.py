"""Tests for path and environment configuration helpers."""

from pathlib import Path

from tsic import settings


def test_default_db_path() -> None:
    assert settings.default_db_path() == Path.home() / ".tsic" / "data.db"


def test_log_path() -> None:
    assert settings.log_path() == Path.home() / ".tsic" / "tsic.log"


def test_fugle_api_key_missing(monkeypatch) -> None:
    monkeypatch.delenv(settings.FUGLE_API_KEY_ENV, raising=False)
    assert settings.fugle_api_key() is None


def test_fugle_api_key_present(monkeypatch) -> None:
    monkeypatch.setenv(settings.FUGLE_API_KEY_ENV, "abc")
    assert settings.fugle_api_key() == "abc"
