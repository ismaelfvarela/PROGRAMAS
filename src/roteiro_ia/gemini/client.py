"""Cliente Gemini: cota, retentativas, JSON validado e chave no Credential Manager."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import keyring
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from roteiro_ia.config import Settings

KEYRING_SERVICE = "RoteiroIA-Gemini"
_KEYRING_USER = "api_key"
PRIVACY_NOTICE_PT = (
    "No plano gratuito, o Google pode usar o conteúdo enviado para melhorar seus produtos. "
    "Use eventos com autorização ou o plano pago para clientes novos."
)
LA = ZoneInfo("America/Los_Angeles")
TOKENS_PER_SECOND = 100
_sleep = time.sleep
_POLL_S = 2.0
_UPLOAD_TIMEOUT_S = 600.0
MAX_TRANSPORT_RETRIES = 5
_EXCLUDE = ("lite", "image", "tts", "live", "audio", "embedding", "thinking-exp")


def get_api_key() -> str | None:
    return keyring.get_password(KEYRING_SERVICE, _KEYRING_USER)


def set_api_key(k: str) -> None:
    keyring.set_password(KEYRING_SERVICE, _KEYRING_USER, k)


class QuotaPaused(Exception):
    def __init__(self, resume_at: datetime, message: str = ""):
        self.resume_at = resume_at
        super().__init__(message or f"Cota do Gemini esgotada; retomar em {resume_at:%d/%m/%Y %H:%M}.")


def _is_quota(e: Exception) -> bool:
    return isinstance(e, errors.APIError) and (
        e.code == 429 or getattr(e, "status", None) == "RESOURCE_EXHAUSTED"
    )


def _is_server(e: Exception) -> bool:
    return isinstance(e, errors.APIError) and isinstance(e.code, int) and 500 <= e.code < 600


def _find_retry_info(obj) -> float | None:
    if isinstance(obj, dict):
        if str(obj.get("@type", "")).endswith("RetryInfo") and "retryDelay" in obj:
            m = re.match(r"([\d.]+)", str(obj["retryDelay"]))
            if m:
                return float(m.group(1))
        for v in obj.values():
            r = _find_retry_info(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_retry_info(v)
            if r is not None:
                return r
    return None


def _retry_delay_s(e: errors.APIError) -> float:
    d = getattr(e, "details", None)
    r = _find_retry_info(d)
    if r is not None:
        return r
    m = re.search(r'retryDelay\W+([\d.]+)s', str(d))
    return float(m.group(1)) if m else 60.0


def _is_daily(e: errors.APIError) -> bool:
    text = f"{getattr(e, 'message', '')} {getattr(e, 'details', '')}".lower()
    return any(k in text for k in ("perday", "per day", "daily"))


def _version(name: str) -> float:
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def _is_file_part(p) -> bool:
    if isinstance(p, str):
        return False
    uri = getattr(p, "uri", None) or getattr(getattr(p, "file_data", None), "file_uri", None)
    mime = getattr(p, "mime_type", None) or getattr(getattr(p, "file_data", None), "mime_type", None) or ""
    return bool(uri) or str(mime).startswith("video/")


class GeminiClient:
    def __init__(self, s: Settings, backend=None):
        self.s = s
        if backend is None:
            key = get_api_key()
            if not key:
                raise RuntimeError(
                    "Chave do Gemini não configurada. Use 'Configurar chave' para informar sua chave de API."
                )
            backend = genai.Client(api_key=key)
        self.backend = backend

    def list_models(self) -> list[str]:
        return [m.name.removeprefix("models/") for m in self.backend.models.list()]

    def pick_default_models(self) -> tuple[str, str]:
        names = self.list_models()

        def best(key: str) -> str:
            cands = [n for n in names if key in n and not any(x in n for x in _EXCLUDE)]
            if not cands:
                raise RuntimeError(f"Nenhum modelo '{key}' do Gemini disponível para esta chave.")
            return max(cands, key=lambda n: (_version(n), not ("preview" in n or "exp" in n)))

        return best("flash"), best("pro")

    def upload(self, path: Path):
        f = self.backend.files.upload(file=str(path))
        waited = 0.0
        while str(getattr(f.state, "name", f.state)) != "ACTIVE":
            if str(getattr(f.state, "name", f.state)) == "FAILED":
                raise RuntimeError(f"O Gemini falhou ao processar o arquivo {Path(path).name}.")
            if waited >= _UPLOAD_TIMEOUT_S:
                raise RuntimeError(f"Tempo esgotado (10 min) aguardando o Gemini processar {Path(path).name}.")
            _sleep(_POLL_S)
            waited += _POLL_S
            f = self.backend.files.get(name=f.name)
        return f

    def _call(self, model: str, contents: list, config):
        """Uma chamada ao backend com retentativas de transporte (429 pago / 5xx), no máximo
        MAX_TRANSPORT_RETRIES chamadas; esgotado, relança o erro."""
        attempts = 0
        while True:
            try:
                return self.backend.models.generate_content(model=model, contents=contents, config=config)
            except Exception as e:  # noqa: BLE001
                quota = _is_quota(e)
                if not quota and not _is_server(e):
                    raise
                if quota and self.s.gemini_mode == "gratis":
                    now = datetime.now(LA)
                    if _is_daily(e):
                        resume = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                    else:
                        resume = now + timedelta(seconds=_retry_delay_s(e))
                    raise QuotaPaused(resume) from e
                attempts += 1
                if attempts >= MAX_TRANSPORT_RETRIES:
                    raise
                wait = float(2**attempts)
                if quota:
                    wait = max(wait, _retry_delay_s(e))
                _sleep(min(wait, 60.0))

    def generate_json(self, model: str, parts: list, schema: type[BaseModel], prompt: str,
                      max_retries: int = 3) -> BaseModel:
        """Dois limites independentes: `max_retries` = tentativas por JSON inválido;
        MAX_TRANSPORT_RETRIES (5) = chamadas por erro 5xx/429(pago) dentro de cada tentativa.
        Esgotar o transporte levanta o erro na hora, sem multiplicar com as de JSON."""
        cfg = dict(response_mime_type="application/json", response_schema=schema)
        if any(_is_file_part(p) for p in parts):
            cfg["media_resolution"] = types.MediaResolution.MEDIA_RESOLUTION_LOW
        config = types.GenerateContentConfig(**cfg)
        contents = [*parts, prompt]
        last = ""
        for _ in range(max_retries):
            resp = self._call(model, contents, config)
            parsed = getattr(resp, "parsed", None)
            if isinstance(parsed, schema):
                return parsed
            try:
                return schema.model_validate_json(resp.text or "")
            except ValidationError as e:
                last = str(e)
        raise ValueError(f"O Gemini não devolveu JSON válido após {max_retries} tentativas: {last}")

    def estimate_cost_usd(self, total_media_s: float) -> float:
        if self.s.gemini_mode != "pago":
            return 0.0
        return total_media_s * TOKENS_PER_SECOND / 1e6 * self.s.price_usd_per_mtok
