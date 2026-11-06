import json
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


SYS = {}


@pytest.fixture(autouse=True)
def _system_dir_tmp(tmp_path):
    """O cliente grava cota.json no system_dir: nos testes, sempre numa pasta temporária."""
    SYS["dir"] = str(tmp_path / "sys")
    yield
    SYS.clear()


def mk(outcomes, mode="gratis", names=(), files=None, price=0.0, rotacao=True):
    s = Settings(gemini_mode=mode, price_usd_per_mtok=price, system_dir=SYS["dir"],
                 gemini_rotacao=rotacao, protected_roots=[])
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
    c, _ = mk([], names=names, mode="pago")
    assert c.pick_default_models() == ("gemini-2.5-flash", "gemini-3.0-pro")
    c2, _ = mk([], names=names, mode="gratis")  # Pro tem limite 0 no grátis
    assert c2.pick_default_models() == ("gemini-2.5-flash", "gemini-2.5-flash")


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
    s = Settings(system_dir=SYS["dir"], protected_roots=[])
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
    with pytest.raises(QuotaPaused) as e2:  # outro modelo: "m" ficou esgotado no cota.json
        c2.generate_json("m2", [], Out, "p")
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


# ------------------------------------------------------------------ revezamento no grátis


NOMES = ["models/gemini-3.6-flash", "models/gemini-3.5-flash", "models/gemini-3.6-flash-lite",
         "models/gemini-3.6-pro", "models/gemini-3.6-flash-image", "models/gemini-3.6-flash-preview-tts",
         "models/gemini-3.6-flash-live", "models/gemini-embedding-001", "models/gemini-3.7-flash-preview"]


def err429v(quota_id, value="20", model="gemini-3.6-flash", delay="20731s"):
    """Formato real (google-genai 2.34.0): details = o JSON inteiro da resposta."""
    return errors.ClientError(429, {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED",
        "message": f"You exceeded your current quota. Quota exceeded for metric: "
                   f"generativelanguage.googleapis.com/generate_content_free_tier_requests, "
                   f"limit: {value}, model: {model}. Please retry in 20731.5s.",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
                "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                "quotaId": quota_id,
                "quotaDimensions": {"location": "global", "model": model},
                "quotaValue": value}]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}})


DIA = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
MINUTO = "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"


def modelos(be):
    return [x[0] for x in be.models.calls]


def test_candidatos_do_revezamento():
    c, _ = mk([], names=NOMES)
    assert c.candidatos("gemini-3.6-flash") == ["gemini-3.6-flash", "gemini-3.6-flash-lite",
                                                "gemini-3.5-flash"]
    # o configurado vem primeiro, mesmo que seja Pro
    assert c.candidatos("gemini-3.6-pro")[:2] == ["gemini-3.6-pro", "gemini-3.6-flash"]


def test_per_day_no_modelo_a_usa_b_sem_pausa(tmp_path):
    c, be = mk([err429v(DIA), '{"ok": true}'], names=NOMES)
    assert c.generate_json("gemini-3.6-flash", [], Out, "p").ok
    assert modelos(be) == ["gemini-3.6-flash", "gemini-3.6-flash-lite"]
    # a próxima chamada já começa pelo B
    be.models.outcomes.append('{"ok": true}')
    c.generate_json("gemini-3.6-flash", [], Out, "p")
    assert modelos(be)[-1] == "gemini-3.6-flash-lite"
    dados = json.loads((tmp_path / "sys" / "cota.json").read_text(encoding="utf-8"))
    assert "gemini-3.6-flash" in dados["esgotados"]


def test_todos_esgotados_pausa_com_o_menor_resume_at():
    c, be = mk([err429v(DIA, delay="7300s"), err429v(DIA, delay="5000s"), err429v(DIA, delay="9000s")],
               names=NOMES)
    antes = datetime.now(timezone.utc)
    with pytest.raises(QuotaPaused) as e:
        c.generate_json("gemini-3.6-flash", [], Out, "p")
    assert e.value.daily is True and len(be.models.calls) == 3
    delta = (e.value.resume_at - antes).total_seconds()
    assert 4999 <= delta <= 5010
    # tudo esgotado: nem chama a API de novo
    with pytest.raises(QuotaPaused):
        c.generate_json("gemini-3.6-flash", [], Out, "p")
    assert len(be.models.calls) == 3


def test_limite_zero_exclui_sem_pausa(tmp_path):
    c, be = mk([err429v(DIA, value="0", model="gemini-3.6-pro"), '{"ok": true}', '{"ok": true}'],
               names=NOMES)
    assert c.generate_json("gemini-3.6-pro", [], Out, "p").ok
    assert modelos(be) == ["gemini-3.6-pro", "gemini-3.6-flash"]
    c.generate_json("gemini-3.6-pro", [], Out, "p")
    assert modelos(be)[-1] == "gemini-3.6-flash"  # o Pro não volta ao revezamento
    dados = json.loads((tmp_path / "sys" / "cota.json").read_text(encoding="utf-8"))
    assert dados["indisponiveis"] == ["gemini-3.6-pro"] and dados["esgotados"] == {}


def test_per_minute_mantem_comportamento_atual():
    c, be = mk([err429v(MINUTO, value="5", delay="40s")], names=NOMES)
    antes = datetime.now(timezone.utc)
    with pytest.raises(QuotaPaused) as e:
        c.generate_json("gemini-3.6-flash", [], Out, "p")
    assert e.value.daily is False and len(be.models.calls) == 1
    assert 39 <= (e.value.resume_at - antes).total_seconds() <= 50


def test_violacao_vale_mais_que_o_texto():
    # a mensagem cita "per day", mas o quotaId violado é por minuto
    e = err429v(MINUTO, delay="30s")
    e.details["error"]["message"] += " (see per day limits)"
    c, be = mk([e], names=NOMES)
    with pytest.raises(QuotaPaused) as ex:
        c.generate_json("gemini-3.6-flash", [], Out, "p")
    assert ex.value.daily is False


def test_cota_json_lido_em_novo_cliente():
    c, be = mk([err429v(DIA), '{"ok": true}'], names=NOMES)
    c.generate_json("gemini-3.6-flash", [], Out, "p")
    c2, be2 = mk(['{"ok": true}'], names=NOMES)
    c2.generate_json("gemini-3.6-flash", [], Out, "p")
    assert modelos(be2) == ["gemini-3.6-flash-lite"]


def test_esgotado_vencido_volta(tmp_path):
    from datetime import timedelta
    (tmp_path / "sys").mkdir()
    passado = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    (tmp_path / "sys" / "cota.json").write_text(
        json.dumps({"esgotados": {"gemini-3.6-flash": passado}, "indisponiveis": []}), encoding="utf-8")
    c, be = mk(['{"ok": true}'], names=NOMES)
    c.generate_json("gemini-3.6-flash", [], Out, "p")
    assert modelos(be) == ["gemini-3.6-flash"]


def test_sem_rotacao_per_day_pausa_na_hora():
    c, be = mk([err429v(DIA)], names=NOMES, rotacao=False)
    with pytest.raises(QuotaPaused) as e:
        c.generate_json("gemini-3.6-flash", [], Out, "p")
    assert e.value.daily is True and len(be.models.calls) == 1


def test_pago_nao_reveza(monkeypatch):
    monkeypatch.setattr(gc, "_sleep", lambda s: None)
    c, be = mk([err429v(DIA, delay="1s"), '{"ok": true}'], names=NOMES, mode="pago")
    assert c.generate_json("gemini-3.6-flash", [], Out, "p").ok
    assert modelos(be) == ["gemini-3.6-flash", "gemini-3.6-flash"]


def test_modelo_usado_vai_para_o_log(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="roteiro_ia")
    c, be = mk([err429v(DIA), '{"ok": true}'], names=NOMES)
    c.generate_json("gemini-3.6-flash", [], Out, "p")
    usados = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("gemini-3.6-flash-lite" in m for m in usados)



# ------------------------------------------------------------------ revisão 1


def test_retry_delay_diario_tem_piso_de_1h():
    from datetime import timedelta
    c, be = mk([err429v(DIA, delay="100s")], names=["models/gemini-3.6-flash"])
    antes = datetime.now(timezone.utc)
    with pytest.raises(QuotaPaused) as e:
        c.generate_json("gemini-3.6-flash", [], Out, "p")
    assert e.value.resume_at - antes >= timedelta(hours=1) - timedelta(seconds=1)


def test_save_cota_junta_o_que_outra_janela_gravou(tmp_path):
    from datetime import timedelta
    c2, _ = mk([], names=NOMES)
    c2._esgotados["gemini-3.5-flash"] = datetime.now(timezone.utc) + timedelta(hours=3)
    # outra janela gravou depois que c2 leu o arquivo
    (tmp_path / "sys").mkdir()
    outro = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    (tmp_path / "sys" / "cota.json").write_text(json.dumps(
        {"esgotados": {"gemini-3.6-flash": outro}, "indisponiveis": ["gemini-3.6-pro"]}), encoding="utf-8")
    c2._save_cota()
    dados = json.loads((tmp_path / "sys" / "cota.json").read_text(encoding="utf-8"))
    assert set(dados["esgotados"]) == {"gemini-3.6-flash", "gemini-3.5-flash"}
    assert dados["indisponiveis"] == ["gemini-3.6-pro"]
    assert not list((tmp_path / "sys").glob("*.part"))  # escrita atômica, sem sobras
