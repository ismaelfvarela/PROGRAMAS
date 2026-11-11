import json
import subprocess
from pathlib import Path

import numpy as np

from roteiro_ia.areas.formatura.cartela import gerar_cartela_png
from roteiro_ia.areas.formatura.cartela_modelo import (CartelaModelo, carregar_cartela_modelo,
                                                       cor_do_quadro, estudar_cartela)
from roteiro_ia.config import Settings
from roteiro_ia.gemini import style
from roteiro_ia.media.tools import ffmpeg_bin, ffprobe_bin


def _ff(*a):
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", *a], check=True)


def _pixel(png, x, y, w, h):
    r = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(png), "-f", "rawvideo", "-pix_fmt",
                        "rgba", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(h, w, 4)[y, x]


def _tam(png):
    r = subprocess.run([ffprobe_bin(), "-v", "error", "-show_entries", "stream=width,height", "-of",
                        "json", str(png)], capture_output=True, text=True)
    st = json.loads(r.stdout)["streams"][0]
    return st["width"], st["height"]


def test_cartela_opaca_na_cor_do_modelo_e_no_tamanho_da_timeline(tmp_path):
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    out = gerar_cartela_png({"Instituição": "SENAI", "Turma": "TARDE"}, None, tmp_path / "c.png", s,
                            tamanho=(3840, 2160), cor_fundo="#E87722", cor_texto="#FFFFFF")
    assert _tam(out) == (3840, 2160)
    r, g, b, a = _pixel(out, 10, 10, 3840, 2160)
    assert a == 255 and abs(int(r) - 0xE8) < 6 and abs(int(g) - 0x77) < 6 and abs(int(b) - 0x22) < 6


def test_cartela_com_imagem_de_fundo(tmp_path):
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    fundo = tmp_path / "fundo.png"
    _ff("-f", "lavfi", "-i", "color=0x00FF00:size=640x360:d=1", "-frames:v", "1", "-update", "1", str(fundo))
    out = gerar_cartela_png({"Instituição": "SENAI"}, None, tmp_path / "c.png", s,
                            tamanho=(1920, 1080), fundo=str(fundo))
    r, g, b, a = _pixel(out, 5, 5, 1920, 1080)
    assert a == 255 and g > 200 and r < 40


def test_cor_do_quadro(tmp_path):
    v = tmp_path / "m.mp4"
    _ff("-f", "lavfi", "-i", "color=0x1D4F91:size=320x180:rate=30:duration=3", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(v))
    cor = cor_do_quadro(v, 1.5)
    r, g, b = (int(cor[i:i + 2], 16) for i in (1, 3, 5))
    assert abs(r - 0x1D) < 12 and abs(g - 0x4F) < 12 and abs(b - 0x91) < 12


class _C:
    def __init__(self):
        self.prompts, self.uploads = [], []

    def pick_default_models(self):
        return ("m", "m")

    def upload(self, path):
        self.uploads.append(Path(path).name)
        return f"file:{path}"

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        self.prompts.append(prompt)
        return CartelaModelo(tem_cartela=True, inicio_s=1.0, fim_s=2.5, cor_fundo="#FF0000",
                             cor_texto="#FFFFFF")


def test_estudar_cartela_mede_a_cor_e_guarda(tmp_path):
    import roteiro_ia.areas.formatura  # noqa: F401
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    pasta = tmp_path / "MODELOS"
    pasta.mkdir()
    v = pasta / "oficina.mp4"
    _ff("-f", "lavfi", "-i", "color=0xE87722:size=320x180:rate=30:duration=3", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(v))
    (pasta / "outro.mp4").write_bytes(b"x")
    cache = Path(s.system_dir) / "estilo_cache" / "formatura_modelos"
    cache.mkdir(parents=True)
    for nome, abertura in (("outro.mp4", "Início direto com fotos"),
                           ("oficina.mp4", "Vinheta animada e cartela em fundo laranja")):
        n = style.VideoStyleNotes(url=nome, tipo="episodio", duracao_s=3, ritmo_corte_s=2,
                                  abertura=abertura, gancho="", uso_falas="", trilha="", cor="",
                                  observacoes="")
        (cache / f"{nome}.json").write_text(n.model_dump_json(), encoding="utf-8")
    c = _C()
    cm = estudar_cartela(c, s, 2026, pasta)
    assert c.uploads == ["oficina.mp4"] and cm.tem_cartela
    r, g, b = (int(cm.cor_fundo[i:i + 2], 16) for i in (1, 3, 5))
    assert abs(r - 0xE8) < 12 and abs(g - 0x77) < 12 and abs(b - 0x22) < 12  # medida no quadro
    c2 = _C()
    assert estudar_cartela(c2, s, 2026, pasta) == cm and c2.prompts == []  # guardado
    assert carregar_cartela_modelo(s, 2026) == cm


def test_estudar_cartela_sem_video_de_cartela(tmp_path):
    import roteiro_ia.areas.formatura  # noqa: F401
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    pasta = tmp_path / "MODELOS"
    pasta.mkdir()
    assert estudar_cartela(_C(), s, 2026, pasta) is None
