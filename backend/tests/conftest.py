from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _never_reach_the_live_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every test to fixture quotes, whatever the developer's .env says.

    Settings reads .env, so a checkout set up for live odds would otherwise hand
    any test that builds `Settings()` the real provider: tests would spend
    credits and fail on upstream answers. Environment variables outrank .env,
    so setting them here wins. A test that needs other values sets its own.
    """
    monkeypatch.setenv("QUOTE_PROVIDER", "in_memory")
    monkeypatch.setenv("ODDS_API_KEY", "")


@pytest.fixture
def sqlite_database_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'test.db'}"
