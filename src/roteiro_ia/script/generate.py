"""Pré-roteiro em série gerado pelo Gemini a partir do catálogo analisado, com validação
de toda referência de cena (mídia real + intervalo dentro da duração) e de trilha."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from roteiro_ia.db import ProjectDB
from roteiro_ia.gemini.style import StyleProfile
from roteiro_ia.models import MediaInfo, TrackInfo
from roteiro_ia.music_index import MusicIndex

CORRECTION_ROUNDS = 2
DURATION_TOLERANCE_S = 0.5
DERIVADOS = {"trailer", "teaser", "stories"}
MAX_PROMPT_TOKENS = 300_000  # acima disso o catálogo é compactado
COMPACT_DESC_CHARS = 120
SO_AUDIO = "[só áudio]"

REGRAS_FOKUSS = """Regras de edição da Fokuss (siga todas):
1. Narrativa em série: o casamento é contado em episódios. Cada episódio (menos o último) termina num GANCHO que só se resolve na ABERTURA do episódio seguinte; diga em gancho_resolve_em onde ele se resolve.
2. Ordem não-cronológica controlada: a cronologia é a base, mas quando um trecho vai baixar a emoção, puxe um momento de outra parte do evento (preparação, despedida de solteiro, pré-wedding, lua de mel…) para manter a intensidade. Toda mistura não-cronológica precisa de um motivo, registrado em 'misturas' e no 'motivo' da cena.
3. Áudio real como fio condutor: use as falas verdadeiras (votos, discursos, depoimentos) para contar a história; coloque a fala usada em 'fala'.
4. Conteúdo acima da técnica: 1º a história — se só existe um take ruim de um momento importante, ele é usado; 2º a qualidade técnica, só para escolher entre opções equivalentes.
5. Duração: cada episódio tem em média 360 s (6 min), com flexibilidade conforme o conteúdo.
6. Cortes na trilha: músicas lentas → cortes nos tempos 1 e 3 (padrão "1-3"); músicas rápidas ou trechos de mais intensidade → tempos 2 e 4 (padrão "2-4"); use "misto" quando a peça alterna.
7. Poucos efeitos: cor viva, transições suaves só quando necessário.
8. Criatividade: você pode sugerir momentos de lembrança/flashback (marque lembranca=true; na edição terão outra tonalidade e áudio filtrado/reverb) e momentos extras fora da lista base.
9. Trailer, teaser e stories/reels: mesma estrutura das peças, focados nos momentos de maior impacto, SEM entregar os ganchos dos episódios.
10. Mídias marcadas [só áudio] no catálogo (mesa, gravador, lapela) não têm imagem: use-as só como 'fala' sobre uma cena de vídeo do mesmo momento, NUNCA como rel_path de uma cena.
11. Som ambiente da câmera: o som ambiente da câmera (risos, aplausos, emoção, falas ao fundo; veja 'som:' no catálogo, ★ = útil) pode ser usado para dar realismo; marque usar_som_camera=true nas cenas em que ele deve ficar audível junto da mesa/ambiente.
12. Trilha pela melodia, não só pela batida (veja voz, clima, instrumentos e intro na lista de trilhas): embaixo de fala real (votos, discursos, depoimentos) prefira trilha instrumental — ou só o trecho instrumental de uma cantada, usando a intro instrumental antes de a voz entrar; montagens sem fala aceitam trilha cantada; gancho e clímax pedem trilha épica, inspiradora ou de perfil crescente; abertura emotiva pede piano, cordas ou clima calmo. Quando a música deve começar em outro ponto (ex.: pular para o refrão ou para um trecho instrumental), informe trecho_inicio_s em segundos."""

_FORMATO = """Formato das referências (obrigatório):
- Cada cena (abertura, desenvolvimento, gancho) usa rel_path EXATAMENTE como aparece no catálogo e start_s/end_s em segundos RELATIVOS AO ARQUIVO, dentro do intervalo do segmento escolhido (início < fim).
- Episódios: tipo "episodio", numero 1, 2, 3… em sequência. Derivados: tipo "trailer", "teaser" ou "stories", numero null.
- curva_emocao: intensidade 0–10 ao longo da peça; duracao_estimada_s em segundos.
- Trilhas por peça: 2–3 opções origem "biblioteca" com path EXATAMENTE como na lista de trilhas (BPM, clima, motivo, padrao_corte); termos de busca para Musicbed em termos_musicbed (origem "musicbed" se sugerir uma faixa de lá); músicas populares com origem "popular" e exige_licenca=true. trecho_inicio_s (opcional): segundo da música em que ela deve começar; null = do início.
- alertas: momentos importantes sem take bom ou qualquer ressalva para o editor."""

_BPM_BANDS = ((0.0, 90.0), (90.0, 120.0), (120.0, float("inf")))
_PERFIS = ("calma", "crescente", "intensa")


class SceneRef(BaseModel):
    rel_path: str
    start_s: float
    end_s: float
    descricao: str
    fala: str | None
    motivo: str | None
    lembranca: bool = False
    usar_som_camera: bool = False


class MusicSuggestion(BaseModel):
    origem: Literal["biblioteca", "musicbed", "popular"]
    path: str | None
    titulo: str
    bpm: float | None
    clima: str
    motivo: str
    padrao_corte: Literal["1-3", "2-4", "misto"]
    exige_licenca: bool
    trecho_inicio_s: float | None = None  # onde começar a música (ex.: só a intro instrumental)


class Piece(BaseModel):
    tipo: Literal["episodio", "trailer", "teaser", "stories"]
    numero: int | None
    titulo: str
    tema: str
    abertura: SceneRef
    desenvolvimento: list[SceneRef]
    gancho: SceneRef | None
    gancho_resolve_em: str | None
    curva_emocao: list[int]
    duracao_estimada_s: float
    misturas: list[str]
    trilhas: list[MusicSuggestion]
    termos_musicbed: list[str]


class Roteiro(BaseModel):
    arco: str
    pecas: list[Piece]
    alertas: list[str]


# ---------------------------------------------------------------- catálogo e trilhas

def _clean(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "/")


def _fraco(a) -> bool:
    """Trecho que pode sair do catálogo compactado: pouca emoção, pouca qualidade, sem fala-chave
    e sem gancho."""
    return (a.emocao_intensidade <= 2 and a.qualidade <= 3 and not a.falas_chave
            and not a.potencial_gancho and not a.som_ambiente_util)


def build_catalog(db: ProjectDB, compact: bool = False) -> str:
    """Uma linha por segmento analisado, com os dias em ordem cronológica (pela mídia mais antiga
    de cada dia; dias sem data vão ao fim) e cada dia na ordem da linha do tempo (mídias sem
    sincronia vão ao fim do seu dia). Tempos relativos ao arquivo. `compact` descarta trechos
    fracos e encurta as descrições."""
    rows = []
    medias = {m.id: m for m in db.list_media()}
    syncs = {mid: db.get_sync(mid) for mid in medias}
    first: dict[str, datetime] = {}
    for m in medias.values():
        sy = syncs.get(m.id)
        day = sy.day_label if sy else m.day_label
        if m.created_at is not None:
            ca = m.created_at.replace(tzinfo=None)
            if day not in first or ca < first[day]:
                first[day] = ca
    for seg in db.list_segments():
        a = db.get_analysis(seg.id)
        m = medias.get(seg.media_id)
        if a is None or m is None:
            continue
        if compact and _fraco(a):
            continue
        sy = syncs.get(m.id)
        day = sy.day_label if sy else m.day_label
        dkey = (0, first[day], day) if day in first else (1, datetime.max, day)
        key = ((dkey, 0, sy.timeline_start_s + seg.start_s, m.rel_path) if sy
               else (dkey, 1, 0.0, m.rel_path))
        momento = a.momento + (f" ({a.extra})" if a.extra else "")
        falas = "; ".join(f'"{_clean(q.text)}" ({q.start_s:.1f}–{q.end_s:.1f})'
                          for q in a.falas_chave) or "-"
        gancho = "sim" + (f" ({_clean(a.motivo_gancho)})" if a.motivo_gancho else "") \
            if a.potencial_gancho else "não"
        extras = " | lembrança: sim" if a.sugestao_lembranca else ""
        if a.som_ambiente:
            extras += f" | som: {_clean(a.som_ambiente)}" + (" ★" if a.som_ambiente_util else "")
        if m.kind != "video":
            extras += f" | {SO_AUDIO}"
        desc = _clean(a.descricao)
        if compact:
            desc = desc[:COMPACT_DESC_CHARS]
        line = (f"{m.rel_path} | {seg.start_s:.1f}–{seg.end_s:.1f} s | dia {day} | "
                f"momento {_clean(momento)} | emoção {a.emocao_intensidade} {_clean(a.emocao_tipo)} | "
                f"qualidade {a.qualidade} | {desc} | falas: {falas} | "
                f"gancho: {gancho}{extras}")
        rows.append((key, seg.start_s, line))
    rows.sort(key=lambda r: (r[0], r[1]))
    return "\n".join(r[2] for r in rows)


def _band(bpm: float) -> int:
    for i, (lo, hi) in enumerate(_BPM_BANDS):
        if lo <= bpm < hi:
            return i
    return len(_BPM_BANDS) - 1


def _voz_txt(t) -> str:
    if not t.has_vocals:
        return "instrumental"
    return f"cantada (voz {round(t.voz_proporcao * 100)}%)" if t.voz_proporcao > 0 else "cantada"


def _track_line(t) -> str:
    dur = int(round(t.duration_s))
    partes = [t.path, f"BPM {t.bpm:.1f}", f"perfil {t.perfil}", f"{dur // 60}:{dur % 60:02d}",
              _voz_txt(t)]
    if t.climas:
        partes.append("clima " + ", ".join(t.climas))
    if t.instrumentos:
        partes.append("instrumentos " + ", ".join(t.instrumentos))
    if t.has_vocals and t.tipo_voz and t.tipo_voz != "sem voz":
        partes.append(f"voz {t.tipo_voz}")
    if t.has_vocals and t.intro_instrumental_s >= 1:
        n = int(round(t.intro_instrumental_s))
        partes.append(f"intro instrumental de {n} s" if t.voz_inicio_s is not None
                      else f"intro instrumental de pelo menos {n} s")
    if t.tonalidade:
        partes.append(f"tom {t.tonalidade}")
    return " | ".join(_clean(p) if i else p for i, p in enumerate(partes))


def music_shortlist(idx: MusicIndex, n: int = 80) -> str:
    """Até n trilhas espalhadas por perfil, faixa de BPM e clima principal (determinístico:
    round-robin entre os grupos, cada grupo ordenado por caminho)."""
    buckets: dict[tuple[int, int, str], list] = {}
    for t in idx.all():
        p = _PERFIS.index(t.perfil) if t.perfil in _PERFIS else len(_PERFIS)
        buckets.setdefault((p, _band(t.bpm), t.climas[0] if t.climas else ""), []).append(t)
    # Ordem dos grupos intercalada por clima: o 1º grupo de cada clima, depois o 2º de cada…
    # Assim todo clima entra antes de algum se repetir, mesmo com mais grupos do que n.
    por_clima: dict[str, list] = {}
    for k in sorted(buckets):
        por_clima.setdefault(k[2], []).append(k)
    listas = [por_clima[c] for c in sorted(por_clima)]
    ordem = [lst[j] for j in range(max(map(len, listas), default=0))
             for lst in listas if j < len(lst)]
    queues = [sorted(buckets[k], key=lambda t: t.path) for k in ordem]
    picked = []
    i = 0
    while len(picked) < n and any(queues):
        q = queues[i % len(queues)]
        if q:
            picked.append(q.pop(0))
        i += 1
    return "\n".join(_track_line(t) for t in picked)


# ---------------------------------------------------------------- validação

def _norm(path: str) -> str:
    return path.replace("/", "\\").strip().lower()


def _media_map(db: ProjectDB) -> dict[str, MediaInfo]:
    return {_norm(m.rel_path): m for m in db.list_media()}


def _ref_problem(ref: SceneRef, media: dict[str, MediaInfo]) -> str | None:
    """None se a referência é válida (e normaliza rel_path para a grafia do banco)."""
    m = media.get(_norm(ref.rel_path))
    if m is None:
        return f"a mídia {ref.rel_path} não existe no catálogo"
    ref.rel_path = m.rel_path
    if m.kind != "video":
        return (f"a mídia {m.rel_path} é só de áudio (sem imagem) — não pode ser cena; "
                "use como fala sobre uma cena de vídeo")
    if not (0 <= ref.start_s < ref.end_s <= m.duration_s + DURATION_TOLERANCE_S):
        return (f"intervalo {ref.start_s:.1f}–{ref.end_s:.1f} s inválido em {m.rel_path} "
                f"(duração {m.duration_s:.1f} s)")
    return None


def _track_map(idx: MusicIndex) -> dict[str, TrackInfo]:
    return {_norm(t.path): t for t in idx.all()}


def _track_problem(ms: MusicSuggestion, tracks: dict[str, TrackInfo]) -> str | None:
    if ms.origem == "popular":
        ms.exige_licenca = True
    if ms.origem != "biblioteca":
        return None
    real = tracks.get(_norm(ms.path or ""))
    if real is None:
        return f"a trilha '{ms.titulo}' ({ms.path}) não existe na biblioteca"
    ms.path = real.path
    return None


def inicio_valido(inicio: float | None, duracao_s: float) -> bool:
    """trecho_inicio_s utilizável: 0 ≤ início < duração da trilha."""
    return inicio is not None and 0 <= inicio < duracao_s


def _check_inicio(ms: MusicSuggestion, tracks: dict[str, TrackInfo], lab: str,
                  r: Roteiro) -> None:
    """Início de trilha fora da música (ou sem a música no índice) é descartado com alerta."""
    if ms.trecho_inicio_s is None:
        return
    info = tracks.get(_norm(ms.path or "")) if ms.origem == "biblioteca" else None
    if info is not None and inicio_valido(ms.trecho_inicio_s, info.duration_s):
        return
    dur = f" (duração {info.duration_s:.0f} s)" if info is not None else ""
    aviso = (f"{lab}, trilhas: início {ms.trecho_inicio_s:.0f} s ignorado na trilha "
             f"'{ms.titulo}'{dur} — a música começa do início")
    ms.trecho_inicio_s = None
    if aviso not in r.alertas:
        r.alertas.append(aviso)


def _label(p: Piece) -> str:
    if p.tipo == "episodio":
        return f"episódio {p.numero}"
    return p.tipo + (f" {p.numero}" if p.numero is not None else "")


def _episodes(r: Roteiro) -> list[Piece]:
    return [p for p in r.pecas if p.tipo == "episodio"]


def validate_refs(r: Roteiro, db: ProjectDB, idx: MusicIndex) -> list[str]:
    """Lista de problemas (em português). Normaliza rel_path/path para a grafia real e
    força exige_licenca nas sugestões populares."""
    media, tracks = _media_map(db), _track_map(idx)
    probs: list[str] = []
    for p in r.pecas:
        lab = _label(p)
        scenes = [("abertura", p.abertura)] + [("desenvolvimento", s) for s in p.desenvolvimento]
        if p.gancho is not None:
            scenes.append(("gancho", p.gancho))
        for where, s in scenes:
            e = _ref_problem(s, media)
            if e:
                probs.append(f"{lab}, {where}: {e}")
            elif s.usar_som_camera and media[_norm(s.rel_path)].audio_channels <= 0:
                s.usar_som_camera = False
                aviso = (f"{lab}, {where}: usar_som_camera ignorado — {s.rel_path} "
                         "não tem áudio (som da câmera indisponível)")
                if aviso not in r.alertas:
                    r.alertas.append(aviso)
        for ms in p.trilhas:
            e = _track_problem(ms, tracks)
            if e:
                probs.append(f"{lab}, trilhas: {e}")
            else:
                _check_inicio(ms, tracks, lab, r)
    eps = _episodes(r)
    nums = [p.numero for p in eps]
    if nums != list(range(1, len(eps) + 1)):
        probs.append(f"episódios devem ser numerados 1..{len(eps)} em sequência (recebido {nums})")
    for p in eps[:-1]:
        if p.gancho is None:
            probs.append(f"{_label(p)}: falta o gancho (só o último episódio pode ficar sem)")
    return probs


def _prune(r: Roteiro, db: ProjectDB, idx: MusicIndex) -> list[str]:
    """Remove o que continua inválido e devolve a descrição de cada remoção."""
    media, tracks = _media_map(db), _track_map(idx)
    alertas: list[str] = []
    kept: list[Piece] = []
    for p in r.pecas:
        lab = _label(p)
        dev = []
        for s in p.desenvolvimento:
            e = _ref_problem(s, media)
            if e:
                alertas.append(f"{lab}: cena removida do desenvolvimento — {e}")
            else:
                dev.append(s)
        p.desenvolvimento = dev
        if p.gancho is not None:
            e = _ref_problem(p.gancho, media)
            if e:
                alertas.append(f"{lab}: gancho removido — {e}")
                p.gancho = None
                p.gancho_resolve_em = None
        e = _ref_problem(p.abertura, media)
        if e:
            if not p.desenvolvimento:
                alertas.append(f"{lab}: peça removida (nenhuma cena válida) — {e}")
                continue
            p.abertura = p.desenvolvimento.pop(0)
            alertas.append(f"{lab}: abertura substituída pela primeira cena válida do "
                           f"desenvolvimento — {e}")
        trilhas = []
        for ms in p.trilhas:
            e = _track_problem(ms, tracks)
            if e:
                alertas.append(f"{lab}: sugestão de trilha removida — {e}")
            else:
                trilhas.append(ms)
        p.trilhas = trilhas
        kept.append(p)
    r.pecas = kept
    eps = _episodes(r)
    if [p.numero for p in eps] != list(range(1, len(eps) + 1)):
        alertas.append(f"episódios renumerados em sequência (1..{len(eps)})")
        for i, p in enumerate(eps, 1):
            p.numero = i
    for p in eps[:-1]:
        if p.gancho is None:
            alertas.append(f"{_label(p)}: sem gancho válido para o próximo episódio")
    return alertas


# ---------------------------------------------------------------- geração

def _style_text(style: StyleProfile) -> str:
    return "\n".join([
        "Perfil de estilo da Fokuss (extraído dos vídeos publicados):",
        f"- resumo: {style.resumo}",
        f"- duração média do episódio: {style.duracao_media_episodio_s:.0f} s; "
        f"ritmo médio de corte: {style.ritmo_corte_medio_s:.1f} s",
        f"- aberturas: {'; '.join(style.padroes_abertura) or '-'}",
        f"- ganchos: {'; '.join(style.padroes_gancho) or '-'}",
        f"- uso de falas: {style.uso_falas}",
        f"- trilhas: {style.trilhas}",
        f"- cor: {style.cor}",
        f"- teaser/trailer: {style.estrutura_teaser_trailer}",
    ])


def _context(db: ProjectDB, idx: MusicIndex, style: StyleProfile | None,
             n_episodios: int | None, derivados: set[str], compact: bool = False) -> str:
    unknown = set(derivados) - DERIVADOS
    if unknown:
        raise ValueError(f"Derivados desconhecidos: {', '.join(sorted(unknown))}")
    qtd = (f"Divida a série em {n_episodios} episódios." if n_episodios
           else "Você decide a quantidade de episódios conforme o material.")
    der = (f"Crie também estes derivados: {', '.join(sorted(derivados))}." if derivados
           else "Não crie derivados (trailer, teaser ou stories).")
    partes = [
        "Você é o roteirista da produtora Fokuss, que edita casamentos como séries.",
        "Escreva o PRÉ-ROTEIRO: o arco da série, cada episódio (título, tema, abertura, "
        "desenvolvimento com cenas em ordem e falas-chave, gancho e onde ele se resolve, curva de "
        "emoção, duração estimada, lembranças sugeridas, motivo de cada mistura não-cronológica) "
        "e as trilhas de cada peça.",
        qtd, der, "", REGRAS_FOKUSS, "", _FORMATO,
    ]
    if style is not None:
        partes += ["", _style_text(style)]
    partes += [
        "", "CATÁLOGO DO MATERIAL (dias em ordem cronológica; rel_path | início–fim do segmento | "
        "dia | momento | emoção | qualidade | descrição | falas | gancho):",
        build_catalog(db, compact=compact) or "(vazio)",
        "", "TRILHAS DA BIBLIOTECA (path | BPM | perfil | duração | instrumental ou cantada | "
        "clima | instrumentos | tipo de voz | intro instrumental | tonalidade; campos sem análise "
        "ficam de fora):",
        music_shortlist(idx) or "(nenhuma trilha indexada)",
    ]
    return "\n".join(partes)


def generate_roteiro(db: ProjectDB, c, idx: MusicIndex, style: StyleProfile | None, model: str,
                     n_episodios: int | None, derivados: set[str],
                     pedido_ajuste: str | None = None) -> Roteiro:
    """Gera (ou ajusta) o pré-roteiro, valida as referências com até 2 rodadas de correção,
    remove o que sobrar inválido (listado em alertas) e grava no banco."""
    def montar(compact: bool) -> tuple[str, str]:
        base = _context(db, idx, style, n_episodios, derivados, compact=compact)
        if not pedido_ajuste:
            return base, base
        anterior = db.latest_roteiro()
        if anterior is None:
            raise ValueError("Não há roteiro anterior para ajustar.")
        return base, "\n".join([
            base, "", "ROTEIRO ANTERIOR (JSON):", anterior, "",
            f"PEDIDO DE AJUSTE DO EDITOR: {pedido_ajuste}",
            "Devolva o roteiro completo já ajustado, mantendo o que não foi pedido para mudar.",
        ])

    base, prompt = montar(False)
    avisos: list[str] = []
    contar = getattr(c, "count_tokens", None)
    if contar is not None:
        n = contar(model, prompt)
        if n > MAX_PROMPT_TOKENS:
            base, prompt = montar(True)
            avisos.append(
                f"Catálogo compactado para caber no Gemini ({n} tokens > {MAX_PROMPT_TOKENS}): "
                "trechos com emoção ≤ 2 e qualidade ≤ 3, sem fala-chave nem gancho, ficaram de fora "
                f"e as descrições foram encurtadas a {COMPACT_DESC_CHARS} caracteres.")
    r: Roteiro = c.generate_json(model, [], Roteiro, prompt)
    probs = validate_refs(r, db, idx)
    for _ in range(CORRECTION_ROUNDS):
        if not probs:
            break
        fix = "\n".join([
            base, "", "ROTEIRO ATUAL (JSON):", r.model_dump_json(), "",
            "O roteiro acima tem estes problemas — corrija usando apenas mídias, intervalos e "
            "trilhas que existem no catálogo e na lista de trilhas, e devolva o roteiro completo:",
            *(f"- {p}" for p in probs),
            *([f"Lembre-se do PEDIDO DE AJUSTE DO EDITOR: {pedido_ajuste}"] if pedido_ajuste else []),
        ])
        r = c.generate_json(model, [], Roteiro, fix)
        probs = validate_refs(r, db, idx)
    if probs:
        r.alertas.extend(_prune(r, db, idx))
    r.alertas.extend(avisos)
    db.add_roteiro(r.model_dump_json())
    return r
