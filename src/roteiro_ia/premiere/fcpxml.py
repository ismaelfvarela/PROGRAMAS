"""Pré-roteiro aprovado → XML do Final Cut Pro 7 (xmeml v4) importável no Premiere 2024
(Arquivo → Importar).

- Uma sequência por episódio (EP01, EP02…) e por derivado (TRAILER, TEASER, STORIES).
- V1: as cenas do roteiro em ordem (abertura, desenvolvimento…, gancho), encostadas a
  partir do quadro 0. V2…Vn: ângulos alternativos sincronizados (até 5, desativados),
  só no trecho sobreposto e alinhados no tempo real (via SyncResult).
- Áudio: mesa / áudio ambiente / lapelas sobrepostos à cena nas faixas de AUDIO_TRACKS;
  sem mesa nem ambiente, o áudio da própria câmera vai para AMBIENTE. Cada clipe de áudio
  recebe o filtro "Audio Levels" com 10^(ganho_dB/20), ganho de `gain_for`.
  Observação: o Premiere limita o nível de clipe a +12 dB (3,98109 linear), então o valor
  linear é limitado a 3,98109 mesmo quando `gain_for` pede mais (até +20 dB).
- A trilha nº 1 da biblioteca vai para a faixa MÚSICA desde o início.
- Os caminhos apontam para os ORIGINAIS (source_root / rel_path), nunca para proxies:
  os proxies são anexados depois pelo painel do Premiere.
- Tempos: segundos → quadros com round(s * fps_real); start/end na taxa da sequência,
  in/out na taxa do próprio clipe. Arquivos só de áudio usam a taxa da sequência em que
  aparecem pela primeira vez.
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
from roteiro_ia.script.generate import Piece, Roteiro, SceneRef

AUDIO_TRACKS = ["MESA", "AMBIENTE", "LAPELA NOIVO", "LAPELA NOIVA", "MÚSICA"]
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
    if fps_den == 1001:
        return round(fps_num / 1000), True
    return round(fps_num / fps_den), False


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
class _Ctx:
    """Estado compartilhado por todo o documento: definição única de cada <file> e ids."""
    defined: set[str] = field(default_factory=set)
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


def _file_el(parent: ET.Element, ctx: _Ctx, fid: str, path: Path, duration_s: float,
             rate: tuple[int, int], video: tuple[int, int] | None, channels: int) -> None:
    """Definição completa na primeira ocorrência; depois só a referência."""
    f = _sub(parent, "file", id=fid)
    if fid in ctx.defined:
        return
    ctx.defined.add(fid)
    _sub(f, "name", PureWindowsPath(str(path)).name)
    _sub(f, "pathurl", pathurl(path))
    _rate_el(f, rate)
    _sub(f, "duration", _frames(duration_s, rate))
    media = _sub(f, "media")
    if video is not None:
        sc = _sub(_sub(media, "video"), "samplecharacteristics")
        _rate_el(sc, rate)
        _sub(sc, "width", video[0])
        _sub(sc, "height", video[1])
        _sub(sc, "anamorphic", "FALSE")
        _sub(sc, "pixelaspectratio", "square")
        _sub(sc, "fielddominance", "none")
    if channels > 0:
        a = _sub(media, "audio")
        sc = _sub(a, "samplecharacteristics")
        _sub(sc, "depth", 16)
        _sub(sc, "samplerate", 48000)
        _sub(a, "channelcount", channels)


@dataclass
class _Src:
    """Um arquivo de mídia pronto para virar <file>."""
    fid: str
    path: Path
    duration_s: float
    rate: tuple[int, int]
    video: tuple[int, int] | None
    channels: int


def _media_src(m: MediaInfo, ctx: _Ctx, source_root: Path, fallback: tuple[int, int]) -> _Src:
    fid = f"file-{m.id}"
    rate = ctx.rate_for(fid, _media_rate(m), fallback)
    video = (m.width, m.height) if m.kind == "video" else None
    return _Src(fid, Path(source_root) / m.rel_path, m.duration_s, rate, video, m.audio_channels)


def _clipitem(track: ET.Element, ctx: _Ctx, src: _Src, name: str, start: int, end: int,
              in_s: float, dur_s: float, audio: bool, enabled: bool = True,
              level: float | None = None) -> ET.Element:
    ci = _sub(track, "clipitem", id=ctx.clip_id())
    _sub(ci, "name", name)
    _sub(ci, "enabled", _bool(enabled))
    _sub(ci, "duration", _frames(src.duration_s, src.rate))
    _rate_el(ci, src.rate)
    _sub(ci, "start", start)
    _sub(ci, "end", end)
    fin = _frames(in_s, src.rate)
    _sub(ci, "in", fin)
    _sub(ci, "out", _frames(in_s + dur_s, src.rate))
    _file_el(ci, ctx, src.fid, src.path, src.duration_s, src.rate, src.video, src.channels)
    if audio:
        st = _sub(ci, "sourcetrack")
        _sub(st, "mediatype", "audio")
        _sub(st, "trackindex", 1)
        _levels(ci, 1.0 if level is None else level)
    return ci


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
        return f"EP{(piece.numero or 0):02d}"
    return _DERIVADO_NAME[piece.tipo]


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
                   name: str | None = None) -> ET.Element:
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
    rate = _seq_rate([m for _, _, m in scenes])

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
    w, h = (1080, 1920) if piece.tipo == "stories" else (1920, 1080)
    _sub(fmt_sc, "width", w)
    _sub(fmt_sc, "height", h)
    _sub(fmt_sc, "anamorphic", "FALSE")
    _sub(fmt_sc, "pixelaspectratio", "square")
    _sub(fmt_sc, "fielddominance", "none")
    audio = _sub(media, "audio")
    afmt = _sub(_sub(audio, "format"), "samplecharacteristics")
    _sub(afmt, "depth", 16)
    _sub(afmt, "samplerate", 48000)

    # Clipitems são montados em listas e anexados no fim (as faixas dependem do conteúdo).
    v_tracks: list[ET.Element] = [ET.Element("track")]
    a_tracks = {t: ET.Element("track") for t in AUDIO_TRACKS}
    markers: list[tuple[str, str, int, int | None]] = []
    cursor = 0
    for kind, ref, m in scenes:
        dur = ref.end_s - ref.start_s
        start, end = cursor, cursor + _frames(dur, rate)
        cursor = end
        src = _media_src(m, ctx, source_root, rate)
        _clipitem(v_tracks[0], ctx, src, PureWindowsPath(m.rel_path).name, start, end,
                  ref.start_s, dur, audio=False)
        if kind == "abertura":
            markers.append(("ABERTURA", ref.descricao, start, None))
        elif kind == "gancho":
            markers.append(("GANCHO", ref.descricao, start, None))
        if ref.fala:
            markers.append((f"FALA: {ref.fala}", ref.fala, start, end))
        if ref.lembranca:
            markers.append((f"LEMBRANÇA: {ref.descricao}",
                            "Lembrança: outra tonalidade e áudio filtrado/reverb", start, end))

        def place(ov0: float, ov1: float, o0: float, t0: float):
            s0 = min(end, start + _frames(ov0 - t0, rate))
            s1 = min(end, start + _frames(ov1 - t0, rate))
            return s0, s1, ov0 - o0, ov1 - ov0

        sm = syncs.get(m.id)
        has_room = False
        if sm is not None:
            t0 = sm.timeline_start_s + ref.start_s
            t1 = t0 + dur
            day = [o for o in synced if o.id != m.id and syncs[o.id].day_label == sm.day_label]
            alts = _overlaps(t0, t1, [o for o in day if o.kind == "video"
                                      and o.role not in _ROLE_TRACK], syncs)[:MAX_ALTERNATES]
            for i, (ov0, ov1, o0, o) in enumerate(alts, start=1):
                s0, s1, ins, d = place(ov0, ov1, o0, t0)
                if s1 <= s0:
                    continue
                while len(v_tracks) <= i:
                    v_tracks.append(ET.Element("track"))
                _clipitem(v_tracks[i], ctx, _media_src(o, ctx, source_root, rate),
                          PureWindowsPath(o.rel_path).name, s0, s1, ins, d, audio=False,
                          enabled=False)
            for role, tname in _ROLE_TRACK.items():
                taken: list[tuple[int, int]] = []
                for ov0, ov1, o0, o in _overlaps(t0, t1, [o for o in day if o.role == role],
                                                 syncs):
                    s0, s1, ins, d = place(ov0, ov1, o0, t0)
                    if s1 <= s0 or any(s0 < b and a < s1 for a, b in taken):
                        continue
                    taken.append((s0, s1))
                    level, noisy = _gain_level(db, o, role)
                    _clipitem(a_tracks[tname], ctx, _media_src(o, ctx, source_root, rate),
                              PureWindowsPath(o.rel_path).name, s0, s1, ins, d, audio=True,
                              level=level)
                    if noisy:
                        markers.append(("RUÍDO", f"Ruído detectado em {o.rel_path}", s0, s1))
                    if role in (Role.mesa, Role.audio_ambiente):
                        has_room = True
        if not has_room and m.audio_channels > 0:
            level, noisy = _gain_level(db, m, m.role)
            _clipitem(a_tracks["AMBIENTE"], ctx, src, PureWindowsPath(m.rel_path).name,
                      start, end, ref.start_s, dur, audio=True, level=level)
            if noisy:
                markers.append(("RUÍDO", f"Ruído detectado em {m.rel_path}", start, end))

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
        length = min(cursor, _frames(info.duration_s, rate))
        _clipitem(a_tracks["MÚSICA"], ctx, src, PureWindowsPath(mpath).name, 0, length,
                  0.0, length / _real(rate), audio=True, level=1.0)

    for t in v_tracks:
        _sub(t, "enabled", "TRUE")
        _sub(t, "locked", "FALSE")
        video.append(t)
    for tname in AUDIO_TRACKS:
        t = a_tracks[tname]
        _sub(t, "enabled", "TRUE")
        _sub(t, "locked", "FALSE")
        audio.append(t)
    for n, c, a, b in sorted(markers, key=lambda x: x[2]):
        _marker(seq, n, c, a, b)
    return seq


# ------------------------------------------------------------------ documento

def _bin(parent: ET.Element, name: str) -> ET.Element:
    b = _sub(parent, "bin")
    _sub(b, "name", name)
    return _sub(b, "children")


def _master_clip(parent: ET.Element, ctx: _Ctx, cid: str, name: str, src: _Src) -> None:
    clip = _sub(parent, "clip", id=cid)
    _sub(clip, "name", name)
    frames = _frames(src.duration_s, src.rate)
    _sub(clip, "duration", frames)
    _rate_el(clip, src.rate)
    media = _sub(clip, "media")
    if src.video is not None:
        track = _sub(_sub(media, "video"), "track")
        _clipitem(track, ctx, src, name, 0, frames, 0.0, src.duration_s, audio=False)
    elif src.channels > 0:
        track = _sub(_sub(media, "audio"), "track")
        _clipitem(track, ctx, src, name, 0, frames, 0.0, src.duration_s, audio=True)


def build_xml(r: Roteiro, db: ProjectDB, idx: MusicIndex, music_path_map: dict[str, str],
              source_root: Path) -> str:
    ctx = _Ctx()
    root = ET.Element("xmeml", version="4")
    project = _sub(root, "project")
    _sub(project, "name", "ROTEIRO IA")
    children = _sub(project, "children")
    ep_bin = _bin(children, "EPISÓDIOS")
    der_bin = _bin(children, "DERIVADOS")

    eps = sorted((p for p in r.pecas if p.tipo == "episodio"), key=lambda p: p.numero or 0)
    ders = [p for p in r.pecas if p.tipo != "episodio"]
    used: Counter[str] = Counter()
    for parent, pieces in ((ep_bin, eps), (der_bin, ders)):
        for p in pieces:
            base = piece_name(p)
            used[base] += 1
            name = base if used[base] == 1 else f"{base} {used[base]}"
            parent.append(build_sequence(p, db, idx, music_path_map, source_root, ctx, name))

    mat = _bin(children, "MATERIAL")
    medias = db.list_media()
    folders: dict[str, ET.Element] = {}
    for m in sorted(medias, key=lambda m: (m.folder, m.rel_path)):
        if m.folder not in folders:
            folders[m.folder] = _bin(mat, m.folder)
        src = _media_src(m, ctx, source_root, DEFAULT_RATE)
        _master_clip(folders[m.folder], ctx, f"masterclip-{m.id}",
                     PureWindowsPath(m.rel_path).name, src)

    tri = _bin(children, "TRILHAS")
    for fid, mpath, dur in ctx.music_used:
        src = _Src(fid, Path(mpath), dur, ctx.file_rates[fid], None, 2)
        _master_clip(tri, ctx, f"masterclip-{fid}", PureWindowsPath(mpath).name, src)

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body + "\n"


def write_xml(xml: str, p: EventPaths, s: Settings) -> Path:
    out = Path(p.analysis_dir) / f"{p.event_name} - PREMIERE.xml"
    safe_write_text(out, xml, s)
    return out
