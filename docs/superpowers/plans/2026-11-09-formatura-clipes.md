# Formatura: clipes funcionando, plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a área Formatura cadastra formaturas, prepara clipes (Oficina, Feira, Prova de toga,
Paraninfo) e processa cada um até o PDF e o XML do Premiere. A colação fica preparada, com o
Iniciar desligado até a 2.3.

**Architecture:** o código novo fica em `src/roteiro_ia/areas/formatura/`. O pipeline é uma
subclasse do comum (`PipelineFormatura`), que troca só os textos da análise e o contexto do
roteiro. O código comum recebe apenas acréscimos com valor padrão, que reproduzem o Casamento
exatamente.

**Tech Stack:** Python 3, pydantic v2, PySide6, pytest e pytest-qt.

**Spec:** `docs/superpowers/specs/2026-11-09-formatura-cadastro-design.md`

## Global Constraints

- Os testes rodam do worktree com `PYTHONPATH=src ../../.venv/Scripts/python.exe -m pytest`.
  Sem `PYTHONPATH`, o venv importa o `src` da pasta principal.
- O Casamento não muda: os prompts, os arquivos e os testes dele ficam idênticos.
- Só os testes provisórios da Formatura em `tests/ui/test_areas.py` podem ser editados:
  `test_areas_registradas_em_ordem` (só a linha de `pode_iniciar`), `test_formatura_nao_inicia`
  e `test_formatura_numera_gemini_como_5`.
- Toda gravação usa `safe_write_text` ou `safe_mkdir` (`roteiro_ia.safety`).
- Textos visíveis em português, com acentos.
- Não usar `git stash`. Os commits ficam no ramo `docs/formatura-briefing`.

## Review Focus

1. **Projeto de Formatura reaberto por "Continuar projeto existente":** o `formatura.json` tem
   que voltar ao formulário com tipo, formatura e turma. Senão o Iniciar fica desligado ou
   processa sem os dados. Teste na Tarefa 5.
2. **Ficha apagada depois de usada:** reabrir não pode quebrar, só avisar. Teste na Tarefa 5.
3. **Oficina com vários dias** em que um dia tem mídia solta e subpastas ao mesmo tempo: esse
   dia é tratado como pasta comum, não como dia. Teste na Tarefa 2.
4. **Prompt do Casamento byte a byte igual** depois do parâmetro `textos`. Teste na Tarefa 1,
   que compara com o texto montado antes da mudança.
5. **Todas as músicas da pasta já usadas:** o roteiro não pode falhar, segue com sugestões pelo
   nome e alerta. Teste na Tarefa 4.

---

### Task 1: Ganchos no código comum

**Files:**
- Modify: `src/roteiro_ia/gemini/analysis.py`, `src/roteiro_ia/script/generate.py`,
  `src/roteiro_ia/gemini/style.py`, `src/roteiro_ia/ui/abas.py` (`EstiloTab._icones`),
  `src/roteiro_ia/areas/base.py` e `src/roteiro_ia/ui/projeto.py` (`_pipeline_padrao`)
- Test: `tests/areas/formatura/test_ganchos.py` (e um `__init__.py` vazio em
  `tests/areas/` e em `tests/areas/formatura/`, se o pytest pedir)

**Interfaces:**
- Produces:
  - `analysis.TextosAnalise` (dataclass congelada: `papel: str`, `evento: str`,
    `momentos: list[str]`, `problemas: str`) e `analysis.TEXTOS_CASAMENTO`;
  - `build_prompt(..., textos: TextosAnalise = TEXTOS_CASAMENTO)`,
    `build_pack_prompt(..., textos=TEXTOS_CASAMENTO)` e
    `analyze_event(..., textos=TEXTOS_CASAMENTO)`, repassado até os builders;
  - `generate.generate_roteiro(..., contexto: Callable[..., str] | None = None)`, onde
    `contexto` tem a assinatura de `_context(db, idx, style, n_episodios, derivados, compact)`;
  - `style.registrar_area(area: str, prompt_video: str, prompt_agg: str) -> None`;
  - `style.video_em_cache(s, url, area: str = "casamento") -> bool`;
  - `Area.pipeline: Callable | None = None`.

- [ ] **Step 1: Write failing tests**

```python
def test_prompt_casamento_identico(db_com_segmentos):  # monte a fixture como em tests/gemini/test_analysis.py
    m, segs = db_com_segmentos
    pr = build_prompt(m, segs, {})
    assert pr.startswith("Você é um assistente de edição de vídeos de casamento da produtora Fokuss.")
    assert "preparação noiva, preparação noivo" in pr
    assert "falhas técnicas (tremido, foco, áudio ruim, escuro)" in pr
    assert build_prompt(m, segs, {}, textos=TEXTOS_CASAMENTO) == pr

def test_prompt_com_textos_proprios(db_com_segmentos):
    m, segs = db_com_segmentos
    t = TextosAnalise(papel="PAPEL X.", evento="da mesma formatura", momentos=["oficina", "extra"],
                      problemas="falhas Y")
    pr = build_prompt(m, segs, {}, textos=t)
    assert pr.startswith("PAPEL X.") and "oficina, extra" in pr and "falhas Y" in pr
    assert "casamento" not in pr
    pk = build_pack_prompt([(m, segs, {}, None)], textos=t)
    assert "do mesmo casamento" not in pk and "da mesma formatura" in pk

def test_generate_usa_contexto(db_e_indice, cliente_falso):  # fixtures como em tests/script/test_generate.py
    vistos = []
    def ctx(db, idx, style, n, der, compact=False):
        vistos.append(compact); return "CONTEXTO PROPRIO"
    generate_roteiro(db, cliente_falso, idx, None, "m", 1, set(), contexto=ctx)
    assert cliente_falso.prompts[0].startswith("CONTEXTO PROPRIO")

def test_style_area_registrada_tem_cache_e_prompts_proprios(settings_tmp):
    registrar_area("teste", "PV", "PA")
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    p = Path(settings_tmp.system_dir) / "estilo_cache" / "abcdefghijk.json"
    p.parent.mkdir(parents=True); p.write_text(VideoStyleNotes(url=url, tipo="outro", duracao_s=1,
        ritmo_corte_s=1, abertura="", gancho="", uso_falas="", trilha="", cor="", observacoes="").model_dump_json(), encoding="utf-8")
    assert video_em_cache(settings_tmp, url)
    assert not video_em_cache(settings_tmp, url, area="teste")

def test_area_pipeline_padrao_e_none():
    assert area_por_id("casamento").pipeline is None
```

- [ ] **Step 2: Run, verify FAIL** (ImportError of `TextosAnalise`, `registrar_area`)

Run: `PYTHONPATH=src ../../.venv/Scripts/python.exe -m pytest tests/areas/formatura/test_ganchos.py -q`

- [ ] **Step 3: Implement.**
  - `analysis.py`:
    - `TEXTOS_CASAMENTO.papel` = a frase atual "Você é um assistente…casamento…".
    - `evento` = "do mesmo casamento".
    - `momentos` = `MOMENTOS`.
    - `problemas` = "falhas técnicas (tremido, foco, áudio ruim, escuro)".
    - `_regras` recebe `textos`. A linha final continua "- problemas: {textos.problemas};
      lista vazia se não houver.".
  - `generate.py`: `base = (contexto or _context)(db, idx, style, n_episodios, derivados,
    compact=compact)`.
  - `style.py`:
    - `_PROMPTS: dict[str, tuple[str, str]] = {}`.
    - `_cache_path(s, url, area="casamento")` grava em `estilo_cache\<area>\` quando
      `area in _PROMPTS`.
    - `build_style_profile` usa `_PROMPTS.get(area, (_PROMPT_VIDEO, _PROMPT_AGG))` e o cache da
      área.
    - `_read_cache` e `video_em_cache` recebem `area`.
  - `abas.py` `_icones`: `video_em_cache(self.s, url, **self._kw_area())`.
  - `base.py`: `pipeline: Callable | None = None`, depois de `aviso_iniciar`.
  - `projeto.py` `_pipeline_padrao`:

```python
fab = area_por_id(self.area).pipeline
if fab is not None:
    return fab(req, s, None, None, eventos, settings_path=self.settings_path)
return Pipeline(req, s, None, None, eventos, settings_path=self.settings_path)
```

- [ ] **Step 4: Run the new tests and the whole suite**

Run: `PYTHONPATH=src ../../.venv/Scripts/python.exe -m pytest -q`
Expected: tudo PASS (515 e mais os novos).

- [ ] **Step 5: Commit** com a mensagem "feat: ganchos comuns para a Formatura (textos da
  análise, contexto do roteiro, estilo por área, pipeline por área)".

---

### Task 2: Cadastro, tipos, funções e momentos

**Files:**
- Create: `src/roteiro_ia/areas/formatura/cadastro.py`, `tipos.py` e `funcoes.py`
- Modify: `src/roteiro_ia/areas/formatura/momentos.py` (acrescentar, sem mudar
  `MOMENTOS_FORMATURA`)
- Test: `tests/areas/formatura/test_cadastro.py` e `test_funcoes.py`

**Interfaces:**
- Produces:
  - `Curso`, `Formatura`, `listar(s)`, `carregar(s, id)`, `salvar(s, f) -> Formatura` (com
    id), `avisos(f) -> list[str]`, `duplicar(f)`, `nome_exibicao(f)`;
  - `TipoTrabalho(StrEnum)`: oficina, feira, prova_toga, paraninfo, colacao;
  - `INFO_TIPO: dict[TipoTrabalho, InfoTipo]`, com `InfoTipo(nome, grupo: "clipe" |
    "colacao", turma: "obrigatoria" | "opcional" | "nenhuma", duracao_min: float | None)`;
  - `TIPOS_CLIPE` (lista em ordem);
  - `FuncaoFormatura(StrEnum)`: camera, camera_iso, camera_audio, mesa_corte, gravador,
    extras, drone, ignorar;
  - `ROTULO_FUNCAO`, `ROLE_DA_FUNCAO`, `funcoes_do_grupo(grupo) -> list[FuncaoFormatura]`;
  - `sugerir_funcao(pasta: str, grupo: str) -> FuncaoFormatura`;
  - `listar_pastas(source: Path) -> list[tuple[str, str]]`;
  - `MOMENTOS_POR_TIPO` e `PROBLEMAS_TECNICOS`.

- [ ] **Step 1: Write failing tests**

```python
def test_salvar_e_listar(settings_tmp):
    f = salvar(settings_tmp, Formatura(instituicao="Escola X", ano=2026, semestre=2,
               cursos=[Curso(nome="Técnico em Eletrônica", turmas=["T106", "T107"])]))
    assert f.id.startswith("escola-x-2026-2-")
    assert (Path(settings_tmp.system_dir) / "FORMATURAS" / f"{f.id}.json").is_file()
    salvar(settings_tmp, Formatura(instituicao="Alfa", ano=2027, semestre=1, cursos=[Curso(nome="A", turmas=["M"])]))
    assert [x.instituicao for x in listar(settings_tmp)] == ["Alfa", "Escola X"]
    assert carregar(settings_tmp, f.id) == f and carregar(settings_tmp, "nao-existe") is None
    assert nome_exibicao(f) == "ESCOLA X — 2026/2"

@pytest.mark.parametrize("cursos,msg", [([], "Cadastre pelo menos um curso."),
    ([Curso(nome="A", turmas=[])], "O curso A está sem turma."),
    ([Curso(nome="A", turmas=["T1", "t1"])], "Turma repetida no curso A: T1.")])
def test_validacao(settings_tmp, cursos, msg):
    with pytest.raises(ValueError, match=re.escape(msg)):
        salvar(settings_tmp, Formatura(instituicao="X", ano=2026, semestre=1, cursos=cursos))
    with pytest.raises(ValueError, match="Informe a instituição."):
        salvar(settings_tmp, Formatura(instituicao=" ", ano=2026, semestre=1, cursos=[Curso(nome="A", turmas=["1"])]))

def test_duplicar_e_avisos(tmp_path):
    f = Formatura(id="x", instituicao="X", ano=2026, semestre=2, cursos=[Curso(nome="A", turmas=["1"])],
                  logo_escola=str(tmp_path / "sumiu.png"))
    d = duplicar(f)
    assert (d.id, d.ano, d.semestre) == ("", 2027, 1)
    assert avisos(f) == [f"Logo da escola não encontrado: {tmp_path / 'sumiu.png'}"]

def test_arquivo_ilegivel_e_pulado(settings_tmp): ...  # grava "{" em FORMATURAS\ruim.json; listar não quebra

@pytest.mark.parametrize("pasta,grupo,esperado", [
    ("CAM A", "clipe", "camera"), ("CAM 1", "colacao", "camera_iso"), ("PGM", "colacao", "mesa_corte"),
    ("CORTE", "colacao", "mesa_corte"), ("ATEM", "colacao", "mesa_corte"), ("H4", "clipe", "gravador"),
    ("H1", "colacao", "gravador"), ("MIC LAPELA", "clipe", "gravador"), ("FRIAS", "colacao", "extras"),
    ("DIA 1\\DECORAÇÃO", "colacao", "extras"), ("DRONE", "clipe", "drone"), ("Proxies", "clipe", "ignorar"),
    ("2026-03-10\\CAM B", "clipe", "camera"), ("CHAMADA", "clipe", "camera")])
def test_sugerir_funcao(pasta, grupo, esperado):
    assert sugerir_funcao(pasta, grupo) == esperado

def test_listar_pastas_com_dias(tmp_path):
    (tmp_path / "2026-03-10" / "CAM A").mkdir(parents=True)
    (tmp_path / "2026-03-10" / "H4").mkdir()
    (tmp_path / "2026-03-12" / "CAM A").mkdir(parents=True)
    (tmp_path / "MISTO" / "SUB").mkdir(parents=True); (tmp_path / "MISTO" / "a.mp4").write_bytes(b"")
    (tmp_path / "DRONE").mkdir()
    assert listar_pastas(tmp_path) == [("2026-03-10\\CAM A", "2026-03-10"), ("2026-03-10\\H4", "2026-03-10"),
        ("2026-03-12\\CAM A", "2026-03-12"), ("DRONE", "principal"), ("MISTO", "principal")]

def test_role_e_momentos():
    assert ROLE_DA_FUNCAO[FuncaoFormatura.mesa_corte] == Role.mesa
    assert ROLE_DA_FUNCAO[FuncaoFormatura.gravador] == Role.audio_ambiente
    assert all(v[-1] == "extra" for v in MOMENTOS_POR_TIPO.values())
    assert FuncaoFormatura.mesa_corte not in funcoes_do_grupo("clipe")
```

- [ ] **Step 2: Run, verify FAIL**
- [ ] **Step 3: Implement**
  - id: `slug` = minúsculas, sem acentos (`unicodedata`), não alfanumérico → "-". Depois
    `f"{slug}-{ano}-{semestre}-{secrets.token_hex(2)}"`.
  - Mídia solta: extensões de `inventory.VIDEO_EXTS | AUDIO_EXTS`.
  - Dias e pastas em ordem alfabética.
  - Pastas de `inventory._dir_ignored` não contam como subpasta de dia, mas aparecem quando
    estão no primeiro nível, como `Proxies` → ignorar.
- [ ] **Step 4: Run tests, PASS**
- [ ] **Step 5: Commit** com a mensagem "feat(formatura): cadastro, tipos, funções das pastas
  e momentos".

---

### Task 3: Projeto, textos da análise e contexto do roteiro

**Files:**
- Create: `src/roteiro_ia/areas/formatura/projeto.py`, `analise.py` e `roteiro.py`, e a
  versão Formatura dos prompts em `estilo.py`
- Test: `tests/areas/formatura/test_projeto.py` e `test_roteiro.py`

**Interfaces:**
- Consumes: Task 1 (`TextosAnalise`, `contexto`, `registrar_area`) e Task 2.
- Produces:
  - `ProjetoFormatura`, como na spec;
  - `RequestFormatura(ProjectRequest)`, uma dataclass com
    `formatura: ProjetoFormatura | None = None`;
  - `caminho(analysis_dir) -> Path`, que é `analysis_dir / "formatura.json"`;
  - `salvar_projeto(analysis_dir, pf, s)` e `carregar_projeto(analysis_dir) ->
    ProjetoFormatura | None`;
  - `musicas_usadas(s, formatura_id: str, exceto: Path | None) -> set[str]`;
  - `TEXTOS_POR_TIPO: dict[TipoTrabalho, TextosAnalise]`;
  - `contexto_clipe(pf, ficha: Formatura | None, ideia_json: str | None) -> Callable`, com a
    assinatura de `_context`;
  - `IndiceSem(idx, excluir: set[str])`, a mesma interface de leitura de `IndiceFiltrado`
    (`all()` e o que `validate_refs` e `music_shortlist` usam);
  - `estilo.PROMPT_VIDEO` e `estilo.PROMPT_AGG`, registrados ao importar `areas.formatura`.

- [ ] **Step 1: Write failing tests**

```python
def test_formatura_json_ida_e_volta(tmp_path, settings_tmp):
    pf = ProjetoFormatura(tipo="oficina", formatura_id="x", curso="A", turma="T106",
                          funcoes={"2026-03-10\\CAM A": "camera"})
    salvar_projeto(tmp_path, pf, settings_tmp)
    assert carregar_projeto(tmp_path) == pf and carregar_projeto(tmp_path / "nada") is None

def test_musicas_usadas(settings_tmp, tmp_path, monkeypatch): ...
    # dois eventos registrados em recentes (area="formatura") com formatura.json: um da mesma
    # formatura com musica "M:\\a.mp3", outro de formatura diferente com "M:\\b.mp3";
    # musicas_usadas(s, "x", exceto=None) == {"M:\\a.mp3"}; com exceto= pasta do 1º → set()

def test_textos_por_tipo():
    t = TEXTOS_POR_TIPO[TipoTrabalho.oficina]
    assert "formatura" in t.papel and "Oficina" in t.papel and "chicote" in t.problemas
    assert t.momentos == MOMENTOS_POR_TIPO[TipoTrabalho.oficina]

def test_contexto_clipe(db_e_indice):
    db, idx = db_e_indice
    ficha = Formatura(id="x", instituicao="Escola X", ano=2026, semestre=2, cursos=[Curso(nome="Eletrônica", turmas=["T106"])])
    pf = ProjetoFormatura(tipo="oficina", formatura_id="x", curso="Eletrônica", turma="T106", duracao_min=4)
    txt = contexto_clipe(pf, ficha, None)(db, idx, None, 1, set())
    for trecho in ("UMA peça", "240 s", "Escola X", "Eletrônica", "T106", "2026/2", "cartela",
                   "chicote", "comercial", 'origem "popular"', 'numero 1'):
        assert trecho in txt
    assert "série" not in txt and "GANCHO" not in txt
    assert "IDEIA DA ORIGINAL" in contexto_clipe(pf, ficha, '{"arco": "x"}')(db, idx, None, 1, set())

def test_indice_sem_exclui(db_e_indice):
    _, idx = db_e_indice
    p = idx.all()[0].path
    assert p not in {t.path for t in IndiceSem(idx, {p}).all()}

def test_prompts_de_estilo_registrados():
    import roteiro_ia.areas.formatura  # noqa: F401
    from roteiro_ia.gemini import style
    assert "formatura" in style._PROMPTS["formatura"][0]
```

- [ ] **Step 2: Run, verify FAIL**
- [ ] **Step 3: Implement.**
  - O contexto monta, nesta ordem:
    1. a apresentação do roteirista da Fokuss, para formaturas;
    2. as regras numeradas 1 a 7 da spec, com `duracao_min*60` em segundos;
    3. `generate._FORMATO`;
    4. o estilo, com `generate._style_text`, quando houver;
    5. o catálogo, com `build_catalog`;
    6. as trilhas, com `music_shortlist(idx)`, ou "(nenhuma trilha disponível; sugira só pelo
       nome)" quando estiver vazio;
    7. a ideia da original, quando houver.
  - `InfoTipo.nome` dá o texto do tipo no prompt.
  - `musicas_usadas` lê os discos de `[s.work_drive]` e `build_event_paths(r.pasta, s,
    r.disco).analysis_dir`.
- [ ] **Step 4: Run tests, PASS**
- [ ] **Step 5: Commit** com a mensagem "feat(formatura): projeto, textos da análise, contexto
  do roteiro e prompts de estilo".

---

### Task 4: PipelineFormatura

**Files:**
- Create: `src/roteiro_ia/areas/formatura/pipeline.py`
- Modify: `src/roteiro_ia/areas/formatura/formulario.py`, onde `FORMATURA` ganha
  `pipeline=PipelineFormatura`. O `pode_iniciar` só muda na Tarefa 5.
- Test: `tests/areas/formatura/test_pipeline.py`

**Interfaces:**
- Consumes: Tasks 1 a 3.
- Produces: `PipelineFormatura(req, s, gemini=None, transcriber=None, events=None, *,
  settings_path=None, music_tracker=None)`. O `req` deve ser `RequestFormatura` com
  `formatura`. Sem ele, o pipeline lê o `formatura.json`. Se não houver nenhum dos dois, sobe
  `PipelineError("Projeto de Formatura sem dados do trabalho (formatura.json).")`.

- [ ] **Step 1: Write failing tests**, usando os falsos de `tests/test_pipeline.py`:
  - `test_grava_formatura_json`: `prepare()` grava `ANALISE\formatura.json` igual ao
    `req.formatura`.
  - `test_colacao_recusada`: com tipo colação, `run()` sobe `PipelineError` com a mensagem
    "A colação chega na próxima etapa (2.3)."
  - `test_analise_usa_textos_do_tipo`: faz monkeypatch de `analyze_event` em
    `roteiro_ia.areas.formatura.pipeline` e verifica `kwargs["textos"] is
    TEXTOS_POR_TIPO["oficina"]`.
  - `test_roteiro_usa_contexto_e_grava_musica`:
    - faz monkeypatch de `generate_roteiro` e captura `n_episodios == 1`, `derivados ==
      set()` e `contexto` não `None`;
    - devolve um `Roteiro` com trilha da biblioteca `"M:\\a.mp3"`;
    - depois, `carregar_projeto(...).musica == "M:\\a.mp3"`.
  - `test_roteiro_sem_musica_livre`: `musicas_usadas` cobre todas as trilhas, e
    `generate_roteiro` recebe um índice vazio sem quebrar.
- [ ] **Step 2: Run, verify FAIL**
- [ ] **Step 3: Implement.**
  - Sobrescrever `prepare` e `run` para gravar o `formatura.json` antes do `super()`. O `run`
    verifica a colação primeiro.
  - Sobrescrever `_st_analise` e `_st_roteiro`, como na spec.
  - A ficha vem de `cadastro.carregar(self._base, pf.formatura_id)`.
  - A ideia vem de `latest_roteiro()` do banco da original
    (`build_event_paths(Path(pf.duplicado_de), s, req.work_drive).db_path`). Só quando
    `seguir_ideia` está marcado e o banco existe.
- [ ] **Step 4: Run tests and full suite, PASS**
- [ ] **Step 5: Commit** com a mensagem "feat(formatura): pipeline dos clipes".

---

### Task 5: Interface da Formatura

**Files:**
- Create: `src/roteiro_ia/areas/formatura/ui_cadastro.py` (`DialogoFormatura` e
  `DialogoCadastro`)
- Modify: `src/roteiro_ia/areas/formatura/formulario.py` (`FormularioFormatura` e
  `FORMATURA`) e `src/roteiro_ia/ui/projeto.py` (`abrir_existente`, só se o
  `load_request` não bastar)
- Modify (provisórios): `tests/ui/test_areas.py`
- Test: `tests/areas/formatura/test_formulario.py` e `test_ui_cadastro.py`

**Interfaces:**
- Consumes: Tasks 2 a 4.
- Produces:
  - `FormularioFormatura`, com:
    - `seg_clipes` e `seg_colacao` (botões);
    - `combo_tipo`, `combo_formatura`, `combo_curso`, `combo_turma` e `spin_duracao`;
    - `btn_formaturas`, `btn_nova` e `btn_duplicar`;
    - `edit_local` e `edit_cidade`;
    - `lista_turmas` (`QListWidget` com caixas de marcar);
    - `combo_canais`;
    - `tabela_f` (Pasta | O que é);
    - `lbl_aviso`;
    - os métodos `projeto_formatura() -> ProjetoFormatura`, `duplicar_de(pasta: Path) ->
      bool` e `motivo_bloqueio() -> str`.
  - `FORMATURA = Area("formatura", "Formatura", FormularioFormatura, pipeline=PipelineFormatura)`,
    com `pode_iniciar` True (o padrão).

- [ ] **Step 1: Write failing tests**
  - `test_oficina_liga_iniciar` (com a fixture `evento` e uma ficha salva):
    - sem formatura: `lbl_aviso.text() == "Escolha a formatura."` e o Iniciar desligado;
    - com a ficha e a turma: o Iniciar ligado;
    - `build_request()` é `RequestFormatura` com `formatura.tipo == "oficina"` e
      `turma == "T106"`;
    - cada assignment tem `Role` traduzido.
  - `test_colacao_avisa`: com Colação e uma turma marcada, `lbl_aviso.text() == "A colação
    chega na próxima etapa (2.3)."` e o Iniciar desligado.
  - `test_feira_sem_turma_inicia`.
  - `test_reabrir_projeto_preenche`: grava o `projeto.json` e o `formatura.json` de uma
    oficina e chama `ProjetoTab(area="formatura").abrir_existente(evento)` com a fábrica falsa.
    Os combos devem mostrar a ficha e a turma, e a fábrica deve receber `RequestFormatura` com
    `formatura`.
  - `test_reabrir_com_ficha_apagada`: `lbl_aviso` "Formatura não encontrada. Escolha outra." e
    nenhuma exceção.
  - `test_duplicar`:
    - `duplicar_de(pasta_original)` copia tipo, formatura, duração e pasta de músicas, e marca
      `seguir_ideia`;
    - a mesma pasta escolhida em seguida é recusada com "Escolha a pasta da nova turma.";
    - `duplicado_de` guarda a pasta original.
  - `test_tabela_com_dias`: um evento com `2026-03-10\CAM A` e `2026-03-10\H4` gera linhas
    nessa ordem, com Câmera e Gravador.
  - `test_dialogo_formatura_salva`: preenche os campos, aceita, e o arquivo aparece em
    `listar`. Um erro de validação mostra a mensagem num banner do diálogo e não fecha.
  - **Substituir os provisórios:**
    - `test_areas_registradas_em_ordem` passa a verificar `area_por_id("formatura").pode_iniciar`;
    - `test_formatura_nao_inicia` vira `test_formatura_sem_trabalho_nao_inicia`, com o Iniciar
      desligado e o tooltip igual a "Escolha a formatura.";
    - `test_formatura_numera_gemini_como_5`: manter, se a numeração ficar igual.
- [ ] **Step 2: Run, verify FAIL**
- [ ] **Step 3: Implement.**
  - **Card "Trabalho":** fica sem número, inserido logo depois do card 1. Assim o Gemini
    continua como 5.
  - **Tabela:** a `tabela_f` substitui a `self.tabela` dentro do mesmo card. `self.tabela`
    fica escondida, mas continua carregada, para o `super().set_event_folder` funcionar.
  - **`set_event_folder`:** chama o `super()` e depois `tabela_f` recebe as linhas de
    `listar_pastas`.
  - **`assignments()`:** `FolderAssignment(folder, ROLE_DA_FUNCAO[f], day_label=dia)`.
  - **`build_request()`:** `RequestFormatura(**vars(super().build_request()),
    formatura=self.projeto_formatura())`.
  - **`load_request(req)`:** chama o `super()`, lê o `formatura.json` com
    `carregar_projeto(build_event_paths(req.source_dir, s, req.work_drive).analysis_dir)` e
    preenche o formulário.
  - **`_atualizar_iniciar`:** liga o Iniciar quando `source` existe, não está rodando e
    `motivo_bloqueio() == ""`. O `lbl_aviso` e o tooltip mostram o motivo.
  - **Motivos de bloqueio, em ordem:**
    1. "Escolha a pasta do evento."
    2. "Escolha a formatura."
    3. "Formatura não encontrada. Escolha outra."
    4. "Escolha a turma."
    5. "Marque as turmas da colação."
    6. "A colação chega na próxima etapa (2.3)."
  - **Duplicar:** lista as oficinas de `recentes.listar(s, [s.work_drive], area="formatura")`
    que têm `formatura.json` com tipo oficina, e escolhe por `QInputDialog.getItem`. Depois
    chama `duplicar_de(pasta)` e pede a pasta nova (`escolher_pasta`). A lógica fica em
    `duplicar_de`, testável sem diálogos.
  - **Formaturas…** abre o `DialogoCadastro`; **+ Nova** abre o `DialogoFormatura` vazio. Ao
    fechar, recarrega o `combo_formatura`.
  - Na colação, a tabela usa `funcoes_do_grupo("colacao")` e mostra o `combo_canais`.
- [ ] **Step 4: Run the full suite, PASS**
- [ ] **Step 5: Commit** com a mensagem "feat(formatura): formulário dos clipes e da colação,
  cadastro e duplicar".

---

### Task 6: Verificação real, briefing e envio

- [ ] **Step 1:** abrir o programa (`PYTHONPATH=src ../../.venv/Scripts/python.exe -m
  roteiro_ia.ui.app`, ou o ponto de entrada do `pyproject`) e conferir:
  - a área Formatura com o card Trabalho;
  - o diálogo de cadastro;
  - a tabela com dias.
- [ ] **Step 2:** rodar um evento curto de teste da pasta `tests/fixtures`, ou um gerado com
  `make_video`, no modo grátis, até o PDF e o XML. Se o Gemini não estiver disponível,
  registrar isso e rodar só até a etapa sem Gemini.
- [ ] **Step 3:** atualizar `docs/formaturas/briefing.md`, na seção de estado, com o que foi
  entregue e o que fica para a 2.3.
- [ ] **Step 4:** juntar ao master e enviar (autorizado pela memória "enviar ao GitHub
  sozinho"): `git checkout master` na pasta principal, `git merge --no-ff
  docs/formatura-briefing`, a suíte inteira no master e o `git push`.
