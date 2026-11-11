"""Mixagem dos clipes da Formatura, aplicada no XML já montado (o Casamento não passa por aqui):

- som ambiente da câmera (faixas SOM CÂMERA): sempre ligado e bem baixo, a DB_CAMERA;
- voz do aluno (faixas VOZ, novas, no fim): a fala inteira a DB_VOZ, correndo por baixo das
  cenas que cobrem a imagem; o som da câmera do próprio aluno sai de baixo dela (seria o mesmo
  som repetido);
- música: DB_MUSICA e abaixa para DB_MUSICA_SOB_VOZ enquanto o aluno fala, com rampas curtas.
  Os pontos de volume (<keyframe>) contam os quadros a partir do início do ARQUIVO da música,
  como no XML do Final Cut 7 (o mesmo do `in` do clipe)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import PureWindowsPath

from roteiro_ia.areas.formatura.acabamento import Voz
from typing import Callable

from roteiro_ia.premiere.fcpxml import (AUDIO_TRACKS, _define_file, _frames, _levels, _link,
                                        _master_id, _Src, _sub, timebase)

DB_CAMERA = -25.0
DB_VOZ = -3.0
DB_MUSICA = 0.0
DB_MUSICA_SOB_VOZ = -15.0
RAMPA_S = 0.4
JUNTAR_S = 1.5   # falas mais perto que isto: a música fica baixa entre elas
VOZ_TRACKS = ("VOZ L", "VOZ R")


def nivel(db: float) -> float:
    return 10 ** (db / 20)


def _rate(el: ET.Element) -> tuple[int, int]:
    tb = int(el.findtext("rate/timebase") or 30)
    return (tb * 1000, 1001) if el.findtext("rate/ntsc") == "TRUE" else (tb, 1)


def _fps(rate: tuple[int, int]) -> float:
    return rate[0] / rate[1]


def _por_trilha(audio: ET.Element) -> dict[str, ET.Element]:
    tracks = audio.findall("track")
    return {nome: tracks[i] for i, nome in enumerate(AUDIO_TRACKS) if i < len(tracks)}


def _definir_nivel(ci: ET.Element, valor: float) -> ET.Element:
    """Valor fixo do filtro Audio Levels do clipe (cria o filtro se não houver)."""
    for f in ci.findall("filter"):
        p = f.find("effect/parameter")
        if f.findtext("effect/effectid") == "audiolevels" and p is not None:
            p.find("value").text = f"{valor:.5f}"
            for k in p.findall("keyframe"):
                p.remove(k)
            return p
    _levels(ci, valor)
    return ci.findall("filter")[-1].find("effect/parameter")


def _canais(root: ET.Element, fid: str) -> int:
    for f in root.iter("file"):
        if f.get("id") == fid and f.find("media/audio/channelcount") is not None:
            return int(f.findtext("media/audio/channelcount") or 0)
    return 2


def _refazer_links(seq: ET.Element) -> None:
    """Depois de tirar clipes, os <link> voltam a apontar a posição certa de cada um."""
    pos: dict[str, tuple[int, int]] = {}
    for tipo in ("video", "audio"):
        for ti, tr in enumerate(seq.findall(f"media/{tipo}/track"), start=1):
            for ci_i, ci in enumerate(tr.findall("clipitem"), start=1):
                pos[ci.get("id")] = (ti, ci_i)
    for ci in seq.iter("clipitem"):
        for ln in list(ci.findall("link")):
            ref = ln.findtext("linkclipref")
            if ref not in pos:
                ci.remove(ln)
                continue
            ln.find("trackindex").text = str(pos[ref][0])
            ln.find("clipindex").text = str(pos[ref][1])


def _faixas_de_voz(seq: ET.Element) -> list[tuple[int, int]]:
    """(início, fim) em quadros da sequência, falas próximas juntas."""
    out: list[list[int]] = []
    rate = _rate(seq)
    for ci in seq.findall("media/audio/track/clipitem"):
        if ci.get("id", "").startswith("voz-") and ci.findtext("sourcetrack/trackindex") == "1":
            a, b = int(ci.findtext("start")), int(ci.findtext("end"))
            if out and a - out[-1][1] <= JUNTAR_S * _fps(rate):
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
    return [(a, b) for a, b in out]


def _abaixar_musica(seq: ET.Element, faixas: list[tuple[int, int]], tracks: dict[str, ET.Element]
                    ) -> None:
    rate = _rate(seq)
    rampa = max(1, round(RAMPA_S * _fps(rate)))
    alto, baixo = nivel(DB_MUSICA), nivel(DB_MUSICA_SOB_VOZ)
    for nome in ("MÚSICA L", "MÚSICA R"):
        tr = tracks.get(nome)
        if tr is None:
            continue
        for ci in tr.findall("clipitem"):
            p = _definir_nivel(ci, alto)
            st, en, cin = int(ci.findtext("start")), int(ci.findtext("end")), int(ci.findtext("in"))
            pontos: list[tuple[int, float]] = []
            for a, b in faixas:
                if b <= st or a >= en:
                    continue
                pontos += [(a - rampa, alto), (a, baixo), (b, baixo), (b + rampa, alto)]
            if not pontos:
                continue
            vistos: dict[int, float] = {}
            for q, v in pontos:
                q = min(max(q, st), en)
                vistos[q] = v if q not in vistos else min(vistos[q], v)
            for q in sorted(vistos):
                k = _sub(p, "keyframe")
                _sub(k, "when", cin + (q - st))
                _sub(k, "value", f"{vistos[q]:.5f}")


def _colocar_vozes(root: ET.Element, seq: ET.Element, vozes: list[Voz],
                   tracks: dict[str, ET.Element], audio: ET.Element,
                   fontes: Callable[[str], _Src | None] | None = None) -> list[str]:
    rate = _rate(seq)
    definidos = {f.get("id") for f in root.iter("file") if len(f)}
    fps = _fps(rate)
    v1 = seq.find("media/video/track")
    alertas: list[str] = []
    novas = []
    for nome in VOZ_TRACKS:
        tr = ET.Element("track")
        novas.append(tr)
    n_audio = len(audio.findall("track"))
    tirar: list[tuple[ET.Element, ET.Element]] = []
    for n, v in enumerate(vozes, start=1):
        arq = PureWindowsPath(v.rel_path).name
        ini = round(v.inicio_s * fps)
        fim = ini + max(1, round(v.dur_s * fps))
        src = fontes(v.rel_path) if fontes is not None else None
        base = None
        for ci in root.iter("clipitem"):
            if ci.findtext("name") == arq and ci.find("file") is not None and (
                    src is None or ci.find("file").get("id") == src.fid):
                base = ci
                break
        if base is None and src is None:
            alertas.append(f"Voz de {arq} não colocada: o vídeo não está na timeline.")
            continue
        if src is not None:
            fid, crate = src.fid, src.rate
            master, dur_txt = _master_id(fid), str(_frames(src.duration_s, src.rate))
            tb, ntsc = timebase(*crate)
            tb_txt, ntsc_txt = str(tb), "TRUE" if ntsc else "FALSE"
        else:
            fid, crate = base.find("file").get("id"), _rate(base)
            master, dur_txt = base.findtext("masterclipid"), base.findtext("duration")
            tb_txt, ntsc_txt = base.findtext("rate/timebase"), base.findtext("rate/ntsc")
        cin = round(v.in_s * _fps(crate))
        cout = cin + (fim - ini) if timebase(*crate) == timebase(*rate) else round(
            (v.in_s + v.dur_s) * _fps(crate))
        itens = []
        for ch in range(2 if _canais(root, fid) >= 2 else 1):
            tr = novas[ch]
            ci = _sub(tr, "clipitem", id=f"voz-{seq.findtext('name').replace(' ', '_')}-{n}-{ch + 1}")
            _sub(ci, "masterclipid", master)
            _sub(ci, "name", arq)
            _sub(ci, "enabled", "TRUE")
            _sub(ci, "duration", dur_txt)
            r = _sub(ci, "rate")
            _sub(r, "timebase", tb_txt)
            _sub(r, "ntsc", ntsc_txt)
            _sub(ci, "start", ini)
            _sub(ci, "end", fim)
            _sub(ci, "in", cin)
            _sub(ci, "out", cout)
            fe = _sub(ci, "file", id=fid)
            if src is not None and fid not in definidos:
                _define_file(fe, src)  # o vídeo do aluno pode não estar na imagem: define aqui
                definidos.add(fid)
            s = _sub(ci, "sourcetrack")
            _sub(s, "mediatype", "audio")
            _sub(s, "trackindex", ch + 1)
            _levels(ci, nivel(DB_VOZ))
            itens.append((ci, "audio", n_audio + ch + 1, len(tr.findall("clipitem"))))
        if len(itens) > 1:
            _link(itens)
        # o som da câmera do próprio aluno, no trecho da fala, sai (a voz já é esse som)
        for nome in ("SOM CÂMERA L", "SOM CÂMERA R"):
            tr = tracks.get(nome)
            for ci in (tr.findall("clipitem") if tr is not None else []):
                a, b = int(ci.findtext("start")), int(ci.findtext("end"))
                if ci.find("file").get("id") == fid and a < fim and ini < b:
                    tirar.append((tr, ci))
    for tr, ci in tirar:
        if ci in list(tr):
            tr.remove(ci)
    for i, tr in enumerate(novas):
        _sub(tr, "enabled", "TRUE")
        _sub(tr, "locked", "FALSE")
        _sub(tr, "outputchannelindex", i + 1)
        audio.append(tr)
    return alertas


def mixar(xml: str, vozes_por_seq: dict[str, list[Voz]],
          fontes: Callable[[str], _Src | None] | None = None) -> tuple[str, list[str]]:
    """Aplica a mixagem nas sequências de `vozes_por_seq` (nome → vozes, pode ser vazio).
    `fontes`: vídeo do aluno → arquivo, para a voz de um vídeo que não aparece na imagem."""
    cab, corpo = xml.split("\n", 2)[:2], xml.split("\n", 2)[2]
    root = ET.fromstring(corpo)
    alertas: list[str] = []
    for seq in root.iter("sequence"):
        nome = seq.findtext("name")
        if nome not in vozes_por_seq:
            continue
        audio = seq.find("media/audio")
        tracks = _por_trilha(audio)
        for t in ("SOM CÂMERA L", "SOM CÂMERA R"):
            for ci in (tracks[t].findall("clipitem") if t in tracks else []):
                ci.find("enabled").text = "TRUE"
                _definir_nivel(ci, nivel(DB_CAMERA))
        alertas += _colocar_vozes(root, seq, vozes_por_seq[nome], tracks, audio, fontes)
        _abaixar_musica(seq, _faixas_de_voz(seq), tracks)
        _refazer_links(seq)
    ET.indent(root, space="  ")
    return "\n".join(cab) + "\n" + ET.tostring(root, encoding="unicode") + "\n", alertas
