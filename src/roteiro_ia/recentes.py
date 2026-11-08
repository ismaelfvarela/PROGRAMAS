"""Projetos recentes (Continuar projeto existente): os abertos por último primeiro, mais os
projetos achados no disco de trabalho que ainda não estão na lista."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from roteiro_ia.config import Settings
from roteiro_ia.paths import _root, build_event_paths
from roteiro_ia.safety import safe_write_text

log = logging.getLogger(__name__)

ARQUIVO = "recentes.json"
MAX_RECENTES = 20
PROJECT_FILE = "projeto.json"  # o mesmo de pipeline.PROJECT_FILE (sem importar o pipeline)
# arquivos que mudam enquanto o projeto anda (o banco em WAL grava primeiro no -wal)
_MARCAS = ("projeto.db", "projeto.db-wal", "log.txt", PROJECT_FILE)


@dataclass
class Recente:
    pasta: Path            # pasta do evento (origem, no R:)
    disco: str             # disco de trabalho
    aberto_em: datetime | None
    alterado_em: datetime | None

    @property
    def nome(self) -> str:
        return self.pasta.name


def _chave(pasta: Path | str) -> str:
    return str(pasta).rstrip("\\/").lower()


def _arquivo(s: Settings) -> Path:
    return Path(s.system_dir) / ARQUIVO


def _ler(s: Settings) -> list[dict]:
    try:
        data = json.loads(_arquivo(s).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [d for d in data if isinstance(d, dict) and d.get("pasta")] if isinstance(data, list) else []


def registrar(s: Settings, pasta: Path, disco: str, agora: datetime | None = None) -> None:
    """Põe o projeto no topo da lista (chamado ao Iniciar/Continuar)."""
    itens = [d for d in _ler(s) if _chave(d["pasta"]) != _chave(pasta)]
    itens.insert(0, {"pasta": str(pasta), "disco": disco,
                     "aberto_em": (agora or datetime.now()).isoformat(timespec="seconds")})
    try:
        safe_write_text(_arquivo(s), json.dumps(itens[:MAX_RECENTES], ensure_ascii=False, indent=2), s)
    except Exception as e:  # noqa: BLE001 - a lista é só conveniência
        log.warning("Não foi possível gravar a lista de projetos recentes: %s", e)


def _analise(pasta: Path, disco: str, s: Settings) -> Path | None:
    try:
        return Path(build_event_paths(pasta, s, disco).analysis_dir)
    except ValueError:  # inclui EventNameError
        return None


def _alterado_em(analise: Path) -> datetime | None:
    ts = []
    for nome in _MARCAS:
        try:
            ts.append((analise / nome).stat().st_mtime)
        except OSError:
            pass
    return datetime.fromtimestamp(max(ts)) if ts else None


def _achados(discos: list[str]) -> list[tuple[Path, str]]:
    """Projetos no disco de trabalho: <disco>\\EDIÇÃO <ano>\\<evento>\\ANALISE\\projeto.json."""
    out = []
    for disco in discos:
        raiz = _root(disco.rstrip("\\/") if len(disco.rstrip("\\/")) == 2 else disco)
        try:
            anos = [p for p in raiz.glob("EDIÇÃO *") if p.is_dir()]
        except OSError:
            continue
        for ano in anos:
            for f in ano.glob(f"*/ANALISE/{PROJECT_FILE}"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    out.append((Path(d["source_dir"]), str(d.get("work_drive") or disco)))
                except (OSError, ValueError, KeyError, TypeError):
                    continue
    return out


def listar(s: Settings, discos: list[str]) -> list[Recente]:
    """Abertos por último primeiro; depois os achados nos discos, do alterado mais recente.
    Só entram projetos cujo projeto.json ainda existe."""
    vistos: set[str] = set()
    abertos: list[Recente] = []
    for d in _ler(s):
        pasta, disco = Path(d["pasta"]), str(d.get("disco") or s.work_drive)
        analise = _analise(pasta, disco, s)
        if _chave(pasta) in vistos or analise is None or not (analise / PROJECT_FILE).is_file():
            continue
        vistos.add(_chave(pasta))
        try:
            quando = datetime.fromisoformat(str(d.get("aberto_em")))
        except ValueError:
            quando = None
        abertos.append(Recente(pasta, disco, quando, _alterado_em(analise)))
    achados: list[Recente] = []
    for pasta, disco in _achados([d for d in dict.fromkeys(discos) if d]):
        analise = _analise(pasta, disco, s)
        if _chave(pasta) in vistos or analise is None:
            continue
        vistos.add(_chave(pasta))
        achados.append(Recente(pasta, disco, None, _alterado_em(analise)))
    achados.sort(key=lambda r: r.alterado_em or datetime.min, reverse=True)
    return abertos + achados


def quando_texto(t: datetime | None, agora: datetime | None = None) -> str:
    if t is None:
        return "sem data"
    agora = agora or datetime.now()
    if t.date() == agora.date():
        return f"hoje {t:%H:%M}"
    if t.date() == (agora - timedelta(days=1)).date():
        return f"ontem {t:%H:%M}"
    return f"{t:%d/%m/%Y %H:%M}"
