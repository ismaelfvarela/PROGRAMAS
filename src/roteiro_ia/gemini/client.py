"""Cliente Gemini: cota, retentativas, JSON validado e chave no Credential Manager."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import keyring
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from roteiro_ia import controle
from roteiro_ia.config import Settings
from roteiro_ia.safety import assert_writable, safe_mkdir, safe_write_text

log = logging.getLogger(__name__)
KEYRING_SERVICE = "RoteiroIA-Gemini"
_KEYRING_USER = "api_key"
PRIVACY_NOTICE_PT = (
    "No plano gratuito, o Google pode usar o conteúdo enviado para melhorar seus produtos. "
    "Use eventos com autorização ou o plano pago para clientes novos."
)
LA = ZoneInfo("America/Los_Angeles")
TOKENS_PER_SECOND = 100
_sleep = controle.dormir  # patchável nos testes; o Parar interrompe a espera
_POLL_S = 2.0
_UPLOAD_TIMEOUT_S = 600.0
# por requisição HTTP: sem isso uma conexão que para de responder trava a etapa para sempre
# (o padrão do google-genai é esperar sem limite); estourado, vira erro de rede e é tentado de novo
HTTP_TIMEOUT_MS = 10 * 60 * 1000
MAX_TRANSPORT_RETRIES = 5
_EXCLUDE = ("lite", "image", "tts", "live", "audio", "embedding", "thinking-exp")
# candidatos do revezamento no grátis: gemini-<versão>-flash e -flash-lite (sem variantes)
_FLASH = re.compile(r"gemini-(\d+(?:\.\d+)?)-flash(-lite)?(?:-\d{3})?")
_ROTATION_EXCLUDE = ("image", "tts", "live", "audio", "embedding", "preview", "exp")
# respostas que o modelo "lite" faz mal (o roteiro do Nicole e Osny saiu com episódios de 1 min
# prometendo 6): sem um flash completo com cota, espera a cota voltar em vez de usar o lite
_SEM_LITE = {"Roteiro"}
COTA_FILE = "cota.json"
DAILY_MIN_WAIT_S = 3600  # piso da espera diária informada pelo retryDelay


def get_api_key() -> str | None:
    return keyring.get_password(KEYRING_SERVICE, _KEYRING_USER)


def set_api_key(k: str) -> None:
    keyring.set_password(KEYRING_SERVICE, _KEYRING_USER, k)


class QuotaPaused(Exception):
    def __init__(self, resume_at: datetime, message: str = "", daily: bool = False):
        self.resume_at = resume_at
        self.daily = daily  # limite diário (True) ou por minuto (False)
        super().__init__(message or f"Cota do Gemini esgotada; retomar em {resume_at:%d/%m/%Y %H:%M}.")


def _is_quota(e: Exception) -> bool:
    return isinstance(e, errors.APIError) and (
        e.code == 429 or getattr(e, "status", None) == "RESOURCE_EXHAUSTED"
    )


def _is_retirado(e: Exception) -> bool:
    """404 do modelo (ex.: "gemini-2.5-flash is no longer available to new users"): o modelo
    aparece na lista da chave mas não atende; no revezamento, sai como os de limite 0."""
    return isinstance(e, errors.APIError) and e.code == 404


def _is_server(e: Exception) -> bool:
    return isinstance(e, errors.APIError) and isinstance(e.code, int) and 500 <= e.code < 600


def _is_transport(e: Exception) -> bool:
    """Queda de rede/timeout: tentada de novo com o mesmo backoff do 5xx."""
    return isinstance(e, (httpx.TransportError, ConnectionError, TimeoutError))


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


def _find_violations(obj) -> list[dict]:
    """Violações de `google.rpc.QuotaFailure` (os limites efetivamente estourados)."""
    out: list[dict] = []
    if isinstance(obj, dict):
        if str(obj.get("@type", "")).endswith("QuotaFailure"):
            out += [v for v in obj.get("violations") or [] if isinstance(v, dict)]
        else:
            for v in obj.values():
                out += _find_violations(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _find_violations(v)
    return out


def _has_retry_info(e: errors.APIError) -> bool:
    return _find_retry_info(getattr(e, "details", None)) is not None


def _quota_kind(e: errors.APIError) -> str:
    """Classifica um 429 pelo limite VIOLADO: "zero" (modelo sem cota no grátis), "diario",
    "minuto". Sem QuotaFailure.violations, usa a regra antiga (texto do erro)."""
    viol = _find_violations(getattr(e, "details", None))
    msg = str(getattr(e, "message", "") or "")
    if any(str(v.get("quotaValue", "")).strip() == "0" for v in viol) or re.search(r"\blimit:\s*0\b", msg):
        return "zero"
    ids = [str(v.get("quotaId", "")) for v in viol]
    if any("PerDay" in q for q in ids):
        return "diario"
    if any("PerMinute" in q for q in ids):
        return "minuto"
    return "diario" if _is_daily(e) else "minuto"


def _next_midnight_la(now: datetime) -> datetime:
    return (now.astimezone(LA) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


class _ModelQuota(Exception):
    """Interno: o modelo da chamada esgotou a cota do dia ("diario") ou não tem cota ("zero")."""

    def __init__(self, kind: str, resume_at: datetime | None):
        self.kind, self.resume_at = kind, resume_at
        super().__init__(kind)


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
            backend = genai.Client(api_key=key,
                                   http_options=types.HttpOptions(timeout=HTTP_TIMEOUT_MS))
        self.backend = backend
        self._names: list[str] | None = None
        self._esgotados: dict[str, datetime] = {}  # modelo -> retomar em (cota diária)
        self._indisponiveis: set[str] = set()      # limite 0 no grátis: fora do revezamento

    def list_models(self) -> list[str]:
        return [m.name.removeprefix("models/") for m in self.backend.models.list()]

    # ------------------------------------------------------------ revezamento (grátis)
    def _rotating(self) -> bool:
        return self.s.gemini_mode == "gratis" and self.s.gemini_rotacao

    def _model_names(self) -> list[str]:
        if self._names is None:
            try:
                self._names = self.list_models()
            except Exception as e:  # noqa: BLE001 - sem lista, reveza só com o configurado
                log.warning("Não foi possível listar os modelos do Gemini: %s", e)
                return []
        return self._names

    def candidatos(self, model: str, sem_lite: bool = False) -> list[str]:
        """O modelo configurado primeiro; depois os gemini-<versão>-flash/-flash-lite da chave,
        por versão decrescente (flash antes de flash-lite). `sem_lite`: só os flash completos."""
        flash = []
        for n in self._model_names():
            m = _FLASH.fullmatch(n)
            if m and not any(x in n for x in _ROTATION_EXCLUDE) and not (sem_lite and m.group(2)):
                flash.append((-float(m.group(1)), bool(m.group(2)), n))
        out = [model]
        for *_k, n in sorted(flash):
            if n not in out:
                out.append(n)
        return out

    def _cota_path(self) -> Path:
        return Path(self.s.system_dir) / COTA_FILE

    def _load_cota(self) -> None:
        """Junta o cota.json (outras execuções/janelas) ao estado em memória."""
        try:
            data = json.loads(self._cota_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for name, iso in (data.get("esgotados") or {}).items():
            try:
                when = datetime.fromisoformat(str(iso))
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=LA)
            if name not in self._esgotados or when > self._esgotados[name]:
                self._esgotados[name] = when
        self._indisponiveis |= {str(n) for n in data.get("indisponiveis") or []}

    def _save_cota(self) -> None:
        """Relê e junta o arquivo (outra janela pode ter gravado) e grava de forma atômica."""
        self._load_cota()
        now = datetime.now(LA)
        data = {"esgotados": {n: w.isoformat() for n, w in sorted(self._esgotados.items()) if w > now},
                "indisponiveis": sorted(self._indisponiveis)}
        path = self._cota_path()
        part = path.with_name(path.name + ".part")
        try:
            safe_mkdir(path.parent, self.s)
            safe_write_text(part, json.dumps(data, ensure_ascii=False, indent=2), self.s)
            assert_writable(path, self.s)
            os.replace(part, path)
        except Exception as e:  # noqa: BLE001 - só memória: vale nesta execução
            log.warning("Não foi possível gravar %s: %s", path, e)
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass

    def _livre(self, name: str, now: datetime) -> bool:
        if name in self._indisponiveis:
            return False
        w = self._esgotados.get(name)
        return w is None or w <= now

    def pick_default_models(self) -> tuple[str, str]:
        names = self.list_models()

        def best(key: str) -> str:
            cands = [n for n in names if key in n and not any(x in n for x in _EXCLUDE)]
            if not cands:
                raise RuntimeError(f"Nenhum modelo '{key}' do Gemini disponível para esta chave.")
            return max(cands, key=lambda n: (_version(n), not ("preview" in n or "exp" in n)))

        if self.s.gemini_mode == "gratis":  # Pro tem limite 0 no grátis: flash para os dois
            f = best("flash")
            return f, f
        return best("flash"), best("pro")

    def upload(self, path: Path):
        f = self._retrying(lambda: self.backend.files.upload(file=str(path)))
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

    def delete_file(self, f) -> None:
        """Apaga do Gemini um arquivo enviado; erros são ignorados (ele expira sozinho em 48 h)."""
        name = getattr(f, "name", None)
        if not name:
            return
        try:
            self.backend.files.delete(name=name)
        except Exception:  # noqa: BLE001
            pass

    def count_tokens(self, model: str, text: str) -> int:
        resp = self._retrying(lambda: self.backend.models.count_tokens(model=model, contents=text))
        return int(getattr(resp, "total_tokens", 0) or 0)

    def _retrying(self, fn, rotate: bool = False):
        """Executa `fn` com retentativas de transporte (429 pago / 5xx / rede), no máximo
        MAX_TRANSPORT_RETRIES chamadas; esgotado, relança o erro. 429 no modo grátis → QuotaPaused
        (com `rotate`, cota diária ou limite 0 do modelo → _ModelQuota, para tentar o próximo)."""
        attempts = 0
        while True:
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                if rotate and _is_retirado(e):
                    raise _ModelQuota("zero", None) from e
                quota = _is_quota(e)
                if not quota and not _is_server(e) and not _is_transport(e):
                    raise
                if quota and self.s.gemini_mode == "gratis":
                    now = datetime.now(LA)
                    kind = _quota_kind(e)
                    if kind == "zero":
                        if rotate:
                            raise _ModelQuota("zero", None) from e
                        raise RuntimeError(
                            "O modelo do Gemini escolhido não tem cota no plano gratuito (limite 0). "
                            "Ative o revezamento de modelos ou escolha um modelo flash.") from e
                    if kind == "diario":
                        # com QuotaFailure + RetryInfo, a espera informada (mín. 1 h); senão
                        # 00:00 (Pacífico)
                        if _find_violations(getattr(e, "details", None)) and _has_retry_info(e):
                            resume = now + timedelta(seconds=max(_retry_delay_s(e), DAILY_MIN_WAIT_S))
                        else:
                            resume = _next_midnight_la(now)
                        if rotate:
                            raise _ModelQuota("diario", resume) from e
                        raise QuotaPaused(resume, daily=True) from e
                    raise QuotaPaused(now + timedelta(seconds=_retry_delay_s(e)), daily=False) from e
                attempts += 1
                if attempts >= MAX_TRANSPORT_RETRIES:
                    raise
                wait = float(2**attempts)
                if quota:
                    wait = max(wait, _retry_delay_s(e))
                _sleep(min(wait, 60.0))

    def _gen(self, model: str, contents: list, config, rotate: bool = False):
        log.info("Gemini: chamando o modelo %s", model)
        return self._retrying(
            lambda: self.backend.models.generate_content(model=model, contents=contents, config=config),
            rotate=rotate)

    def _call(self, model: str, contents: list, config, sem_lite: bool = False):
        if not self._rotating():
            return self._gen(model, contents, config)
        self._load_cota()
        tentados: set[str] = set()
        while True:
            now = datetime.now(LA)
            cands = self.candidatos(model, sem_lite)
            livres = [n for n in cands if n not in tentados and self._livre(n, now)]
            if not livres:
                raise self._sem_modelo(cands, now)
            atual = livres[0]
            tentados.add(atual)
            try:
                return self._gen(atual, contents, config, rotate=True)
            except _ModelQuota as q:
                if q.kind == "zero":
                    self._indisponiveis.add(atual)
                    log.warning("Modelo %s sem cota no plano gratuito ou indisponível para esta "
                                "chave; fora do revezamento.", atual)
                else:
                    self._esgotados[atual] = q.resume_at
                    log.warning("Cota diária do modelo %s esgotada até %s; tentando o próximo.",
                                atual, q.resume_at.astimezone().strftime("%d/%m %H:%M"))
                self._save_cota()

    def _sem_modelo(self, cands: list[str], now: datetime) -> Exception:
        esperas = [self._esgotados[n] for n in cands
                   if n not in self._indisponiveis and n in self._esgotados and self._esgotados[n] > now]
        if esperas:
            return QuotaPaused(min(esperas), daily=True)
        return RuntimeError("Nenhum modelo do Gemini com cota no plano gratuito para esta chave "
                            "(todos com limite 0). Use o plano pago ou outra chave.")

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
            resp = self._call(model, contents, config, sem_lite=schema.__name__ in _SEM_LITE)
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
