"""Cadastro das formaturas (a ficha): fica fora dos projetos, em <system_dir>/FORMATURAS/, para
uma oficina gravada um ano antes e a colação usarem os mesmos dados."""
from __future__ import annotations

import re
import secrets
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from roteiro_ia.config import Settings
from roteiro_ia.safety import safe_mkdir, safe_write_text

PASTA = "FORMATURAS"


class Curso(BaseModel):
    nome: str
    turmas: list[str]


class Formatura(BaseModel):
    id: str = ""
    instituicao: str
    logo_escola: str | None = None
    ano: int
    semestre: Literal[1, 2]
    cursos: list[Curso]
    pasta_grafismos: str | None = None


def _pasta(s: Settings) -> Path:
    return Path(s.system_dir) / PASTA


def _slug(txt: str) -> str:
    sem = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", sem.lower()).strip("-") or "formatura"


def _validar(f: Formatura) -> None:
    if not f.instituicao.strip():
        raise ValueError("Informe a instituição.")
    if not f.cursos:
        raise ValueError("Cadastre pelo menos um curso.")
    for c in f.cursos:
        if not c.nome.strip():
            raise ValueError("Há um curso sem nome.")
        turmas = [t.strip() for t in c.turmas if t.strip()]
        if not turmas:
            raise ValueError(f"O curso {c.nome.strip()} está sem turma.")
        vistas: set[str] = set()
        for t in turmas:
            if t.casefold() in vistas:
                raise ValueError(f"Turma repetida no curso {c.nome.strip()}: {t}.")
            vistas.add(t.casefold())


def _limpa(f: Formatura) -> Formatura:
    cursos = [Curso(nome=c.nome.strip(), turmas=[t.strip() for t in c.turmas if t.strip()])
              for c in f.cursos]
    return f.model_copy(update={"instituicao": f.instituicao.strip(), "cursos": cursos})


def salvar(s: Settings, f: Formatura) -> Formatura:
    """Valida (ValueError com a mensagem para o editor), gera o id se faltar e grava."""
    _validar(f)
    f = _limpa(f)
    if not f.id:
        f = f.model_copy(update={
            "id": f"{_slug(f.instituicao)}-{f.ano}-{f.semestre}-{secrets.token_hex(2)}"})
    safe_mkdir(_pasta(s), s)
    safe_write_text(_pasta(s) / f"{f.id}.json", f.model_dump_json(indent=2), s)
    return f


def carregar(s: Settings, id: str) -> Formatura | None:
    if not id:
        return None
    try:
        return Formatura.model_validate_json((_pasta(s) / f"{id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return None


def listar(s: Settings) -> list[Formatura]:
    """Da mais nova (ano/semestre) para a mais antiga; depois pela instituição."""
    out = []
    try:
        arquivos = sorted(_pasta(s).glob("*.json"))
    except OSError:
        return []
    for p in arquivos:
        f = carregar(s, p.stem)
        if f is not None:
            out.append(f)
    return sorted(out, key=lambda f: (-f.ano, -f.semestre, f.instituicao.casefold()))


def avisos(f: Formatura) -> list[str]:
    out = []
    if f.logo_escola and not Path(f.logo_escola).is_file():
        out.append(f"Logo da escola não encontrado: {f.logo_escola}")
    if f.pasta_grafismos and not Path(f.pasta_grafismos).is_dir():
        out.append(f"Pasta de grafismos não encontrada: {f.pasta_grafismos}")
    return out


def duplicar(f: Formatura) -> Formatura:
    """Cópia para o semestre seguinte (2026/2 → 2027/1), ainda sem id."""
    ano, sem = (f.ano + 1, 1) if f.semestre == 2 else (f.ano, 2)
    return f.model_copy(update={"id": "", "ano": ano, "semestre": sem}, deep=True)


def nome_exibicao(f: Formatura) -> str:
    return f"{f.instituicao.upper()} — {f.ano}/{f.semestre}"
