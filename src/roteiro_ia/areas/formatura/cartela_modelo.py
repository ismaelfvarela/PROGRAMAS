"""Cartela do vídeo modelo do ano: em que segundo ela aparece (Gemini) e a cor real do fundo
(medida num quadro do vídeo). Guardado em FORMATURAS/_cartela_<ano>.json; refeito só se
apagado."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ValidationError

from roteiro_ia import proc
from roteiro_ia.areas.formatura.cadastro import PASTA
from roteiro_ia.config import Settings
from roteiro_ia.inventory import VIDEO_EXTS
from roteiro_ia.media.tools import ffmpeg_bin
from roteiro_ia.safety import safe_mkdir, safe_write_text

log = logging.getLogger(__name__)

PROMPT = (
    "Este é um vídeo de formatura da produtora Fokuss. Ele tem, no começo, uma CARTELA (tela com "
    "os dados da turma: escola, curso, turma, ano)? Responda: tem_cartela; inicio_s e fim_s "
    "(segundos em que a cartela fica parada e legível na tela); cor_fundo (cor predominante do "
    "fundo da cartela, em hexadecimal #RRGGBB); cor_texto (cor do texto principal, #RRGGBB).")


class CartelaModelo(BaseModel):
    tem_cartela: bool
    inicio_s: float = 0.0
    fim_s: float = 0.0
    cor_fundo: str = ""
    cor_texto: str = "#FFFFFF"
    video: str = ""


def _arquivo(s: Settings, ano: int) -> Path:
    return Path(s.system_dir) / PASTA / f"_cartela_{ano}.json"


def carregar_cartela_modelo(s: Settings, ano: int) -> CartelaModelo | None:
    try:
        return CartelaModelo.model_validate_json(_arquivo(s, ano).read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return None


def cor_do_quadro(video: Path, t: float) -> str:
    """Cor predominante (#RRGGBB) da borda de um quadro do vídeo no segundo `t`."""
    r = proc.run([ffmpeg_bin(), "-v", "error", "-nostdin", "-ss", f"{max(0.0, t):.2f}", "-i",
                  str(video), "-frames:v", "1", "-vf", "scale=64:36", "-f", "rawvideo",
                  "-pix_fmt", "rgb24", "-"], timeout=120)
    if r.returncode != 0 or len(r.stdout) < 64 * 36 * 3:
        raise RuntimeError(f"O ffmpeg não conseguiu ler um quadro de {Path(video).name}.")
    q = np.frombuffer(r.stdout[:64 * 36 * 3], dtype=np.uint8).reshape(36, 64, 3).astype(int)
    borda = np.concatenate([q[:4].reshape(-1, 3), q[-4:].reshape(-1, 3),
                            q[:, :4].reshape(-1, 3), q[:, -4:].reshape(-1, 3)])
    rr, gg, bb = (int(np.median(borda[:, i])) for i in range(3))
    return f"#{rr:02X}{gg:02X}{bb:02X}"


def _video_com_cartela(s: Settings, pasta: Path) -> Path | None:
    """O vídeo modelo cujo estudo de estilo cita uma cartela na abertura."""
    from roteiro_ia.gemini import style
    cache = Path(s.system_dir) / "estilo_cache" / "formatura_modelos"
    nomes = {f.name: f for f in pasta.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXTS}
    try:
        notas = sorted(cache.glob("*.json"))
    except OSError:
        return None
    for arq in notas:
        try:
            n = style.VideoStyleNotes.model_validate_json(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            continue
        if n.url in nomes and "cartela" in n.abertura.casefold():
            return nomes[n.url]
    return None


def estudar_cartela(c, s: Settings, ano: int, pasta) -> CartelaModelo | None:
    """Estuda a cartela do vídeo modelo uma vez (o resultado fica guardado)."""
    from roteiro_ia.areas.formatura.modelos import _parte
    guardada = carregar_cartela_modelo(s, ano)
    if guardada is not None:
        return guardada
    pasta = Path(pasta)
    if not pasta.is_dir():
        return None
    video = _video_com_cartela(s, pasta)
    if video is None:
        return None
    model = s.gemini_model_script or c.pick_default_models()[0]
    f = c.upload(video)
    try:
        cm: CartelaModelo = c.generate_json(model, [_parte(f)], CartelaModelo, PROMPT)
    finally:
        if hasattr(c, "delete_file"):
            try:
                c.delete_file(f)
            except Exception:  # noqa: BLE001
                pass
    cm = cm.model_copy(update={"video": video.name})
    if cm.tem_cartela:
        try:  # a cor medida no quadro vale mais que a descrita
            cm = cm.model_copy(update={"cor_fundo": cor_do_quadro(video, (cm.inicio_s + cm.fim_s) / 2)})
        except RuntimeError as e:
            log.warning("Cor da cartela não medida (%s); fica a do Gemini.", e)
    safe_mkdir(_arquivo(s, ano).parent, s)
    safe_write_text(_arquivo(s, ano), cm.model_dump_json(indent=2), s)
    return cm

