"""Configuração persistente do Roteiro IA."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path(r"Y:\SISTEMA ROTEIRO\config.json")


class ConfigArea(BaseModel):
    """Configuração própria de uma área de trabalho (ex.: formatura)."""
    style_urls: list[str] = []
    pasta_musicas: str = ""  # vazio = usa Settings.music_root


class Settings(BaseModel):
    protected_roots: list[str] = Field(default_factory=lambda: ["R:\\", "M:\\"])
    music_root: str = "M:\\"
    work_drive: str = "Y:"
    e_root: str = "E:\\"
    g_root: str = "G:\\"
    client_folder: str = "01 - FOKUSS"
    system_dir: str = r"Y:\SISTEMA ROTEIRO"
    gemini_mode: Literal["gratis", "pago"] = "gratis"
    gemini_model_analysis: str = ""
    gemini_model_script: str = ""
    gemini_pacote_max_s: int = 1800  # máx. de vídeo (s) por chamada de análise em pacote
    gemini_rotacao: bool = True  # grátis: reveza entre os modelos flash quando um esgota a cota do dia
    price_usd_per_mtok: float = 0.0
    style_urls: list[str] = Field(default_factory=list)
    copy_music_to_work: bool = False
    noise_floor_threshold_db: float = -45.0
    areas: dict[str, ConfigArea] = {}
    area_atual: str = "casamento"


def config_area(s: Settings, area: str) -> ConfigArea:
    """Devolve a configuração da área, criando a entrada se ela não existir."""
    if area not in s.areas:
        s.areas[area] = ConfigArea()
    return s.areas[area]


def urls_estilo(s: Settings, area: str) -> list[str]:
    """URLs de estilo da área. Casamento usa o campo legado Settings.style_urls."""
    if area == "casamento":
        return s.style_urls
    return config_area(s, area).style_urls


def set_urls_estilo(s: Settings, area: str, urls: list[str]) -> None:
    """Define as URLs de estilo da área (mesma regra de urls_estilo)."""
    if area == "casamento":
        s.style_urls = urls
    else:
        config_area(s, area).style_urls = urls


def pasta_musicas_padrao(s: Settings, area: str) -> str:
    """Pasta de músicas da área; se não configurada, cai em Settings.music_root."""
    return config_area(s, area).pasta_musicas or s.music_root


def load_settings(path: Path | None = None) -> Settings:
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return Settings()
    return Settings.model_validate_json(path.read_text(encoding="utf-8"))


def save_settings(s: Settings, path: Path | None = None) -> None:
    from .safety import safe_mkdir, safe_write_text  # import tardio: safety importa config

    path = Path(path or DEFAULT_CONFIG_PATH)
    safe_mkdir(path.parent, s)
    safe_write_text(path, s.model_dump_json(indent=2), s)