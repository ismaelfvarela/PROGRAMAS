"""Funções das pastas na Formatura e a tradução para os papéis (Role) do pipeline comum."""
from __future__ import annotations

import os
import re
from enum import StrEnum
from pathlib import Path

from roteiro_ia.inventory import AUDIO_EXTS, VIDEO_EXTS, _dir_ignored
from roteiro_ia.models import Role


class FuncaoFormatura(StrEnum):
    camera = "camera"
    camera_iso = "camera_iso"
    camera_audio = "camera_audio"
    mesa_corte = "mesa_corte"
    gravador = "gravador"
    extras = "extras"
    drone = "drone"
    ignorar = "ignorar"


ROTULO_FUNCAO: dict[FuncaoFormatura, str] = {
    FuncaoFormatura.camera: "Câmera",
    FuncaoFormatura.camera_iso: "Câmera ISO",
    FuncaoFormatura.camera_audio: "Câmera com áudio principal",
    FuncaoFormatura.mesa_corte: "Mesa de corte (programa)",
    FuncaoFormatura.gravador: "Gravador / lapela",
    FuncaoFormatura.extras: "Imagens extras / frias",
    FuncaoFormatura.drone: "Drone",
    FuncaoFormatura.ignorar: "Ignorar",
}

ROLE_DA_FUNCAO: dict[FuncaoFormatura, Role] = {
    FuncaoFormatura.camera: Role.camera,
    FuncaoFormatura.camera_iso: Role.camera,
    FuncaoFormatura.camera_audio: Role.camera,
    FuncaoFormatura.mesa_corte: Role.mesa,
    FuncaoFormatura.gravador: Role.audio_ambiente,
    FuncaoFormatura.extras: Role.drone,
    FuncaoFormatura.drone: Role.drone,
    FuncaoFormatura.ignorar: Role.ignorar,
}

_GRUPOS = {
    "clipe": [FuncaoFormatura.camera, FuncaoFormatura.gravador, FuncaoFormatura.extras,
              FuncaoFormatura.drone, FuncaoFormatura.ignorar],
    "colacao": [FuncaoFormatura.mesa_corte, FuncaoFormatura.camera_iso,
                FuncaoFormatura.camera_audio, FuncaoFormatura.gravador, FuncaoFormatura.extras,
                FuncaoFormatura.drone, FuncaoFormatura.ignorar],
}

_PALAVRAS = [
    (FuncaoFormatura.mesa_corte, {"pgm", "corte", "atem"}),
    (FuncaoFormatura.gravador, {"h1", "h4", "h5", "h6", "zoom", "lapela", "mic", "gravador"}),
    (FuncaoFormatura.extras, {"frias", "decoração", "decoracao", "bastidores", "ambiente", "extras"}),
    (FuncaoFormatura.drone, {"drone"}),
]


def funcoes_do_grupo(grupo: str) -> list[FuncaoFormatura]:
    return list(_GRUPOS[grupo])


def sugerir_funcao(pasta: str, grupo: str) -> FuncaoFormatura:
    """Pelo nome da última parte da pasta (DIA\\PASTA), em palavras inteiras."""
    nome = re.split(r"[\\/]", pasta)[-1]
    if _dir_ignored(nome):
        return FuncaoFormatura.ignorar
    palavras = set(re.findall(r"\w+", nome.casefold()))
    validas = _GRUPOS[grupo]
    for funcao, chaves in _PALAVRAS:
        if funcao in validas and palavras & chaves:
            return funcao
    return FuncaoFormatura.camera if grupo == "clipe" else FuncaoFormatura.camera_iso


def _subpastas(p: Path) -> list[str]:
    return sorted(d.name for d in p.iterdir() if d.is_dir())


def _e_dia(p: Path) -> bool:
    """Pasta de um dia: tem subpastas (fora Proxies/autosave) e nenhuma mídia solta."""
    subs = [d for d in _subpastas(p) if not _dir_ignored(d)]
    if not subs:
        return False
    for f in os.listdir(p):
        if os.path.splitext(f)[1].lower() in VIDEO_EXTS | AUDIO_EXTS and (p / f).is_file():
            return False
    return True


def listar_pastas(source: Path) -> list[tuple[str, str]]:
    """(pasta relativa, dia). Pastas de dia viram DIA\\SUB com dia = nome da pasta do dia."""
    source = Path(source)
    out: list[tuple[str, str]] = []
    for nome in _subpastas(source):
        p = source / nome
        if not _dir_ignored(nome) and _e_dia(p):
            out.extend((f"{nome}\\{sub}", nome) for sub in _subpastas(p) if not _dir_ignored(sub))
        else:
            out.append((nome, "principal"))
    return out
