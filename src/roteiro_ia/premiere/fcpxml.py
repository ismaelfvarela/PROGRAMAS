"""Pré-roteiro aprovado → XML do Final Cut Pro 7 (xmeml v4) importável no Premiere 2024
(Arquivo → Importar).

- Uma sequência por episódio (EP 01, EP 02…) e por derivado (TRAILER, TEASER, STORIES), soltas
  na raiz do XML: o painel as põe na pasta de peças (EPS) do padrão da Fokuss.
- V1: as cenas do roteiro em ordem (abertura, desenvolvimento…, gancho), encostadas a
  partir do quadro 0. V2…Vn: ângulos alternativos sincronizados (até 5, desativados),
  só no trecho sobreposto e alinhados no tempo real (via SyncResult).
- Cena só-de-áudio (mesa/gravador/lapela; o roteiro não deveria trazer, mas pode): V1 recebe o
  vídeo sincronizado de maior sobreposição; sem nenhum, V1 fica vazio e entra o marcador
  SEM IMAGEM. O áudio da cena vai para a faixa do seu papel (AMBIENTE se não tiver uma).
- Áudio: mesa / áudio ambiente / lapelas sobrepostos à cena nas faixas de AUDIO_TRACKS.
  O som da PRÓPRIA câmera do clipe de V1 (quando tem áudio) vai SEMPRE para o par SOM CÂMERA,
  alinhado ao V1 e com ganho `gain_for(Role.camera, …)`; a faixa fica habilitada quando a
  cena pede `usar_som_camera` (marcador SOM CÂMERA) ou quando não há mesa/ambiente
  (realismo garantido sem outra fonte — antes esse áudio ia para AMBIENTE) e desabilitada
  nos demais casos, pronta para o editor ativar. As faixas vêm em
  pares L/R: fonte estéreo (≥2 canais) vira dois clipitems ligados (<link>), canal 1 na
  faixa L e canal 2 na R; fonte mono usa só a L. Cada clipe de áudio
  recebe o filtro "Audio Levels" com 10^(ganho_dB/20), ganho de `gain_for`.
  Observação: o Premiere limita o nível de clipe a +12 dB (3,98109 linear), então o valor
  linear é limitado a 3,98109 mesmo quando `gain_for` pede mais (até +20 dB).
- A trilha nº 1 da biblioteca vai para a faixa MÚSICA desde o quadro 0; o `in` é o
  `trecho_inicio_s` sugerido (0 ≤ início < duração; inválido → começo da música + marcador TRILHA;
  o fim nunca passa da duração e, se não sobrar nenhum quadro, só o marcador TRILHA).
- Os caminhos apontam para os ORIGINAIS (source_root / rel_path), nunca para proxies:
  os proxies são anexados depois pelo painel do Premiere.
- Tempos: segundos → quadros com round(s * fps_real); start/end na taxa da sequência,
  in/out na taxa do próprio clipe. Arquivos só de áudio usam a taxa da sequência em que
  aparecem pela primeira vez. Quando a taxa do clipe é a da sequência, out = in + (end − start).
- Cada <file> é definido por completo na sua primeira ocorrência na ORDEM DO DOCUMENTO
  (preenchido numa passada final); as demais ocorrências são só `<file id="..."/>`.
- SEM clips mestres (bins MATERIAL/TRILHAS): com eles o Premiere 2024 recusava o XML inteiro
  ("The project appears to be damaged"). As mídias entram no projeto pelo painel, importadas do
  disco para VÍDEOS/<pasta>; o Premiere cria um item por arquivo usado (agrupado pelo
  <masterclipid>) e o painel junta os repetidos.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.media.audio import gain_for
from roteiro_ia.models import MediaInfo, Role
from roteiro_ia.music_index import MusicIndex
from roteiro_ia.paths import EventPaths
from roteiro_ia.safety import safe_write_text
from roteiro_ia.script.generate import Piece, Roteiro, SceneRef, inicio_valido

_AUDIO_GROUPS = ["MESA", "AMBIENTE", "SOM CÂMERA", "LAPELA NOIVO", "LAPELA NOIVA", "MÚSICA"]
AUDIO_TRACKS = [f"{g} {side}" for g in _AUDIO_GROUPS for side in ("L", "R")]
_ROLE_TRACK = {Role.mesa: "MESA", Role.audio_ambiente: "AMBIENTE",
               Role.lapela_noivo: "LAPELA NOIVO", Role.lapela_noiva: "LAPELA NOIVA"}
MAX_ALTERNATES = 5
MAX_LEVEL = 3.98109  # +12 dB, máximo do nível de clipe no Premiere
DEFAULT_RATE = (30000, 1001)
_DERIVADO_NAME = {"trailer": "TRAILER", "teaser": "TEASER", "stories": "STORIES"}


# ------------------------------------------------------------------ utilitários

def pathurl(p: Path) -> str:
    """Caminho do Windows → `file://localhost/R%3a/...` (UTF-8 percent-encoding)."""
    w = PureWindowsPath(str(p))
    parts = [quote(x, safe="") for x in w.parts[1:]]
    drive = w.drive
    if drive.startswith("\\\\"):  # UNC: \\host\share
        host, _, share = drive[2:].partition("\\")
        return "file://" + "/".join([quote(host, safe=""), quote(share, safe=""), *parts])
    letter = drive.rstrip(":")
    return "file://localhost/" + "/".join([f"{letter}%3a", *parts])


def timebase(fps_num: int, fps_den: int) -> tuple[int, bool]:
    """(30000, 1001) → (30, True); (25, 1) → (25, False)."""
    if fps_num <= 0 or fps_den <= 0:
        fps_num, fps_den = DEFAULT_RATE
    fps = fps_num / fps_den
    whole = round(fps)
    if abs(fps - whole) > 1e-6 and abs(fps - whole * 1000 / 1001) < 0.01:
        return whole, True
    return whole, False


def _real(rate: tuple[int, int]) -> float:
    return rate[0] / rate[1]


def _frames(seconds: float, rate: tuple[int, int]) -> int:
    return round(seconds * _real(rate))


def _sub(parent: ET.Element, tag: str, text=None, **attrs) -> ET.Element:
    e = ET.SubElement(parent, tag, attrs)
    if text is not None:
        e.text = str(text)
    return e


def _bool(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def _rate_el(parent: ET.Element, rate: tuple[int, int]) -> None:
    tb, ntsc = timebase(*rate)
    r = _sub(parent, "rate")
    _sub(r, "timebase", tb)
    _sub(r, "ntsc", _bool(ntsc))


def _media_rate(m: MediaInfo) -> tuple[int, int] | None:
    if m.kind == "video" and m.fps_num > 0 and m.fps_den > 0:
        return (m.fps_num, m.fps_den)
    return None


# ------------------------------------------------------------------ contexto do documento

@dataclass
class _Src:
    """Um arquivo de mídia pronto para virar <file>."""
    fid: str
    path: Path
    duration_s: float
    rate: tuple[int, int]
    video: tuple[int, int] | None
    channels: int


@dataclass
class _Ctx:
    """Estado compartilhado por todo o documento: arquivos usados, taxas e ids."""
    files: dict[str, _Src] = field(default_factory=dict)
    file_rates: dict[str, tuple[int, int]] = field(default_factory=dict)
    music_ids: dict[str, str] = field(default_factory=dict)
    music_used: list[tuple[str, str, float]] = field(default_factory=list)  # id, caminho, dur
    n_clip: int = 0

    def clip_id(self) -> str:
        self.n_clip += 1
        return f"clipitem-{self.n_clip}"

    def rate_for(self, fid: str, own: tuple[int, int] | None,
                 fallback: tuple[int, int]) -> tuple[int, int]:
        return self.file_rates.setdefault(fid, own or fallback)

    def music_id(self, path: str) -> str:
        if path not in self.music_ids:
            self.music_ids[path] = f"music-{len(self.music_ids) + 1}"
        return self.music_ids[path]


def _define_file(f: ET.Element, src: _Src) -> None:
    _sub(f, "name", PureWindowsPath(str(src.path)).name)
    _sub(f, "pathurl", pathurl(src.path))
    _rate_el(f, src.rate)
    _sub(f, "duration", _frames(src.duration_s, src.rate))
    media = _sub(f, "media")
    if src.video is not None:
        sc = _sub(_sub(media, "video"), "samplecharacteristics")
        _rate_el(sc, src.rate)
        _sub(sc, "width", src.video[0])
        _sub(sc, "height", src.video[1])
        _sub(sc, "anamorphic", "FALSE")
        _sub(sc, "pixelaspectratio", "square")
        _sub(sc, "fielddominance", "none")
    if src.channels > 0:
        a = _sub(media, "audio")
        sc = _sub(a, "samplecharacteristics")
        _sub(sc, "depth", 16)
        _sub(sc, "samplerate", 48000)
        _sub(a, "channelcount", src.channels)


def _fill_files(root: ET.Element, ctx: _Ctx) -> None:
    """Definição completa no primeiro <file> de cada id na ordem do documento."""
    seen: set[str] = set()
    for f in list(root.iter("file")):
        fid = f.get("id")
        if fid in seen or len(f):
            seen.add(fid)
            continue
        seen.add(fid)
        _define_file(f, ctx.files[fid])


def _media_src(m: MediaInfo, ctx: _Ctx, source_root: Path, fallback: tuple[int, int]) -> _Src:
    fid = f"file-{m.id}"
    rate = ctx.rate_for(fid, _media_rate(m), fallback)
    video = None
    if m.kind == "video":
        video = (m.height, m.width) if m.rotation % 180 == 90 else (m.width, m.height)
    return _Src(fid, Path(source_root) / m.rel_path, m.duration_s, rate, video, m.audio_channels)


def _master_id(fid: str) -> str:
    return f"masterclip-{fid}"


def _clipitem(track: ET.Element, ctx: _Ctx, src: _Src, name: str, start: int, end: int,
              in_s: float, dur_s: float, seq_rate: tuple[int, int],
              audio_index: int | None = None, enabled: bool = True,
              level: float | None = None) -> ET.Element:
    ci = _sub(track, "clipitem", id=ctx.clip_id())
    _sub(ci, "masterclipid", _master_id(src.fid))
    _sub(ci, "name", name)
    _sub(ci, "enabled", _bool(enabled))
    _sub(ci, "duration", _frames(src.duration_s, src.rate))
    _rate_el(ci, src.rate)
    _sub(ci, "start", start)
    _sub(ci, "end", end)
    fin = _frames(in_s, src.rate)
    _sub(ci, "in", fin)
    if timebase(*src.rate) == timebase(*seq_rate):
        fout = fin + (end - start)
    else:
        fout = _frames(in_s + dur_s, src.rate)
    _sub(ci, "out", fout)
    ctx.files.setdefault(src.fid, src)
    _sub(ci, "file", id=src.fid)
    if audio_index is not None:
        st = _sub(ci, "sourcetrack")
        _sub(st, "mediatype", "audio")
        _sub(st, "trackindex", audio_index)
        _levels(ci, 1.0 if level is None else level)
    return ci


def _link(items: list[tuple[ET.Element, str, int, int]]) -> None:
    """Liga clipitems (padrão do export FCP7 do Premiere): cada um lista todos do grupo."""
    for ci, *_ in items:
        for other, mediatype, trackindex, clipindex in items:
            ln = _sub(ci, "link")
            _sub(ln, "linkclipref", other.get("id"))
            _sub(ln, "mediatype", mediatype)
            _sub(ln, "trackindex", trackindex)
            _sub(ln, "clipindex", clipindex)


def _place_audio(a_tracks: dict[str, ET.Element], group: str, ctx: _Ctx, src: _Src, name: str,
                 start: int, end: int, in_s: float, dur_s: float, seq_rate: tuple[int, int],
                 level: float, enabled: bool = True) -> None:
    """Fonte estéreo → par L/R ligado; mono → só L."""
    items = []
    for ch in range(2 if src.channels >= 2 else 1):
        label = f"{group} {'LR'[ch]}"
        tr = a_tracks[label]
        ci = _clipitem(tr, ctx, src, name, start, end, in_s, dur_s, seq_rate,
                       audio_index=ch + 1, level=level, enabled=enabled)
        items.append((ci, "audio", AUDIO_TRACKS.index(label) + 1, len(tr.findall("clipitem"))))
    if len(items) > 1:
        _link(items)


def _levels(ci: ET.Element, value: float) -> None:
    eff = _sub(_sub(ci, "filter"), "effect")
    _sub(eff, "name", "Audio Levels")
    _sub(eff, "effectid", "audiolevels")
    _sub(eff, "effectcategory", "audiolevels")
    _sub(eff, "effecttype", "audiolevels")
    _sub(eff, "mediatype", "audio")
    p = _sub(eff, "parameter", authoringApp="PremierePro")
    _sub(p, "parameterid", "level")
    _sub(p, "name", "Level")
    _sub(p, "valuemin", 0)
    _sub(p, "valuemax", MAX_LEVEL)
    _sub(p, "value", f"{value:.5f}")


def _gain_level(db: ProjectDB, m: MediaInfo, role: Role) -> tuple[float, bool]:
    st = db.get_audio_stats(m.id)
    if st is None:
        return 1.0, False
    level = 10 ** (gain_for(role, st.mean_db) / 20)
    return min(level, MAX_LEVEL), st.noisy


# ------------------------------------------------------------------ sequência

def _scenes(piece: Piece) -> list[tuple[str, SceneRef]]:
    out = [("abertura", piece.abertura)]
    out += [("desenvolvimento", s) for s in piece.desenvolvimento]
    if piece.gancho is not None:
        out.append(("gancho", piece.gancho))
    return out


def piece_name(piece: Piece) -> str:
    if piece.tipo == "episodio":
        return f"EP {(piece.numero or 0):02d}"
    return _DERIVADO_NAME[piece.tipo]


@dataclass(frozen=True)
class Formato:
    """Formato das timelines: o da maioria dos vídeos do projeto (resolução já girada,
    quadros por segundo) e a taxa de amostragem do áudio deles."""
    width: int = 1920
    height: int = 1080
    rate: tuple[int, int] = DEFAULT_RATE
    samplerate: int = 48000

    def vertical(self) -> "Formato":
        w, h = sorted((self.width, self.height))
        return Formato(w, h, self.rate, self.samplerate)


AMOSTRA_AUDIO = 12  # vídeos sondados (ffprobe) para a taxa de amostragem do áudio


def _samplerate(path: Path) -> int | None:
    from roteiro_ia import proc
    from roteiro_ia.media.tools import ffprobe_bin
    try:
        r = proc.run([ffprobe_bin(), "-v", "error", "-select_streams", "a:0", "-show_entries",
                      "stream=sample_rate", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                     text=True, encoding="utf-8", errors="replace", timeout=30)
        return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    except Exception:  # noqa: BLE001 - sem ffprobe, arquivo fora do ar…: fica o padrão
        return None


def formato_do_projeto(db: ProjectDB, source_root: Path, sondar=_samplerate) -> Formato:
    """Maioria dos vídeos do projeto (fora os ignorados): resolução (girada quando o vídeo está
    em pé), quadros e a taxa de amostragem do áudio (amostra de AMOSTRA_AUDIO vídeos)."""
    videos = [m for m in db.list_media()
              if m.kind == "video" and m.role != Role.ignorar and m.width > 0 and m.height > 0]
    if not videos:
        return Formato()
    tam = Counter((m.height, m.width) if m.rotation % 180 == 90 else (m.width, m.height)
                  for m in videos)
    (w, h), _n = tam.most_common(1)[0]
    rate = _seq_rate(videos)
    com_audio = [m for m in videos if m.audio_channels > 0]
    passo = max(1, len(com_audio) // AMOSTRA_AUDIO)
    taxas = Counter(t for t in (sondar(Path(source_root) / m.rel_path)
                                for m in com_audio[::passo][:AMOSTRA_AUDIO]) if t)
    sr = taxas.most_common(1)[0][0] if taxas else 48000
    return Formato(w, h, rate, sr)


def _seq_rate(medias: list[MediaInfo]) -> tuple[int, int]:
    c = Counter(r for r in (_media_rate(m) for m in medias) if r)
    if not c:
        return DEFAULT_RATE
    top = c.most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        return DEFAULT_RATE
    return top[0][0]


def _marker(seq: ET.Element, name: str, comment: str, fin: int, fout: int | None = None) -> None:
    mk = _sub(seq, "marker")
    _sub(mk, "name", name)
    _sub(mk, "comment", comment)
    _sub(mk, "in", fin)
    _sub(mk, "out", fin if fout is None else fout)


def _overlaps(t0: float, t1: float, cands, syncs) -> list[tuple[float, float, float, MediaInfo]]:
    """(ov0, ov1, início da mídia na linha do tempo, mídia) ordenado pela maior sobreposição."""
    out = []
    for o in cands:
        so = syncs[o.id]
        o0, o1 = so.timeline_start_s, so.timeline_start_s + o.duration_s
        a, b = max(t0, o0), min(t1, o1)
        if b - a > 1e-6:
            out.append((a, b, o0, o))
    out.sort(key=lambda x: (-(x[1] - x[0]), x[3].rel_path))
    return out


def build_sequence(piece: Piece, db: ProjectDB, idx: MusicIndex, music_path_map: dict[str, str],
                   source_root: Path, ctx: _Ctx | None = None,
                   name: str | None = None, formato: Formato | None = None) -> ET.Element:
    """`formato`: o do projeto (build_xml); sem ele, os quadros vêm das cenas da peça e a
    resolução é a padrão (1920×1080)."""
    own_ctx = ctx is None
    ctx = ctx or _Ctx()
    name = name or piece_name(piece)
    all_media = db.list_media()
    syncs = {m.id: db.get_sync(m.id) for m in all_media}
    synced = [m for m in all_media if syncs[m.id] is not None]

    scenes = []
    for kind, ref in _scenes(piece):
        m = db.media_by_rel(ref.rel_path)
        if m is None:
            raise ValueError(f"Mídia do roteiro não encontrada no projeto: {ref.rel_path}")
        scenes.append((kind, ref, m))
    fmt = formato or Formato(rate=_seq_rate([m for _, _, m in scenes]))
    if piece.tipo == "stories":
        fmt = fmt.vertical()
    rate = fmt.rate

    seq = ET.Element("sequence", id="seq-" + name.replace(" ", "_"))
    _sub(seq, "name", name)
    dur_el = _sub(seq, "duration", 0)
    _rate_el(seq, rate)
    tc = _sub(seq, "timecode")
    _rate_el(tc, rate)
    _sub(tc, "string", "00:00:00:00")
    _sub(tc, "frame", 0)
    _sub(tc, "displayformat", "NDF")
    media = _sub(seq, "media")
    video = _sub(media, "video")
    fmt_sc = _sub(_sub(video, "format"), "samplecharacteristics")
    _rate_el(fmt_sc, rate)
    _sub(fmt_sc, "width", fmt.width)
    _sub(fmt_sc, "height", fmt.height)
    _sub(fmt_sc, "anamorphic", "FALSE")
    _sub(fmt_sc, "pixelaspectratio", "square")
    _sub(fmt_sc, "fielddominance", "none")
    audio = _sub(media, "audio")
    _sub(audio, "numOutputChannels", 2)
    afmt = _sub(_sub(audio, "format"), "samplecharacteristics")
    _sub(afmt, "depth", 16)
    _sub(afmt, "samplerate", fmt.samplerate)

    # Clipitems são montados em listas e anexados no fim (as faixas dependem do conteúdo).
    v_tracks: list[ET.Element] = [ET.Element("track")]
    a_tracks = {t: ET.Element("track") for t in AUDIO_TRACKS}
    markers: list[tuple[str, str, int, int | None]] = []
    cursor = 0
    for kind, ref, m in scenes:
        dur = ref.end_s - ref.start_s
        start, end = cursor, cursor + _frames(dur, rate)
        cursor = end

        def place(ov0: float, ov1: float, o0: float, t0: float):
            s0 = min(end, start + _frames(ov0 - t0, rate))
            s1 = min(end, start + _frames(ov1 - t0, rate))
            return s0, s1, ov0 - o0, ov1 - ov0

        src = _media_src(m, ctx, source_root, rate)
        so_audio = m.kind != "video"
        cam = None  # clipe de V1 cujo áudio vira SOM CÂMERA: (mídia, src, início, fim, in_s, dur)
        if not so_audio:
            _clipitem(v_tracks[0], ctx, src, PureWindowsPath(m.rel_path).name, start, end,
                      ref.start_s, dur, rate)
            cam = (m, src, start, end, ref.start_s, dur)
        if kind == "abertura":
            markers.append(("ABERTURA", ref.descricao, start, None))
        elif kind == "gancho":
            markers.append(("GANCHO", ref.descricao, start, None))
        if ref.usar_som_camera:
            markers.append(("SOM CÂMERA", "Som ambiente da câmera audível nesta cena (realismo)",
                            start, end))
        if ref.fala:
            markers.append((f"FALA: {ref.fala}", ref.fala, start, end))
        if ref.lembranca:
            markers.append((f"LEMBRANÇA: {ref.descricao}",
                            "Lembrança: outra tonalidade e áudio filtrado/reverb", start, end))

        sm = syncs.get(m.id)
        has_room = False
        v1_id = None
        if so_audio:
            tname_m = _ROLE_TRACK.get(m.role, "AMBIENTE")
            if m.audio_channels > 0:
                level, noisy = _gain_level(db, m, m.role)
                _place_audio(a_tracks, tname_m, ctx, src, PureWindowsPath(m.rel_path).name,
                             start, end, ref.start_s, dur, rate, level)
                if noisy:
                    markers.append(("RUÍDO", f"Ruído detectado em {m.rel_path}", start, end))
            has_room = True  # o próprio áudio da cena já está na faixa
        if sm is not None:
            t0 = sm.timeline_start_s + ref.start_s
            t1 = t0 + dur
            day = [o for o in synced if o.id != m.id and syncs[o.id].day_label == sm.day_label]
            if so_audio:
                vids = _overlaps(t0, t1, [o for o in day if o.kind == "video"], syncs)
                if vids:
                    ov0, ov1, o0, o = vids[0]
                    s0, s1, ins, d = place(ov0, ov1, o0, t0)
                    if s1 > s0:
                        osrc = _media_src(o, ctx, source_root, rate)
                        _clipitem(v_tracks[0], ctx, osrc,
                                  PureWindowsPath(o.rel_path).name, s0, s1, ins, d, rate)
                        v1_id = o.id
                        cam = (o, osrc, s0, s1, ins, d)
            alts = _overlaps(t0, t1, [o for o in day if o.kind == "video" and o.id != v1_id
                                      and o.role not in _ROLE_TRACK], syncs)[:MAX_ALTERNATES]
            for i, (ov0, ov1, o0, o) in enumerate(alts, start=1):
                s0, s1, ins, d = place(ov0, ov1, o0, t0)
                if s1 <= s0:
                    continue
                while len(v_tracks) <= i:
                    v_tracks.append(ET.Element("track"))
                _clipitem(v_tracks[i], ctx, _media_src(o, ctx, source_root, rate),
                          PureWindowsPath(o.rel_path).name, s0, s1, ins, d, rate,
                          enabled=False)
            for role, tname in _ROLE_TRACK.items():
                taken: list[tuple[int, int]] = (
                    [(start, end)] if so_audio and _ROLE_TRACK.get(m.role, "AMBIENTE") == tname
                    else [])
                for ov0, ov1, o0, o in _overlaps(t0, t1, [o for o in day if o.role == role],
                                                 syncs):
                    s0, s1, ins, d = place(ov0, ov1, o0, t0)
                    if s1 <= s0 or any(s0 < b and a < s1 for a, b in taken):
                        continue
                    taken.append((s0, s1))
                    level, noisy = _gain_level(db, o, role)
                    _place_audio(a_tracks, tname, ctx, _media_src(o, ctx, source_root, rate),
                                 PureWindowsPath(o.rel_path).name, s0, s1, ins, d, rate, level)
                    if noisy:
                        markers.append(("RUÍDO", f"Ruído detectado em {o.rel_path}", s0, s1))
                    if role in (Role.mesa, Role.audio_ambiente):
                        has_room = True
        if so_audio and v1_id is None:
            markers.append(("SEM IMAGEM", f"Cena só de áudio ({m.rel_path}) sem vídeo "
                            "sincronizado: escolha uma imagem para cobrir a fala.", start, end))
        if cam is not None and cam[0].audio_channels > 0:
            cm, csrc, c0, c1, cin, cdur = cam
            on = ref.usar_som_camera or not has_room
            level, noisy = _gain_level(db, cm, Role.camera)
            _place_audio(a_tracks, "SOM CÂMERA", ctx, csrc, PureWindowsPath(cm.rel_path).name,
                         c0, c1, cin, cdur, rate, level, enabled=on)
            if noisy and on:
                markers.append(("RUÍDO", f"Ruído detectado em {cm.rel_path}", c0, c1))

    dur_el.text = str(cursor)

    music = next((t for t in piece.trilhas if t.origem == "biblioteca" and t.path), None)
    info = idx.get(music.path) if music else None
    if info is not None and cursor > 0:
        mpath = music_path_map.get(music.path, music.path)
        fid = ctx.music_id(mpath)
        mrate = ctx.rate_for(fid, None, rate)
        if fid not in [u[0] for u in ctx.music_used]:
            ctx.music_used.append((fid, mpath, info.duration_s))
        src = _Src(fid, Path(mpath), info.duration_s, mrate, None, 2)
        inicio = 0.0
        if music.trecho_inicio_s is not None:
            if inicio_valido(music.trecho_inicio_s, info.duration_s):
                inicio = float(music.trecho_inicio_s)
            else:
                markers.append(("TRILHA", f"Início sugerido da trilha ({music.trecho_inicio_s:.0f} s) "
                                f"fora da música ({info.duration_s:.0f} s): usado o começo.", 0, None))
        # Quadros que sobram da música a partir do `in` (na taxa do clipe; sem passar do fim).
        resto = _frames(info.duration_s, mrate) - _frames(inicio, mrate)
        if timebase(*mrate) != timebase(*rate):
            resto = int(resto / _real(mrate) * _real(rate))
        length = min(cursor, resto)
        if length > 0:
            _place_audio(a_tracks, "MÚSICA", ctx, src, PureWindowsPath(mpath).name, 0, length,
                         inicio, length / _real(rate), rate, 1.0)
        else:
            markers.append(("TRILHA", f"Início sugerido da trilha ({inicio:.2f} s) além do fim "
                            f"da música ({info.duration_s:.2f} s): trilha não colocada.", 0, None))

    for t in v_tracks:
        _sub(t, "enabled", "TRUE")
        _sub(t, "locked", "FALSE")
        video.append(t)
    for tname in AUDIO_TRACKS:
        t = a_tracks[tname]
        _sub(t, "enabled", "TRUE")
        _sub(t, "locked", "FALSE")
        _sub(t, "outputchannelindex", 1 if tname.endswith(" L") else 2)
        audio.append(t)
    for n, c, a, b in sorted(markers, key=lambda x: x[2]):
        _marker(seq, n, c, a, b)
    if own_ctx:
        _fill_files(seq, ctx)
    return seq


# ------------------------------------------------------------------ documento

def _bin(parent: ET.Element, name: str) -> ET.Element:
    b = _sub(parent, "bin")
    _sub(b, "name", name)
    return _sub(b, "children")


def build_xml(r: Roteiro, db: ProjectDB, idx: MusicIndex, music_path_map: dict[str, str],
              source_root: Path, formato: Formato | None = None) -> str:
    """Timelines no formato da maioria dos vídeos do projeto (`formato_do_projeto`)."""
    formato = formato or formato_do_projeto(db, source_root)
    ctx = _Ctx()
    root = ET.Element("xmeml", version="4")
    project = _sub(root, "project")
    _sub(project, "name", "ROTEIRO IA")
    children = _sub(project, "children")

    eps = sorted((p for p in r.pecas if p.tipo == "episodio"), key=lambda p: p.numero or 0)
    ders = [p for p in r.pecas if p.tipo != "episodio"]
    used: Counter[str] = Counter()
    for p in [*eps, *ders]:
        base = piece_name(p)
        used[base] += 1
        name = base if used[base] == 1 else f"{base} {used[base]}"
        children.append(build_sequence(p, db, idx, music_path_map, source_root, ctx, name,
                                       formato))

    _fill_files(root, ctx)
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body + "\n"


def write_xml(xml: str, p: EventPaths, s: Settings) -> Path:
    out = Path(p.analysis_dir) / f"{p.event_name} - PREMIERE.xml"
    safe_write_text(out, xml, s)
    return out
