"""Observações do editor para um evento: perfil do casal/estilo do vídeo, o que não pode faltar,
o que evitar e as músicas (estilo, nomes, pasta e playlist). Vão com prioridade para a IA em
toda geração do roteiro (a primeira, as regeradas e os ajustes) e aparecem no PDF."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PureWindowsPath

from pydantic import BaseModel

MIN_NOME = 4  # nomes de música mais curtos que isso não são procurados na biblioteca


class Observacoes(BaseModel):
    perfil: str = ""         # perfil do casal / estilo do vídeo
    obrigatorio: str = ""    # o que não pode faltar
    evitar: str = ""         # o que evitar
    musicas: str = ""        # estilo de música e nomes de trilhas do casal / do evento
    musicas_pasta: str = ""  # pasta com as músicas do casal (entra no índice de trilhas)
    musicas_link: str = ""   # playlist (Spotify, YouTube…): a IA não abre links; vai no PDF

    def vazia(self) -> bool:
        return not any(v.strip() for v in self.model_dump().values())

    def preenchidas(self) -> int:
        return sum(1 for v in self.model_dump().values() if v.strip())

    def itens_pdf(self) -> list[tuple[str, str]]:
        rot = [("Perfil do casal / estilo do vídeo", self.perfil), ("Não pode faltar", self.obrigatorio),
               ("Evitar", self.evitar), ("Músicas", self.musicas),
               ("Pasta de músicas do casal", self.musicas_pasta), ("Playlist", self.musicas_link)]
        return [(r, v.strip()) for r, v in rot if v.strip()]


def texto_prompt(o: Observacoes | None, preferidas: int = 0) -> str:
    """Seção do prompt do roteiro (vazia quando não há observações)."""
    if o is None or o.vazia():
        return ""
    linhas = ["OBSERVAÇÕES DO EDITOR PARA ESTE EVENTO — PRIORIDADE MÁXIMA: siga-as acima das regras "
              "gerais e do estilo quando houver conflito."]
    if o.perfil.strip():
        linhas.append(f"- Perfil do casal / estilo do vídeo: {o.perfil.strip()}")
    if o.obrigatorio.strip():
        linhas.append(f"- NÃO PODE FALTAR (cada item em pelo menos uma peça; se não houver material "
                      f"no catálogo, diga isso nos alertas): {o.obrigatorio.strip()}")
    if o.evitar.strip():
        linhas.append(f"- EVITAR (não use em nenhuma peça): {o.evitar.strip()}")
    if o.musicas.strip() or preferidas:
        m = [f"- Músicas: {o.musicas.strip()}" if o.musicas.strip() else "- Músicas:"]
        if preferidas:
            m.append(f"As {preferidas} trilha(s) marcadas com ★ na lista de trilhas são do casal "
                     "ou foram pedidas: prefira-as.")
        m.append("Músicas pedidas que não estão na lista de trilhas podem ir como origem "
                 "\"popular\" (exige_licenca=true).")
        linhas.append(" ".join(m))
    return "\n".join(linhas)


def _simples(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def nomes_pedidos(texto: str) -> list[str]:
    """Nomes de músicas escritos pelo editor (um por linha, ou separados por ; ou ,)."""
    partes = re.split(r"[\n;,]+", texto or "")
    return [s for s in (_simples(p) for p in partes) if len(s) >= MIN_NOME]


def _dentro(path: str, pasta: str) -> bool:
    a = str(PureWindowsPath(path)).lower().rstrip("\\")
    b = str(PureWindowsPath(pasta)).lower().rstrip("\\")
    return a == b or a.startswith(b + "\\")


def trilhas_preferidas(caminhos: list[str], o: Observacoes | None) -> set[str]:
    """Trilhas do índice que estão na pasta do casal ou cujo nome contém um nome pedido."""
    if o is None:
        return set()
    nomes = nomes_pedidos(o.musicas)
    pasta = o.musicas_pasta.strip()
    out = set()
    for c in caminhos:
        if pasta and _dentro(c, pasta):
            out.add(c)
            continue
        base = _simples(Path(PureWindowsPath(c).name).stem)
        if any(n in base for n in nomes):
            out.add(c)
    return out


class IndiceComPreferidas:
    """Visão do índice para o roteiro: as trilhas de `base` mais as `extras` (pasta do casal) e
    o conjunto `preferidas` (caminhos marcados com ★ na lista enviada à IA). O resto delega."""

    def __init__(self, base, extras: list, o: Observacoes | None):
        self._base = base
        self._extras = list(extras)
        self.preferidas = trilhas_preferidas([t.path for t in self.all()], o)

    def all(self) -> list:
        return [*self._base.all(), *self._extras]

    def __getattr__(self, nome):
        return getattr(self._base, nome)
