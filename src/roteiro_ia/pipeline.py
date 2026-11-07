"""Pipeline retomável: liga todas as etapas, pausa na cota grátis do Gemini e tenta de novo
quedas de rede/disco (NAS). O estado de cada etapa fica em `stages` do banco do projeto."""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Literal

from roteiro_ia import controle
from roteiro_ia.config import Settings, save_settings
from roteiro_ia.controle import Interrompido
from roteiro_ia.db import ProjectDB
from roteiro_ia.gemini.analysis import analyze_event
from roteiro_ia.gemini.client import GeminiClient, QuotaPaused
from roteiro_ia.gemini.style import build_style_profile, load_style_profile
from roteiro_ia.inventory import scan
from roteiro_ia.media.audio import analyze_audio
from roteiro_ia.media.proxies import make_proxies
from roteiro_ia.models import FolderAssignment, Role
from roteiro_ia.music_index import MusicIndex, trilhas_antigas, update_index
from roteiro_ia.paths import (EventPaths, build_event_paths, check_free_space, create_event_folders,
                              estimate_proxy_gb)
from roteiro_ia.premiere.fcpxml import build_xml, write_xml
from roteiro_ia.premiere.job import write_job
from roteiro_ia.report.pdf import collect_technical_alerts, html_to_pdf, render_html
from roteiro_ia.safety import ProtectedPathError, assert_writable, safe_copy, safe_write_text
from roteiro_ia.scenes import detect_segments
from roteiro_ia.script.generate import Roteiro, generate_roteiro
from roteiro_ia.sync import sync_event
from roteiro_ia.transcribe import transcribe_event

_sleep = controle.dormir  # patchável nos testes; o Parar interrompe a espera
RETRY_WAITS_S = (10, 20, 40, 80, 160)

# trilhas antes de estilo/análise: o índice local aproveita o tempo em que o Gemini estaria pausado
STAGES = ["inventario", "proxies", "audio", "sync", "transcricao", "cenas", "trilhas", "estilo",
          "analise", "roteiro", "pdf", "premiere"]
STAGE_LABELS = {
    "inventario": "inventário das mídias",
    "proxies": "proxies 480p",
    "audio": "análise de áudio",
    "sync": "sincronização",
    "transcricao": "transcrição das falas",
    "cenas": "detecção de cenas",
    "estilo": "perfil de estilo",
    "analise": "análise das cenas (Gemini)",
    "trilhas": "índice de trilhas",
    "roteiro": "pré-roteiro",
    "pdf": "PDF do roteiro",
    "premiere": "XML e job do Premiere",
}
GEMINI_STAGES = {"estilo", "analise", "roteiro"}
# etapas que registram falhas por arquivo (o nome da etapa é o `etapa` da falha)
FALHA_STAGES = {"inventario", "proxies", "audio", "sync", "transcricao", "cenas", "analise"}
FALHAS_PREFIX = "falhas="
PROJECT_FILE = "projeto.json"
LOG_FILE = "log.txt"
# o custo da análise (vídeo) ganha +20% para cobrir o perfil de estilo e o roteiro (texto)
TEXT_STAGES_MARGIN = 1.2
_log = logging.getLogger("roteiro_ia")

Events = Callable[[str, str, float], None]


class PipelineError(RuntimeError):
    """Etapa interrompida (mensagem em português para o editor)."""


@dataclass
class ProjectRequest:
    source_dir: Path
    work_drive: str
    assignments: list[FolderAssignment]
    n_episodios: int | None
    derivados: set[str]
    gemini_mode: Literal["gratis", "pago"]

    def to_dict(self) -> dict:
        return {
            "source_dir": str(self.source_dir),
            "work_drive": self.work_drive,
            "assignments": [a.model_dump(mode="json") for a in self.assignments],
            "n_episodios": self.n_episodios,
            "derivados": sorted(self.derivados),
            "gemini_mode": self.gemini_mode,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectRequest":
        return cls(source_dir=Path(d["source_dir"]), work_drive=d["work_drive"],
                   assignments=[FolderAssignment.model_validate(a) for a in d["assignments"]],
                   n_episodios=d.get("n_episodios"), derivados=set(d.get("derivados", [])),
                   gemini_mode=d.get("gemini_mode", "gratis"))

    def save(self, path: Path, s: Settings) -> None:
        safe_write_text(Path(path), json.dumps(self.to_dict(), ensure_ascii=False, indent=2), s)

    @classmethod
    def load(cls, path: Path) -> "ProjectRequest":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def music_paths(r: Roteiro, p: EventPaths, s: Settings) -> dict[str, str]:
    """Trilhas `biblioteca` do roteiro → caminho a usar no XML (cópia em TRILHAS\\ ou original)."""
    out: dict[str, str] = {}
    used: dict[str, str] = {}  # nome em TRILHAS (casefold) → original
    for pc in r.pecas:
        for t in pc.trilhas:
            if t.origem != "biblioteca" or not t.path or t.path in out:
                continue
            src = Path(t.path)
            if not s.copy_music_to_work or not src.is_file():
                out[t.path] = t.path  # sem cópia (ou original sumiu: o Premiere mostra offline)
                continue
            name = PureWindowsPath(t.path).name
            stem, suf, n = PureWindowsPath(name).stem, PureWindowsPath(name).suffix, 2
            while used.get(name.casefold(), t.path) != t.path:
                name, n = f"{stem} ({n}){suf}", n + 1
            used[name.casefold()] = t.path
            dst = Path(p.music_dir) / name
            st = src.stat()
            if not (dst.is_file() and dst.stat().st_size == st.st_size):
                safe_copy(src, dst, s)
            out[t.path] = str(dst)
    return out


class Pipeline:
    def __init__(self, req: ProjectRequest, s: Settings, gemini: GeminiClient | None = None,
                 transcriber=None, events: Events | None = None, *,
                 settings_path: Path | None = None, music_tracker=None):
        self.req = req
        self._base = s
        # o modo do pedido vale para esta execução sem alterar as Settings do editor
        self.s = s.model_copy(update={"gemini_mode": req.gemini_mode})
        self.p = build_event_paths(req.source_dir, self.s, req.work_drive)
        self.source = Path(req.source_dir)
        self._gemini = gemini
        if isinstance(gemini, GeminiClient):
            gemini.s = self.s
        self._transcriber = transcriber
        self._events = events
        self._settings_path = Path(settings_path) if settings_path else Path(s.system_dir) / "config.json"
        self._tracker = music_tracker
        self._db: ProjectDB | None = None
        self._idx: MusicIndex | None = None
        self._aprovado = False
        self._pedido: str | None = None
        self.resume_at: datetime | None = None
        self.impl: dict[str, Callable[[], str | None]] = {n: getattr(self, f"_st_{n}") for n in STAGES}

    # ------------------------------------------------------------ recursos
    @property
    def db(self) -> ProjectDB:
        if self._db is None:
            self._db = ProjectDB(self.p.db_path, self.s)
        return self._db

    def _index(self) -> MusicIndex:
        if self._idx is None:
            self._idx = MusicIndex(Path(self.s.system_dir) / "trilhas.db", self.s)
        return self._idx

    def _client(self):
        if self._gemini is None:
            self._gemini = GeminiClient(self.s)
        return self._gemini

    def _models(self) -> tuple[str, str]:
        if not (self.s.gemini_model_analysis and self.s.gemini_model_script):
            a, b = self._client().pick_default_models()
            # no grátis a escolha (flash para tudo) vale só nesta execução: gravada no config,
            # o roteiro continuaria no flash depois de mudar para o pago
            gratis = self.s.gemini_mode == "gratis"
            for st in (self.s,) if gratis else (self.s, self._base):
                st.gemini_model_analysis = st.gemini_model_analysis or a
                st.gemini_model_script = st.gemini_model_script or b
            if not gratis:
                assert_writable(self._settings_path, self._base)
                save_settings(self._base, self._settings_path)
        return self.s.gemini_model_analysis, self.s.gemini_model_script

    def close(self) -> None:
        for r in (self._db, self._idx):
            if r is not None:
                r.close()
        self._db = self._idx = None

    def __enter__(self) -> "Pipeline":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------ eventos
    def _emit(self, stage: str, msg: str, frac: float) -> None:
        _log.info("[%s] %s", stage, msg)
        if self._events:
            self._events(stage, msg, frac)

    def _progress(self, stage: str):
        label = STAGE_LABELS[stage]

        def cb(i: int, total: int, *rest) -> None:
            extra = f" — {rest[0]}" if rest else ""
            self._emit(stage, f"{label}: {i}/{total}{extra}", i / total if total else 1.0)
        return cb

    # ------------------------------------------------------------ custo
    def estimate_cost(self) -> float:
        """Custo estimado em US$: análise do vídeo (100 tokens/s) + 20% para estilo e roteiro."""
        total = sum(m.duration_s for m in self.db.list_media()
                    if m.role not in (Role.ignorar, Role.outro_dia))
        return GeminiClient(self.s, backend=object()).estimate_cost_usd(total) * TEXT_STAGES_MARGIN

    def _check_price(self) -> None:
        if self.s.gemini_mode == "pago" and self.s.price_usd_per_mtok <= 0:
            raise PipelineError("Modo pago do Gemini sem preço: defina o preço por milhão de tokens "
                                "em Configurações antes de começar.")

    def _check_cost(self) -> None:
        if self.s.gemini_mode == "pago" and not self._aprovado:
            raise PipelineError(
                f"Modo pago do Gemini: o custo estimado (US$ {self.estimate_cost():.2f}) precisa ser "
                "aprovado antes das etapas que usam o Gemini.")

    # ------------------------------------------------------------ execução
    def _project_file(self) -> Path:
        return Path(self.p.analysis_dir) / PROJECT_FILE

    def _open_log(self) -> logging.Handler:
        """ANALISE\\log.txt: eventos e avisos desta execução (anexados ao arquivo)."""
        path = Path(self.p.analysis_dir) / LOG_FILE
        assert_writable(path, self.s)
        path.parent.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(path, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s",
                                         "%Y-%m-%d %H:%M:%S"))
        h.setLevel(logging.INFO)
        _log.addHandler(h)
        if _log.level == logging.NOTSET or _log.level > logging.INFO:
            _log.setLevel(logging.INFO)
        return h

    @staticmethod
    def _close_log(h: logging.Handler) -> None:
        _log.removeHandler(h)
        h.close()

    def prepare(self) -> tuple[EventPaths, float]:
        self._check_price()
        self.req.save(self._project_file(), self.s)
        self._run_stage("inventario")
        return self.p, self.estimate_cost()

    def run(self, aprovado_custo: bool = False,
            refazer_falhas: bool = True) -> Literal["concluido", "pausado", "parado"]:
        """`refazer_falhas=False` (retomadas automáticas): etapas já feitas com falhas por
        arquivo não são refeitas; True (Iniciar/Continuar explícitos) refaz essas etapas.
        "parado": o editor clicou em Parar; a etapa em andamento volta a pendente e o próximo
        run retoma dela (o que já foi gravado fica)."""
        self._check_price()
        self._aprovado = aprovado_custo
        if not self._project_file().is_file():
            self.req.save(self._project_file(), self.s)
        h = self._open_log()
        try:
            for name in STAGES:
                controle.atual().checkpoint()  # Pausar/Parar entre etapas
                self._run_stage(name, refazer_falhas=refazer_falhas)
        except QuotaPaused:
            return "pausado"
        except Interrompido:
            _log.info("Parado pelo editor; o próximo Continuar segue de onde parou.")
            return "parado"
        finally:
            self._close_log(h)
        return "concluido"

    def revise(self, pedido: str, aprovado_custo: bool = False) -> None:
        """Regera roteiro, PDF e XML a partir do banco; nunca refaz etapas de mídia."""
        if self.db.stage_status("analise") != "feito":
            raise PipelineError("Rode o processamento completo antes de pedir ajustes no roteiro.")
        self._check_price()
        self._aprovado = aprovado_custo
        self._pedido = pedido
        h = self._open_log()
        try:
            try:
                self._run_stage("roteiro", force=True)
            finally:
                self._pedido = None
            controle.atual().checkpoint()
            self._run_stage("pdf", force=True)
            controle.atual().checkpoint()
            self._run_stage("premiere", force=True)
        finally:
            self._close_log(h)

    def _run_stage(self, name: str, force: bool = False, refazer_falhas: bool = True) -> None:
        db = self.db
        status = db.stage_status(name)
        if (not force and status == "feito"
                and (not refazer_falhas or not db.stage_detail(name).startswith(FALHAS_PREFIX))):
            return
        if name in GEMINI_STAGES:
            self._check_cost()
        if name == "analise" and status != "pausado":
            db.clear_quota_strikes()  # a contagem de pausas seguidas só vale entre retomadas
        label = STAGE_LABELS[name]
        antes = (status, db.stage_detail(name))
        self._emit(name, f"Iniciando: {label}", 0.0)
        db.set_stage(name, "rodando")
        attempt = 0
        while True:
            try:
                if name in FALHA_STAGES:
                    db.clear_falhas(name)  # cada tentativa registra as suas: sem duplicatas
                detail = self.impl[name]() or ""
                # etapa que devolve normalmente quando parada (índice de trilhas) não fica feita
                controle.atual().checkpoint()
                if name in FALHA_STAGES and not os.path.isdir(self.source):
                    # NAS caiu no meio da etapa: os arquivos perdidos viraram falhas; repete
                    raise OSError(f"Pasta de origem inacessível: {self.source}")
                n_falhas = db.count_falhas(name) if name in FALHA_STAGES else 0
                if n_falhas:
                    detail = f"{FALHAS_PREFIX}{n_falhas}"
                break
            except Interrompido:
                # Parar: nada de erro. Volta a pendente (ou ao 'feito' anterior num ajuste,
                # cujo roteiro/PDF/XML antigos continuam valendo) e o próximo run retoma daqui.
                if antes[0] == "feito":
                    db.set_stage(name, "feito", antes[1])
                else:
                    db.set_stage(name, "pendente")
                self._emit(name, f"Parado: {label}", 0.0)
                raise
            except QuotaPaused as e:
                self.resume_at = e.resume_at
                db.set_stage(name, "pausado", e.resume_at.isoformat())
                local = e.resume_at.astimezone()
                self._emit(name, f"Cota gratuita do Gemini esgotada. Retomar a partir de "
                                 f"{local:%d/%m/%Y %H:%M}.", 0.0)
                raise
            except ProtectedPathError as e:
                db.set_stage(name, "erro", str(e))
                self._emit(name, f"Erro em {label}: {e}", 0.0)
                raise
            except OSError as e:
                if attempt >= len(RETRY_WAITS_S):
                    msg = (f"A etapa '{label}' falhou após {attempt + 1} tentativas por erro de "
                           f"rede ou disco: {e}")
                    db.set_stage(name, "erro", msg)
                    self._emit(name, msg, 0.0)
                    raise PipelineError(msg) from e
                wait = RETRY_WAITS_S[attempt]
                attempt += 1
                self._emit(name, f"Erro de rede ou disco em {label}: {e}. Nova tentativa "
                                 f"({attempt}/{len(RETRY_WAITS_S)}) em {wait} s.", 0.0)
                _sleep(wait)
            except Exception as e:
                msg = f"A etapa '{label}' falhou: {e}"
                db.set_stage(name, "erro", msg)
                self._emit(name, msg, 0.0)
                raise
        db.set_stage(name, "feito", detail)
        self._emit(name, f"Concluído: {label}", 1.0)

    # ------------------------------------------------------------ etapas
    def _st_inventario(self) -> str:
        create_event_folders(self.p, self.s)
        n = scan(self.source, self.req.assignments, self.db, on_progress=self._progress("inventario"))
        return f"{n} arquivos"

    def _st_proxies(self) -> None:
        falta = 0.0  # só os vídeos que ainda não têm proxy
        for m in self.db.list_media():
            if m.kind != "video":
                continue
            prx = self.db.proxy_for(m.id)
            if not (prx and Path(prx).is_file()):
                falta += m.duration_s
        if falta > 0:
            check_free_space(self.p, estimate_proxy_gb(falta))
        make_proxies(self.db, self.p, self.s, self.source, on_progress=self._progress("proxies"))

    def _st_audio(self) -> None:
        analyze_audio(self.db, self.s, self.source)

    def _st_sync(self) -> None:
        sync_event(self.db, self.source)

    def _st_transcricao(self) -> None:
        if self._transcriber is None:
            from roteiro_ia.transcribe import WhisperTranscriber
            self._transcriber = WhisperTranscriber()
        transcribe_event(self.db, self.source, self._transcriber,
                         on_progress=self._progress("transcricao"))

    def _st_cenas(self) -> None:
        detect_segments(self.db, self.p)

    def _st_estilo(self) -> str:
        if not self.s.style_urls or load_style_profile(self.s) is not None:
            return ""
        self._models()
        build_style_profile(self._client(), self.s)
        return "perfil criado"

    def _st_analise(self) -> None:
        model, _ = self._models()
        analyze_event(self.db, self._client(), self.p, model, load_style_profile(self.s),
                      on_progress=self._progress("analise"),
                      max_video_s=self.s.gemini_pacote_max_s)

    def _st_trilhas(self) -> str:
        idx = self._index()
        try:
            # Só novas/alteradas: reanalisar a biblioteca de versão antiga leva horas e é feito
            # pela aba Trilhas (ou `roteiro-ia trilhas`).
            n = update_index(self.s, idx, on_progress=self._progress("trilhas"),
                             tracker=self._tracker, atualizar_versao=False)
        except FileNotFoundError as e:
            if not idx.all():
                raise PipelineError(
                    f"{e} Não há trilhas no índice: conecte a pasta de músicas e use "
                    "'roteiro-ia trilhas' para criar o índice.") from None
            self._emit("trilhas", f"{e} Usando o índice existente ({len(idx.all())} trilhas).", 1.0)
            self._avisar_trilhas_antigas(idx)
            return "índice existente (pasta de músicas inacessível)"
        self._avisar_trilhas_antigas(idx)
        return f"{n} trilhas analisadas"

    def _avisar_trilhas_antigas(self, idx: MusicIndex) -> None:
        n = trilhas_antigas(idx)
        if n:
            self._emit("trilhas", f"Há {n} trilhas com análise antiga — rode 'Atualizar índice' "
                       "na aba Trilhas (pode levar horas)", 1.0)

    def _st_roteiro(self) -> None:
        _, model = self._models()
        generate_roteiro(self.db, self._client(), self._index(), load_style_profile(self.s), model,
                         self.req.n_episodios, set(self.req.derivados), pedido_ajuste=self._pedido)

    def _roteiro(self) -> Roteiro:
        txt = self.db.latest_roteiro()
        if txt is None:
            raise PipelineError("Ainda não há roteiro gerado para este evento.")
        return Roteiro.model_validate_json(txt)

    def _st_pdf(self) -> None:
        html = render_html(self._roteiro(), self.p, collect_technical_alerts(self.db),
                           idx=self._index())
        out = html_to_pdf(html, self.p.pdf_path, self.s,
                          html_path=Path(self.p.analysis_dir) / "roteiro.html")
        if out is not None and Path(out) != Path(self.p.pdf_path):
            msg = f"O PDF anterior está aberto; salvei como {Path(out).name}."
            self._emit("pdf", msg, 1.0)

    def _st_premiere(self) -> None:
        r = self._roteiro()
        xml = build_xml(r, self.db, self._index(), music_paths(r, self.p, self.s), self.source)
        xml_path = write_xml(xml, self.p, self.s)
        write_job(self.p, self.s, xml_path, self.db)
