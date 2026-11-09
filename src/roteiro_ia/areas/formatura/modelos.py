"""Estudo de estilo a partir dos vídeos modelo do ano (arquivos locais, não links).

Cada vídeo é enviado ao Gemini uma vez (cache por arquivo: caminho, tamanho e data); o perfil do
ano é refeito só quando a lista de vídeos estudados muda."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from google.genai import types
from pydantic import ValidationError

from roteiro_ia import controle
from roteiro_ia.config import Settings
from roteiro_ia.gemini import style
from roteiro_ia.gemini.client import QuotaPaused
from roteiro_ia.inventory import VIDEO_EXTS
from roteiro_ia.safety import safe_mkdir, safe_write_text

log = logging.getLogger(__name__)


def _chave(v: Path) -> str:
    st = v.stat()
    txt = f"{v.resolve()}|{st.st_size}|{st.st_mtime_ns}".casefold()
    return hashlib.sha1(txt.encode("utf-8")).hexdigest()[:16]


def caminho_perfil(s: Settings, ano: int) -> Path:
    return Path(s.system_dir) / f"perfil_estilo_formatura_{ano}.json"


def carregar_perfil_ano(s: Settings, ano: int) -> style.StyleProfile | None:
    try:
        return style.StyleProfile.model_validate_json(caminho_perfil(s, ano).read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return None


def _parte(f) -> types.Part:
    return types.Part.from_uri(file_uri=getattr(f, "uri", None) or str(f),
                               mime_type=getattr(f, "mime_type", None) or "video/mp4")


def estudar_modelos(c, s: Settings, ano: int, pasta) -> style.StyleProfile | None:
    pasta = Path(pasta)
    if not pasta.is_dir():
        return None
    videos = sorted(f for f in pasta.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXTS)
    if not videos:
        return None
    prompt_video, prompt_agg = style._PROMPTS["formatura"]
    cache = Path(s.system_dir) / "estilo_cache" / "formatura_modelos"
    notas, chaves, model = [], [], None
    for v in videos:
        k = _chave(v)
        arq = cache / f"{k}.json"
        try:
            notas.append(style.VideoStyleNotes.model_validate_json(arq.read_text(encoding="utf-8")))
            chaves.append(k)
            continue
        except (OSError, ValueError, ValidationError):
            pass
        controle.atual().checkpoint()
        model = model or s.gemini_model_script or c.pick_default_models()[0]
        f = None
        try:
            f = c.upload(v)
            n = c.generate_json(model, [_parte(f)], style.VideoStyleNotes, prompt_video)
        except QuotaPaused:
            raise
        except Exception as e:  # noqa: BLE001 - os outros modelos seguem
            log.warning("Vídeo modelo não estudado (%s): %s", v.name, e)
            continue
        finally:
            if f is not None and hasattr(c, "delete_file"):
                try:
                    c.delete_file(f)
                except Exception:  # noqa: BLE001
                    pass
        n = n.model_copy(update={"url": v.name})
        safe_mkdir(cache, s)
        safe_write_text(arq, n.model_dump_json(indent=2), s)
        notas.append(n)
        chaves.append(k)
    if not notas:
        return None
    atual = carregar_perfil_ano(s, ano)
    if atual is not None and sorted(atual.fontes) == sorted(chaves):
        return atual
    model = model or s.gemini_model_script or c.pick_default_models()[0]
    payload = json.dumps([n.model_dump() for n in notas], ensure_ascii=False, indent=1)
    prof = c.generate_json(model, [], style.StyleProfile, prompt_agg + payload)
    prof = prof.model_copy(update={"fontes": chaves})
    safe_write_text(caminho_perfil(s, ano), prof.model_dump_json(indent=2), s)
    return prof
