"""Pipeline da Formatura: as etapas comuns, com a análise e o roteiro do clipe próprios; na
colação, as últimas etapas viram a íntegra corrigida (defeitos, espaços mortos, partes, imagens
frias, XML por parte e entregas no G)."""
from __future__ import annotations

import json
from pathlib import Path

from roteiro_ia.areas.formatura.analise import TEXTOS_POR_TIPO
from roteiro_ia.areas.formatura.cadastro import carregar
from roteiro_ia.areas.formatura.cartela import (campos_cartela, colocar_cartela, gerar_cartela_png,
                                                job_cartela)
from roteiro_ia.areas.formatura.ajustes import carregar_ajustes, modelos_do_ano
from roteiro_ia.areas.formatura.modelos import carregar_perfil_ano, estudar_modelos
from roteiro_ia.areas.formatura.colacao.clipes import contexto_abertura_encerramento, nomes_clipes
from roteiro_ia.areas.formatura.colacao.defeitos import Defeito, classificar, medir
from roteiro_ia.areas.formatura.colacao.entrega import write_job_integra
from roteiro_ia.areas.formatura.colacao.frias import banco_frias
from roteiro_ia.areas.formatura.colacao.partes import (ParteNomeada, detectar_partes,
                                                       transcricao_em_linhas)
from roteiro_ia.areas.formatura.colacao.plano import PlanoIntegra, montar_plano
from roteiro_ia.areas.formatura.colacao.relatorio import render_relatorio
from roteiro_ia.areas.formatura.colacao.silencio import silencios
from roteiro_ia.areas.formatura.colacao.xml_integra import build_xml_integra
from roteiro_ia.areas.formatura.funcoes import FuncaoFormatura
from roteiro_ia.areas.formatura.projeto import (ProjetoFormatura, carregar_projeto, musicas_usadas,
                                                salvar_projeto)
from roteiro_ia.areas.formatura.roteiro import IndiceSem, contexto_clipe
from roteiro_ia.areas.formatura.tipos import INFO_TIPO
from roteiro_ia.config import pasta_musicas_padrao
from roteiro_ia.db import ProjectDB
from roteiro_ia.gemini.analysis import analyze_event
from roteiro_ia.models import MediaInfo, Role
from roteiro_ia.music_index import IndiceFiltrado
from roteiro_ia.paths import EventNameError, build_event_paths, parse_event_name
from roteiro_ia.gemini.client import QuotaPaused
from roteiro_ia.controle import Interrompido
from roteiro_ia.pipeline import FALHAS_PREFIX, Pipeline, PipelineError, music_paths
from roteiro_ia.premiere.fcpxml import write_xml
from roteiro_ia.report.pdf import html_to_pdf
from roteiro_ia.safety import safe_mkdir, safe_write_text
from roteiro_ia.script.generate import Roteiro, generate_roteiro

MSG_SEM_PGM = "Marque a pasta da mesa de corte (PGM, CORTE ou ATEM)."
ARQ_INTEGRA = "integra.json"
ARQ_MEDIDAS = "defeitos.json"
SILENCIO_ABAIXO_DA_MEDIA_DB = 25.0
SILENCIO_PADRAO_DB = -45.0


class PipelineFormatura(Pipeline):
    def projeto(self) -> ProjetoFormatura:
        """Os dados do trabalho: os do pedido (formulário) ou os gravados no formatura.json."""
        pf = getattr(self.req, "formatura", None) or carregar_projeto(Path(self.p.analysis_dir))
        if pf is None:
            raise PipelineError("Projeto de Formatura sem dados do trabalho (formatura.json).")
        return pf

    def _colacao(self) -> bool:
        return INFO_TIPO[self.projeto().tipo].grupo == "colacao"

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
        if (INFO_TIPO[pf.tipo].grupo == "colacao"
                and FuncaoFormatura.mesa_corte not in pf.funcoes.values()):
            raise PipelineError(MSG_SEM_PGM)
        return pf

    def prepare(self):
        self._gravar_projeto(self._checar())
        return super().prepare()

    def run(self, aprovado_custo: bool = False, refazer_falhas: bool = True):
        pf = self._checar()
        if getattr(self.req, "formatura", None) is not None:
            self._gravar_projeto(pf)
        return super().run(aprovado_custo=aprovado_custo, refazer_falhas=refazer_falhas)

    # ------------------------------------------------------------ etapas
    def _ano(self) -> int | None:
        ficha = carregar(self._base, self.projeto().formatura_id)
        return ficha.ano if ficha else None

    def _pasta_modelos(self) -> tuple[int, str] | None:
        ano = self._ano()
        m = modelos_do_ano(self._base, ano) if ano else None
        return (ano, m.pasta) if m and m.pasta else None

    def _st_estilo(self) -> str:
        """Com vídeos modelo do ano, o estilo vem deles; senão, dos links da aba Estilo."""
        mod = self._pasta_modelos()
        try:
            if mod is None:
                return super()._st_estilo()
            ano, pasta = mod
            self._models()
            prof = estudar_modelos(self._client(), self.s, ano, pasta)
        except (QuotaPaused, Interrompido):
            raise
        except Exception as e:  # noqa: BLE001 - o estilo ajuda, mas não é obrigatório
            # ex.: 503 "high demand" do Gemini. O projeto segue sem o estilo; a etapa fica
            # "feita com falhas" e é refeita no próximo Continuar (os vídeos já estudados
            # ficam no cache).
            self._emit("estilo", "O Gemini não conseguiu estudar o estilo agora (servidor "
                       f"ocupado ou erro: {e}). O projeto segue sem ele; o estudo é refeito no "
                       "próximo Continuar.", 1.0)
            return f"{FALHAS_PREFIX}1"
        return f"vídeos modelo de {ano} estudados" if prof else "nenhum vídeo modelo na pasta do ano"

    def _perfil(self):
        mod = self._pasta_modelos()
        if mod is not None and (prof := carregar_perfil_ano(self.s, mod[0])) is not None:
            return prof
        return super()._perfil()

    def _st_trilhas(self) -> str:
        if not self._colacao():
            return super()._st_trilhas()
        try:  # só os clipes de abertura/encerramento usam música: sem o HD, a colação segue
            return super()._st_trilhas()
        except PipelineError as e:
            return f"sem trilhas (os clipes saem sem música): {e}"

    def _rels_frias(self) -> set[str]:
        pf = self.projeto()
        pastas = {p for p, f in pf.funcoes.items() if f == FuncaoFormatura.extras}
        return {m.rel_path for m in self.db.list_media() if m.folder in pastas}

    def _st_analise(self) -> str | None:
        model, _ = self._models()
        incluir = None
        if self._colacao():
            # imagens frias (banco de cobertura) e a mesa de corte (melhores momentos e falas dos
            # clipes de abertura e encerramento); as ISOs não, pelo custo
            alvo = self._rels_frias() | {m.rel_path for m, _t in self._pgms()}
            incluir = (lambda m: m.rel_path in alvo)  # noqa: E731
        analyze_event(self.db, self._client(), self.p, model, self._perfil(),
                      on_progress=self._progress("analise"),
                      max_video_s=self.s.gemini_pacote_max_s,
                      textos=TEXTOS_POR_TIPO[self.projeto().tipo], incluir=incluir)
        return None

    def _st_roteiro(self) -> str | None:
        if self._colacao():
            plano = self._plano_integra()
            self._roteiro_clipes(plano)
            return f"{len(plano.partes)} parte(s)" + (" + abertura e encerramento" if plano.clipes else "")
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
        return None

    def _st_pdf(self) -> None:
        if not self._colacao():
            return super()._st_pdf()
        plano = self._plano_salvo()
        html = render_relatorio(plano, self.p.event_name, self._clipes(plano))
        html_to_pdf(html, self.p.pdf_path, self.s, html_path=Path(self.p.analysis_dir) / "integra.html")

    def _st_premiere(self) -> None:
        if not self._colacao():
            super()._st_premiere()
            self._aplicar_cartela(["EP 01"])  # o clipe é a única peça ("EP 01" no XML)
            return
        plano = self._plano_salvo()
        r = self._clipes(plano)
        ab = next((pc for pc in r.pecas if pc.tipo == "trailer"), None) if r else None
        enc = next((pc for pc in r.pecas if pc.tipo == "teaser"), None) if r else None
        nome_ab, nome_enc = nomes_clipes(len(plano.partes))
        xml = build_xml_integra(plano, self.db, self.source, abertura=ab, encerramento=enc,
                                idx=self._index(), musicas=music_paths(r, self.p, self.s) if r else {},
                                logo=carregar_ajustes(self._base).logo_produtora)
        xml_path = write_xml(xml, self.p, self.s)
        write_job_integra(self.p, self.s, xml_path, self.db, plano,
                          clipes=(nome_ab if ab else None, nome_enc if enc else None))
        if ab is not None:
            self._aplicar_cartela([nome_ab])

    def _aplicar_cartela(self, nomes: list[str]) -> None:
        """Cartela no início das sequências: MOGRT do ano (o painel preenche) ou a cartela simples."""
        pf = self.projeto()
        ficha = carregar(self._base, pf.formatura_id)
        try:
            data = parse_event_name(self.source.name).isoformat()
        except EventNameError:
            data = None
        campos = campos_cartela(pf, ficha, data)
        ad = Path(self.p.analysis_dir)
        xml_path = ad / f"{self.p.event_name} - PREMIERE.xml"
        xml = xml_path.read_text(encoding="utf-8")
        mod = modelos_do_ano(self._base, ficha.ano) if ficha else None
        if mod is not None and mod.mogrt and Path(mod.mogrt).is_file():
            safe_write_text(xml_path, colocar_cartela(xml, nomes, None), self.s)
            job_cartela(ad / "job.json", self.s, mod.mogrt, nomes, campos)
            return
        try:
            png = gerar_cartela_png(campos, ficha.logo_escola if ficha else None, ad / "cartela.png", self.s)
        except RuntimeError as e:
            self._emit("premiere", f"Cartela não gerada: {e}", 1.0)
            return
        safe_write_text(xml_path, colocar_cartela(xml, nomes, str(png)), self.s)

    # ------------------------------------------------------------ clipes
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

    # ------------------------------------------------------------ íntegra da colação
    def _pgms(self) -> list[tuple[MediaInfo, float]]:
        """(mídia da mesa de corte, início na linha do tempo), em ordem."""
        out = []
        for m in self.db.list_media(Role.mesa):
            sy = self.db.get_sync(m.id)
            if m.kind == "video":
                out.append((m, sy.timeline_start_s if sy else 0.0))
        if not out:
            raise PipelineError(MSG_SEM_PGM)
        return sorted(out, key=lambda x: x[1])

    def _medidas(self, pgms, alertas: list[str]) -> dict:
        """Defeitos e espaços mortos por arquivo da mesa (calculados uma vez; o ajuste reaproveita)."""
        arq = Path(self.p.analysis_dir) / ARQ_MEDIDAS
        try:
            cache = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        mudou = False
        for m, _t0 in pgms:
            if m.rel_path in cache:
                continue
            item = {"defeitos": [], "mortos": []}
            proxy = self.db.proxy_for(m.id)
            if proxy and Path(proxy).is_file():
                try:
                    item["defeitos"] = [d.model_dump() for d in classificar(medir(Path(proxy)))]
                except RuntimeError as e:
                    alertas.append(f"Não consegui medir os defeitos de {m.rel_path}: {e}")
            else:
                alertas.append(f"{m.rel_path} sem proxy: defeitos de imagem não medidos.")
            st = self.db.get_audio_stats(m.id)
            limite = (st.mean_db - SILENCIO_ABAIXO_DA_MEDIA_DB) if st else SILENCIO_PADRAO_DB
            try:
                item["mortos"] = silencios(self.source / m.rel_path, limite)
            except Exception as e:  # noqa: BLE001 - sem cortes de espaço morto, a íntegra segue
                alertas.append(f"Não consegui achar os espaços mortos de {m.rel_path}: {e}")
            cache[m.rel_path] = item
            mudou = True
        if mudou:
            safe_write_text(arq, json.dumps(cache, ensure_ascii=False, indent=1), self.s)
        return cache

    def _plano_integra(self) -> PlanoIntegra:
        pf = self.projeto()
        _, model = self._models()
        pgms = self._pgms()
        alertas: list[str] = []
        med = self._medidas(pgms, alertas)
        defeitos, mortos, palavras = [], [], []
        for m, t0 in pgms:
            item = med.get(m.rel_path, {})
            defeitos += [Defeito(**{**d, "inicio_s": d["inicio_s"] + t0, "fim_s": d["fim_s"] + t0})
                         for d in item.get("defeitos", [])]
            mortos += [(a + t0, b + t0) for a, b in item.get("mortos", [])]
            tr = self.db.get_transcript(m.id)
            if tr is not None:
                palavras += [(w.start_s + t0, w.text) for w in tr.words]
        fim = max(t0 + m.duration_s for m, t0 in pgms)
        partes, al_partes = detectar_partes(self._client(), model, transcricao_em_linhas(palavras),
                                            [tuple(t) for t in pf.turmas_colacao], fim,
                                            pedido=self._pedido)
        isos = []
        for m in self.db.list_media(Role.camera):
            sy = self.db.get_sync(m.id)
            if m.kind == "video" and sy is not None:
                isos.append((m.rel_path, sy.timeline_start_s, sy.timeline_start_s + m.duration_s))
        plano = montar_plano(partes, fim, defeitos, sorted(mortos), isos,
                             banco_frias(self.db, self._rels_frias()))
        plano.alertas = alertas + al_partes + plano.alertas
        safe_write_text(Path(self.p.analysis_dir) / ARQ_INTEGRA, plano.model_dump_json(indent=1), self.s)
        return plano

    def _roteiro_clipes(self, plano: PlanoIntegra) -> None:
        """Roteiro da abertura e do encerramento; uma falha comum não derruba a íntegra."""
        pf = self.projeto()
        _, model = self._models()
        partes = [ParteNomeada(codigo=p.codigo, nome=p.nome, inicio_s=p.inicio_s) for p in plano.partes]
        try:
            data = parse_event_name(self.source.name).isoformat()
        except EventNameError:
            data = None
        pasta = self.req.pasta_musicas or pasta_musicas_padrao(self._base, self.req.area)
        ctx = contexto_abertura_encerramento(pf, carregar(self._base, pf.formatura_id), partes, data)
        try:
            generate_roteiro(self.db, self._client(), IndiceFiltrado(self._index(), Path(pasta)),
                             self._perfil(), model, None, {"trailer", "teaser"},
                             pedido_ajuste=self._pedido, contexto=ctx)
            plano.clipes = True
        except QuotaPaused:
            raise
        except Exception as e:  # noqa: BLE001 - a íntegra sai mesmo sem os clipes
            plano.clipes = False
            plano.alertas.append(f"Clipes de abertura e encerramento não gerados: {e}")
        safe_write_text(Path(self.p.analysis_dir) / ARQ_INTEGRA, plano.model_dump_json(indent=1), self.s)

    def _clipes(self, plano: PlanoIntegra) -> Roteiro | None:
        if not plano.clipes:
            return None
        txt = self.db.latest_roteiro()
        return Roteiro.model_validate_json(txt) if txt else None

    def _plano_salvo(self) -> PlanoIntegra:
        try:
            return PlanoIntegra.model_validate_json(
                (Path(self.p.analysis_dir) / ARQ_INTEGRA).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise PipelineError("Ainda não há plano da íntegra; rode o processamento completo.") from e
