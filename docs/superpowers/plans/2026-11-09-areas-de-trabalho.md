# Áreas de trabalho (Casamento | Formatura) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separar o Roteiro IA em áreas de trabalho (Casamento | Formatura) com seletor no topo, recentes e estilos por área, pasta de músicas por projeto e fila de projetos no mesmo PC, sem mudar o comportamento do Casamento.

**Architecture:** Novo pacote `roteiro_ia/areas/` descreve cada área (formulário, se pode iniciar). A janela ganha um `QStackedWidget` com uma página de abas por área; Trilhas e Configurações são instâncias únicas que mudam de página. Uma `FilaProjetos` única decide qual `ProjetoTab` roda. Código compartilhado ganha parâmetros novos sempre com padrão igual ao comportamento atual.

**Tech Stack:** Python 3.12, PySide6, pydantic, pytest + pytest-qt (`uv run pytest`).

**Spec:** `docs/superpowers/specs/2026-11-09-areas-de-trabalho-design.md`

## Global Constraints

- O Casamento não muda de comportamento. **Todos os testes atuais passam sem alteração** (só se acrescentam testes; nenhum teste existente é editado).
- Todo parâmetro novo em código compartilhado tem valor padrão que reproduz o comportamento de hoje (`area="casamento"`, `root=None`, `pasta_musicas=None`).
- Nomes de evento sempre `AAAA-MM-DD NOME` (validação atual de `paths.parse_event_name`, nas duas áreas).
- Textos da interface em português, no tom atual. Textos fixos:
  - aviso da Formatura: `"A Formatura chega na próxima etapa."`
  - espera na fila: `"Na fila — começa quando {nome} terminar."`
  - botão: `"Tirar da fila"`
  - projeto de outra área: `"Este projeto é de {Nome da área}. Abra pela área {Nome da área}."`
- Áreas e ids: `casamento` ("Casamento"), `formatura` ("Formatura"), nessa ordem.
- Rodar testes: `uv run pytest -q` (o `addopts` já exclui `gemini` e `modelos`).

**Desvio deliberado da spec (mesmo comportamento, menos código):** os links de estilo do Casamento continuam só em `Settings.style_urls` (sem cópia em `areas["casamento"]`), então não há migração nem sincronização. As outras áreas guardam os links em `Settings.areas[id].style_urls`.

## Review Focus

1. **Projeto antigo (Nicole e Osny) aberto depois da mudança:** `projeto.json` sem `area`/`pasta_musicas` abre como Casamento e o índice usado é o `music_root` inteiro (Task 2 e Task 3).
2. **`config.json` antigo sem `areas`/`area_atual`:** carrega sem erro e salva de volta com os campos novos (Task 1).
3. **Pasta de músicas apagada ou desconectada depois de escolhida:** o pipeline não quebra; segue com o índice existente e avisa, como já faz quando o M: some (Task 3).
4. **Fechar o programa com projeto na fila:** o aviso de fechar aparece também quando só há projeto esperando (Task 7).
5. **Abrir pela área errada um projeto de outra área** (recente achado no disco ou "Outra pasta…"): recusa com a mensagem fixa, sem iniciar (Task 5).

---

### Task 1: Configuração por área

**Files:**
- Modify: `src/roteiro_ia/config.py`
- Test: `tests/test_config_areas.py` (novo)

**Interfaces:**
- Produces:
  - `class ConfigArea(BaseModel)`: `style_urls: list[str] = []`, `pasta_musicas: str = ""`.
  - `Settings.areas: dict[str, ConfigArea] = {}` e `Settings.area_atual: str = "casamento"`.
  - `config_area(s: Settings, area: str) -> ConfigArea` (cria e devolve a entrada se faltar).
  - `urls_estilo(s: Settings, area: str) -> list[str]` (casamento → `s.style_urls`; outras → `config_area(s, area).style_urls`).
  - `set_urls_estilo(s: Settings, area: str, urls: list[str]) -> None` (mesma regra).
  - `pasta_musicas_padrao(s: Settings, area: str) -> str` (`config_area(...).pasta_musicas` ou, se vazio, `s.music_root`).

- [ ] **Step 1: Write the failing tests**

```python
def test_config_antigo_carrega_sem_areas(tmp_path):
    f = tmp_path / "config.json"
    f.write_text('{"style_urls": ["https://youtu.be/a"], "music_root": "M:\\\\"}', encoding="utf-8")
    s = load_settings(f)
    assert s.area_atual == "casamento" and s.areas == {}
    assert urls_estilo(s, "casamento") == ["https://youtu.be/a"]
    assert urls_estilo(s, "formatura") == []
    assert pasta_musicas_padrao(s, "formatura") == "M:\\"

def test_urls_por_area_sao_independentes():
    s = Settings(style_urls=["c"])
    set_urls_estilo(s, "formatura", ["f"])
    assert s.style_urls == ["c"] and urls_estilo(s, "formatura") == ["f"]
    set_urls_estilo(s, "casamento", ["c2"])
    assert s.style_urls == ["c2"] and urls_estilo(s, "formatura") == ["f"]

def test_pasta_padrao_da_area_e_salva(tmp_path):
    s = Settings(system_dir=str(tmp_path), protected_roots=[])
    config_area(s, "formatura").pasta_musicas = r"M:\COMERCIAIS"
    s.area_atual = "formatura"
    save_settings(s, tmp_path / "config.json")
    s2 = load_settings(tmp_path / "config.json")
    assert pasta_musicas_padrao(s2, "formatura") == r"M:\COMERCIAIS"
    assert s2.area_atual == "formatura"
```

- [ ] **Step 2:** `uv run pytest tests/test_config_areas.py -q` → FAIL (ImportError).
- [ ] **Step 3:** Implementar em `config.py` o que está em Interfaces.
- [ ] **Step 4:** `uv run pytest -q` → tudo PASS.
- [ ] **Step 5:** Commit `feat: configuração por área (estilo e pasta de músicas)`.

---

### Task 2: Área e pasta de músicas no projeto e nos recentes

**Files:**
- Modify: `src/roteiro_ia/pipeline.py` (`ProjectRequest`), `src/roteiro_ia/recentes.py`
- Test: `tests/test_recentes.py` (só acrescentar testes), `tests/test_projeto_area.py` (novo)

**Interfaces:**
- Produces:
  - `ProjectRequest.area: str = "casamento"` e `ProjectRequest.pasta_musicas: str | None = None` (campos com padrão, no fim do dataclass); `to_dict` grava os dois; `from_dict` usa `d.get("area", "casamento")` e `d.get("pasta_musicas")`.
  - `recentes.registrar(s, pasta, disco, agora=None, area: str = "casamento")` grava `"area"` no item.
  - `recentes.listar(s, discos, area: str | None = None) -> list[Recente]`: `None` = todos (comportamento atual); com área, só itens dela. Itens sem `"area"` contam como `"casamento"`; achados no disco tomam `area` do próprio `projeto.json` (`d.get("area", "casamento")`).
  - `Recente.area: str = "casamento"` (campo novo, com padrão, no fim).

- [ ] **Step 1: Write the failing tests**

```python
def test_projeto_json_antigo_e_casamento(tmp_path):
    d = {"source_dir": "R:/2023-09-09 X", "work_drive": "Y:", "assignments": [],
         "n_episodios": None, "derivados": [], "gemini_mode": "gratis"}
    r = ProjectRequest.from_dict(d)
    assert r.area == "casamento" and r.pasta_musicas is None

def test_projeto_ida_e_volta_com_area():
    r = ProjectRequest(Path("R:/2026-12-01 F"), "Y:", [], None, set(), "gratis",
                       area="formatura", pasta_musicas=r"M:\COMERCIAIS")
    r2 = ProjectRequest.from_dict(r.to_dict())
    assert (r2.area, r2.pasta_musicas) == ("formatura", r"M:\COMERCIAIS")

# em tests/test_recentes.py, reaproveitando os helpers do arquivo (_projeto, settings):
def test_listar_filtra_por_area(...):
    # registrar a (casamento, sem passar area) e b (area="formatura")
    assert [r.pasta for r in recentes.listar(s, [y], area="casamento")] == [a]
    assert [r.pasta for r in recentes.listar(s, [y], area="formatura")] == [b]
    assert len(recentes.listar(s, [y])) == 2

def test_achado_no_disco_usa_area_do_projeto_json(...):
    # projeto.json gravado com "area": "formatura" e não registrado
    assert recentes.listar(s, [y], area="casamento") == []
    assert recentes.listar(s, [y], area="formatura")[0].area == "formatura"
```

- [ ] **Step 2:** rodar os testes novos → FAIL.
- [ ] **Step 3:** Implementar o que está em Interfaces. Para os achados, `_achados` devolve também a área.
- [ ] **Step 4:** `uv run pytest -q` → tudo PASS.
- [ ] **Step 5:** Commit `feat: projeto e recentes guardam a área`.

---

### Task 3: Pasta de músicas no pipeline (índice filtrado e protegido)

**Files:**
- Modify: `src/roteiro_ia/music_index.py`, `src/roteiro_ia/pipeline.py`
- Test: `tests/test_music_index.py` (acrescentar), `tests/test_pipeline_musicas.py` (novo)

**Interfaces:**
- Consumes: `ProjectRequest.pasta_musicas` (Task 2).
- Produces:
  - `update_index(..., root: Path | None = None)`: `None` = `s.music_root` (atual). A mensagem de pasta inacessível usa o `root` efetivo.
  - `class IndiceFiltrado` em `music_index.py`: `IndiceFiltrado(idx: MusicIndex, pasta: Path)`; `all()` devolve só as trilhas cujo caminho está dentro de `pasta` (subpastas incluídas, comparação sem diferenciar maiúsculas e com `os.path.normcase(os.path.abspath(...))`); qualquer outro atributo delega para `idx` (`__getattr__`).
  - `Pipeline`: quando `req.pasta_musicas` está preenchida:
    - no `__init__`, `self.s` vira `s.model_copy(update={"protected_roots": [*s.protected_roots, req.pasta_musicas]})` (pasta só leitura);
    - `_st_trilhas` chama `update_index(..., root=Path(req.pasta_musicas))`;
    - `_st_roteiro` passa `IndiceFiltrado(self._index(), Path(req.pasta_musicas))` para `generate_roteiro`. PDF e Premiere continuam com o índice inteiro.
  - Sem `pasta_musicas`, nada muda.

- [ ] **Step 1: Write the failing tests**

```python
def test_update_index_com_root_varre_so_a_pasta(tmp_path, ...):
    # M/A/x.wav e M/B/y.wav; update_index(s, idx, tracker=LibrosaTracker(), root=M/"A") == 1
    # e o índice só tem x.wav

def test_indice_filtrado_inclui_subpastas_e_ignora_resto(...):
    # trilhas em M/COM/a.wav, M/COM/sub/b.wav, M/OUTRA/c.wav no índice
    f = IndiceFiltrado(idx, M / "com")          # caixa diferente de propósito
    assert sorted(Path(t.path).name for t in f.all()) == ["a.wav", "b.wav"]
    assert f.get(str(M / "OUTRA" / "c.wav")) is not None   # delegação

def test_pipeline_protege_a_pasta_de_musicas(tmp_path, ...):
    # Pipeline montado com req.pasta_musicas=str(pasta); assert_writable(pasta/"x.txt", p.s) levanta

def test_pipeline_pasta_sumiu_usa_indice_existente(tmp_path, ...):
    # índice com 1 trilha, req.pasta_musicas aponta para pasta inexistente;
    # _st_trilhas devolve "índice existente (pasta de músicas inacessível)" sem exceção
```

Para montar o `Pipeline` nos testes, copiar o padrão de construção dos testes de pipeline existentes (`tests/test_pipeline*.py`).

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implementar o que está em Interfaces.
- [ ] **Step 4:** `uv run pytest -q` → tudo PASS.
- [ ] **Step 5:** Commit `feat: pasta de músicas por projeto (índice filtrado, só leitura)`.

---

### Task 4: Estilo por área

**Files:**
- Modify: `src/roteiro_ia/gemini/style.py`, `src/roteiro_ia/pipeline.py`, `src/roteiro_ia/ui/abas.py` (`EstiloTab`)
- Test: `tests/gemini/test_style.py` (acrescentar), `tests/ui/test_estilo.py` (acrescentar)

**Interfaces:**
- Consumes: `urls_estilo`, `set_urls_estilo` (Task 1).
- Produces:
  - `load_style_profile(s, area: str = "casamento")` e `build_style_profile(c, s, model=None, on_progress=None, area: str = "casamento")`. Arquivo do perfil: casamento `perfil_estilo.json` (atual); outras `perfil_estilo_{area}.json`. Links: `urls_estilo(s, area)`. O cache por vídeo (`estilo_cache/`) continua comum.
  - `Pipeline` passa `area=self.req.area` nas três chamadas de `load_style_profile` e na geração do perfil.
  - `EstiloTab(s, settings_path, runner, parent=None, area: str = "casamento")`: lê e grava os links com `urls_estilo`/`set_urls_estilo`, gera e mostra o perfil daquela área.

- [ ] **Step 1: Write the failing tests**

```python
def test_perfil_da_formatura_e_separado(tmp_path):
    s = Settings(system_dir=str(tmp_path), protected_roots=[])
    # gravar perfil casamento (como o teste existente faz) e conferir
    assert load_style_profile(s, "formatura") is None
    # gravar perfil formatura → arquivo perfil_estilo_formatura.json
    assert (tmp_path / "perfil_estilo_formatura.json").is_file()
    assert load_style_profile(s) == perfil_casamento

def test_aba_estilo_formatura_grava_links_proprios(qtbot, tmp_path):
    s = Settings(system_dir=str(tmp_path), protected_roots=[], style_urls=["https://youtu.be/c"])
    aba = EstiloTab(s, tmp_path / "config.json", Runner(), area="formatura")
    assert aba.lista.count() == 0
    aba.edit_url.setText("https://youtu.be/f"); aba.adicionar()
    assert s.style_urls == ["https://youtu.be/c"]
    assert urls_estilo(s, "formatura") == ["https://youtu.be/f"]
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implementar o que está em Interfaces.
- [ ] **Step 4:** `uv run pytest -q` → tudo PASS.
- [ ] **Step 5:** Commit `feat: estilo separado por área`.

---

### Task 5: Pacote de áreas, formulário com pasta de músicas e formulário da Formatura

**Files:**
- Create: `src/roteiro_ia/areas/__init__.py`, `src/roteiro_ia/areas/base.py`, `src/roteiro_ia/areas/casamento.py`, `src/roteiro_ia/areas/formatura/__init__.py`, `src/roteiro_ia/areas/formatura/formulario.py`, `src/roteiro_ia/areas/formatura/momentos.py`
- Modify: `src/roteiro_ia/ui/widgets.py` (novo `CampoPastaMusicas`), `src/roteiro_ia/ui/formulario.py`, `src/roteiro_ia/ui/projeto.py`
- Test: `tests/ui/test_areas.py` (novo)

**Interfaces:**
- Consumes: `pasta_musicas_padrao` (Task 1), `ProjectRequest.area/pasta_musicas` e `recentes(..., area=)` (Task 2).
- Produces:
  - `areas/base.py`: `@dataclass(frozen=True) class Area: id: str; nome: str; formulario: type; pode_iniciar: bool = True; aviso_iniciar: str = ""`.
  - `areas/__init__.py`: `AREAS: list[Area]` (casamento, formatura) e `area_por_id(id: str) -> Area` (id desconhecido → casamento).
  - `areas/casamento.py`: `CASAMENTO = Area("casamento", "Casamento", FormularioEvento)`.
  - `areas/formatura/momentos.py`: `MOMENTOS_FORMATURA: list[str]` copiada do briefing (Oficina, Prova de toga, Escolha do paraninfo, Decoração, Bastidores, Abertura do mestre de cerimônias e entrada dos professores, Entrada das turmas, Hino Nacional, Fala do diretor ou representante, Colação de grau, Oradores, Paraninfos, Homenagens, Hino e encerramento). Só dados; a parte 2 usa.
  - `areas/formatura/formulario.py`: `class FormularioFormatura(FormularioEvento)` que esconde o card "Entregas" (episódios/trailer…) e deixa `btn_iniciar` sempre desligado com tooltip e um rótulo com `"A Formatura chega na próxima etapa."`. `FORMATURA = Area("formatura", "Formatura", FormularioFormatura, pode_iniciar=False, aviso_iniciar="A Formatura chega na próxima etapa.")`.
  - `widgets.CampoPastaMusicas(QWidget)`: rótulo com o caminho + "Escolher…" + "Usar padrão"; `pasta() -> str | None` (`None` quando está no padrão), `set_pasta(p: str | None)`, `set_padrao(p: str)`. Escolher abre `QFileDialog.getExistingDirectory`. Se a pasta mostrada não existir, `aviso` (QLabel, estado "aviso") mostra `"Pasta de músicas não encontrada. O roteiro segue sem músicas dela."`; senão fica escondido.
  - `FormularioEvento(s, runner, parent=None, area: str = "casamento")`: novo card "Músicas" (pasta de músicas, com a dica "Vale a pasta e todas as subpastas.") logo antes de "Entregas"; `build_request` preenche `area=self.area` e `pasta_musicas=self.campo_musicas.pasta()`; `load_request` aplica `req.pasta_musicas`. O card entra em `self.cards` (trava junto ao rodar).
  - `ProjetoTab(s, settings_path, runner, factory=None, parent=None, area: str = "casamento", fila=None)`: cria o formulário de `area_por_id(area).formulario`; usa `area` em `recentes.registrar` e `recentes.listar`; em `abrir_existente`, se `req.area != self.area`, mostra `"Este projeto é de {Nome}. Abra pela área {Nome}."` no banner de erro e devolve `False`. (`fila` é usado na Task 6; aqui só o parâmetro.)

- [ ] **Step 1: Write the failing tests**

```python
def test_areas_registradas_em_ordem():
    assert [a.id for a in AREAS] == ["casamento", "formatura"]
    assert area_por_id("xyz").id == "casamento"

def test_formulario_casamento_manda_pasta_de_musicas(qtbot, settings_tmp, ...):
    # escolher pasta de evento válida, campo_musicas.set_pasta(r"R:\2023-09-09 X\MUSICAS")
    req = form.build_request()
    assert req.area == "casamento" and req.pasta_musicas.endswith("MUSICAS")
    form.campo_musicas.set_pasta(None)
    assert form.build_request().pasta_musicas is None

def test_campo_musicas_avisa_pasta_inexistente(qtbot, tmp_path):
    c = CampoPastaMusicas(); c.set_padrao(str(tmp_path))
    assert c.aviso.isHidden()
    c.set_pasta(str(tmp_path / "SUMIU"))
    assert not c.aviso.isHidden()

def test_formatura_nao_inicia(qtbot, settings_tmp, ...):
    tab = ProjetoTab(settings_tmp, cfg, Runner(), area="formatura")
    tab.set_event_folder(pasta_valida)
    assert not tab.btn_iniciar.isEnabled()

def test_formatura_recusa_pasta_fora_do_padrao(qtbot, ...):
    assert tab.set_event_folder(tmp_path / "FORMATURA SEM DATA") is False

def test_abrir_projeto_de_outra_area_recusa(qtbot, ...):
    # projeto.json gravado com area "formatura"; ProjetoTab(area="casamento").abrir_existente(pasta)
    assert ok is False
    assert "Este projeto é de Formatura. Abra pela área Formatura." in tab.status.banner_erro.texto()
```

Usar os fixtures de `tests/ui/conftest.py` (`settings_tmp` e o de pasta de evento, se houver) e o texto do banner pelo mesmo acesso que os testes existentes de `ProjetoTab` usam.

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implementar o que está em Interfaces.
- [ ] **Step 4:** `uv run pytest -q` → tudo PASS (os testes atuais de formulário/projeto passam sem edição).
- [ ] **Step 5:** Commit `feat: áreas Casamento/Formatura e pasta de músicas no formulário`.

---

### Task 6: Fila de projetos

**Files:**
- Create: `src/roteiro_ia/ui/fila.py`
- Modify: `src/roteiro_ia/ui/projeto.py`, `src/roteiro_ia/ui/status.py` (botão "Tirar da fila")
- Test: `tests/ui/test_fila.py` (novo)

**Interfaces:**
- Produces:
  - `class ClienteFila(Protocol)`: `nome_fila() -> str`; `comecar() -> None`; `suspender() -> None` (pausar o worker); `retomar_suspenso() -> None` (soltar a pausa); `mostrar_espera(texto: str | None) -> None` (`None` apaga o aviso).
  - `class FilaProjetos(QObject)` com sinal `mudou = Signal()` e:
    - `pedir(c: ClienteFila) -> None`: entra no fim da ordem (se já estiver, mantém o lugar) e despacha.
    - `sair(c) -> None`: terminou, parou, deu erro, foi cancelado ou "Tirar da fila"; despacha.
    - `esperando_cota(c) -> None`: continua na ordem, mas deixa o próximo rodar; despacha.
    - `ativo() -> ClienteFila | None`, `na_fila() -> list[ClienteFila]` (esperando para começar).
  - Regra de despacho (o algoritmo que os testes fixam): percorrer a ordem; o primeiro cliente que não está em `esperando_cota` é o **dono**. Se o dono ainda não começou → `comecar()`; se estava suspenso → `retomar_suspenso()`. Qualquer outro cliente que esteja rodando e não esteja em cota → `suspender()` (marca suspenso). Clientes ainda não começados e que não são dono recebem `mostrar_espera("Na fila — começa quando {nome do dono} terminar.")`. Quando um cliente em cota chama `pedir` de novo (retomada), sai do estado de cota e mantém o lugar original na ordem.
  - `ProjetoTab` implementa `ClienteFila`: `_start` passa a chamar `self.fila.pedir(self)` guardando a ação; `comecar()` faz o que `_start` faz hoje; `_on_terminou` chama `fila.esperando_cota(self)` no status `"pausado"` (cota) e `fila.sair(self)` nos demais; `cancelar_retomada` chama `sair`. Sem `fila` passada, o `ProjetoTab` cria a própria `FilaProjetos` (começa na hora: comportamento atual).
  - `status.StatusPanel`: botão `btn_tirar_fila` ("Tirar da fila"), visível só enquanto espera; liga em `ProjetoTab.tirar_da_fila()` → `fila.sair(self)`, destrava o formulário e apaga o aviso.

- [ ] **Step 1: Write the failing tests** (com um `Falso` que registra chamadas em uma lista)

```python
def test_segundo_espera_e_comeca_quando_primeiro_termina():
    f, a, b = FilaProjetos(), Falso("2023-09-09 A"), Falso("2026-12-01 B")
    f.pedir(a); f.pedir(b)
    assert a.log == ["comecar"] and b.espera == "Na fila — começa quando 2023-09-09 A terminar."
    f.sair(a)
    assert b.log == ["comecar"] and b.espera is None

def test_cota_deixa_o_proximo_adiantar_e_primeiro_retoma_com_prioridade():
    f.pedir(a); f.pedir(b); f.esperando_cota(a)
    assert b.log == ["comecar"]
    f.pedir(a)                                   # cota voltou
    assert b.log == ["comecar", "suspender"] and a.log[-1] == "comecar"
    f.sair(a)
    assert b.log[-1] == "retomar_suspenso"

def test_tirar_da_fila():
    f.pedir(a); f.pedir(b); f.sair(b); f.sair(a)
    assert b.log == []

def test_sem_fila_compartilhada_comeca_na_hora(qtbot, ...):
    # ProjetoTab sem fila: Iniciar roda como hoje (fábrica falsa dos testes existentes)
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implementar `fila.py` e a integração em `ProjetoTab`/`StatusPanel`.
- [ ] **Step 4:** `uv run pytest -q` → tudo PASS.
- [ ] **Step 5:** Commit `feat: fila de projetos no mesmo PC`.

---

### Task 7: Janela com seletor de áreas

**Files:**
- Modify: `src/roteiro_ia/ui/app.py`, `src/roteiro_ia/ui/tema.qss`
- Test: `tests/ui/test_areas_janela.py` (novo)

**Interfaces:**
- Consumes: `AREAS`, `area_por_id` (Task 5); `EstiloTab(area=)` (Task 4); `ProjetoTab(area=, fila=)` e `FilaProjetos` (Task 6); `Settings.area_atual` (Task 1).
- Produces:
  - `MainWindow` cria uma `FilaProjetos` e, para cada área, uma página com seu `QTabWidget` (abas na ordem atual: Projeto, Trilhas, Estilo, Configurações) dentro de um `QStackedWidget`. Acima, uma faixa com um botão checável por área (`objectName="area"`, texto = nome) e a `BarraGeral` à direita.
  - `MainWindow.areas: dict[str, PaginaArea]`, com `PaginaArea` tendo `tabs`, `projeto`, `estilo`.
  - Atributos atuais mantidos para os testes existentes: `self.projeto`/`self.estilo`/`self.tabs` = os da área **Casamento**; `self.trilhas`, `self.config` = instâncias únicas.
  - `mostrar_area(id: str) -> None`: troca a página, move `trilhas` e `config` para as abas da área nova nas posições 1 e 3, grava `s.area_atual` e salva a config. Ao abrir, a janela mostra `s.area_atual`.
  - Marca no botão da área fora de vista quando ela tem projeto rodando, em cota ou na fila: o texto do botão ganha `" •"`.
  - Barra geral e `closeEvent` consideram os `ProjetoTab` de todas as áreas (`em_pausa_cota`, `rodando`) e a fila (`na_fila()` não vazia também dispara o aviso de fechar).
  - `tema.qss`: estilo para `QPushButton#area` (mesmo padrão do `#segmento`, com `:checked` no laranja `#d9774a`).

- [ ] **Step 1: Write the failing tests**

```python
def test_abre_na_ultima_area_e_troca(qtbot, settings_tmp, tmp_path):
    settings_tmp.area_atual = "formatura"
    w = MainWindow(settings_tmp, tmp_path / "SISTEMA" / "config.json")
    assert w.stack.currentWidget() is w.areas["formatura"]
    w.mostrar_area("casamento")
    assert settings_tmp.area_atual == "casamento"
    assert load_settings(tmp_path / "SISTEMA" / "config.json").area_atual == "casamento"

def test_trilhas_e_config_sao_uma_so_instancia(qtbot, ...):
    w.mostrar_area("formatura")
    assert w.areas["formatura"].tabs.indexOf(w.trilhas) == 1
    assert w.areas["formatura"].tabs.indexOf(w.config) == 3
    assert w.areas["casamento"].tabs.indexOf(w.trilhas) == -1

def test_projeto_casamento_e_o_atributo_antigo(qtbot, ...):
    assert w.projeto is w.areas["casamento"].projeto

def test_fechar_com_projeto_na_fila_pergunta(qtbot, monkeypatch, ...):
    # fila com um cliente esperando; QMessageBox.question devolve No → e.isAccepted() é False
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implementar o que está em Interfaces.
- [ ] **Step 4:** `uv run pytest -q` → tudo PASS, incluindo todos os testes existentes de janela sem edição.
- [ ] **Step 5:** Commit `feat: seletor de áreas na janela`.

---

### Task 8: Conferência no programa de verdade

- [ ] **Step 1:** `uv run pytest -q` completo → tudo PASS; anotar o número de testes.
- [ ] **Step 2:** Abrir o programa pelo atalho (ou `.venv\Scripts\pythonw.exe -c "from roteiro_ia.ui.app import main; main()"`) e conferir: seletor com as duas áreas; troca mantém Trilhas/Configurações; Formatura com Estilo vazio e Iniciar desligado com o aviso; Casamento com o card Músicas; "Continuar projeto existente…" do Casamento lista o Nicole e Osny e o da Formatura não. Fechar e reabrir: volta na última área.
- [ ] **Step 3:** Atualizar `docs/formaturas/briefing.md` com uma linha "Parte 1 (áreas de trabalho) concluída" e commit `docs: parte 1 das áreas concluída`.
