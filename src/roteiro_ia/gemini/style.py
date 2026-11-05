"""Perfil de estilo de edição a partir de vídeos públicos do YouTube (analisados pelo Gemini)."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlparse

from google.genai import types
from pydantic import BaseModel, ValidationError

from roteiro_ia.config import Settings
from roteiro_ia.gemini.client import QuotaPaused
from roteiro_ia.safety import safe_mkdir, safe_write_text

log = logging.getLogger(__name__)
_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
_WATCH = "https://www.youtube.com/watch?v="


class VideoStyleNotes(BaseModel):
    url: str
    tipo: Literal["episodio", "teaser", "trailer", "outro"]
    duracao_s: float
    ritmo_corte_s: float
    abertura: str
    gancho: str
    uso_falas: str
    trilha: str
    cor: str
    observacoes: str


class StyleProfile(BaseModel):
    fontes: list[str]
    duracao_media_episodio_s: float
    ritmo_corte_medio_s: float
    padroes_abertura: list[str]
    padroes_gancho: list[str]
    uso_falas: str
    trilhas: str
    cor: str
    estrutura_teaser_trailer: str
    resumo: str


def _video_id(url: str) -> str | None:
    u = urlparse(url.strip())
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    vid = None
    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com"):
        if u.path == "/watch":
            vid = (parse_qs(u.query).get("v") or [None])[0]
        elif u.path.startswith("/shorts/"):
            vid = u.path.split("/")[2] if len(u.path.split("/")) > 2 else None
    return vid if vid and _ID.match(vid) else None


def expand_playlists(urls: list[str]) -> tuple[list[str], list[str]]:
    """Devolve (vídeos canônicos sem repetição, URLs ignoradas — ex.: playlists puras)."""
    videos: list[str] = []
    ignored: list[str] = []
    for url in urls:
        vid = _video_id(url)
        if vid is None:
            if url.strip() and url not in ignored:
                ignored.append(url)
            continue
        canon = _WATCH + vid
        if canon not in videos:
            videos.append(canon)
    return videos, ignored


def _profile_path(s: Settings) -> Path:
    return Path(s.system_dir) / "perfil_estilo.json"


def _cache_path(s: Settings, url: str) -> Path:
    return Path(s.system_dir) / "estilo_cache" / f"{_video_id(url)}.json"


def load_style_profile(s: Settings) -> StyleProfile | None:
    try:
        return StyleProfile.model_validate_json(_profile_path(s).read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return None


_PROMPT_VIDEO = (
    "Assista a este vídeo de casamento publicado pela Fokuss e descreva de forma técnica e objetiva o "
    "ESTILO DE EDIÇÃO, sem resumir a história nem a vida particular do casal. Informe: tipo (episodio, "
    "teaser, trailer ou outro); duração total em segundos; ritmo médio de corte em segundos por plano; "
    "como o vídeo abre; como termina com gancho para o próximo; uso de falas reais (discursos, votos, "
    "depoimentos) e como entram; uso e tipo de trilha musical; tratamento de cor; e observações "
    "relevantes de montagem. Responda em português."
)
_PROMPT_AGG = (
    "A seguir estão anotações técnicas de edição de vários vídeos de casamento da Fokuss, em JSON. "
    "Consolide-as em um perfil de estilo reutilizável para guiar roteiros futuros: duração média dos "
    "episódios, ritmo médio de corte, padrões de abertura, padrões de gancho final, uso de falas reais, "
    "trilhas, cor, estrutura de teasers e trailers e um resumo curto. Seja objetivo e técnico, em "
    "português. Anotações:\n"
)


def build_style_profile(c, s: Settings, model: str | None = None) -> StyleProfile:


    videos, ignored = expand_playlists(s.style_urls)
    for u in ignored:
        log.warning("URL ignorada (playlist ou link inválido; adicione os vídeos individualmente): %s", u)
    model = model or s.gemini_model_script or c.pick_default_models()[0]
    safe_mkdir(Path(s.system_dir) / "estilo_cache", s)
    all_notes: list[VideoStyleNotes] = []
    for url in videos:
        cp = _cache_path(s, url)
        try:
            all_notes.append(VideoStyleNotes.model_validate_json(cp.read_text(encoding="utf-8")))
            continue
        except (OSError, ValueError, ValidationError):
            pass
        part = types.Part.from_uri(file_uri=url, mime_type="video/*")
        try:
            n = c.generate_json(model, [part], VideoStyleNotes, _PROMPT_VIDEO)
        except QuotaPaused:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Vídeo pulado (indisponível ou erro na análise) %s: %s", url, e)
            continue
        n = n.model_copy(update={"url": url})
        safe_write_text(cp, n.model_dump_json(indent=2), s)
        all_notes.append(n)
    if not all_notes:
        raise RuntimeError(
            "Nenhum vídeo de estilo pôde ser analisado. Confira os links (públicos, vídeos individuais) "
            "nas configurações."
        )
    payload = json.dumps([n.model_dump() for n in all_notes], ensure_ascii=False, indent=1)
    prof = c.generate_json(model, [], StyleProfile, _PROMPT_AGG + payload)
    prof = prof.model_copy(update={"fontes": [n.url for n in all_notes]})
    safe_write_text(_profile_path(s), prof.model_dump_json(indent=2), s)
    return prof
