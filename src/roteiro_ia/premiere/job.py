"""job.json: o que o painel do Premiere precisa para abrir o projeto do evento."""
from __future__ import annotations

import json
import os
from pathlib import Path

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.paths import EventPaths, next_free_prproj
from roteiro_ia.safety import safe_mkdir, safe_write_text


def _abs(path) -> str:
    return os.path.abspath(str(path))


def _proxies(p: EventPaths, db: ProjectDB) -> list[dict[str, str]]:
    out = []
    for m in db.list_media():
        px = db.proxy_for(m.id)
        if px and Path(px).is_file():
            out.append({"original": _abs(Path(p.source_dir) / m.rel_path), "proxy": _abs(px)})
    return out


def write_job(p: EventPaths, s: Settings, xml_path: Path, db: ProjectDB | None = None) -> Path:
    """Grava ANALISE\\job.json e a cópia <system_dir>\\ultimo_job.json (UTF-8, caminhos
    absolutos). Sem `db`, abre o banco do evento (se existir) só para listar os proxies."""
    if db is not None:
        proxies = _proxies(p, db)
    elif Path(p.db_path).is_file():
        with ProjectDB(p.db_path, s) as own:
            proxies = _proxies(p, own)
    else:
        proxies = []
    job = {
        "evento": p.event_name,
        "xml": _abs(xml_path),
        "prproj": _abs(next_free_prproj(p)),
        "backup_dir": _abs(p.backup_dir),
        "export_dir": _abs(p.export_dir),
        "proxies": proxies,
    }
    text = json.dumps(job, ensure_ascii=False, indent=2)
    out = Path(p.analysis_dir) / "job.json"
    safe_write_text(out, text, s)
    sysdir = Path(s.system_dir)
    safe_mkdir(sysdir, s)
    safe_write_text(sysdir / "ultimo_job.json", text, s)
    return out
