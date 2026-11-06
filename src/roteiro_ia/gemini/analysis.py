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
# pacote: várias mídias curtas numa só chamada (o grátis permite ~20 chamadas/dia por modelo)
PACOTE_MAX_VIDEO_S = 1800  # padrão; o pipeline usa Settings.gemini_pacote_max_s
PACOTE_MAX_SEGMENTOS = 60
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


def _seg_lines(segments: list[Segment], transcripts: dict[int, str]) -> list[str]:
    linhas = []
    for s in segments:
        fala = transcripts.get(s.id) or "(sem fala transcrita)"
        linhas.append(f"- segment_id={s.id} | início={s.start_s:.2f}s | fim={s.end_s:.2f}s | fala: {fala}")
    return linhas


def _regras(com_video: bool, style: StyleProfile | None) -> list[str]:
    partes = [
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
    if com_video:
        partes.append(
            "- som_ambiente: o que se ouve no áudio da PRÓPRIA câmera naquele trecho (risos, "
            "aplausos, choro, falas ao fundo, música ao vivo, vento, sinos…), em português e curto; "
            "string vazia se não houver nada relevante. som_ambiente_util: true se esse som serve "
            "para dar realismo à cena.")
    if style is not None:
        partes.append(_style_text(style))
    return partes


def build_prompt(media: MediaInfo, segments: list[Segment], transcripts: dict[int, str],
                 style: StyleProfile | None = None,
                 clip: tuple[float, float] | None = None) -> str:
    fonte = ("Você recebe apenas o áudio transcrito (sem imagem)." if media.kind == "audio"
             else "Você está assistindo ao vídeo (proxy 480p) e recebe a fala transcrita de cada trecho.")
    partes = [
        "Você é um assistente de edição de vídeos de casamento da produtora Fokuss.",
        f"{fonte} Arquivo: {media.rel_path} (duração {media.duration_s:.1f}s).",
        *([f"O vídeo enviado é só o trecho de {clip[0]:.2f}s a {clip[1]:.2f}s do arquivo; "
           "mesmo assim, responda com tempos relativos ao arquivo inteiro."] if clip else []),
        "Analise cada segmento abaixo e devolva EXATAMENTE um item por segmento, usando o mesmo segment_id.",
        "Segmentos:", *_seg_lines(segments, transcripts),
        *_regras(media.kind != "audio", style),
    ]
    return "\n".join(partes)


def build_pack_prompt(items: list[tuple[MediaInfo, list[Segment], dict[int, str],
                                        tuple[float, float] | None]],
                      style: StyleProfile | None = None) -> str:
    """Prompt de um pacote: segmentos agrupados por ARQUIVO n (na ordem das parts enviadas)."""
    partes = [
        "Você é um assistente de edição de vídeos de casamento da produtora Fokuss.",
        f"Você recebe {len(items)} arquivo(s) do mesmo casamento. Cada arquivo vem anunciado por um "
        "texto 'ARQUIVO n: <caminho>'; logo depois vem o vídeo (proxy 480p) quando for vídeo. "
        "Arquivos só de áudio não têm imagem: use a fala transcrita.",
        "Analise cada segmento abaixo e devolva EXATAMENTE um item por segmento de TODOS os "
        "arquivos, usando o mesmo segment_id (os ids são únicos no pacote).",
    ]
    for n, (m, segs, speech, clip) in enumerate(items, 1):
        tipo = "só áudio, sem imagem" if m.kind == "audio" else "vídeo"
        partes.append(f"ARQUIVO {n}: {m.rel_path} ({tipo}, duração {m.duration_s:.1f}s)")
        if clip:
            partes.append(f"  O vídeo enviado é só o trecho de {clip[0]:.2f}s a {clip[1]:.2f}s deste "
                          "arquivo; responda com tempos relativos ao arquivo inteiro.")
        partes += _seg_lines(segs, speech)
    partes += _regras(any(m.kind != "audio" for m, *_ in items), style)
    return "\n".join(partes)


def _clamp(items, seg: Segment):
    out = []
    for it in items:
        a = min(max(it.start_s, seg.start_s), seg.end_s)
        b = min(max(it.end_s, seg.start_s), seg.end_s)
        if b - a > 0:
            out.append(it.model_copy(update={"start_s": a, "end_s": b}))
    return out


def _ask(db: ProjectDB, c, model: str, segs: list[Segment],
         request: Callable[[list[Segment]], tuple[list, str]]) -> tuple[list[Segment], str]:
    """Até MAX_ATTEMPTS chamadas. Depois de cada uma, grava na hora toda análise válida (id
    pedido, sem repetição) e a próxima pede SÓ os segmentos que faltam (`request(faltando)`
    devolve parts e prompt). Devolve (segmentos ainda sem análise, motivo)."""
    pending = {s.id: s for s in segs}
    msg = ""
    for _ in range(MAX_ATTEMPTS):
        parts, prompt = request([s for s in segs if s.id in pending])
        try:
            resp = c.generate_json(model, parts, FileAnalysis, prompt, max_retries=1)
        except ValueError as e:
            msg = str(e)
            continue
        got = [a.segment_id for a in resp.segmentos]
        ok, seen = [], set()
        for a in resp.segmentos:
            if a.segment_id in pending and a.segment_id not in seen:
                seen.add(a.segment_id)
                ok.append(a)
        _save(db, FileAnalysis(segmentos=ok), [pending[i] for i in seen])
        for i in seen:
            del pending[i]
        if not pending:
            return [], ""
        msg = (f"ids inválidos (faltando {sorted(pending)}, "
               f"desconhecidos {sorted(set(got) - {s.id for s in segs})}, "
               f"repetidos {len(got) - len(set(got))})")
    return [s for s in segs if s.id in pending], msg


def _clip_part(f, start_s: float, end_s: float):
    """Só o intervalo do lote: o Gemini não reprocessa o vídeo inteiro a cada chamada."""
    return types.Part(
        file_data=types.FileData(file_uri=getattr(f, "uri", None) or str(f),
                                 mime_type=getattr(f, "mime_type", None) or "video/mp4"),
        video_metadata=types.VideoMetadata(start_offset=f"{start_s:.2f}s", end_offset=f"{end_s:.2f}s"))


def _analyze_media(db: ProjectDB, c, m: MediaInfo, todo: list[Segment], uploaded, model: str,
                   style: StyleProfile | None) -> None:
    speech = {s.id: segment_speech(db, m, s) for s in todo}

    def request(segs: list[Segment]) -> tuple[list, str]:
        clip = (segs[0].start_s, segs[-1].end_s) if uploaded is not None else None
        parts = [_clip_part(uploaded, *clip)] if clip else []
        return parts, build_prompt(m, segs, speech, style, clip=clip)

    for k in range(0, len(todo), BATCH):
        batch = todo[k:k + BATCH]
        key = f"{m.id}:{batch[0].id}"
        if db.quota_strikes(key) >= MAX_MINUTE_PAUSES:
            db.add_falha("analise", m.rel_path, _MSG_MINUTO)
            return
        try:
            missing, msg = _ask(db, c, model, batch, request)
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
        if missing:
            db.add_falha("analise", m.rel_path,
                         f"O Gemini não devolveu uma análise válida após {MAX_ATTEMPTS} tentativas: {msg}")
            return


def _save(db: ProjectDB, resp: FileAnalysis, segs: list[Segment]) -> None:
    by_id = {s.id: s for s in segs}
    for a in resp.segmentos:
        seg = by_id[a.segment_id]
        db.set_analysis(a.model_copy(update={
            "melhores_trechos": _clamp(a.melhores_trechos, seg),
            "falas_chave": _clamp(a.falas_chave, seg)}))


def _delete(c, uploaded) -> None:
    delete = getattr(c, "delete_file", None)
    if uploaded is None or delete is None:
        return
    try:
        delete(uploaded)
    except Exception:  # noqa: BLE001
        pass


_SEM_UPLOAD = object()  # mídia só de áudio: nada a enviar


def _upload(db: ProjectDB, c, m: MediaInfo):
    """Envia o proxy do vídeo. Devolve o arquivo enviado, _SEM_UPLOAD (áudio) ou None (falha
    já registrada). QuotaPaused propaga."""
    if m.kind != "video":
        return _SEM_UPLOAD
    proxy = db.proxy_for(m.id)
    if not proxy:
        db.add_falha("analise", m.rel_path, "Não foi possível analisar: sem proxy para este vídeo.")
        return None
    try:
        return c.upload(Path(proxy))
    except QuotaPaused:
        raise
    except Exception as e:  # noqa: BLE001
        db.add_falha("analise", m.rel_path, f"Falha ao enviar o vídeo ao Gemini: {e}")
        return None


def _video_s(m: MediaInfo, todo: list[Segment]) -> float:
    """Segundos de vídeo enviados (o trecho recortado do primeiro ao último segmento)."""
    return 0.0 if m.kind == "audio" else max(0.0, todo[-1].end_s - todo[0].start_s)


def _sozinha(m: MediaInfo, todo: list[Segment], max_video_s: float = PACOTE_MAX_VIDEO_S) -> bool:
    return _video_s(m, todo) > max_video_s or len(todo) > PACOTE_MAX_SEGMENTOS


def _analyze_solo(db: ProjectDB, c, m: MediaInfo, todo: list[Segment], model: str,
                  style: StyleProfile | None) -> None:
    """Mídia longa: sozinha, em lotes por intervalo (como antes dos pacotes)."""
    f = _upload(db, c, m)
    if f is None:
        return
    uploaded = None if f is _SEM_UPLOAD else f
    try:
        _analyze_media(db, c, m, todo, uploaded, model, style)
    finally:
        _delete(c, uploaded)


# item de pacote: (mídia, segmentos pendentes, falas por segment_id, arquivo enviado|_SEM_UPLOAD)
_Item = tuple[MediaInfo, list[Segment], dict[int, str], object]


def _pack_request(items: list[_Item], style: StyleProfile | None,
                  segs: list[Segment]) -> tuple[list, str]:
    """Parts e prompt só com `segs` (os arquivos sem segmento pedido ficam de fora; o recorte
    de cada vídeo vai do primeiro ao último segmento pedido dele)."""
    want = {s.id for s in segs}
    parts: list = []
    prompt_items = []
    n = 0
    for m, todo, sp, f in items:
        mine = [s for s in todo if s.id in want]
        if not mine:
            continue
        n += 1
        clip = None if f is _SEM_UPLOAD else (mine[0].start_s, mine[-1].end_s)
        parts.append(f"ARQUIVO {n}: {m.rel_path}")
        if clip:
            parts.append(_clip_part(f, *clip))
        prompt_items.append((m, mine, sp, clip))
    return parts, build_pack_prompt(prompt_items, style)


def _split(items: list[_Item]) -> tuple[list[_Item], list[_Item]] | None:
    """Metade das mídias; com uma mídia só, metade dos segmentos (e do recorte)."""
    if len(items) > 1:
        h = len(items) // 2
        return items[:h], items[h:]
    m, todo, sp, f = items[0]
    if len(todo) < 2:
        return None
    h = len(todo) // 2
    return [(m, todo[:h], sp, f)], [(m, todo[h:], sp, f)]


def _pack_call(db: ProjectDB, c, items: list[_Item], model: str, style: StyleProfile | None) -> None:
    # só o que ainda não foi analisado (ex.: salvo antes de uma pausa)
    items = [(m, [s for s in todo if db.get_analysis(s.id) is None], sp, f) for m, todo, sp, f in items]
    items = [it for it in items if it[1]]
    if not items:
        return
    segs = [s for _m, todo, *_ in items for s in todo]
    # o tamanho entra na chave: as metades de um pacote dividido têm contagem própria
    key = f"{items[0][0].id}:{segs[0].id}:{len(segs)}"

    def falha(msg: str, only: set[int] | None = None) -> None:
        for m, todo, *_ in items:
            if only is None or any(s.id in only for s in todo):
                db.add_falha("analise", m.rel_path, msg)

    def dividir() -> None:
        halves = _split(items)
        if halves is None:
            falha(_MSG_MINUTO)
            return
        for h in halves:
            _pack_call(db, c, h, model, style)

    if db.quota_strikes(key) >= MAX_MINUTE_PAUSES:
        dividir()  # já desistido numa execução anterior: segue direto com as metades
        return
    try:
        missing, msg = _ask(db, c, model, segs, lambda want: _pack_request(items, style, want))
    except QuotaPaused as e:
        if e.daily or db.bump_quota_strike(key) < MAX_MINUTE_PAUSES:
            raise
        dividir()  # pacote grande demais para a cota por minuto: tenta em duas metades
        return
    except Exception as e:  # noqa: BLE001 — erro da API/rede: falha das mídias do pacote, segue
        db.clear_quota_strike(key)
        falha(f"Falha na análise pelo Gemini: {e}",
              {s.id for s in segs if db.get_analysis(s.id) is None})
        return
    db.clear_quota_strike(key)
    if missing:
        falha(f"O Gemini não devolveu uma análise válida após {MAX_ATTEMPTS} tentativas: {msg}",
              {s.id for s in missing})


def _analyze_pack(db: ProjectDB, c, pack: list[tuple[MediaInfo, list[Segment]]], model: str,
                  style: StyleProfile | None) -> None:
    """Uma chamada para o pacote todo (ou para metades, se a cota por minuto não comportar);
    o que faltar após as tentativas vira falha de cada mídia afetada. Uploads apagados no fim."""
    uploads = []
    try:
        items: list[_Item] = []
        for m, todo in pack:
            f = _upload(db, c, m)
            if f is None:
                continue
            if f is not _SEM_UPLOAD:
                uploads.append(f)
            items.append((m, todo, {s.id: segment_speech(db, m, s) for s in todo}, f))
        if items:
            _pack_call(db, c, items, model, style)
    finally:
        for f in uploads:
            _delete(c, f)


def analyze_event(db: ProjectDB, c, p: EventPaths, model: str, style: StyleProfile | None = None,
                  on_progress: Callable[[int, int, str], None] | None = None,
                  max_video_s: float = PACOTE_MAX_VIDEO_S) -> None:
    """Mídias curtas vão em pacotes (até `max_video_s` de vídeo e PACOTE_MAX_SEGMENTOS
    segmentos por chamada, na ordem do banco); mídia longa vai sozinha, em lotes por intervalo."""
    medias = [m for m in db.list_media() if m.role not in (Role.ignorar, Role.outro_dia)]
    total = len(medias)
    pack: list[tuple[MediaInfo, list[Segment]]] = []
    video_s = 0.0
    n_segs = 0

    def flush() -> None:
        nonlocal pack, video_s, n_segs
        if pack:
            cur, pack, video_s, n_segs = pack, [], 0.0, 0
            _analyze_pack(db, c, cur, model, style)

    for i, m in enumerate(medias, 1):
        if on_progress:
            on_progress(i, total, m.rel_path)
        todo = [s for s in db.list_segments(m.id) if db.get_analysis(s.id) is None]
        if not todo:
            continue
        if m.kind == "video" and not db.proxy_for(m.id):
            db.add_falha("analise", m.rel_path, "Não foi possível analisar: sem proxy para este vídeo.")
            continue
        if _sozinha(m, todo, max_video_s):
            _analyze_solo(db, c, m, todo, model, style)
            continue
        v = _video_s(m, todo)
        if pack and (video_s + v > max_video_s or n_segs + len(todo) > PACOTE_MAX_SEGMENTOS):
            flush()
        pack.append((m, todo))
        video_s += v
        n_segs += len(todo)
    flush()
