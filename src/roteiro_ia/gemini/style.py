"""Perfil de estilo de edição a partir de vídeos públicos do YouTube (analisados pelo Gemini)."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import parse_qs, urlparse

from google.genai import types
from pydantic import BaseModel, ValidationError

from roteiro_ia import controle
from roteiro_ia.config import Settings, urls_estilo
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


def _profile_path(s: Settings, area: str = "casamento") -> Path:
    nome = "perfil_estilo.json" if area == "casamento" else f"perfil_estilo_{area}.json"
    return Path(s.system_dir) / nome


# prompts (vídeo, agregado) das áreas que estudam o estilo com textos próprios; o Casamento usa
# _PROMPT_VIDEO/_PROMPT_AGG e o cache na raiz de estilo_cache
_PROMPTS: dict[str, tuple[str, str]] = {}


def registrar_area(area: str, prompt_video: str, prompt_agg: str) -> None:
    """A área passa a ter prompts próprios e cache em estilo_cache/<area>/."""
    _PROMPTS[area] = (prompt_video, prompt_agg)


def _cache_dir(s: Settings, area: str = "casamento") -> Path:
    base = Path(s.system_dir) / "estilo_cache"
    return base / area if area in _PROMPTS else base


def _cache_path(s: Settings, url: str, area: str = "casamento") -> Path:
    return _cache_dir(s, area) / f"{_video_id(url)}.json"


def _read_cache(s: Settings, url: str, area: str = "casamento") -> VideoStyleNotes | None:
    try:
        return VideoStyleNotes.model_validate_json(
            _cache_path(s, url, area).read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return None


def video_em_cache(s: Settings, url: str, area: str = "casamento") -> bool:
    """True se o vídeo (URL em qualquer formato aceito) já foi analisado e está no cache."""
    return _video_id(url) is not None and _read_cache(s, url, area) is not None


def load_style_profile(s: Settings, area: str = "casamento") -> StyleProfile | None:
    try:
        return StyleProfile.model_validate_json(_profile_path(s, area).read_text(encoding="utf-8"))
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


ProgressoVideo = Callable[[str, str, int, int], None]
ESTADOS = ("aguardando", "analisando", "feito", "erro", "ignorado")


def build_style_profile(c, s: Settings, model: str | None = None,
                        on_progress: ProgressoVideo | None = None,
                        area: str = "casamento") -> StyleProfile:
    """`on_progress(url, estado, feitos, total)`: estados em ESTADOS; `url` é a canônica
    (watch?v=) para vídeos e a original para as ignoradas; `feitos` conta só os analisados."""
    def prog(url: str, estado: str) -> None:
        if on_progress:
            on_progress(url, estado, len(all_notes), len(videos))

    prompt_video, prompt_agg = _PROMPTS.get(area, (_PROMPT_VIDEO, _PROMPT_AGG))
    videos, ignored = expand_playlists(urls_estilo(s, area))
    all_notes: list[VideoStyleNotes] = []
    for u in ignored:
        log.warning("URL ignorada (playlist ou link inválido; adicione os vídeos individualmente): %s", u)
        prog(u, "ignorado")
    pendentes = []
    for url in videos:  # os do cache contam como feitos na hora
        n = _read_cache(s, url, area)
        if n is None:
            pendentes.append(url)
        else:
            all_notes.append(n)
            prog(url, "feito")
    for url in pendentes:
        prog(url, "aguardando")
    if pendentes:
        model = model or s.gemini_model_script or c.pick_default_models()[0]
        safe_mkdir(_cache_dir(s, area), s)
    for url in pendentes:
        controle.atual().checkpoint()  # Pausar/Parar entre vídeos (os já analisados ficam no cache)
        prog(url, "analisando")
        part = types.Part.from_uri(file_uri=url, mime_type="video/*")
        try:
            n = c.generate_json(model, [part], VideoStyleNotes, prompt_video)
        except QuotaPaused:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Vídeo pulado (indisponível ou erro na análise) %s: %s", url, e)
            prog(url, "erro")
            continue
        n = n.model_copy(update={"url": url})
        safe_write_text(_cache_path(s, url, area), n.model_dump_json(indent=2), s)
        all_notes.append(n)
        prog(url, "feito")
    if not all_notes:
        raise RuntimeError(
            "Nenhum vídeo de estilo pôde ser analisado. Confira os links (públicos, vídeos individuais) "
            "nas configurações."
        )
    controle.atual().checkpoint()  # Parar antes do perfil agregado não gera perfil incompleto
    model = model or s.gemini_model_script or c.pick_default_models()[0]
    payload = json.dumps([n.model_dump() for n in all_notes], ensure_ascii=False, indent=1)
    prof = c.generate_json(model, [], StyleProfile, prompt_agg + payload)
    prof = prof.model_copy(update={"fontes": [n.url for n in all_notes]})
    safe_write_text(_profile_path(s, area), prof.model_dump_json(indent=2), s)
    return prof
