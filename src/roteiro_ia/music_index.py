"""Índice incremental das trilhas da biblioteca: batida (BPM, tempos 1-4, energia, perfil) e
melodia (voz separada pelo Demucs, tonalidade, clima/instrumentos/tipo de voz pelo CLAP).

Os modelos (Demucs, CLAP) são plugáveis e carregados uma vez por execução; sem eles a trilha é
analisada só pela batida + heurística antiga de voz e marcada `analise_parcial`."""
from __future__ import annotations

import bisect
import logging
import math
import os
import sqlite3
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from .config import Settings
from .models import TrackInfo
from .safety import assert_writable, safe_mkdir

log = logging.getLogger(__name__)

AUDIO_EXTS = {".mp3", ".wav", ".m4a"}
INTENSE_BPM = 110.0
# Energia (RMS médio, amostras em [-1, 1]) a partir da qual a trilha é considerada intensa.
INTENSE_RMS = 0.15
CRESCENDO_RATIO = 1.3
# Heurística grosseira de voz: fração da energia harmônica (HPSS) entre 300 e 3400 Hz.
# Instrumentos melódicos também caem nessa faixa; serve só como sugestão, não como verdade.
VOCAL_RATIO = 0.55
VOCAL_BAND_HZ = (300.0, 3400.0)
VOCAL_EXCERPT_S = 45  # HPSS só no trecho central: a faixa inteira seria lenta demais
_SR = 22050
_HOP = 128  # resolução fina (~6 ms) para o BPM não oscilar entre quadros
ANALISE_VERSAO = 2

# --- voz (separação com Demucs)
VOZ_LIMIAR = 0.35         # RMS(voz)/RMS(mix) por segundo a partir do qual o segundo "tem voz"
VOZ_MIN_PROPORCAO = 0.15  # fração de segundos com voz para a trilha ser "cantada"
_SILENCIO_RMS = 1e-4      # segundos mais baixos que isso (≈ -80 dBFS) não contam como voz
TRECHO_INICIO_S = 60.0
TRECHO_CURTO_S = 20.0     # meio e clímax
MUSICA_CURTA_S = 100.0    # abaixo disso a música é analisada inteira
_SR_MODELOS = 44100       # áudio para Demucs/CLAP (o 22050 do BPM corta o agudo da voz)

# --- tonalidade (Krumhansl–Schmuckler)
NOTAS = ("Dó", "Dó#", "Ré", "Ré#", "Mi", "Fá", "Fá#", "Sol", "Sol#", "Lá", "Lá#", "Si")
_PERFIL_MAIOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
_PERFIL_MENOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

# --- clima / instrumentos / voz (CLAP zero-shot): prompt em inglês → nome em português
CLIMAS = {"romantic": "romântica", "emotional": "emotiva", "happy": "alegre", "epic": "épica",
          "inspiring": "inspiradora", "nostalgic": "nostálgica", "tense": "tensa",
          "calm": "calma", "festive": "festiva"}
INSTRUMENTOS = {"piano": "piano", "acoustic guitar": "violão", "strings": "cordas",
                "orchestra": "orquestra", "electronic": "eletrônica", "drums": "bateria",
                "choir": "coral", "solo voice": "voz solo"}
TIPO_VOZ = {"male vocals": "masculina", "female vocals": "feminina", "choir": "coral",
            "instrumental": "sem voz"}
SEM_VOZ = "sem voz"
CLAP_MODELO = "laion/clap-htsat-unfused"
# O repositório principal só tem pytorch_model.bin, que o transformers>=4.50 recusa carregar com
# torch < 2.6 (CVE do torch.load). A PR oficial de conversão (SFconvertbot) traz o safetensors.
# Fixada no commit para o qual refs/pr/3 apontava em 2026-11-06 (cache local do HF); se esse
# commit sumir, tenta a própria PR.
CLAP_REVISAO_PESOS = "79b58ed25fc00386262a2bea4b19fd21dc4310a0"
CLAP_REVISAO_ALTERNATIVA = "refs/pr/3"
CLAP_SR = 48000
CLAP_JANELA_S = 10.0

# Erros que indicam a CUDA quebrada (não só falta de memória): a execução passa para a CPU de vez.
_ERROS_CUDA_QUEBRADA = ("cuda error", "cudnn", "cublas", "driver", "device-side assert")


def _tipo_erro_gpu(e: BaseException) -> str | None:
    """"memoria" (falta de memória: temporário), "quebrada" (CUDA/driver/cuDNN) ou None."""
    import torch

    msg = str(e).lower()
    oom = getattr(torch.cuda, "OutOfMemoryError", None)
    if (oom is not None and isinstance(e, oom)) or "out of memory" in msg:
        return "memoria"
    if any(s in msg for s in _ERROS_CUDA_QUEBRADA):
        return "quebrada"
    return None


def _executar_com_gpu(obj, rotulo: str, executar: Callable[[], object],
                      mover: Callable[[str], object]):
    """Roda `executar()` no `obj.device`. Falta de memória na GPU: limpa o cache, refaz só esta
    chamada na CPU e devolve o modelo à GPU. CUDA quebrada: o resto da execução fica na CPU.
    Outros erros sobem (a trilha fica com análise parcial)."""
    try:
        return executar()
    except RuntimeError as e:
        if obj.device == "cpu":
            raise
        tipo = _tipo_erro_gpu(e)
        if tipo is None:
            raise
        import torch

        if tipo == "memoria":
            log.warning("Memória da GPU insuficiente para %s nesta trilha; refazendo só esta "
                        "trilha na CPU.", rotulo)
            original = obj.device
            torch.cuda.empty_cache()
            mover("cpu")
            obj.device = "cpu"
            try:
                return executar()
            finally:
                try:
                    mover(original)
                    obj.device = original
                except Exception as e2:  # a GPU não voltou: segue na CPU
                    log.warning("Não foi possível voltar para a GPU (%s); usando CPU.", e2)
        log.warning("Erro na GPU ao %s (%s); o restante da análise usa a CPU (mais lento).",
                    rotulo, e)
        obj.device = "cpu"
        mover("cpu")
        return executar()


def _liberar_gpu() -> None:
    """Devolve ao sistema a memória da GPU guardada pelo cache do PyTorch (se ele foi usado)."""
    import sys

    torch = sys.modules.get("torch")
    try:
        if torch is not None and torch.cuda.is_available() and torch.cuda.is_initialized():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001 — limpeza é só cortesia
        pass


class BeatTracker(Protocol):
    def track(self, path: Path) -> tuple[list[float], list[float]]:
        """Retorna (beats_s, downbeats_s)."""


class BeatThisTracker:
    """beat_this (GPU se possível, senão CPU). O modelo só é carregado no primeiro uso."""

    def __init__(self, device: str = "cuda"):
        self.device = device
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        from beat_this.inference import File2Beats

        try:
            self._model = File2Beats(checkpoint_path="final0", device=self.device, dbn=False)
        except Exception as e:
            if self.device == "cpu":
                raise
            log.warning("Não foi possível usar a GPU para os tempos das trilhas (%s); usando CPU.", e)
            self.device = "cpu"
            self._model = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)
        return self._model

    def track(self, path: Path) -> tuple[list[float], list[float]]:
        beats, downbeats = self._load()(str(path))
        return [float(b) for b in beats], [float(d) for d in downbeats]


class LibrosaTracker:
    """Alternativa sem modelo: beats do librosa; tempo 1 = fase de 4 em 4 com mais ataque."""

    def track(self, path: Path) -> tuple[list[float], list[float]]:
        return self.track_signal(_load_audio(path))

    def track_signal(self, y: np.ndarray) -> tuple[list[float], list[float]]:
        import librosa

        env = librosa.onset.onset_strength(y=y, sr=_SR, hop_length=_HOP)
        _, frames = librosa.beat.beat_track(onset_envelope=env, sr=_SR, hop_length=_HOP,
                                            tightness=300)
        frames = np.asarray(frames, dtype=int)
        if len(frames) == 0:
            return [], []
        beats = librosa.frames_to_time(frames, sr=_SR, hop_length=_HOP)
        strength = env[np.clip(frames, 0, len(env) - 1)]
        best = max(range(min(4, len(beats))),
                   key=lambda ph: float(np.mean(strength[ph::4])))
        return [float(b) for b in beats], [float(b) for b in beats[best::4]]


class VocalSeparator(Protocol):
    def vocals(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """Stem de voz (mono, mesmo tamanho e taxa de `audio`)."""


class DemucsSeparator:
    """Demucs (htdemucs) na GPU se possível, senão CPU. Modelo carregado no primeiro uso."""

    def __init__(self, device: str = "cuda", model: str = "htdemucs"):
        self.device = device
        self.model_name = model
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        import torch
        from demucs.pretrained import get_model

        model = get_model(self.model_name)
        model.eval()
        if self.device != "cpu" and not torch.cuda.is_available():
            log.warning("GPU indisponível para separar a voz das trilhas; usando CPU (mais lento).")
            self.device = "cpu"
        try:
            model.to(self.device)
        except Exception as e:
            if self.device == "cpu":
                raise
            log.warning("Não foi possível usar a GPU para separar a voz (%s); usando CPU.", e)
            self.device = "cpu"
            model.to("cpu")
        self._model = model
        return model

    def _run(self, x, model):
        import torch
        from demucs.apply import apply_model

        mix = x.unsqueeze(0).repeat(model.audio_channels, 1)
        ref = mix.mean(0)
        mean, std = ref.mean(), ref.std()
        if float(std) < 1e-8:
            return torch.zeros_like(x)
        with torch.no_grad():
            out = apply_model(model, ((mix - mean) / std)[None], device=self.device, shifts=0,
                              split=True, overlap=0.25, progress=False)[0]
        out = out * std + mean
        return out[model.sources.index("vocals")].mean(0).cpu()

    def vocals(self, audio: np.ndarray, sr: int) -> np.ndarray:
        import torch
        import torchaudio

        model = self._load()
        x = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))
        if sr != model.samplerate:
            x = torchaudio.functional.resample(x, sr, model.samplerate)
        v = _executar_com_gpu(self, "separar a voz", lambda: self._run(x, model), model.to)
        if sr != model.samplerate:
            v = torchaudio.functional.resample(v, model.samplerate, sr)
        out = v.numpy().astype(np.float32)
        if len(out) < len(audio):
            out = np.pad(out, (0, len(audio) - len(out)))
        return out[:len(audio)]


def _default_separator() -> VocalSeparator | None:
    sep = DemucsSeparator()
    try:
        sep._load()
    except Exception as e:
        log.warning("Não foi possível carregar o separador de voz (Demucs): %s. A voz das trilhas "
                    "será estimada pelo método antigo, menos preciso (análise parcial).", e)
        return None
    return sep


class AudioTagger(Protocol):
    def scores(self, audio: np.ndarray, sr: int, rotulos: list[str]) -> list[float]:
        """Um score por rótulo (texto livre), maior = mais parecido com o áudio."""


def _carregar_processador_clap():
    from transformers import ClapProcessor

    return ClapProcessor.from_pretrained(CLAP_MODELO)


def _carregar_modelo_clap(revisao: str):
    from transformers import ClapModel

    return ClapModel.from_pretrained(CLAP_MODELO, revision=revisao, use_safetensors=True)


class ClapTagger:
    """CLAP zero-shot (transformers) em janelas de 10 s a 48 kHz, média das janelas.
    GPU se possível, senão CPU; modelo carregado no primeiro uso. O embedding do último
    áudio é reaproveitado entre as chamadas (clima, instrumentos e voz do mesmo trecho)."""

    def __init__(self, device: str = "cuda"):
        self.device = device
        self._model = None
        self._proc = None
        self._ultimo: tuple[np.ndarray, int, object] | None = None
        self._textos: dict[tuple[str, ...], object] = {}

    def _load(self):
        if self._model is not None:
            return self._model, self._proc
        import torch

        proc = _carregar_processador_clap()
        try:
            model = _carregar_modelo_clap(CLAP_REVISAO_PESOS)
        except Exception as e:
            log.warning("Revisão fixa do CLAP indisponível (%s); tentando %s.", e,
                        CLAP_REVISAO_ALTERNATIVA)
            model = _carregar_modelo_clap(CLAP_REVISAO_ALTERNATIVA)
        model.eval()
        if self.device != "cpu" and not torch.cuda.is_available():
            log.warning("GPU indisponível para o clima das trilhas (CLAP); usando CPU.")
            self.device = "cpu"
        try:
            model.to(self.device)
        except Exception as e:
            if self.device == "cpu":
                raise
            log.warning("Não foi possível usar a GPU para o CLAP (%s); usando CPU.", e)
            self.device = "cpu"
            model.to("cpu")
        self._model, self._proc = model, proc
        return model, proc

    def _audio_emb(self, audio: np.ndarray, sr: int):
        import torch
        import torchaudio

        if self._ultimo is not None and self._ultimo[0] is audio and self._ultimo[1] == sr:
            return self._ultimo[2]
        model, proc = self._load()
        x = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))
        if sr != CLAP_SR:
            x = torchaudio.functional.resample(x, sr, CLAP_SR)
        x = x.numpy()
        n = int(CLAP_JANELA_S * CLAP_SR)
        janelas = [x[i:i + n] for i in range(0, len(x), n) if len(x[i:i + n]) >= CLAP_SR]
        if not janelas:
            janelas = [x]
        entrada = proc(audio=janelas, sampling_rate=CLAP_SR, return_tensors="pt")

        def executar():
            with torch.no_grad():
                inp = {k: v.to(self.device) for k, v in entrada.items()}
                return torch.nn.functional.normalize(model.get_audio_features(**inp),
                                                     dim=-1).cpu()

        emb = _executar_com_gpu(self, "classificar o clima (CLAP)", executar, model.to)
        self._ultimo = (audio, sr, emb)
        return emb

    def _text_emb(self, rotulos: list[str]):
        import torch

        key = tuple(rotulos)
        if key not in self._textos:
            model, proc = self._load()
            entrada = proc(text=list(rotulos), return_tensors="pt", padding=True)

            def executar():
                with torch.no_grad():
                    inp = {k: v.to(self.device) for k, v in entrada.items()}
                    return torch.nn.functional.normalize(model.get_text_features(**inp),
                                                         dim=-1).cpu()

            self._textos[key] = _executar_com_gpu(self, "classificar o clima (CLAP)", executar,
                                                  model.to)
        return self._textos[key]

    def scores(self, audio: np.ndarray, sr: int, rotulos: list[str]) -> list[float]:
        import torch

        a = self._audio_emb(audio, sr)  # embeddings ficam na CPU (o dispositivo pode mudar)
        t = self._text_emb(rotulos)
        with torch.no_grad():
            # áudio → texto usa a escala do áudio (logits_per_audio no transformers)
            logits = a @ t.T * float(self._model.logit_scale_a.exp())
            probs = logits.softmax(dim=-1).mean(dim=0)
        return [float(p) for p in probs.cpu()]


def _default_tagger() -> AudioTagger | None:
    tg = ClapTagger()
    try:
        tg._load()
    except Exception as e:
        log.warning("Não foi possível carregar o modelo de clima das trilhas (CLAP): %s. Clima, "
                    "instrumentos e tipo de voz ficarão em branco (análise parcial).", e)
        return None
    return tg


def _load_audio(path: Path, sr: int = _SR) -> np.ndarray:
    import librosa

    try:
        y, _ = librosa.load(str(path), sr=sr, mono=True)
        return y
    except Exception:
        from .media.audio import load_mono

        return load_mono(Path(path), sr=sr)


def _default_tracker() -> BeatTracker:
    t = BeatThisTracker()
    try:
        t._load()
    except Exception as e:
        log.warning("Não foi possível carregar o modelo de tempos (beat_this): %s. "
                    "Usando o método alternativo (librosa), menos preciso.", e)
        return LibrosaTracker()
    return t


def _bpm(beats: list[float]) -> float:
    if len(beats) < 2:
        return 0.0
    return float(60.0 / np.median(np.diff(beats)))


def _energy_per_second(y: np.ndarray) -> list[float]:
    n = math.ceil(len(y) / _SR)
    out = []
    for i in range(n):
        seg = y[i * _SR:(i + 1) * _SR]
        out.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
    return out


def _perfil(bpm: float, energy: list[float]) -> str:
    if len(energy) >= 3:
        k = len(energy) // 3
        first, last = float(np.mean(energy[:k])), float(np.mean(energy[-k:]))
        if first > 0 and last > CRESCENDO_RATIO * first:
            return "crescente"
    mean = float(np.mean(energy)) if energy else 0.0
    if bpm >= INTENSE_BPM or mean >= INTENSE_RMS:
        return "intensa"
    return "calma"


def _has_vocals(y: np.ndarray) -> bool:
    import librosa

    if len(y) < 2048:
        return False
    n = VOCAL_EXCERPT_S * _SR
    if len(y) > n:
        mid = len(y) // 2
        y = y[mid - n // 2: mid + n // 2]
    harm = librosa.effects.harmonic(y)
    spec = np.abs(librosa.stft(harm, n_fft=2048)) ** 2
    freqs = librosa.fft_frequencies(sr=_SR, n_fft=2048)
    total = float(spec.sum())
    if total <= 0:
        return False
    band = (freqs >= VOCAL_BAND_HZ[0]) & (freqs <= VOCAL_BAND_HZ[1])
    return float(spec[band].sum()) / total >= VOCAL_RATIO


def trechos(duracao_s: float, energia: list[float]) -> list[tuple[str, float, float]]:
    """Trechos analisados pelos modelos: início (0–60 s), meio (20 s centrados em 50%) e
    clímax (20 s de maior energia RMS começando depois do início). Música curta: inteira."""
    duracao_s = float(duracao_s)
    if duracao_s < MUSICA_CURTA_S:
        return [("inteira", 0.0, duracao_s)]
    c = duracao_s / 2
    meio = ("meio", c - TRECHO_CURTO_S / 2, c + TRECHO_CURTO_S / 2)
    n = int(TRECHO_CURTO_S)
    starts = range(int(TRECHO_INICIO_S), int(math.floor(duracao_s - TRECHO_CURTO_S)) + 1)

    def media(s0: int) -> float:
        w = energia[s0:s0 + n]
        return float(np.mean(w)) if w else 0.0

    best = max(starts, key=lambda s0: (media(s0), -s0))
    return [("inicio", 0.0, TRECHO_INICIO_S), meio,
            ("climax", float(best), float(best) + TRECHO_CURTO_S)]


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def _voz_por_segundo(mix: np.ndarray, voz: np.ndarray, sr: int) -> list[bool]:
    out = []
    for i in range(math.ceil(len(mix) / sr)):
        m = _rms(mix[i * sr:(i + 1) * sr])
        out.append(m >= _SILENCIO_RMS and _rms(voz[i * sr:(i + 1) * sr]) / m >= VOZ_LIMIAR)
    return out


def analisar_voz(y: np.ndarray, sr: int, separator: VocalSeparator,
                 partes: list[tuple[str, float, float]]) -> tuple[float, float | None, float]:
    """(voz_proporcao, voz_inicio_s, intro_instrumental_s) separando só os `partes`."""
    total: list[bool] = []
    inicio: tuple[float, float, list[bool]] | None = None
    for nome, a, b in partes:
        seg = y[int(round(a * sr)):int(round(b * sr))]
        if len(seg) == 0:
            continue
        flags = _voz_por_segundo(seg, np.asarray(separator.vocals(seg, sr)), sr)
        total += flags
        if nome in ("inicio", "inteira"):
            inicio = (a, min(b, len(y) / sr), flags)
    prop = sum(total) / len(total) if total else 0.0
    if inicio is None:
        return prop, None, 0.0
    a, b, flags = inicio
    first = next((i for i, f in enumerate(flags) if f), None)
    if first is None:
        return prop, None, float(b)
    return prop, float(a + first), float(a + first)


def tonalidade(y: np.ndarray, sr: int) -> tuple[str, str]:
    """("Lá menor", "menor") pelo croma CQT médio + perfis de Krumhansl–Schmuckler.
    Sem conteúdo tonal (silêncio): ("", "")."""
    import librosa

    if len(y) < 2048 or _rms(y) < _SILENCIO_RMS:
        return "", ""
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=2048)
    perfil = chroma.mean(axis=1)
    if not np.isfinite(perfil).all() or float(np.std(perfil)) < 1e-6:
        return "", ""
    best = (-2.0, "", "")
    for modo, ref in (("maior", _PERFIL_MAIOR), ("menor", _PERFIL_MENOR)):
        for tonica in range(12):
            r = float(np.corrcoef(perfil, np.roll(ref, tonica))[0, 1])
            if r > best[0]:
                best = (r, f"{NOTAS[tonica]} {modo}", modo)
    return best[1], best[2]


def _top(tagger: AudioTagger, audio: np.ndarray, sr: int, rotulos: dict[str, str],
         prompt: str) -> list[str]:
    """Nomes em português ordenados pelo score (maior primeiro; empate na ordem da tabela)."""
    sc = tagger.scores(audio, sr, [prompt.format(r) for r in rotulos])
    ordem = sorted(range(len(rotulos)), key=lambda i: -float(sc[i]))
    nomes = list(rotulos.values())
    return [nomes[i] for i in ordem]


def classificar(audio: np.ndarray, sr: int, tagger: AudioTagger,
                has_vocals: bool) -> tuple[list[str], list[str], str]:
    """(climas top 3, instrumentos top 3, tipo de voz). Se a voz foi detectada, o tipo é o
    melhor entre os cantados (o CLAP não desmente o Demucs); sem voz → "sem voz"."""
    climas = _top(tagger, audio, sr, CLIMAS, "a {} song")[:3]
    instrumentos = _top(tagger, audio, sr, INSTRUMENTOS, "music with {}")[:3]
    vozes = _top(tagger, audio, sr, TIPO_VOZ, "music with {}")
    tipo = next((v for v in vozes if v != SEM_VOZ), SEM_VOZ) if has_vocals else SEM_VOZ
    return climas, instrumentos, tipo


def analyze_track(path: Path, tracker: BeatTracker | None = None,
                  separator: VocalSeparator | None = None, tagger: AudioTagger | None = None,
                  *, carregar_modelos: bool = True) -> TrackInfo:
    """Analisa uma trilha. Modelos ausentes (None) são carregados aqui, a menos que
    `carregar_modelos=False` (o update_index carrega uma vez e passa o que conseguiu)."""
    path = Path(path)
    if tracker is None:
        tracker = _default_tracker()
    if separator is None and carregar_modelos:
        separator = _default_separator()
    if tagger is None and carregar_modelos:
        tagger = _default_tagger()
    y = _load_audio(path)
    if isinstance(tracker, LibrosaTracker):
        beats, downbeats = tracker.track_signal(y)
    else:
        beats, downbeats = tracker.track(path)
    bpm = _bpm(beats)
    energy = _energy_per_second(y)
    duracao = len(y) / _SR
    partes = trechos(duracao, energy)
    y_hi = _load_audio(path, _SR_MODELOS) if separator is not None or tagger is not None else None
    voz = None
    if separator is not None:
        try:
            voz = analisar_voz(y_hi, _SR_MODELOS, separator, partes)
        except Exception as e:
            log.warning("Não foi possível separar a voz da trilha '%s' (%s); usando o método "
                        "antigo (análise parcial).", path.name, e)
    if voz is None:
        has_vocals = _has_vocals(y)
        prop, voz_inicio, intro = 0.0, None, 0.0
    else:
        prop, voz_inicio, intro = voz
        has_vocals = prop >= VOZ_MIN_PROPORCAO
    clap = None
    if tagger is not None:
        try:
            ouvir = np.concatenate([y_hi[int(round(a * _SR_MODELOS)):int(round(b * _SR_MODELOS))]
                                    for _, a, b in partes])
            clap = classificar(ouvir, _SR_MODELOS, tagger, has_vocals)
        except Exception as e:
            log.warning("Não foi possível classificar o clima da trilha '%s' (%s); "
                        "análise parcial.", path.name, e)
    climas, instrumentos, tipo_voz = clap or ([], [], "" if has_vocals else SEM_VOZ)
    nome_tom, modo = tonalidade(y, _SR)
    return TrackInfo(
        path=os.path.abspath(path), bpm=bpm, beats_s=beats, downbeats_s=downbeats,
        energy=energy, duration_s=duracao, has_vocals=has_vocals,
        perfil=_perfil(bpm, energy), mtime=path.stat().st_mtime,
        voz_proporcao=prop, voz_inicio_s=voz_inicio, intro_instrumental_s=intro,
        tonalidade=nome_tom, modo=modo, climas=climas, instrumentos=instrumentos,
        tipo_voz=tipo_voz,
        versao_analise=ANALISE_VERSAO, analise_parcial=voz is None or clap is None,
    )


def beat_positions(t: TrackInfo) -> list[tuple[float, int]]:
    """(tempo_s, nº 1-4) de cada beat, contando a partir do último tempo 1 (downbeat).

    Beats antes do primeiro downbeat são numerados para trás, mantendo o ciclo.
    """
    beats = t.beats_s
    if not beats:
        return []
    downs = sorted(t.downbeats_s)
    if not downs:
        return [(b, i % 4 + 1) for i, b in enumerate(beats)]
    d_idx = sorted({min(range(len(beats)), key=lambda i: abs(beats[i] - d)) for d in downs})
    out: list[tuple[float, int]] = []
    for i, b in enumerate(beats):
        if i < d_idx[0]:
            out.append((b, (i - d_idx[0]) % 4 + 1))
        else:
            last = d_idx[bisect.bisect_right(d_idx, i) - 1]
            out.append((b, (i - last) % 4 + 1))
    return out


class MusicIndex:
    def __init__(self, path: Path, s: Settings):
        path = Path(path)
        assert_writable(path, s)
        safe_mkdir(path.parent, s)
        self.path = path
        self._c = sqlite3.connect(str(path), check_same_thread=False)
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.execute("CREATE TABLE IF NOT EXISTS tracks("
                        "path TEXT PRIMARY KEY, mtime REAL NOT NULL, data TEXT NOT NULL)")
        self._c.commit()

    def close(self) -> None:
        self._c.close()

    def __enter__(self) -> "MusicIndex":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def upsert(self, t: TrackInfo) -> None:
        self._c.execute("INSERT INTO tracks(path, mtime, data) VALUES(?,?,?) "
                        "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, data=excluded.data",
                        (t.path, t.mtime, t.model_dump_json()))
        self._c.commit()

    def get(self, path: str) -> TrackInfo | None:
        r = self._c.execute("SELECT data FROM tracks WHERE path=?", (str(path),)).fetchone()
        return TrackInfo.model_validate_json(r[0]) if r else None

    def all(self) -> list[TrackInfo]:
        rows = self._c.execute("SELECT data FROM tracks ORDER BY path").fetchall()
        return [TrackInfo.model_validate_json(r[0]) for r in rows]

    def remove_missing(self, existing: set[str]) -> None:
        for (p,) in self._c.execute("SELECT path FROM tracks").fetchall():
            if p not in existing:
                self._c.execute("DELETE FROM tracks WHERE path=?", (p,))
        self._c.commit()


def analise_completa(t: TrackInfo) -> bool:
    return t.versao_analise >= ANALISE_VERSAO and not t.analise_parcial


def resumo_indice(idx: MusicIndex) -> tuple[int, int]:
    """(trilhas no índice, trilhas com análise completa)."""
    todas = idx.all()
    return len(todas), sum(analise_completa(t) for t in todas)


def update_index(s: Settings, idx: MusicIndex,
                 on_progress: Callable[[int, int, str], None] | None = None,
                 tracker: BeatTracker | None = None, separator: VocalSeparator | None = None,
                 tagger: AudioTagger | None = None, atualizar_versao: bool = True) -> int:
    """Varre music_root (somente leitura) e analisa só o que é novo, foi alterado, tem análise
    de versão antiga ou ficou parcial (quando os modelos agora carregam). Os modelos ausentes
    são carregados uma única vez por execução, e só se houver algo a analisar.

    `atualizar_versao=False` (etapa do pipeline): só arquivos novos ou alterados; registros
    antigos ou parciais ficam como estão (a reanálise da biblioteca leva horas e é feita pela
    aba Trilhas / `roteiro-ia trilhas`)."""
    try:
        return _update_index(s, idx, on_progress, tracker, separator, tagger, atualizar_versao)
    finally:
        _liberar_gpu()


def trilhas_antigas(idx: MusicIndex) -> int:
    """Quantas trilhas do índice têm análise de versão anterior à atual."""
    return sum(t.versao_analise < ANALISE_VERSAO for t in idx.all())


def _update_index(s, idx, on_progress, tracker, separator, tagger, atualizar_versao) -> int:
    root = Path(s.music_root)
    if not root.is_dir():
        raise FileNotFoundError(
            f"A pasta de músicas '{root}' não está acessível. Confira se o drive está conectado; "
            "o índice não foi alterado.")
    walk_errors: list[OSError] = []
    files: list[tuple[Path, str]] = []
    for dirpath, _dirs, names in os.walk(root, onerror=walk_errors.append):
        for n in names:
            if Path(n).suffix.lower() in AUDIO_EXTS:
                f = Path(dirpath) / n
                files.append((f, os.path.abspath(f)))
    existing = {key for _, key in files}
    done = 0
    tentou_modelos = False
    for i, (f, key) in enumerate(files, 1):
        if on_progress:
            on_progress(i, len(files), f.name)
        try:
            old = idx.get(key)
            inalterada = old is not None and old.mtime == f.stat().st_mtime
            if inalterada and not atualizar_versao:
                continue
            atual = inalterada and old.versao_analise >= ANALISE_VERSAO
            if atual and not old.analise_parcial:
                continue
            if not tentou_modelos:
                tentou_modelos = True
                if separator is None:
                    separator = _default_separator()
                if tagger is None:
                    tagger = _default_tagger()
            if atual and (separator is None or tagger is None):
                continue  # parcial e os modelos continuam indisponíveis
            if tracker is None:
                tracker = _default_tracker()
            idx.upsert(analyze_track(f, tracker, separator, tagger, carregar_modelos=False))
            done += 1
        except Exception as e:
            log.warning("Não foi possível analisar a trilha '%s': %s", f.name, e)
    if walk_errors:
        log.warning("Algumas pastas de músicas não puderam ser lidas (%d); "
                    "nenhuma trilha foi removida do índice.", len(walk_errors))
    elif not files and idx.all():
        log.warning("Nenhuma trilha encontrada na pasta de músicas; o índice foi mantido.")
    else:
        idx.remove_missing(existing)
    return done
