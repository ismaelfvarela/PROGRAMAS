from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from google.genai import errors
from pydantic import BaseModel

from roteiro_ia.config import Settings
from roteiro_ia.gemini import client as gc
from roteiro_ia.gemini.client import GeminiClient, QuotaPaused


class Out(BaseModel):
    ok: bool


def err429(msg="quota", delay="37s"):
    return errors.ClientError(429, {"error": {"code": 429, "message": msg, "status": "RESOURCE_EXHAUSTED",
        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}})


class FakeModels:
    def __init__(self, outcomes, names=()):
        self.outcomes = list(outcomes)
        self.calls = []
        self.names = names

    def generate_content(self, *, model, contents, config):
        self.calls.append((model, contents, config))
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return SimpleNamespace(text=o, parsed=None)

    def list(self):
        return [SimpleNamespace(name=n) for n in self.names]


class FakeFiles:
    def __init__(self, states):
        self.states = list(states)

    def upload(self, *, file, config=None):
        return SimpleNamespace(name="files/abc", state="PROCESSING", uri="u")

    def get(self, *, name, config=None):
        return SimpleNamespace(name=name, state=self.states.pop(0), uri="u")


def mk(outcomes, mode="gratis", names=(), files=None, price=0.0):
    s = Settings(gemini_mode=mode, price_usd_per_mtok=price)
    be = SimpleNamespace(models=FakeModels(outcomes, names), files=files)
    return GeminiClient(s, backend=be), be


def test_json_invalido_reenvia_e_desiste():
    c, be = mk(["x", "{", "nope"])
    with pytest.raises(ValueError):
        c.generate_json("m", [], Out, "p")
    assert len(be.models.calls) == 3


def test_json_valido_segunda_tentativa():
    c, be = mk(["x", '{"ok": true}'])
    assert c.generate_json("m", ["a"], Out, "p").ok is True
    assert len(be.models.calls) == 2
    assert be.models.calls[0][1][-1] == "p"
    assert be.models.calls[0][2].media_resolution is None


def test_media_resolution_low_com_video():
    c, be = mk(['{"ok": true}'])
    c.generate_json("m", [SimpleNamespace(uri="u", mime_type="video/mp4")], Out, "p")
    assert be.models.calls[0][2].media_resolution is not None


def test_429_gratis_pausa():
    c, _ = mk([err429()])
    with pytest.raises(QuotaPaused) as e:
        c.generate_json("m", [], Out, "p")
    assert e.value.resume_at > datetime.now(timezone.utc)
    assert e.value.resume_at.tzinfo is not None


def test_429_gratis_limite_diario():
    c, _ = mk([err429("Quota exceeded PerDay")])
    with pytest.raises(QuotaPaused) as e:
        c.generate_json("m", [], Out, "p")
    assert e.value.resume_at.astimezone(gc.LA).hour == 0


def test_429_pago_retenta(monkeypatch):
    sleeps = []
    monkeypatch.setattr(gc, "_sleep", sleeps.append)
    c, be = mk([err429(), '{"ok": true}'], mode="pago")
    assert c.generate_json("m", [], Out, "p").ok
    assert sleeps == [37]


def test_5xx_pago_esgota(monkeypatch):
    monkeypatch.setattr(gc, "_sleep", lambda s: None)
    e = errors.ServerError(503, {"error": {"code": 503, "message": "x"}})
    c, be = mk([e] * 10, mode="pago")
    with pytest.raises(errors.ServerError):
        c.generate_json("m", [], Out, "p")
    assert len(be.models.calls) == gc.MAX_TRANSPORT_RETRIES


def test_5xx_gratis_retenta(monkeypatch):
    sleeps = []
    monkeypatch.setattr(gc, "_sleep", sleeps.append)
    e = errors.ServerError(503, {"error": {"code": 503, "message": "overloaded"}})
    c, _ = mk([e, '{"ok": true}'], mode="gratis")
    assert c.generate_json("m", [], Out, "p").ok
    assert sleeps == [2]


def test_429_pago_respeita_retry_delay(monkeypatch):
    sleeps = []
    monkeypatch.setattr(gc, "_sleep", sleeps.append)
    c, _ = mk([err429(delay="37s"), err429(delay="120s"), '{"ok": true}'], mode="pago")
    assert c.generate_json("m", [], Out, "p").ok
    assert sleeps == [37, 60]


def test_estimate_cost():
    c, _ = mk([], mode="pago", price=0.3)
    assert c.estimate_cost_usd(12 * 3600) == pytest.approx(1.296)


def test_estimate_cost_gratis_zero():
    c, _ = mk([], mode="gratis", price=0.3)
    assert c.estimate_cost_usd(12 * 3600) == 0.0


def test_pick_default_models():
    names = ["models/gemini-1.5-flash", "models/gemini-x-flash", "models/gemini-2.5-flash",
             "models/gemini-2.5-flash-lite", "models/gemini-2.5-pro", "models/gemini-3.0-pro-preview",
             "models/gemini-3.0-pro", "models/gemini-2.5-flash-image", "models/gemini-2.5-flash-preview-tts"]
    c, _ = mk([], names=names)
    assert c.pick_default_models() == ("gemini-2.5-flash", "gemini-3.0-pro")


def test_pick_default_sem_modelo():
    c, _ = mk([], names=["models/embedding-001"])
    with pytest.raises(RuntimeError):
        c.pick_default_models()


def test_upload_espera_active(monkeypatch, tmp_path):
    monkeypatch.setattr(gc, "_sleep", lambda s: None)
    c, _ = mk([], files=FakeFiles(["PROCESSING", "ACTIVE"]))
    assert c.upload(tmp_path / "a.mp4").state == "ACTIVE"


def test_upload_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(gc, "_sleep", lambda s: None)
    c, _ = mk([], files=FakeFiles(["FAILED"]))
    with pytest.raises(RuntimeError):
        c.upload(tmp_path / "a.mp4")


def test_keyring(monkeypatch):
    store = {}
    monkeypatch.setattr(gc.keyring, "get_password", lambda s, u: store.get((s, u)))
    monkeypatch.setattr(gc.keyring, "set_password", lambda s, u, p: store.__setitem__((s, u), p))
    assert gc.get_api_key() is None
    gc.set_api_key("k")
    assert gc.get_api_key() == "k" and store[("RoteiroIA-Gemini", "api_key")] == "k"


def test_sem_chave(monkeypatch):
    monkeypatch.setattr(gc, "get_api_key", lambda: None)
    with pytest.raises(RuntimeError, match="Configurar chave"):
        GeminiClient(Settings())


@pytest.mark.gemini
def test_real_json_simples():
    if not gc.get_api_key():
        pytest.skip("sem chave Gemini configurada")
    s = Settings()
    c = GeminiClient(s)
    flash, _ = c.pick_default_models()
    assert c.generate_json(flash, [], Out, 'Responda {"ok": true}').ok is True


# ------------------------------------------------------------------ revisão final


def test_erro_de_transporte_retenta(monkeypatch):
    import httpx
    sleeps = []
    monkeypatch.setattr(gc, "_sleep", sleeps.append)
    c, be = mk([httpx.ConnectError("rede caiu"), httpx.ReadTimeout("lento"), ConnectionError("x"),
                '{"ok": true}'])
    assert c.generate_json("m", [], Out, "p").ok
    assert sleeps == [2, 4, 8] and len(be.models.calls) == 4


def test_erro_de_transporte_esgota(monkeypatch):
    import httpx
    monkeypatch.setattr(gc, "_sleep", lambda s: None)
    c, be = mk([httpx.ConnectError("rede")] * 10)
    with pytest.raises(httpx.ConnectError):
        c.generate_json("m", [], Out, "p")
    assert len(be.models.calls) == gc.MAX_TRANSPORT_RETRIES


def test_quota_diaria_marcada():
    c, _ = mk([err429("Quota exceeded PerDay")])
    with pytest.raises(QuotaPaused) as e:
        c.generate_json("m", [], Out, "p")
    assert e.value.daily is True
    c2, _ = mk([err429()])
    with pytest.raises(QuotaPaused) as e2:
        c2.generate_json("m", [], Out, "p")
    assert e2.value.daily is False


class FilesComErro:
    def __init__(self, first):
        self.first = list(first)
        self.deleted = []

    def upload(self, *, file, config=None):
        if self.first:
            raise self.first.pop(0)
        return SimpleNamespace(name="files/abc", state="ACTIVE", uri="u")

    def delete(self, *, name, config=None):
        self.deleted.append(name)
        raise RuntimeError("já apagado")


def test_upload_429_gratis_pausa(tmp_path):
    c, _ = mk([], files=FilesComErro([err429()]))
    with pytest.raises(QuotaPaused):
        c.upload(tmp_path / "a.mp4")


def test_upload_transporte_retenta(monkeypatch, tmp_path):
    import httpx
    monkeypatch.setattr(gc, "_sleep", lambda s: None)
    c, _ = mk([], files=FilesComErro([httpx.ConnectError("x")]))
    assert c.upload(tmp_path / "a.mp4").name == "files/abc"


def test_delete_file_ignora_erros():
    f = FilesComErro([])
    c, _ = mk([], files=f)
    c.delete_file(SimpleNamespace(name="files/abc"))
    assert f.deleted == ["files/abc"]
    c.delete_file("sem nome")  # nada a apagar, sem erro


def test_count_tokens():
    class M(FakeModels):
        def count_tokens(self, *, model, contents, config=None):
            self.calls.append((model, contents))
            return SimpleNamespace(total_tokens=1234)
    s = Settings()
    be = SimpleNamespace(models=M([]), files=None)
    c = GeminiClient(s, backend=be)
    assert c.count_tokens("pro", "texto") == 1234
    assert be.models.calls == [("pro", "texto")]
