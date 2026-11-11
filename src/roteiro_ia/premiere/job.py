"""job.json: o que o painel do Premiere precisa para criar/abrir o projeto do evento no padrão
de pastas da Fokuss e, com o roteiro pronto, puxar o XML para dentro dele.

Padrão de pastas do projeto (bins): COISAS, CREDITOS, <peças>, SEQUENCIA, TRILHA e VÍDEOS (uma
subpasta por pasta de câmera/áudio do evento). <peças> é EPS no Casamento; na Formatura, CLIPES
(oficina, feira…) ou PARTES DA COLAÇÃO (colação).

O pedido ao painel (`pedido_premiere.json` na pasta do sistema) diz o que fazer: "abrir" (cria o
projeto com as pastas, ou só abre) ou "puxar" (importa as mídias e as timelines do XML)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.models import Role
from roteiro_ia.paths import EventPaths
from roteiro_ia.safety import safe_mkdir, safe_write_text

PASTAS_FIXAS = ("COISAS", "CREDITOS")
PASTA_SEQUENCIA = "SEQUENCIA"
PASTA_TRILHA = "TRILHA"
PASTA_VIDEOS = "VÍDEOS"
PASTA_PECAS = {"casamento": "EPS", "formatura": "CLIPES"}
# projeto vazio do Premiere 2024: o painel copia e abre quando o "criar projeto" do Premiere falha
MODELO_VAZIO = Path(__file__).with_name("projeto_vazio.prproj")
JOB = "job.json"
ULTIMO_JOB = "ultimo_job.json"
PEDIDO = "pedido_premiere.json"
RESULTADO = "resultado_premiere.json"  # gravado pelo painel/serviço do Premiere
ACOES = ("abrir", "puxar")


def _abs(path) -> str:
    return os.path.abspath(str(path))


def pasta_pecas(area: str) -> str:
    return PASTA_PECAS.get(area, PASTA_PECAS["casamento"])


def _proxies(p: EventPaths, db: ProjectDB) -> list[dict[str, str]]:
    out = []
    for m in db.list_media():
        px = db.proxy_for(m.id)
        if px and Path(px).is_file():
            out.append({"original": _abs(Path(p.source_dir) / m.rel_path), "proxy": _abs(px)})
    return out


def _midias(p: EventPaths, db: ProjectDB) -> list[dict[str, str]]:
    """Cada mídia do evento e a subpasta de VÍDEOS dela (a pasta de origem: A, B, E - H4…)."""
    return [{"original": _abs(Path(p.source_dir) / m.rel_path), "pasta": m.folder}
            for m in db.list_media() if m.role != Role.ignorar]


def _do_banco(p: EventPaths, s: Settings, db: ProjectDB | None, fn) -> list:
    if db is not None:
        return fn(p, db)
    if Path(p.db_path).is_file():
        with ProjectDB(p.db_path, s) as own:
            return fn(p, own)
    return []


def job_path(p: EventPaths) -> Path:
    return Path(p.analysis_dir) / JOB


def _gravar(p: EventPaths, s: Settings, job: dict) -> Path:
    text = json.dumps(job, ensure_ascii=False, indent=2)
    out = job_path(p)
    safe_write_text(out, text, s)
    sysdir = Path(s.system_dir)
    safe_mkdir(sysdir, s)
    safe_write_text(sysdir / ULTIMO_JOB, text, s)
    return out


def write_job(p: EventPaths, s: Settings, xml_path: Path | None, db: ProjectDB | None = None,
              area: str = "casamento", pecas: str | None = None) -> Path:
    """Grava ANALISE\\job.json e a cópia <system_dir>\\ultimo_job.json (UTF-8, caminhos
    absolutos). Sem `db`, abre o banco do evento (se existir) só para listar mídias e proxies.
    Campos que outras áreas acrescentam (ex.: entregas e cartela da Formatura) são mantidos;
    `xml` só é trocado quando vem um novo."""
    try:
        job = json.loads(job_path(p).read_text(encoding="utf-8"))
        if not isinstance(job, dict):
            job = {}
    except (OSError, ValueError):
        job = {}
    if xml_path is not None:
        job["xml"] = _abs(xml_path)
    job.setdefault("xml", "")
    job.update({
        "evento": p.event_name,
        "area": area,
        # sempre o mesmo projeto: o painel cria se não existe e só abre se já existe
        "prproj": _abs(p.prproj_path),
        "backup_dir": _abs(p.backup_dir),
        "export_dir": _abs(p.export_dir),
        "pastas": {"fixas": list(PASTAS_FIXAS), "pecas": pecas or pasta_pecas(area),
                   "sequencia": PASTA_SEQUENCIA, "trilha": PASTA_TRILHA, "videos": PASTA_VIDEOS},
        "midias": _do_banco(p, s, db, _midias),
        "proxies": _do_banco(p, s, db, _proxies),
    })
    if MODELO_VAZIO.is_file():
        job["modelo_vazio"] = str(MODELO_VAZIO)
    return _gravar(p, s, job)


def ler_resultado(s: Settings, pedido_em: str) -> dict | None:
    """Resultado que o Premiere gravou para o pedido feito em `pedido_em` (None = ainda não)."""
    try:
        r = json.loads((Path(s.system_dir) / RESULTADO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return r if isinstance(r, dict) and r.get("pedido_em") == pedido_em else None


def pedido_pendente(s: Settings) -> bool:
    return (Path(s.system_dir) / PEDIDO).is_file()


def pedir_ao_premiere(s: Settings, acao: str, job: Path, agora: datetime | None = None) -> Path:
    """Deixa o pedido para o painel do Premiere (que o lê e apaga)."""
    if acao not in ACOES:
        raise ValueError(f"Ação desconhecida para o Premiere: {acao}")
    pedido = {"acao": acao, "job": _abs(job),
              "quando": (agora or datetime.now()).isoformat(timespec="seconds")}
    out = Path(s.system_dir) / PEDIDO
    safe_write_text(out, json.dumps(pedido, ensure_ascii=False, indent=2), s)
    return out
