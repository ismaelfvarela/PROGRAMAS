"""Pipeline da Formatura: as etapas comuns, com a análise e o roteiro do clipe próprios."""
from __future__ import annotations

from pathlib import Path

from roteiro_ia.areas.formatura.analise import TEXTOS_POR_TIPO
from roteiro_ia.areas.formatura.cadastro import carregar
from roteiro_ia.areas.formatura.projeto import (ProjetoFormatura, carregar_projeto, musicas_usadas,
                                                salvar_projeto)
from roteiro_ia.areas.formatura.roteiro import IndiceSem, contexto_clipe
from roteiro_ia.areas.formatura.tipos import INFO_TIPO
from roteiro_ia.config import pasta_musicas_padrao
from roteiro_ia.db import ProjectDB
from roteiro_ia.gemini.analysis import analyze_event
from roteiro_ia.music_index import IndiceFiltrado
from roteiro_ia.paths import build_event_paths
from roteiro_ia.pipeline import Pipeline, PipelineError
from roteiro_ia.safety import safe_mkdir
from roteiro_ia.script.generate import generate_roteiro

MSG_COLACAO = "A colação chega na próxima etapa (2.3)."


class PipelineFormatura(Pipeline):
    def projeto(self) -> ProjetoFormatura:
        """Os dados do trabalho: os do pedido (formulário) ou os gravados no formatura.json."""
        pf = getattr(self.req, "formatura", None) or carregar_projeto(Path(self.p.analysis_dir))
        if pf is None:
            raise PipelineError("Projeto de Formatura sem dados do trabalho (formatura.json).")
        return pf

    def _gravar_projeto(self, pf: ProjetoFormatura) -> None:
        """Grava o formatura.json; a música que o roteiro já escolheu (gravada no arquivo) fica,
        mesmo quando o pedido vem do formulário sem ela (Continuar)."""
        if pf.musica is None:
            antigo = carregar_projeto(Path(self.p.analysis_dir))
            if antigo is not None and antigo.musica:
                pf = pf.model_copy(update={"musica": antigo.musica})
        safe_mkdir(Path(self.p.analysis_dir), self.s)
        salvar_projeto(Path(self.p.analysis_dir), pf, self.s)

    def _checar(self) -> ProjetoFormatura:
        pf = self.projeto()
        if INFO_TIPO[pf.tipo].grupo == "colacao":
            raise PipelineError(MSG_COLACAO)
        return pf

    def prepare(self):
        self._gravar_projeto(self._checar())
        return super().prepare()

    def run(self, aprovado_custo: bool = False, refazer_falhas: bool = True):
        pf = self._checar()
        if getattr(self.req, "formatura", None) is not None:
            self._gravar_projeto(pf)
        return super().run(aprovado_custo=aprovado_custo, refazer_falhas=refazer_falhas)

    # ------------------------------------------------------------ etapas próprias
    def _st_analise(self) -> None:
        model, _ = self._models()
        analyze_event(self.db, self._client(), self.p, model, self._perfil(),
                      on_progress=self._progress("analise"),
                      max_video_s=self.s.gemini_pacote_max_s,
                      textos=TEXTOS_POR_TIPO[self.projeto().tipo])

    def _ideia(self, pf: ProjetoFormatura) -> str | None:
        """Roteiro mais recente da oficina original (duplicada com 'seguir a ideia')."""
        if not (pf.duplicado_de and pf.seguir_ideia):
            return None
        try:
            db_path = Path(build_event_paths(Path(pf.duplicado_de), self.s, self.req.work_drive).db_path)
        except ValueError:
            return None
        if not db_path.is_file():
            return None
        db = ProjectDB(db_path, self.s)
        try:
            return db.latest_roteiro()
        finally:
            db.close()

    def _st_roteiro(self) -> None:
        pf = self.projeto()
        _, model = self._models()
        pasta = self.req.pasta_musicas or pasta_musicas_padrao(self._base, self.req.area)
        usadas = musicas_usadas(self._base, pf.formatura_id, exceto=self.source)
        idx = IndiceSem(IndiceFiltrado(self._index(), Path(pasta)), usadas)
        ctx = contexto_clipe(pf, carregar(self._base, pf.formatura_id), self._ideia(pf))
        r = generate_roteiro(self.db, self._client(), idx, self._perfil(), model, 1, set(),
                             pedido_ajuste=self._pedido, contexto=ctx)
        musica = next((ms.path for p in r.pecas for ms in p.trilhas
                       if ms.origem == "biblioteca" and ms.path), None)
        self._gravar_projeto(pf.model_copy(update={"musica": musica}))
