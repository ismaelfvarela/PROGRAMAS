"""Íntegra da colação → XML do Premiere (xmeml v4): uma sequência por parte.

V1: a gravação da mesa de corte (PGM), trocada pela câmera ISO ou por uma imagem fria nos
trechos com defeito. V2/V3: outras ISOs do mesmo momento, desligadas. MESA L/R: o áudio do PGM
contínuo nos trechos mantidos. AMBIENTE: gravadores, desligados (reserva). Marcadores em cada
troca e em cada espaço morto cortado. Reaproveita os blocos de premiere/fcpxml.py."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath

from roteiro_ia.areas.formatura.colacao.plano import ParteIntegra, PlanoIntegra, Troca
from roteiro_ia.db import ProjectDB
from roteiro_ia.models import MediaInfo, Role
from roteiro_ia.premiere.fcpxml import (AUDIO_TRACKS, DEFAULT_RATE, _bin, _clipitem, _Ctx,
                                        _fill_files, _frames, _gain_level, _marker, _master_clip,
                                        _media_src, _place_audio, _rate_el, _seq_rate, _sub)

MAX_ALTERNATIVAS = 2
_EPS = 1e-6


def _nome(m: MediaInfo) -> str:
    return PureWindowsPath(m.rel_path).name


def _camera(rel: str) -> str:
    return PureWindowsPath(rel).parts[-2] if len(PureWindowsPath(rel).parts) > 1 else rel


def nome_sequencia(p: ParteIntegra) -> str:
    return f"{p.numero:02d} - {p.nome}"


def _nova_sequencia(nome: str, rate) -> tuple[ET.Element, ET.Element, ET.Element, ET.Element]:
    seq = ET.Element("sequence", id="seq-" + nome.replace(" ", "_"))
    _sub(seq, "name", nome)
    dur = _sub(seq, "duration", 0)
    _rate_el(seq, rate)
    tc = _sub(seq, "timecode")
    _rate_el(tc, rate)
    _sub(tc, "string", "00:00:00:00")
    _sub(tc, "frame", 0)
    _sub(tc, "displayformat", "NDF")
    media = _sub(seq, "media")
    video = _sub(media, "video")
    sc = _sub(_sub(video, "format"), "samplecharacteristics")
    _rate_el(sc, rate)
    for tag, val in (("width", 1920), ("height", 1080), ("anamorphic", "FALSE"),
                     ("pixelaspectratio", "square"), ("fielddominance", "none")):
        _sub(sc, tag, val)
    audio = _sub(media, "audio")
    _sub(audio, "numOutputChannels", 2)
    af = _sub(_sub(audio, "format"), "samplecharacteristics")
    _sub(af, "depth", 16)
    _sub(af, "samplerate", 48000)
    return seq, video, audio, dur


class _Montador:
    def __init__(self, db: ProjectDB, source_root: Path):
        self.db, self.root, self.ctx = db, Path(source_root), _Ctx()
        self.medias = db.list_media()
        self.syncs = {m.id: db.get_sync(m.id) for m in self.medias}
        self.por_rel = {m.rel_path.casefold(): m for m in self.medias}
        sinc = [m for m in self.medias if self.syncs[m.id] is not None]
        self.pgms = sorted((m for m in sinc if m.role == Role.mesa and m.kind == "video"),
                           key=lambda m: self.syncs[m.id].timeline_start_s)
        self.isos = [m for m in sinc if m.role == Role.camera and m.kind == "video"]
        self.gravadores = [m for m in sinc if m.role == Role.audio_ambiente]
        self.rate = _seq_rate(self.pgms) if self.pgms else DEFAULT_RATE

    def midia(self, rel: str) -> MediaInfo | None:
        return self.por_rel.get(rel.casefold())

    def _cobertura(self, ms: list[MediaInfo], a: float, b: float):
        """(mídia, in_s, a, b) dos pedaços de [a, b] cobertos por cada mídia sincronizada."""
        out = []
        for m in ms:
            t0 = self.syncs[m.id].timeline_start_s
            x, y = max(a, t0), min(b, t0 + m.duration_s)
            if y - x > _EPS:
                out.append((m, x - t0, x, y))
        return sorted(out, key=lambda r: r[2])

    def src(self, m: MediaInfo):
        return _media_src(m, self.ctx, self.root, self.rate)

    def parte(self, p: ParteIntegra) -> ET.Element:
        nome = nome_sequencia(p)
        seq, video, audio, dur_el = _nova_sequencia(nome, self.rate)
        v_tracks = [ET.Element("track")]
        a_tracks = {t: ET.Element("track") for t in AUDIO_TRACKS}
        marcadores: list[tuple[str, str, int, int | None]] = []
        r = self.rate
        cursor = 0
        cortes = sorted(p.cortes)
        for x, y in p.trechos:
            base = cursor

            def fr(t: float) -> int:
                return base + _frames(t - x, r)

            for a, b, troca in self._pedacos(x, y, p.trocas):
                s0, s1 = fr(a), fr(b)
                if s1 <= s0:
                    continue
                self._video(v_tracks, a, b, s0, s1, troca, fr)
                if troca is not None:
                    marcadores.append(self._marcador(troca, s0, s1))
            for m, ins, a, b in self._cobertura(self.pgms, x, y):
                level, _ = _gain_level(self.db, m, Role.mesa)
                _place_audio(a_tracks, "MESA", self.ctx, self.src(m), _nome(m), fr(a), fr(b), ins,
                             b - a, r, level)
            for m, ins, a, b in self._cobertura(self.gravadores, x, y):
                level, _ = _gain_level(self.db, m, Role.audio_ambiente)
                _place_audio(a_tracks, "AMBIENTE", self.ctx, self.src(m), _nome(m), fr(a), fr(b),
                             ins, b - a, r, level, enabled=False)
            cursor = base + _frames(y - x, r)
            for c0, c1 in cortes:
                if abs(c0 - y) < 0.01:
                    marcadores.append((f"CORTE: {round(c1 - c0)} s sem fala",
                                       f"Espaço morto cortado ({c0:.1f}–{c1:.1f} s da mesa).",
                                       cursor, None))
        dur_el.text = str(cursor)
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
        for n, c, a, b in sorted(marcadores, key=lambda x: x[2]):
            _marker(seq, n, c, a, b)
        return seq

    @staticmethod
    def _pedacos(x: float, y: float, trocas: list[Troca]):
        out, cur = [], x
        for t in sorted(trocas, key=lambda t: t.inicio_s):
            a, b = max(t.inicio_s, x), min(t.fim_s, y)
            if b - a <= _EPS:
                continue
            if a > cur:
                out.append((cur, a, None))
            out.append((a, b, t))
            cur = b
        if y > cur:
            out.append((cur, y, None))
        return out

    def _video(self, v_tracks, a, b, s0, s1, troca, fr) -> None:
        r = self.rate
        fonte = troca.fonte if troca else "pgm"
        usado = None
        if fonte.startswith("iso:") and (m := self.midia(fonte[4:])) is not None:
            ins = a - self.syncs[m.id].timeline_start_s
            _clipitem(v_tracks[0], self.ctx, self.src(m), _nome(m), s0, s1, ins, b - a, r)
            usado = m.id
        elif fonte.startswith("fria:") and (m := self.midia(fonte[5:].rsplit("@", 1)[0])) is not None:
            f0 = float(fonte.rsplit("@", 1)[1].split("-")[0])
            _clipitem(v_tracks[0], self.ctx, self.src(m), _nome(m), s0, s1, f0, b - a, r)
        else:  # PGM (também quando não há cobertura: fica a imagem original, marcada)
            for m, ins, pa, pb in self._cobertura(self.pgms, a, b):
                _clipitem(v_tracks[0], self.ctx, self.src(m), _nome(m), fr(pa), fr(pb), ins, pb - pa, r)
        if troca is None:
            return
        alts = [c for c in self._cobertura(self.isos, a, b) if c[0].id != usado]
        alts.sort(key=lambda c: -(c[3] - c[2]))
        for i, (m, ins, pa, pb) in enumerate(alts[:MAX_ALTERNATIVAS], start=1):
            while len(v_tracks) <= i:
                v_tracks.append(ET.Element("track"))
            _clipitem(v_tracks[i], self.ctx, self.src(m), _nome(m), fr(pa), fr(pb), ins, pb - pa, r,
                      enabled=False)

    @staticmethod
    def _marcador(t: Troca, s0: int, s1: int):
        if t.fonte.startswith("iso:"):
            return (f"TROCA: {t.motivo} → {_camera(t.fonte[4:])}",
                    f"Imagem da mesa com {t.motivo}; trocada pela câmera ISO.", s0, s1)
        if t.fonte.startswith("fria:"):
            return (f"IMAGEM FRIA: {t.motivo}",
                    f"Imagem da mesa com {t.motivo} e nenhuma ISO no momento; coberta por imagem fria.",
                    s0, s1)
        return (f"SEM COBERTURA: {t.motivo}",
                f"Imagem da mesa com {t.motivo}; não há ISO nem imagem fria. Confira.", s0, s1)


def build_xml_integra(plano: PlanoIntegra, db: ProjectDB, source_root: Path) -> str:
    mt = _Montador(db, source_root)
    root = ET.Element("xmeml", version="4")
    project = _sub(root, "project")
    _sub(project, "name", "ROTEIRO IA")
    children = _sub(project, "children")
    integra = _bin(children, "ÍNTEGRA")
    for p in plano.partes:
        integra.append(mt.parte(p))
    mat = _bin(children, "MATERIAL")
    pastas: dict[str, ET.Element] = {}
    for m in sorted(mt.medias, key=lambda m: (m.folder, m.rel_path)):
        if m.folder not in pastas:
            pastas[m.folder] = _bin(mat, m.folder)
        _master_clip(pastas[m.folder], mt.ctx, _nome(m), _media_src(m, mt.ctx, mt.root, DEFAULT_RATE))
    _fill_files(root, mt.ctx)
    ET.indent(root, space="  ")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
            + ET.tostring(root, encoding="unicode") + "\n")
