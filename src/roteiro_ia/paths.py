"""Caminhos de destino de um evento (somente construção de strings + criação segura de pastas)."""
from __future__ import annotations

import datetime
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from roteiro_ia.config import Settings
from roteiro_ia.safety import safe_mkdir

_NAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\s*-?\s*\S")


class EventNameError(ValueError):
    pass


class InsufficientSpaceError(RuntimeError):
    pass


def parse_event_name(folder_name: str) -> datetime.date:
    m = _NAME_RE.match(folder_name.strip())
    if not m:
        raise EventNameError(
            f"Não encontrei a data no nome da pasta '{folder_name}'. "
            "Use o formato 'AAAA-MM-DD NOME DO EVENTO'."
        )
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise EventNameError(
            f"A data no nome da pasta '{folder_name}' é inválida."
        ) from None


@dataclass(frozen=True)
class EventPaths:
    event_name: str
    event_date: datetime.date
    year: int
    source_dir: Path
    work_dir: Path
    proxies_dir: Path
    analysis_dir: Path
    music_dir: Path
    backup_dir: Path
    pdf_path: Path
    db_path: Path
    premiere_dir: Path
    prproj_path: Path
    export_dir: Path


def _root(value: str) -> Path:
    """Aceita letra de unidade ("Y:") ou diretório completo."""
    if len(value) == 2 and value[1] == ":":
        return Path(value + "\\")
    return Path(value)


def build_event_paths(
    source_dir: Path, s: Settings, work_drive: str | None = None
) -> EventPaths:
    name = Path(source_dir).name
    date = parse_event_name(name)
    year = date.year
    work_dir = _root(work_drive or s.work_drive) / f"EDIÇÃO {year}" / name
    premiere_dir = _root(s.e_root) / f"VÍDEOS {year}" / s.client_folder / name
    export_dir = _root(s.g_root) / str(year) / s.client_folder / name
    analysis_dir = work_dir / "ANALISE"
    return EventPaths(
        event_name=name,
        event_date=date,
        year=year,
        source_dir=Path(source_dir),
        work_dir=work_dir,
        proxies_dir=work_dir / "PROXIES",
        analysis_dir=analysis_dir,
        music_dir=work_dir / "TRILHAS",
        backup_dir=work_dir / "BACKUP PROJETO",
        pdf_path=work_dir / f"{name} - ROTEIRO.pdf",
        db_path=analysis_dir / "projeto.db",
        premiere_dir=premiere_dir,
        prproj_path=premiere_dir / f"{name}.prproj",
        export_dir=export_dir,
    )


def create_event_folders(p: EventPaths, s: Settings) -> None:
    for d in (p.work_dir, p.proxies_dir, p.analysis_dir, p.music_dir,
              p.backup_dir, p.premiere_dir, p.export_dir):
        safe_mkdir(d, s)


def next_free_prproj(p: EventPaths) -> Path:
    if not p.prproj_path.exists():
        return p.prproj_path
    n = 2
    while True:
        cand = p.premiere_dir / f"{p.event_name}_v{n}.prproj"
        if not cand.exists():
            return cand
        n += 1


def estimate_proxy_gb(total_duration_s: float) -> float:
    return total_duration_s / 3600.0 * 1.0 + 2.0


def check_free_space(p: EventPaths, required_gb: float) -> None:
    base = p.work_dir
    while not base.exists() and base.parent != base:
        base = base.parent
    free_gb = shutil.disk_usage(base).free / 1024**3
    if free_gb < required_gb:
        raise InsufficientSpaceError(
            f"Espaço insuficiente em {base.anchor or base}: "
            f"livre {free_gb:.1f} GB, necessário {required_gb:.1f} GB."
        )
