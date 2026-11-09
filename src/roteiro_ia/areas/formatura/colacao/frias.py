"""Banco de imagens frias (decoração, plateia, bastidores…) para cobrir trechos sem câmera boa."""
from __future__ import annotations

from pydantic import BaseModel

from roteiro_ia.db import ProjectDB

PREFERENCIA = {
    "hino": ["decoração", "bastidores"],
    "colacao": ["plateia e família", "emoção", "comemoração"],
}
PADRAO = ["plateia e família", "decoração"]


class ItemFria(BaseModel):
    midia_rel: str
    inicio_s: float
    fim_s: float
    momento: str
    qualidade: int


class BancoFrias:
    def __init__(self, itens: list[ItemFria]):
        self.itens = list(itens)
        self._usado: dict[int, float] = {}  # índice do item → até onde já foi usado

    def _ordem(self, assunto: str) -> list[int]:
        pref = PREFERENCIA.get(assunto, PADRAO)

        def chave(i: int):
            it = self.itens[i]
            p = pref.index(it.momento) if it.momento in pref else len(pref)
            # clipe ainda não usado antes do resto de um já usado: a cobertura varia
            return (p, i in self._usado, -it.qualidade, it.midia_rel, it.inicio_s)
        return sorted(range(len(self.itens)), key=chave)

    def escolher(self, assunto: str, duracao_s: float) -> list[tuple[str, float, float]]:
        """Trechos (mídia, início, fim) que somam `duracao_s`; não repete o que já foi usado."""
        out: list[tuple[str, float, float]] = []
        falta = duracao_s
        for i in self._ordem(assunto):
            if falta <= 1e-6:
                break
            it = self.itens[i]
            ini = self._usado.get(i, it.inicio_s)
            livre = it.fim_s - ini
            if livre <= 0.2:
                continue
            usa = min(livre, falta)
            out.append((it.midia_rel, ini, ini + usa))
            self._usado[i] = ini + usa
            falta -= usa
        return out


def banco_frias(db: ProjectDB, rels: set[str]) -> BancoFrias:
    """Segmentos analisados das mídias de imagens frias."""
    itens = []
    for m in db.list_media():
        if m.rel_path not in rels or m.kind != "video":
            continue
        for seg in db.list_segments(m.id):
            a = db.get_analysis(seg.id)
            if a is not None:
                itens.append(ItemFria(midia_rel=m.rel_path, inicio_s=seg.start_s, fim_s=seg.end_s,
                                      momento=a.momento, qualidade=a.qualidade))
    return BancoFrias(itens)
