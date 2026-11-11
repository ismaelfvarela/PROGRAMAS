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


def _hex_ff(cor: str) -> str:
    """'#E87722' → '0xE87722' (cor no formato do ffmpeg)."""
    c = cor.strip().lstrip("#")
    return "0x" + (c if len(c) == 6 else "FFFFFF")


def gerar_cartela_png(campos: dict[str, str], logo_escola: str | None, saida: Path, s: Settings,
                      tamanho: tuple[int, int] = (1920, 1080), cor_fundo: str | None = None,
                      cor_texto: str | None = None, fundo: str | None = None) -> Path:
    """PNG da cartela no tamanho da timeline: logo da escola no alto e as linhas centralizadas.

    Fundo, nesta ordem: a imagem `fundo` (escolhida nos modelos do ano), a cor `cor_fundo`
    (a da cartela do vídeo modelo) ou transparente com uma faixa escura atrás do texto."""
    saida = Path(saida)
    assert_writable(saida, s)
    W, H = tamanho
    k = H / 1080  # tudo foi desenhado para 1080 linhas: escala para 4K etc.
    linhas = linhas_cartela(campos) or [" "]
    logo = Path(logo_escola) if logo_escola and Path(logo_escola).is_file() else None
    img_fundo = Path(fundo) if fundo and Path(fundo).is_file() else None
    negrito = next((f for f in FONTES if f.is_file()), None)
    normal = next((f for f in reversed(FONTES) if f.is_file()), None)
    texto = _hex_ff(cor_texto) if cor_texto else "white"
    with tempfile.TemporaryDirectory() as tmp:
        y = int((470 if logo is not None else 360) * k)
        cmd = [ffmpeg_bin(), "-v", "error", "-y"]
        if img_fundo is not None:
            cmd += ["-loop", "1", "-i", str(img_fundo)]
            filtros = [f"[0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                       "format=rgba[b0]"]
        elif cor_fundo:
            cmd += ["-f", "lavfi", "-i", f"color=c={_hex_ff(cor_fundo)}:s={W}x{H}:d=1,format=rgba"]
            filtros = ["[0]format=rgba[b0]"]
        else:
            altura = int((110 + 66 * (len(linhas) - 1) + 60) * k)
            topo = max(0, y - int(40 * k))
            cmd += ["-f", "lavfi", "-i", (f"color=c=black@0.35:s={W}x{altura}:d=1,format=rgba,"
                                          f"pad={W}:{H}:0:{topo}:color=black@0.0")]
            filtros = ["[0]format=rgba[b0]"]
        atual = "b0"
        if logo is not None:
            cmd += ["-i", str(logo)]
            filtros.append(f"[1]scale=-1:{int(300 * k)},format=rgba[lg]")
            filtros.append(f"[{atual}][lg]overlay=(W-w)/2:{int(110 * k)}[b1]")
            atual = "b1"
        for i, txt in enumerate(linhas):
            arq = Path(tmp) / f"l{i}.txt"
            arq.write_text(txt, encoding="utf-8")
            fonte = negrito if i == 0 else normal
            tam = int((78 if i == 0 else 48) * k)
            partes = [f"textfile='{_esc_caminho(arq)}'", "expansion=none", f"fontsize={tam}",
                      f"fontcolor={texto}", "shadowcolor=black@0.5", f"shadowx={max(1, int(3 * k))}",
                      f"shadowy={max(1, int(3 * k))}", "x=(w-text_w)/2", f"y={y}"]
            if fonte is not None:
                partes.insert(0, f"fontfile='{_esc_caminho(fonte)}'")
            filtros.append(f"[{atual}]drawtext=" + ":".join(partes) + f"[t{i}]")
            atual = f"t{i}"
            y += int((110 if i == 0 else 66) * k)
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


def tamanho_da_sequencia(xml: str, nome: str) -> tuple[int, int]:
    """Largura e altura da timeline `nome` no XML (padrão 1920×1080)."""
    root = ET.fromstring(xml.split("\n", 2)[2])
    for seq in root.iter("sequence"):
        if seq.findtext("name") == nome:
            sc = seq.find("media/video/format/samplecharacteristics")
            if sc is not None and sc.findtext("width") and sc.findtext("height"):
                return int(sc.findtext("width")), int(sc.findtext("height"))
    return 1920, 1080


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
            sc = seq.find("media/video/format/samplecharacteristics")
            tam = ((int(sc.findtext("width") or 1920), int(sc.findtext("height") or 1080))
                   if sc is not None else (1920, 1080))
            src = _Src("file-cartela", Path(png), dur_s, rate, tam, 0)
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
