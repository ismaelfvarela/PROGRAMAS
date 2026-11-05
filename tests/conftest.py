import pytest

from roteiro_ia import safety
from roteiro_ia.config import Settings


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def settings_unc(monkeypatch):
    s = Settings()
    monkeypatch.setattr(
        safety,
        "protected_paths",
        lambda _s: ["r:\\", "m:\\", r"\\192.168.168.2\fokuss\m - musicas"],
    )
    return s
