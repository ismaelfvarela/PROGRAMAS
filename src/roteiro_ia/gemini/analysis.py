"""Análise de cena com Gemini: um catálogo estruturado por segmento de cada mídia."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from google.genai import types
from pydantic import BaseModel

from roteiro_ia.db import ProjectDB
from roteiro_ia.gemini.client import QuotaPaused
from roteiro_ia.gemini.style import StyleProfile
from roteiro_ia.models import MediaInfo, Role, SceneAnalysis, Segment
from roteiro_ia.paths import EventPaths
from roteiro_ia.transcribe import SOURCE_PRIORITY, words_between

MOMENTOS = ["preparação noiva", "preparação noivo", "first look", "entrada", "votos", "alianças",
            "beijo", "saída", "ensaio", "entrada na festa", "valsa", "discursos", "pista",
            "despedida", "pré-wedding", "despedida de solteiro", "lua de mel", "extra"]
BATCH = 40
MAX_ATTEMPTS = 3
MAX_MINUTE_PAUSES = 3  # pausas por minuto seguidas na mesma requisição antes de desistir dela
_MSG_MINUTO = ("O Gemini pausou 3 vezes seguidas por cota por minuto neste trecho; "
               "a mídia ficou sem análise (será tentada de novo ao clicar em Continuar).")
_BETTER = (Role.mesa, Role.lapela_noivo, Role.lapela_noiva, Role.audio_ambiente)


class FileAnalysis(BaseModel):
    segmentos: list[SceneAnalysis]


def segment_speech(db: ProjectDB, media: MediaInfo, seg: Segment) -> str:
    """Fala do trecho: transcrição da própria mídia ou, na falta, a da melhor fonte do mesmo dia."""
    own = db.get_transcript(media.id)
    if own is not None:
        return words_between(own, seg.start_s, seg.end_s)
    sync = db.get_sync(media.id)
    if sync is None:
        return ""
    t0, t1 = sync.timeline_start_s + seg.start_s, sync.timeline_start_s + seg.end_s
    mid = (t0 + t1) / 2
    cands = []
    for o in db.list_media():
        if o.id == media.id or o.role not in _BETTER:
            continue
        osync = db.get_sync(o.id)
        if osync is None or osync.day_label != sync.day_label:
            continue
        if osync.timeline_start_s <= mid <= osync.timeline_start_s + o.duration_s:
            cands.append((SOURCE_PRIORITY.index(o.role), o, osync))
    for _, o, osync in sorted(cands, key=lambda x: x[0]):
        t = db.get_transcript(o.id)
        if t is None:
            continue
        text = words_between(t, t0 - osync.timeline_start_s, t1 - osync.timeline_start_s)
        if text:
            return text
    return ""


def _style_text(style: StyleProfile) -> str:
    pad = "; ".join([*style.padroes_abertura, *style.padroes_gancho])
    return (f"Estilo da Fokuss (use este vocabulário nas descrições): {style.resumo}"
            + (f" Padrões: {pad}." if pad else ""))


def build_prompt(media: MediaInfo, segments: list[Segment], transcripts: dict[int, str],
                 style: StyleProfile | None = None,
                 clip: tuple[float, float] | None = None) -> str:
    linhas = []
    for s in segments:
        fala = transcripts.get(s.id) or "(sem fala transcrita)"
        linhas.append(f"- segment_id={s.id} | início={s.start_s:.2f}s | fim={s.end_s:.2f}s | fala: {fala}")
    fonte = ("Você recebe apenas o áudio transcrito (sem imagem)." if media.kind == "audio"
             else "Você está assistindo ao vídeo (proxy 480p) e recebe a fala transcrita de cada trecho.")
    partes = [
        "Você é um assistente de edição de vídeos de casamento da produtora Fokuss.",
        f"{fonte} Arquivo: {media.rel_path} (duração {media.duration_s:.1f}s).",
        *([f"O vídeo enviado é só o trecho de {clip[0]:.2f}s a {clip[1]:.2f}s do arquivo; "
           "mesmo assim, responda com tempos relativos ao arquivo inteiro."] if clip else []),
        "Analise cada segmento abaixo e devolva EXATAMENTE um item por segmento, usando o mesmo segment_id.",
        "Segmentos:", *linhas,
        "Regras:",
        f"- momento: use um destes valores: {', '.join(MOMENTOS)}. Se nenhum servir, use 'extra' "
        "e preencha o campo 'extra' com o nome do momento.",
        "- descricao: o que acontece, em português; pessoas: quem aparece ou fala.",
        "- emocao_intensidade e qualidade: inteiros de 0 a 10; emocao_tipo: ex. riso, choro, ternura.",
        "- problemas: falhas técnicas (tremido, foco, áudio ruim, escuro); lista vazia se não houver.",
        "- melhores_trechos (pontos bons de entrada e saída) e falas_chave (citações marcantes): "
        "tempos em segundos RELATIVOS AO ARQUIVO (não ao segmento), dentro do intervalo do segmento.",
        "- potencial_gancho: true se serve para abrir um teaser/episódio, com motivo_gancho; "
        "sugestao_lembranca: true se funciona como flashback/lembrança.",
    ]
    if style is not None:
        partes.append(_style_text(style))
    return "\n".join(partes)


def _clamp(items, seg: Segment):
    out = []
    for it in items:
        a = min(max(it.start_s, seg.start_s), seg.end_s)
        b = min(max(it.end_s, seg.start_s), seg.end_s)
        if b - a > 0:
            out.append(it.model_copy(update={"start_s": a, "end_s": b}))
    return out


def _check(resp: FileAnalysis, ids: list[int]) -> str | None:
    got = [a.segment_id for a in resp.segmentos]
    if sorted(got) == sorted(ids):
        return None
    return (f"ids inválidos (faltando {sorted(set(ids) - set(got))}, "
            f"desconhecidos {sorted(set(got) - set(ids))}, repetidos {len(got) - len(set(got))})")


def _ask(c, model: str, parts: list, prompt: str, ids: list[int]) -> tuple[FileAnalysis | None, str]:
    msg = ""
    for _ in range(MAX_ATTEMPTS):
        try:
            resp = c.generate_json(model, parts, FileAnalysis, prompt, max_retries=1)
        except ValueError as e:
            msg = str(e)
            continue
        bad = _check(resp, ids)
        if bad is None:
            return resp, ""
        msg = bad
    return None, msg


def _clip_part(f, start_s: float, end_s: float):
    """Só o intervalo do lote: o Gemini não reprocessa o vídeo inteiro a cada chamada."""
    return types.Part(
        file_data=types.FileData(file_uri=getattr(f, "uri", None) or str(f),
                                 mime_type=getattr(f, "mime_type", None) or "video/mp4"),
        video_metadata=types.VideoMetadata(start_offset=f"{start_s:.2f}s", end_offset=f"{end_s:.2f}s"))


def _analyze_media(db: ProjectDB, c, m: MediaInfo, todo: list[Segment], uploaded, model: str,
                   style: StyleProfile | None) -> None:
    for k in range(0, len(todo), BATCH):
        batch = todo[k:k + BATCH]
        key = f"{m.id}:{batch[0].id}"
        if db.quota_strikes(key) >= MAX_MINUTE_PAUSES:
            db.add_falha("analise", m.rel_path, _MSG_MINUTO)
            return
        clip = (batch[0].start_s, batch[-1].end_s) if uploaded is not None else None
        parts = [_clip_part(uploaded, *clip)] if clip else []
        speech = {s.id: segment_speech(db, m, s) for s in batch}
        prompt = build_prompt(m, batch, speech, style, clip=clip)
        try:
            resp, msg = _ask(c, model, parts, prompt, [s.id for s in batch])
        except QuotaPaused as e:
            if e.daily or db.bump_quota_strike(key) < MAX_MINUTE_PAUSES:
                raise
            db.add_falha("analise", m.rel_path, _MSG_MINUTO)
            return
        except Exception as e:  # noqa: BLE001 — erro da API/rede: falha desta mídia, segue
            db.clear_quota_strike(key)
            db.add_falha("analise", m.rel_path, f"Falha na análise pelo Gemini: {e}")
            return
        db.clear_quota_strike(key)
        if resp is None:
            db.add_falha("analise", m.rel_path,
                         f"O Gemini não devolveu uma análise válida após {MAX_ATTEMPTS} tentativas: {msg}")
            return
        by_id = {s.id: s for s in batch}
        for a in resp.segmentos:
            seg = by_id[a.segment_id]
            db.set_analysis(a.model_copy(update={
                "melhores_trechos": _clamp(a.melhores_trechos, seg),
                "falas_chave": _clamp(a.falas_chave, seg)}))


def analyze_event(db: ProjectDB, c, p: EventPaths, model: str, style: StyleProfile | None = None,
                  on_progress: Callable[[int, int, str], None] | None = None) -> None:
    medias = [m for m in db.list_media() if m.role not in (Role.ignorar, Role.outro_dia)]
    total = len(medias)
    for i, m in enumerate(medias, 1):
        if on_progress:
            on_progress(i, total, m.rel_path)
        todo = [s for s in db.list_segments(m.id) if db.get_analysis(s.id) is None]
        if not todo:
            continue
        uploaded = None
        if m.kind == "video":
            proxy = db.proxy_for(m.id)
            if not proxy:
                db.add_falha("analise", m.rel_path, "Não foi possível analisar: sem proxy para este vídeo.")
                continue
            try:
                uploaded = c.upload(Path(proxy))
            except QuotaPaused:
                raise
            except Exception as e:  # noqa: BLE001
                db.add_falha("analise", m.rel_path, f"Falha ao enviar o vídeo ao Gemini: {e}")
                continue
        try:
            _analyze_media(db, c, m, todo, uploaded, model, style)
        finally:
            delete = getattr(c, "delete_file", None)
            if uploaded is not None and delete is not None:
                try:
                    delete(uploaded)
                except Exception:  # noqa: BLE001
                    pass
