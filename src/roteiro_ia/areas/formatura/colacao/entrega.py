"""job.json da íntegra: o do Casamento mais a lista de entregas (sequência → arquivo no G)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from roteiro_ia.areas.formatura.colacao.plano import PlanoIntegra
from roteiro_ia.areas.formatura.colacao.xml_integra import nome_sequencia
from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.paths import EventPaths
from roteiro_ia.premiere.job import write_job
from roteiro_ia.safety import safe_write_text


def nome_arquivo(nome: str) -> str:
    """Nome válido no Windows (sem < > : " / \\ | ? *), sem espaços repetidos."""
    return re.sub(r"\s+", " ", re.sub(r'[<>:"/\\|?*]', " ", nome)).strip()


def write_job_integra(p: EventPaths, s: Settings, xml_path: Path, db: ProjectDB,
                      plano: PlanoIntegra) -> Path:
    out = write_job(p, s, xml_path, db)
    job = json.loads(Path(out).read_text(encoding="utf-8"))
    job["entregas"] = [
        {"sequencia": nome_sequencia(pt),
         "arquivo": str(Path(p.export_dir) / f"{nome_arquivo(nome_sequencia(pt))}.mp4")}
        for pt in plano.partes]
    texto = json.dumps(job, ensure_ascii=False, indent=2)
    safe_write_text(out, texto, s)
    safe_write_text(Path(s.system_dir) / "ultimo_job.json", texto, s)
    return out
