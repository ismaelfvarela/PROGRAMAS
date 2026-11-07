"""Política de GPU dos modelos de trilha (fakes; nenhum modelo real é carregado)."""
import math

import numpy as np
import pytest
import torch

from roteiro_ia import music_index as mi

SR = 22050


class FakeModel:
    """Modelo falso: registra para onde foi movido."""

    def __init__(self, samplerate=SR):
        self.samplerate = samplerate
        self.movimentos = []

    def to(self, device):
        self.movimentos.append(device)
        return self

    def eval(self):
        return self


def _oom():
    return torch.cuda.OutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB")


def _separador(erro_na_gpu, vezes=1):
    sep = mi.DemucsSeparator(device="cuda")
    sep._model = FakeModel()
    estado = {"falhas": 0, "dispositivos": []}

    def run(x, model):
        estado["dispositivos"].append(sep.device)
        if sep.device == "cuda" and estado["falhas"] < vezes:
            estado["falhas"] += 1
            raise erro_na_gpu()
        return torch.zeros_like(x)

    sep._run = run
    return sep, estado


def test_demucs_oom_refaz_so_a_trilha_na_cpu_e_volta_para_gpu(monkeypatch):
    limpezas = []
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: limpezas.append(1))
    sep, estado = _separador(_oom)
    out = sep.vocals(np.zeros(SR, dtype=np.float32), SR)
    assert len(out) == SR
    assert estado["dispositivos"] == ["cuda", "cpu"]
    assert sep.device == "cuda" and sep._model.movimentos == ["cpu", "cuda"]
    assert limpezas
    sep.vocals(np.zeros(SR, dtype=np.float32), SR)  # a próxima trilha volta à GPU
    assert estado["dispositivos"][-1] == "cuda"


def test_demucs_oom_por_mensagem_tambem_e_temporario(monkeypatch):
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    sep, estado = _separador(lambda: RuntimeError("CUDA error: out of memory"))
    sep.vocals(np.zeros(SR, dtype=np.float32), SR)
    assert sep.device == "cuda"


def test_demucs_cuda_quebrada_passa_para_cpu_de_vez(monkeypatch):
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    sep, estado = _separador(lambda: RuntimeError("CUDA error: an illegal memory access"))
    sep.vocals(np.zeros(SR, dtype=np.float32), SR)
    assert sep.device == "cpu" and sep._model.movimentos == ["cpu"]
    sep.vocals(np.zeros(SR, dtype=np.float32), SR)
    assert estado["dispositivos"] == ["cuda", "cpu", "cpu"]


def test_demucs_cudnn_tambem_e_permanente(monkeypatch):
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    sep, _ = _separador(lambda: RuntimeError("cuDNN error: CUDNN_STATUS_INTERNAL_ERROR"))
    sep.vocals(np.zeros(SR, dtype=np.float32), SR)
    assert sep.device == "cpu"


def test_demucs_outro_erro_propaga(monkeypatch):
    sep, _ = _separador(lambda: RuntimeError("shape mismatch"))
    with pytest.raises(RuntimeError, match="shape"):
        sep.vocals(np.zeros(SR, dtype=np.float32), SR)
    assert sep.device == "cuda"


# ---------------------------------------------------------------- CLAP

class _Entrada:
    """Tensor falso de entrada: `.to()` não move nada de verdade."""

    def __init__(self):
        self.destinos = []

    def to(self, device):
        self.destinos.append(device)
        return self


class FakeProc:
    def __call__(self, text=None, audio=None, **kw):
        return {"x": _Entrada()}


class FakeClap(FakeModel):
    def __init__(self, falhas_audio=0):
        super().__init__()
        self.device = "cuda"
        self.falhas_audio = falhas_audio
        self.logit_scale_a = torch.tensor(math.log(10.0))
        self.logit_scale_t = torch.tensor(math.log(1.0))

    def to(self, device):
        self.device = device
        return super().to(device)

    def get_audio_features(self, **kw):
        if self.device == "cuda" and self.falhas_audio:
            self.falhas_audio -= 1
            raise _oom()
        return torch.tensor([[1.0, 0.0]])

    def get_text_features(self, **kw):
        return torch.tensor([[1.0, 0.0], [0.0, 1.0]])


def _tagger(model):
    tg = mi.ClapTagger(device="cuda")
    tg._model, tg._proc = model, FakeProc()
    return tg


def test_clap_usa_escala_de_audio():
    tg = _tagger(FakeClap())
    sc = tg.scores(np.zeros(mi.CLAP_SR * 2, dtype=np.float32), mi.CLAP_SR, ["a", "b"])
    esperado = math.exp(10) / (math.exp(10) + 1)  # cos 1 e 0 × escala 10 (logit_scale_a)
    assert sc[0] == pytest.approx(esperado, rel=1e-4)


def test_clap_oom_refaz_na_cpu_e_volta(monkeypatch):
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    model = FakeClap(falhas_audio=1)
    tg = _tagger(model)
    sc = tg.scores(np.zeros(mi.CLAP_SR * 2, dtype=np.float32), mi.CLAP_SR, ["a", "b"])
    assert len(sc) == 2
    assert tg.device == "cuda" and model.movimentos == ["cpu", "cuda"]


# ---------------------------------------------------------------- revisão fixa do CLAP

def test_clap_revisao_fixa_com_alternativa(monkeypatch):
    assert len(mi.CLAP_REVISAO_PESOS) == 40 and mi.CLAP_REVISAO_ALTERNATIVA == "refs/pr/3"
    tentativas = []

    def modelo(revisao):
        tentativas.append(revisao)
        if revisao == mi.CLAP_REVISAO_PESOS:
            raise OSError("revisão não encontrada")
        return FakeClap()

    monkeypatch.setattr(mi, "_carregar_modelo_clap", modelo)
    monkeypatch.setattr(mi, "_carregar_processador_clap", FakeProc)
    tg = mi.ClapTagger(device="cpu")
    tg._load()
    assert tentativas == [mi.CLAP_REVISAO_PESOS, "refs/pr/3"]
