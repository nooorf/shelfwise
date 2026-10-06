import pytest

from shelfwise.config import Settings


def test_settings_read_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELFWISE_PROFILE", "cuda")
    monkeypatch.setenv("SHELFWISE_DATABASE_URL", "postgresql://u:p@db:5432/x")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.profile == "cuda"
    assert settings.database_url == "postgresql://u:p@db:5432/x"


def test_settings_reject_unknown_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELFWISE_PROFILE", "tpu")

    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]
