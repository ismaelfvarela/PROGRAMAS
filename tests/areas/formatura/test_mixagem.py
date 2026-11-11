import xml.etree.ElementTree as ET

from roteiro_ia.areas.formatura.acabamento import Voz
from roteiro_ia.areas.formatura.mixagem import (DB_CAMERA, DB_MUSICA_SOB_VOZ, DB_VOZ, mixar,
                                                nivel)
from roteiro_ia.premiere.fcpxml import AUDIO_TRACKS


def _clip(tr, cid, nome, fid, a, b, cin, audio=None, nivel_=None):
    ci = ET.SubElement(tr, "clipitem", id=cid)
    ET.SubElement(ci, "masterclipid").text = f"masterclip-{fid}"
    ET.SubElement(ci, "name").text = nome
    ET.SubElement(ci, "enabled").text = "FALSE" if audio else "TRUE"
    ET.SubElement(ci, "duration").text = "1800"
    r = ET.SubElement(ci, "rate")
    ET.SubElement(r, "timebase").text = "30"
    ET.SubElement(r, "ntsc").text = "FALSE"
    for k, v in (("start", a), ("end", b), ("in", cin), ("out", cin + b - a)):
        ET.SubElement(ci, k).text = str(v)
    f = ET.SubElement(ci, "file", id=fid)
    if fid == "file-1" and cid == "v1":
        ET.SubElement(f, "name").text = nome
        ET.SubElement(ET.SubElement(ET.SubElement(f, "media"), "audio"), "channelcount").text = "2"
    if audio:
        s = ET.SubElement(ci, "sourcetrack")
        ET.SubElement(s, "mediatype").text = "audio"
        ET.SubElement(s, "trackindex").text = str(audio)
        eff = ET.SubElement(ET.SubElement(ci, "filter"), "effect")
        ET.SubElement(eff, "effectid").text = "audiolevels"
        p = ET.SubElement(eff, "parameter")
        ET.SubElement(p, "value").text = str(nivel_ or 1.0)
    return ci


def _xml():
    """Aluno (file-1) 0–60, cobertura (file-2) 60–150, aluno de novo 150–210 (30 fps)."""
    seq = ET.Element("sequence", id="s")
    ET.SubElement(seq, "name").text = "EP 01"
    r = ET.SubElement(seq, "rate")
    ET.SubElement(r, "timebase").text = "30"
    ET.SubElement(r, "ntsc").text = "FALSE"
    media = ET.SubElement(seq, "media")
    v1 = ET.SubElement(ET.SubElement(media, "video"), "track")
    _clip(v1, "v1", "aluno.mp4", "file-1", 0, 60, 300)
    _clip(v1, "v2", "cob.mp4", "file-2", 60, 150, 30)
    _clip(v1, "v3", "aluno.mp4", "file-1", 150, 210, 450)
    audio = ET.SubElement(media, "audio")
    tr = {n: ET.SubElement(audio, "track") for n in AUDIO_TRACKS}
    for lado, ch in (("L", 1), ("R", 2)):
        t = tr[f"SOM CÂMERA {lado}"]
        _clip(t, f"a1{lado}", "aluno.mp4", "file-1", 0, 60, 300, ch, 3.0)
        _clip(t, f"a2{lado}", "cob.mp4", "file-2", 60, 150, 30, ch, 3.0)
        _clip(t, f"a3{lado}", "aluno.mp4", "file-1", 150, 210, 450, ch, 3.0)
        _clip(tr[f"MÚSICA {lado}"], f"m{lado}", "musica.mp3", "music-1", 0, 210, 240, ch)
    root = ET.Element("xmeml")
    ET.SubElement(ET.SubElement(root, "project"), "children").append(seq)
    return '<?xml version="1.0"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode")


def _seq(xml):
    return ET.fromstring(xml.split("\n", 2)[2]).find(".//sequence")


def _nivel(ci):
    return float(ci.find("filter/effect/parameter/value").text)


def test_voz_por_baixo_camera_baixa_e_musica_abaixa():
    voz = Voz(inicio_s=0.0, rel_path="A\\aluno.mp4", in_s=10.0, dur_s=6.0)
    xml, alertas = mixar(_xml(), {"EP 01": [voz]})
    assert alertas == []
    seq = _seq(xml)
    tracks = seq.findall("media/audio/track")
    assert len(tracks) == len(AUDIO_TRACKS) + 2  # VOZ L e VOZ R no fim
    vz = tracks[-2].findall("clipitem") + tracks[-1].findall("clipitem")
    assert len(vz) == 2
    assert all(c.findtext("start") == "0" and c.findtext("end") == "180" and c.findtext("in") == "300"
               for c in vz)
    assert all(abs(_nivel(c) - nivel(DB_VOZ)) < 1e-4 for c in vz)
    cam = tracks[AUDIO_TRACKS.index("SOM CÂMERA L")].findall("clipitem")
    assert [c.findtext("name") for c in cam] == ["cob.mp4"]  # o som do aluno saiu de baixo da voz
    assert cam[0].findtext("enabled") == "TRUE" and abs(_nivel(cam[0]) - nivel(DB_CAMERA)) < 1e-4
    mus = tracks[AUDIO_TRACKS.index("MÚSICA L")].find("clipitem")
    kf = [(int(k.findtext("when")), float(k.findtext("value")))
          for k in mus.findall("filter/effect/parameter/keyframe")]
    # quadros contados do começo do arquivo (in = 240): baixa já no início, volta depois da fala
    assert kf[0] == (240, round(nivel(DB_MUSICA_SOB_VOZ), 5))
    assert (240 + 180, round(nivel(DB_MUSICA_SOB_VOZ), 5)) in kf
    assert kf[-1] == (240 + 180 + 12, 1.0)
    # links L/R da voz apontam para as faixas novas
    for c in vz:
        idx = sorted(int(ln.findtext("trackindex")) for ln in c.findall("link"))
        assert idx == [len(AUDIO_TRACKS) + 1, len(AUDIO_TRACKS) + 2]


def test_sem_vozes_so_volumes_e_outras_sequencias_intactas():
    xml, _ = mixar(_xml(), {"EP 01": []})
    seq = _seq(xml)
    assert len(seq.findall("media/audio/track")) == len(AUDIO_TRACKS) + 2
    cam = seq.findall("media/audio/track")[AUDIO_TRACKS.index("SOM CÂMERA L")].findall("clipitem")
    assert len(cam) == 3 and all(abs(_nivel(c) - nivel(DB_CAMERA)) < 1e-4 for c in cam)
    assert not seq.findall(".//keyframe")
    igual, _ = mixar(_xml(), {"OUTRA": []})
    assert "keyframe" not in igual and "0.05623" not in igual


def test_voz_de_video_fora_da_timeline_vira_aviso():
    voz = Voz(inicio_s=3.0, rel_path="A/outro.mp4", in_s=10.0, dur_s=2.0)
    _, alertas = mixar(_xml(), {"EP 01": [voz]})
    assert alertas and "outro.mp4" in alertas[0]


def test_voz_sem_rosto_entra_com_o_arquivo_definido():
    from pathlib import Path

    from roteiro_ia.premiere.fcpxml import _Src
    voz = Voz(inicio_s=3.0, rel_path="A/outro.mp4", in_s=10.0, dur_s=2.0)
    src = _Src("file-9", Path("Y:/x/A/outro.mp4"), 60.0, (30, 1), (1920, 1080), 2)
    xml, alertas = mixar(_xml(), {"EP 01": [voz]}, fontes=lambda r: src)
    assert alertas == []
    root = ET.fromstring(xml.split(chr(10), 2)[2])
    vozes = [ci for ci in root.iter("clipitem") if ci.get("id", "").startswith("voz-")]
    assert len(vozes) == 2 and all(int(ci.findtext("start")) == 90 for ci in vozes)
    defs = [f for f in root.iter("file") if f.get("id") == "file-9" and len(f)]
    assert len(defs) == 1 and defs[0].findtext("pathurl")
