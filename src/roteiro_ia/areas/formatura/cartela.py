"""Cartela de abertura (dados do evento): MOGRT do ano preenchido pelo painel do Premiere ou, sem
ele, uma cartela simples (PNG transparente) gerada aqui e posta numa faixa por cima."""
from __future__ import annotations

import json
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from roteiro_ia import proc
from roteiro_ia.areas.formatura.cadastro import Formatura
from roteiro_ia.areas.formatura.projeto import ProjetoFormatura
from roteiro_ia.config import Settings
from roteiro_ia.media.tools import ffmpeg_bin
from roteiro_ia.premiere.fcpxml import _clipitem, _Ctx, _define_file, _frames, _marker, _Src, _sub
from roteiro_ia.safety import assert_writable, safe_write_text

CARTELA_S = 5
FONTES = (Path("C:/Windows/Fonts/segoeuib.ttf"), Path("C:/Windows/Fonts/segoeui.ttf"))


def campos_cartela(pf: ProjetoFormatura, ficha: Formatura | None, data_iso: str | None) -> dict[str, str]:
    """Nome do campo (como no MOGRT) → texto. Campos vazios ficam de fora."""
    c: dict[str, str] = {}
    if ficha is not None:
        c["Instituição"] = ficha.instituicao
    if pf.curso:
        c["Curso"] = pf.curso
    if pf.turma:
        c["Turma"] = pf.turma
    if ficha is not None:
        c["Formatura"] = f"{ficha.ano}/{ficha.semestre}"
        c["Semestre"] = f"{ficha.semestre}º semestre"
        c["Ano"] = str(ficha.ano)
    if pf.turmas_colacao:
        c["Turmas"] = "; ".join(f"{cu} — {tu}" for cu, tu in pf.turmas_colacao)
    if pf.local:
        c["Local"] = pf.local
    if pf.cidade:
        c["Cidade"] = pf.cidade
    if data_iso:
        try:
            c["Data"] = date.fromisoformat(data_iso).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return c


def linhas_cartela(c: dict[str, str]) -> list[str]:
    """Texto da cartela simples, uma linha por item (a 1ª é a instituição, em destaque)."""
    out = [c["Instituição"]] if "Instituição" in c else []
    if "Curso" in c:
        out.append(c["Curso"])
    if "Turma" in c:
        out.append(f"Turma {c['Turma']}")
    if "Turmas" in c:
        out += c["Turmas"].split("; ")
    if "Formatura" in c:
        out.append(f"Formatura {c['Formatura']}")
    lugar = " — ".join(x for x in (c.get("Local"), c.get("Cidade")) if x)
    if lugar:
        out.append(lugar)
    if "Data" in c:
        out.append(c["Data"])
    return out


def _esc_caminho(p: Path) -> str:
    """Caminho dentro de um filtro do ffmpeg (barras normais, ':' escapado)."""
    return str(p).replace("\\", "/").replace(":", "\\:")


def gerar_cartela_png(campos: dict[str, str], logo_escola: str | None, saida: Path, s: Settings) -> Path:
    """PNG 1920×1080 transparente: logo da escola no alto e as linhas centralizadas."""
    saida = Path(saida)
    assert_writable(saida, s)
    linhas = linhas_cartela(campos) or [" "]
    logo = Path(logo_escola) if logo_escola and Path(logo_escola).is_file() else None
    negrito = next((f for f in FONTES if f.is_file()), None)
    normal = next((f for f in reversed(FONTES) if f.is_file()), None)
    with tempfile.TemporaryDirectory() as tmp:
        y = 470 if logo is not None else 360
        altura = 110 + 66 * (len(linhas) - 1) + 60
        topo = max(0, y - 40)
        cmd = [ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi",
               "-i", (f"color=c=black@0.35:s=1920x{altura}:d=1,format=rgba,"
                      f"pad=1920:1080:0:{topo}:color=black@0.0")]
        filtros = ["[0]format=rgba[b0]"]
        atual = "b0"
        if logo is not None:
            cmd += ["-i", str(logo)]
            filtros.append("[1]scale=-1:300,format=rgba[lg]")
            filtros.append(f"[{atual}][lg]overlay=(W-w)/2:110[b1]")
            atual = "b1"
        for i, txt in enumerate(linhas):
            arq = Path(tmp) / f"l{i}.txt"
            arq.write_text(txt, encoding="utf-8")
            fonte = negrito if i == 0 else normal
            tam = 78 if i == 0 else 48
            partes = [f"textfile='{_esc_caminho(arq)}'", "expansion=none", f"fontsize={tam}",
                      "fontcolor=white",
                      "shadowcolor=black@0.7", "shadowx=3", "shadowy=3", "x=(w-text_w)/2", f"y={y}"]
            if fonte is not None:
                partes.insert(0, f"fontfile='{_esc_caminho(fonte)}'")
            filtros.append(f"[{atual}]drawtext=" + ":".join(partes) + f"[t{i}]")
            atual = f"t{i}"
            y += 110 if i == 0 else 66
        cmd += ["-filter_complex", ";".join(filtros), "-map", f"[{atual}]", "-frames:v", "1",
                "-update", "1", "-pix_fmt", "rgba", str(saida)]
        r = proc.run(cmd, timeout=120)
    if r.returncode != 0 or not saida.is_file():
        erro = r.stderr.decode("utf-8", "replace").strip().splitlines() if r.stderr else []
        raise RuntimeError(f"O ffmpeg não conseguiu gerar a cartela: {erro[-1] if erro else 'erro desconhecido'}")
    return saida


def _rate(seq: ET.Element) -> tuple[int, int]:
    tb = int(seq.findtext("rate/timebase") or 30)
    return (tb * 1000, 1001) if seq.findtext("rate/ntsc") == "TRUE" else (tb, 1)


def colocar_cartela(xml: str, nomes: list[str], png: str | None, dur_s: float = CARTELA_S) -> str:
    """Faixa de vídeo nova por cima nas sequências `nomes`: com o PNG no início ou, para o MOGRT
    (png None), vazia e reservada para o painel preencher."""
    cab, corpo = xml.split("\n", 2)[:2], xml.split("\n", 2)[2]
    root = ET.fromstring(corpo)
    ctx = _Ctx()
    definido = False
    for seq in root.iter("sequence"):
        if seq.findtext("name") not in nomes:
            continue
        rate = _rate(seq)
        fim = _frames(dur_s, rate)
        video = seq.find("media/video")
        track = ET.Element("track")
        if png:
            src = _Src("file-cartela", Path(png), dur_s, rate, (1920, 1080), 0)
            ci = _clipitem(track, ctx, src, Path(png).name, 0, fim, 0.0, dur_s, rate)
            if not definido:
                _define_file(ci.find("file"), src)
                definido = True
            _marker(seq, "CARTELA", "Cartela com os dados do evento (simples, gerada pelo sistema).", 0, fim)
        else:
            _marker(seq, "CARTELA (MOGRT)", "Faixa reservada: o painel do Premiere põe a cartela "
                    "do ano aqui e preenche os textos.", 0, fim)
        _sub(track, "enabled", "TRUE")
        _sub(track, "locked", "FALSE")
        video.append(track)
    ET.indent(root, space="  ")
    return "\n".join(cab) + "\n" + ET.tostring(root, encoding="unicode") + "\n"


def job_cartela(job_path: Path, s: Settings, mogrt: str, sequencias: list[str],
                campos: dict[str, str]) -> None:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    job["cartela"] = {"mogrt": mogrt, "sequencias": sequencias, "campos": campos}
    texto = json.dumps(job, ensure_ascii=False, indent=2)
    safe_write_text(Path(job_path), texto, s)
    safe_write_text(Path(s.system_dir) / "ultimo_job.json", texto, s)
