# Roteiro IA — Fase 1 — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Programa que analisa o material bruto de um casamento (somente leitura), gera um pré-roteiro em episódios + trailer/teaser/stories com trilhas sugeridas, entrega PDF e monta o projeto Premiere com proxies.

**Architecture:** Pacote Python `roteiro_ia` com etapas independentes (inventário → proxies → áudio/sincronização → transcrição → cenas → Gemini → trilhas → roteiro → PDF → XML) orquestradas por um pipeline retomável sobre um SQLite por projeto. Toda escrita em disco passa por um guarda que bloqueia `R:`/`M:` (e seus caminhos UNC). O Premiere recebe um XML FCP 7 + um `job.json`; um painel CEP com ExtendScript cria o `.prproj`, anexa proxies e faz backup.

**Tech Stack:** Python 3.12 (uv), pydantic v2, ffmpeg/ffprobe (NVENC), faster-whisper (CUDA), PySceneDetect, numpy/scipy, librosa, beat_this, google-genai, keyring, Jinja2, Microsoft Edge headless (HTML→PDF), PySide6, pytest. Painel: CEP 11 + ExtendScript (Premiere Pro 2024).

**Spec:** `docs/superpowers/specs/2026-11-03-roteiro-ia-fase1-design.md`

## Global Constraints

- `R:` e `M:` são **somente leitura**: nenhuma criação, renomeação, movimentação ou exclusão — inclusive pelos caminhos UNC equivalentes (`\\192.168.168.2\fokuss\R - EDITAR TIME`, `\\192.168.168.2\fokuss\M - MUSICAS`).
- Ano de todas as pastas = **ano do evento** (4 primeiros dígitos do nome da pasta no `R:`).
- Cliente padrão: `01 - FOKUSS`.
- Pasta de trabalho: `<DISCO>\EDIÇÃO <ANO>\<EVENTO>\` com `PROXIES\`, `ANALISE\`, `TRILHAS\`, `BACKUP PROJETO\`, `<EVENTO> - ROTEIRO.pdf`. Disco padrão `Y:`.
- Projeto: `E:\VÍDEOS <ANO>\01 - FOKUSS\<EVENTO>\<EVENTO>.prproj`; se existir → `<EVENTO>_v2.prproj`, `_v3`… nunca sobrescreve.
- Exports: `G:\<ANO>\01 - FOKUSS\<EVENTO>\` (criada vazia).
- Sistema: `Y:\SISTEMA ROTEIRO\` (`config.json`, `trilhas.db`, `perfil_estilo.json`, `ultimo_job.json`).
- Proxy: H.264 NVENC, altura **480**, proporção preservada, **mesmo fps e mesmo nº de canais de áudio** do original, sufixo `_Proxy`, em `PROXIES\<subpasta>\`.
- Prioridade de fonte de fala: mesa > lapela > gravador ambiente > câmera.
- Alvos de áudio: mesa **−3 dB** (média), ambiente **−18 dB**; ganho limitado a ±20 dB.
- Episódio: média **6 min** (360 s), flexível; nº de episódios informado ou "livre".
- Corte sugerido: lentas → tempos **1 e 3**; rápidas/intensas → **2 e 4**.
- Gemini: modo `gratis` (pausa e retoma no limite) ou `pago` (estimativa + aprovação antes de enviar). Aviso de privacidade do plano grátis exibido na interface.
- Ignorar sempre: `.pek`, `.cfa`, `.pkf`, `.prv`, pastas chamadas `Proxies`, `Adobe Premiere Pro *`.
- Toda interface e texto para o editor em **português**.

## Review Focus

1. **Caminhos com acento, espaço e apóstrofo** (`VÍDEOS 2023`, `EDIÇÃO`, `STYLLUS´S`) → XML, job.json e ExtendScript abrem o arquivo certo. Teste em Task 16 (`test_pathurl_acentos`) e Task 17 (`test_job_json_utf8`).
2. **Mesmo nome de arquivo em câmeras diferentes** (`A\C0001.MP4` e `B\C0001.MP4`) → proxies e referências do roteiro não colidem. Teste em Task 5 (`test_proxy_path_por_subpasta`) e Task 14 (`test_ref_usa_caminho_relativo`).
3. **Nome de pasta de evento fora do padrão exato** (`2026-05-08- EVENTO`, `2026-03-31 IMAGENS SITE`, sem data) → aceita variações de hífen/espaço; sem data dá erro claro em português. Teste em Task 2.
4. **NAS cai no meio / arquivo some** → etapa pausa e tenta de novo; arquivo que continua falhando vai para o relatório e o resto segue; rodar de novo retoma. Teste em Task 17 (`test_retoma_apos_oserror`).
5. **fps fracionários e vídeo vertical** (29.97, 59.94, 23.976; 1080×1920) → proxy com fps idêntico e XML com `timebase`/`ntsc` corretos. Teste em Task 5 e Task 16.

---

## Estrutura de arquivos

```
pyproject.toml
src/roteiro_ia/
  config.py          Settings, load/save, unidades protegidas (+UNC)
  safety.py          guarda de escrita (única porta para gravar em disco)
  paths.py           nome/ano do evento, EventPaths, criação de pastas, espaço
  models.py          modelos pydantic compartilhados
  db.py              ProjectDB (SQLite do projeto) + estado das etapas
  media/probe.py     ffprobe → MediaInfo
  inventory.py       varredura, sugestão de papel por subpasta
  media/proxies.py   comando ffmpeg, reaproveitamento .LRF
  media/audio.py     extração PCM, volume médio/pico, piso de ruído, ganho
  sync.py            linha do tempo real (hora + correlação de áudio)
  transcribe.py      faster-whisper, escolha de fonte
  scenes.py          PySceneDetect → segmentos
  gemini/client.py   cliente: modos, cota, reenvio, validação, custo, chave
  gemini/style.py    perfil de estilo a partir de URLs do YouTube
  gemini/analysis.py análise de cena por arquivo
  music_index.py     índice incremental de trilhas
  script/generate.py geração/revisão do roteiro + validação de referências
  report/pdf.py      HTML (Jinja2) → PDF (Edge headless) + SVG da curva
  report/templates/roteiro.html
  premiere/fcpxml.py XML FCP 7 (xmeml v4)
  premiere/job.py    job.json para o painel
  pipeline.py        orquestração retomável
  cli.py             `roteiro-ia` (linha de comando)
  ui/app.py          janela PySide6
premiere_panel/
  CSXS/manifest.xml  index.html  main.js  host/montar.jsx
  instalar_painel.ps1
tests/ (espelha src/) + tests/fixtures/make_media.py
```

---

### Task 1: Ambiente, configuração e guarda de escrita

**Files:**
- Create: `pyproject.toml`, `src/roteiro_ia/__init__.py`, `src/roteiro_ia/config.py`, `src/roteiro_ia/safety.py`, `.gitignore`
- Test: `tests/test_safety.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `Settings` (pydantic): `protected_roots: list[str] = ["R:\\", "M:\\"]`, `music_root: str = "M:\\"`, `work_drive: str = "Y:"`, `e_root: str = "E:\\"`, `g_root: str = "G:\\"`, `client_folder: str = "01 - FOKUSS"`, `system_dir: str = "Y:\\SISTEMA ROTEIRO"`, `gemini_mode: Literal["gratis","pago"] = "gratis"`, `gemini_model_analysis: str = ""`, `gemini_model_script: str = ""`, `price_usd_per_mtok: float = 0.0`, `style_urls: list[str] = []`, `copy_music_to_work: bool = False`, `noise_floor_threshold_db: float = -45.0`
  - `load_settings(path: Path | None = None) -> Settings` (padrão `Y:\SISTEMA ROTEIRO\config.json`; ausente → padrões)
  - `save_settings(s: Settings, path: Path | None = None) -> None`
  - `protected_paths(s: Settings) -> list[str]`: roots + equivalentes UNC obtidos de `net use` (normalizados, minúsculos)
  - `class ProtectedPathError(Exception)`
  - `assert_writable(path: Path, s: Settings) -> Path`
  - `safe_mkdir(path, s) -> Path`, `safe_write_text(path, text, s) -> None` (UTF-8), `safe_write_bytes(path, data, s)`, `safe_copy(src, dst, s) -> Path`

- [ ] **Step 1: Instalar ferramentas**

Run: `winget install --id astral-sh.uv -e; winget install --id Gyan.FFmpeg -e` e depois `uv python install 3.12`.
Expected: `uv --version` e `ffmpeg -version` respondem (abrir terminal novo).

- [ ] **Step 2: `pyproject.toml`** com `requires-python = ">=3.12,<3.13"`, pacote em `src/`, script `roteiro-ia = "roteiro_ia.cli:main"`, deps: pydantic, numpy, scipy, librosa, soundfile, faster-whisper, nvidia-cublas-cu12, nvidia-cudnn-cu12, scenedetect[opencv], beat_this, torch (índice CUDA 12), google-genai, keyring, jinja2, PySide6; dev: pytest. `.gitignore`: `.venv/`, `__pycache__/`, `tests/_tmp/`. Rodar `uv sync`.

- [ ] **Step 3: Testes que falham**

```python
def test_bloqueia_escrita_em_R(settings):
    with pytest.raises(ProtectedPathError):
        safe_write_text(Path(r"R:\2023\x.txt"), "a", settings)

def test_bloqueia_unc_equivalente(settings_unc):  # protected_paths inclui \\192.168.168.2\fokuss\m - musicas
    with pytest.raises(ProtectedPathError):
        assert_writable(Path(r"\\192.168.168.2\fokuss\M - MUSICAS\a.mp3"), settings_unc)

def test_bloqueia_letra_minuscula(settings):
    with pytest.raises(ProtectedPathError):
        assert_writable(Path(r"r:\2023\x.txt"), settings)

def test_permite_escrita_no_trabalho(tmp_path, settings):
    safe_write_text(tmp_path / "ok.txt", "ç", settings)
    assert (tmp_path / "ok.txt").read_text(encoding="utf-8") == "ç"

def test_safe_copy_destino_protegido_falha(tmp_path, settings): ...  # dst em M:\ → ProtectedPathError

def test_settings_roundtrip(tmp_path):
    s = Settings(style_urls=["https://youtu.be/x"]); save_settings(s, tmp_path/"c.json")
    assert load_settings(tmp_path/"c.json") == s
```
(fixture `settings_unc` monta `Settings` e faz monkeypatch de `protected_paths` para incluir o UNC; comparação sem diferenciar maiúsculas.)

- [ ] **Step 4:** `uv run pytest tests/test_safety.py tests/test_config.py -v` → FAIL (import).
- [ ] **Step 5: Implementar** `config.py` e `safety.py`. `assert_writable` normaliza com `os.path.abspath` + `casefold` e testa prefixo contra `protected_paths`. `protected_paths` chama `net use` via `subprocess` uma vez (cache) e mapeia `R:`/`M:` → UNC; falha de `net use` → só as letras.
- [ ] **Step 6:** testes → PASS.
- [ ] **Step 7: Commit** `feat: configuração e guarda de somente-leitura`

---

### Task 2: Caminhos do evento

**Files:**
- Create: `src/roteiro_ia/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: `Settings`, `safe_mkdir`
- Produces:
  - `class EventNameError(ValueError)`, `class InsufficientSpaceError(RuntimeError)`
  - `parse_event_name(folder_name: str) -> datetime.date` (regex `^(\d{4})-(\d{2})-(\d{2})\s*-?\s*\S`)
  - `@dataclass(frozen=True) EventPaths`: `event_name: str`, `event_date: date`, `year: int`, `source_dir`, `work_dir`, `proxies_dir`, `analysis_dir`, `music_dir`, `backup_dir`, `pdf_path`, `db_path` (`ANALISE\projeto.db`), `premiere_dir`, `prproj_path`, `export_dir` (todos `Path`)
  - `build_event_paths(source_dir: Path, s: Settings, work_drive: str | None = None) -> EventPaths`
  - `create_event_folders(p: EventPaths, s: Settings) -> None` (work, PROXIES, ANALISE, TRILHAS, BACKUP PROJETO, premiere_dir, export_dir)
  - `next_free_prproj(p: EventPaths) -> Path` (`_v2`, `_v3`…)
  - `estimate_proxy_gb(total_duration_s: float) -> float` = horas × 1.0 + 2.0
  - `check_free_space(p: EventPaths, required_gb: float) -> None`

- [ ] **Step 1: Testes que falham**

```python
@pytest.mark.parametrize("nome", ["2023-09-09 CASAMENTO NICOLE E OSNY", "2026-05-08- EVENTO ADHONEP", "2026-03-31 IMAGENS SITE", "2026-04-15 - PEDRO REIS"])
def test_parse_aceita_variacoes(nome): assert parse_event_name(nome).year in (2023, 2026)

def test_parse_sem_data_erro_pt():
    with pytest.raises(EventNameError, match="data"): parse_event_name("OFICINAS")

def test_caminhos_usam_ano_do_evento(settings):
    p = build_event_paths(Path(r"R:\2023\2023-09-09 CASAMENTO NICOLE E OSNY"), settings)
    assert str(p.work_dir) == r"Y:\EDIÇÃO 2023\2023-09-09 CASAMENTO NICOLE E OSNY"
    assert str(p.prproj_path) == r"E:\VÍDEOS 2023\01 - FOKUSS\2023-09-09 CASAMENTO NICOLE E OSNY\2023-09-09 CASAMENTO NICOLE E OSNY.prproj"
    assert str(p.export_dir) == r"G:\2023\01 - FOKUSS\2023-09-09 CASAMENTO NICOLE E OSNY"
    assert p.pdf_path.name == "2023-09-09 CASAMENTO NICOLE E OSNY - ROTEIRO.pdf"

def test_next_free_prproj(tmp_path, settings): ...  # cria .prproj e _v2 → retorna _v3
def test_estimate_proxy_gb(): assert estimate_proxy_gb(12*3600) == pytest.approx(14.0)
def test_espaco_insuficiente(monkeypatch, ...): ...  # shutil.disk_usage → free 1 GB, required 14 → InsufficientSpaceError com "GB" na mensagem
```
- [ ] **Step 2:** rodar → FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: caminhos e pastas do evento`

---

### Task 3: Modelos e banco do projeto

**Files:**
- Create: `src/roteiro_ia/models.py`, `src/roteiro_ia/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces (`models.py`, pydantic):
  - `Role(StrEnum)`: `camera, drone, pocket, audio_ambiente, mesa, lapela_noivo, lapela_noiva, outro_dia, ignorar`
  - `FolderAssignment(folder: str, role: Role, day_label: str = "principal")` (`outro_dia` → role da mídia é inferido por tipo: vídeo=`camera`, áudio=`audio_ambiente`, e `day_label` = nome da pasta)
  - `MediaInfo(id: int|None, rel_path: str, folder: str, role: Role, day_label: str, kind: Literal["video","audio"], duration_s: float, fps_num: int, fps_den: int, width: int, height: int, rotation: int, audio_channels: int, created_at: datetime|None, timecode: str|None)`
  - `AudioStats(media_id, mean_db: float, peak_db: float, noise_floor_db: float, noisy: bool)`
  - `SyncResult(media_id, day_label: str, timeline_start_s: float, confidence: float, method: Literal["audio","hora"])`
  - `Word(text: str, start_s: float, end_s: float)`; `Transcript(media_id, words: list[Word], source_role: Role)`
  - `Segment(id: int|None, media_id: int, start_s: float, end_s: float)`
  - `Highlight(start_s, end_s, reason: str)`; `Quote(text, start_s, end_s)`
  - `SceneAnalysis(segment_id: int, momento: str, extra: str|None, descricao: str, pessoas: list[str], emocao_intensidade: int (0–10), emocao_tipo: str, qualidade: int (0–10), problemas: list[str], melhores_trechos: list[Highlight], falas_chave: list[Quote], potencial_gancho: bool, motivo_gancho: str|None, sugestao_lembranca: bool)`
  - `TrackInfo(path: str, bpm: float, beats_s: list[float], downbeats_s: list[float], energy: list[float], duration_s: float, has_vocals: bool, perfil: Literal["calma","crescente","intensa"], mtime: float)`
- Produces (`db.py`): `ProjectDB(path: Path)` com tabelas `media, proxies, audio_stats, sync, transcripts, segments, analyses, roteiros, stages, falhas` e métodos:
  `add_media(m) -> int`, `list_media(role: Role|None=None) -> list[MediaInfo]`, `get_media(id)`, `media_by_rel(rel_path)`,
  `set_proxy(media_id, path, origem: Literal["gerado","lrf"])`, `proxy_for(media_id) -> str|None`,
  `set_audio_stats(a)`, `get_audio_stats(media_id)`, `set_sync(r)`, `get_sync(media_id)`,
  `set_transcript(t)`, `get_transcript(media_id)`, `add_segments(list[Segment])`, `list_segments(media_id=None)`,
  `set_analysis(a: SceneAnalysis)`, `get_analysis(segment_id)`, `add_roteiro(json_text) -> int (versão)`, `latest_roteiro() -> str|None`,
  `stage_status(name) -> Literal["pendente","rodando","pausado","feito","erro"]`, `set_stage(name, status, detail="")`,
  `add_falha(etapa, rel_path, msg)`, `list_falhas()`.
  Todas idempotentes (`INSERT OR REPLACE` por chave natural). Gravação do arquivo `.db` via caminho validado por `assert_writable`.

- [ ] **Step 1: Testes que falham:** `test_add_media_idempotente` (adicionar o mesmo `rel_path` 2× → 1 linha), `test_mesmo_nome_pastas_diferentes` (`A\C0001.MP4` e `B\C0001.MP4` → 2 ids), `test_stage_default_pendente`, `test_roteiro_versoes` (2 inserções → `latest_roteiro` é a segunda, versões 1 e 2), `test_analysis_roundtrip`, `test_db_em_R_bloqueado`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar (JSON em colunas TEXT para listas). **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: modelos e banco do projeto`

---

### Task 4: Inventário e ffprobe

**Files:**
- Create: `src/roteiro_ia/media/__init__.py`, `src/roteiro_ia/media/probe.py`, `src/roteiro_ia/inventory.py`, `tests/fixtures/make_media.py`
- Test: `tests/test_inventory.py`

**Interfaces:**
- Consumes: `MediaInfo`, `Role`, `FolderAssignment`, `ProjectDB`
- Produces:
  - `probe(path: Path) -> dict` (saída JSON do ffprobe) e `media_info_from_probe(path: Path, root: Path, a: FolderAssignment) -> MediaInfo` (fps de `r_frame_rate` como fração; `rotation` do side_data; `created_at` de `creation_time`)
  - `list_subfolders(source_dir: Path) -> list[str]`
  - `suggest_role(folder_name: str) -> Role`: letra única (`A`…`D`) → `camera`; contém `H4|ZOOM|TASCAM|GRAVADOR` → `audio_ambiente`; `MESA` → `mesa`; `LAPELA` + `NOIVO`/`NOIVA` → respectivo; `DRONE|DJI|MAVIC` → `drone`; `POCKET|OSMO|CELULAR` → `pocket`; `TRILHA|MUSICA|PROXIES` → `ignorar`; contém `DESPEDIDA|PRE|LUA DE MEL|MAKING|PADRINHOS` → `outro_dia`; senão `camera`.
  - `scan(source_dir: Path, assignments: list[FolderAssignment], db: ProjectDB, on_progress: Callable[[int,int],None] | None = None) -> int` — extensões vídeo `.mp4 .mov .mxf .mts .avi`, áudio `.wav .mp3 .m4a`; `.lrf` não entra como mídia; ignora a lista das Global Constraints; erro de ffprobe → `db.add_falha("inventario", …)` e segue.
  - `tests/fixtures/make_media.py`: `make_video(path, seconds, fps="30000/1001", size="1920x1080", channels=2, tone_hz=440)`, `make_audio(path, seconds, noise_seed, delay_s=0.0)` via ffmpeg `testsrc2`/`sine`/`anoisesrc`.

- [ ] **Step 1: Testes que falham:** `test_suggest_role` (parametrizado: `A`→camera, `E - H4`→audio_ambiente, `H - DESPEDIDA DE SOLTEIRO`→outro_dia, `TRILHAS`→ignorar), `test_scan_ignora_caches` (pasta com `x.pek`, `y.cfa`, `Proxies\z.mp4` → não entram), `test_scan_fps_fracionario` (vídeo 29.97 → `fps_num=30000, fps_den=1001`), `test_scan_vertical` (1080×1920 → width 1080, height 1920), `test_scan_arquivo_corrompido_vira_falha`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: inventário de mídia`

---

### Task 5: Proxies 480p

**Files:**
- Create: `src/roteiro_ia/media/proxies.py`
- Test: `tests/test_proxies.py`

**Interfaces:**
- Consumes: `MediaInfo`, `EventPaths`, `ProjectDB`, `safe_mkdir`
- Produces:
  - `proxy_path(m: MediaInfo, p: EventPaths) -> Path` = `PROXIES\<subpastas de rel_path>\<stem>_Proxy.mp4`
  - `ffmpeg_proxy_cmd(src: Path, dst: Path, m: MediaInfo, gpu: bool = True) -> list[str]`: `-c:v h264_nvenc` (`libx264` se `gpu=False`), **lado menor = 480** (horizontal `-vf scale=-2:480`; vertical `-vf scale=480:-2`, considerando `rotation`), `-r <fps_num>/<fps_den>`, `-b:v 2M`, `-c:a aac -b:a 128k -ac <audio_channels>`; sem áudio → `-an`.
  - `lrf_compatible(lrf: Path, m: MediaInfo) -> bool` (mesmo fps, mesma proporção ±1%, duração ±0.5 s)
  - `make_proxies(db: ProjectDB, p: EventPaths, s: Settings, source_root: Path, on_progress=None) -> None` — pula mídias com proxy existente; `.LRF` de mesmo stem compatível → copia (via `safe_copy`) como proxy com `origem="lrf"`; NVENC indisponível → refaz com `gpu=False`.

- [ ] **Step 1: Testes que falham:** `test_proxy_path_por_subpasta` (`A\C0001.MP4` e `B\C0001.MP4` → caminhos diferentes), `test_cmd_mantem_fps_e_canais` (29.97, 4 canais → `-r 30000/1001`, `-ac 4`), `test_cmd_vertical_lado_menor_480`, `test_proxy_real_mesmo_fps` (gera vídeo 59.94 de 2 s, roda `make_proxies` com `gpu=False` forçado, ffprobe do proxy → fps 60000/1001 e altura 480), `test_lrf_reaproveitado`, `test_nao_escreve_na_origem` (origem num `tmp_path` registrado como protegido em `settings` → proxies saem só em `PROXIES`).
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: geração de proxies 480p`

---

### Task 6: Medidas de áudio

**Files:**
- Create: `src/roteiro_ia/media/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Produces:
  - `load_mono(path: Path, sr: int = 8000, start_s: float = 0, dur_s: float | None = None) -> np.ndarray` (ffmpeg → float32 PCM via pipe; nunca grava em disco)
  - `measure(path: Path) -> tuple[float, float, float]` → (mean_db, peak_db, noise_floor_db). Média e pico via ffmpeg `volumedetect`; piso de ruído = percentil 10 do RMS em janelas de 50 ms, em dBFS.
  - `gain_for(role: Role, mean_db: float) -> float` = alvo − média (mesa −3, audio_ambiente −18, lapelas −3, camera −18), limitado a ±20.
  - `analyze_audio(db: ProjectDB, s: Settings, source_root: Path) -> None` → grava `AudioStats` (`noisy = noise_floor_db > s.noise_floor_threshold_db`).

- [ ] **Step 1: Testes que falham:** `test_measure_seno_volume_conhecido` (seno a −12 dBFS → mean ≈ −15 ±1, peak ≈ −12 ±0.5), `test_noise_floor_detecta_chiado` (fala sintética + ruído branco a −40 dB → noisy True; mesmo sinal sem ruído → False), `test_gain_limitado` (`gain_for(Role.mesa, -40) == 20`), `test_gain_ambiente` (`gain_for(Role.audio_ambiente, -24) == 6`).
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: medidas de áudio e ganho`

---

### Task 7: Sincronização (linha do tempo real)

**Files:**
- Create: `src/roteiro_ia/sync.py`
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `load_mono`, `ProjectDB`, `SyncResult`
- Produces:
  - `xcorr_offset(ref: np.ndarray, other: np.ndarray, sr: int) -> tuple[float, float]` → (offset_s de `other` em relação a `ref`, confiança = pico / 2º maior pico fora de ±0.1 s)
  - `sync_event(db: ProjectDB, source_root: Path, min_confidence: float = 3.0) -> None`

Algoritmo de `sync_event`, por `day_label`: (1) referência = mídia de áudio mais longa entre `mesa` → `audio_ambiente` → maior vídeo; (2) estimativa inicial de cada mídia = `created_at − created_at_ref`; (3) correlaciona FFT de uma janela de 60 s da mídia contra a referência em `estimativa ± 300 s` (8 kHz, envelope de energia se o sinal for longo); (4) confiança ≥ `min_confidence` → `method="audio"`; senão `method="hora"` com a estimativa; sem `created_at` e sem correlação → `confidence=0`, `timeline_start_s = soma das durações anteriores da mesma pasta` e falha registrada; (5) mídias sem áudio (drone) → `hora`.

- [ ] **Step 1: Testes que falham:** `test_xcorr_offset_conhecido` (ruído aleatório; cópia atrasada 2.5 s → 2.5 ±0.02, confiança > 3), `test_xcorr_sem_relacao_baixa_confianca` (dois ruídos independentes → confiança < 3), `test_sync_event_posiciona_camera` (referência de áudio 120 s; vídeo com o mesmo áudio do segundo 40 ao 70 e `created_at` errado em 20 s → `timeline_start_s ≈ 40`, método `audio`), `test_drone_sem_audio_usa_hora`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: sincronização das fontes`

---

### Task 8: Transcrição

**Files:**
- Create: `src/roteiro_ia/transcribe.py`
- Test: `tests/test_transcribe.py`

**Interfaces:**
- Consumes: `ProjectDB`, `SyncResult`, `Transcript`, `Word`
- Produces:
  - `SOURCE_PRIORITY = [Role.mesa, Role.lapela_noivo, Role.lapela_noiva, Role.audio_ambiente, Role.camera, Role.pocket]`
  - `plan_sources(db: ProjectDB) -> list[int]`: transcreve inteiras todas as mídias `mesa`, `lapela_*`, `audio_ambiente`; câmeras/pockets só se **não** houver sobreposição na linha do tempo com fonte melhor (usa `SyncResult`).
  - `class Transcriber(Protocol)`: `transcribe(path: Path) -> list[Word]`
  - `WhisperTranscriber(model: str = "large-v3", device: str = "cuda", compute_type: str = "int8_float16")` — `language="pt"`, `word_timestamps=True`, `vad_filter=True`; CUDA indisponível → `device="cpu", compute_type="int8"` com aviso.
  - `transcribe_event(db, source_root, t: Transcriber, on_progress=None) -> None` (pula já transcritas)
  - `words_between(t: Transcript, start_s, end_s) -> str`

- [ ] **Step 1: Testes que falham** (com `FakeTranscriber`): `test_plan_prefere_mesa_sobre_camera` (camera totalmente coberta por mesa → fora da lista), `test_plan_camera_sem_cobertura_entra`, `test_transcribe_event_pula_feitas` (fake conta chamadas: 2ª execução → 0), `test_words_between`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Teste manual de GPU:** `uv run python -c "from roteiro_ia.transcribe import WhisperTranscriber as W; print(W().transcribe(r'<um wav curto de fala em pt>')[:5])"` → palavras em português com tempos.
- [ ] **Step 6: Commit** `feat: transcrição com faster-whisper`

---

### Task 9: Segmentos de cena

**Files:**
- Create: `src/roteiro_ia/scenes.py`
- Test: `tests/test_scenes.py`

**Interfaces:**
- Produces:
  - `split_long(cuts: list[tuple[float,float]], max_s: float = 60.0, min_s: float = 2.0) -> list[tuple[float,float]]` (corta trechos > 60 s em partes iguais ≤ 60; junta < 2 s ao anterior)
  - `detect_segments(db: ProjectDB, p: EventPaths) -> None` — `ContentDetector` (PySceneDetect) sobre o **proxy**; mídias só de áudio → segmentos de 60 s; grava `Segment`s.

- [ ] **Step 1: Testes que falham:** `test_split_long` (`[(0,150)]` → `[(0,50),(50,100),(100,150)]`), `test_junta_curtos` (`[(0,10),(10,11),(11,30)]` → `[(0,11),(11,30)]`), `test_detect_em_video_com_corte` (fixture: 3 s de cor A + 3 s de cor B → 2 segmentos, corte em 3 ±0.2).
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: detecção de cenas`

---

### Task 10: Cliente Gemini

**Files:**
- Create: `src/roteiro_ia/gemini/__init__.py`, `src/roteiro_ia/gemini/client.py`
- Test: `tests/gemini/test_client.py`

**Interfaces:**
- Produces:
  - `KEYRING_SERVICE = "RoteiroIA-Gemini"`; `get_api_key() -> str | None`; `set_api_key(k: str) -> None`
  - `class QuotaPaused(Exception)`: `resume_at: datetime`
  - `class GeminiClient`: `__init__(s: Settings, backend=None)` (backend = `google.genai.Client` real ou fake)
    - `list_models() -> list[str]`; `pick_default_models() -> tuple[str, str]` (mais recente com "flash" p/ análise e "pro" p/ roteiro, a partir de `list_models`)
    - `upload(path: Path) -> object` (Files API; espera estado ACTIVE)
    - `generate_json(model: str, parts: list, schema: type[BaseModel], prompt: str, max_retries: int = 3) -> BaseModel` — `response_mime_type="application/json"`, `response_schema=schema`, `media_resolution=LOW` quando houver vídeo; JSON inválido → reenvia até `max_retries`, depois `ValueError`; HTTP 429 → em `gratis`: `QuotaPaused(resume_at = agora + retryDelay do erro, ou próxima 00:00 America/Los_Angeles se a mensagem indicar limite diário)`; em `pago`: espera exponencial (2, 4, 8… até 60 s) e tenta de novo.
    - `estimate_cost_usd(total_media_s: float) -> float` = `total_media_s × 100 tokens/s ÷ 1e6 × s.price_usd_per_mtok` (0 no modo grátis)
  - `PRIVACY_NOTICE_PT: str` = "No plano gratuito, o Google pode usar o conteúdo enviado para melhorar seus produtos. Use eventos com autorização ou o plano pago para clientes novos."

- [ ] **Step 1: Testes que falham** (backend fake): `test_json_invalido_reenvia_e_desiste` (3 respostas inválidas → `ValueError`, 3 chamadas), `test_json_valido_segunda_tentativa`, `test_429_gratis_pausa` (→ `QuotaPaused` com `resume_at` futuro), `test_429_pago_retenta` (1º 429, 2º ok → resultado; `sleep` monkeypatched), `test_estimate_cost` (`price=0.3`, 12 h → `12*3600*100/1e6*0.3 ≈ 1.296`), `test_pick_default_models` (lista fake com `gemini-x-flash`, `gemini-y-pro`).
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Teste real (opcional, marcado `@pytest.mark.gemini`, pulado sem chave):** `test_real_json_simples` pede `{"ok": true}` ao modelo flash.
- [ ] **Step 6: Commit** `feat: cliente Gemini com cota e validação`

---

### Task 11: Perfil de estilo (YouTube)

**Files:**
- Create: `src/roteiro_ia/gemini/style.py`
- Test: `tests/gemini/test_style.py`

**Interfaces:**
- Consumes: `GeminiClient.generate_json`, `Settings.style_urls`, `safe_write_text`
- Produces:
  - `VideoStyleNotes(url, tipo: Literal["episodio","teaser","trailer","outro"], duracao_s: float, ritmo_corte_s: float, abertura: str, gancho: str, uso_falas: str, trilha: str, cor: str, observacoes: str)`
  - `StyleProfile(fontes: list[str], duracao_media_episodio_s: float, ritmo_corte_medio_s: float, padroes_abertura: list[str], padroes_gancho: list[str], uso_falas: str, trilhas: str, cor: str, estrutura_teaser_trailer: str, resumo: str)`
  - `expand_playlists(urls: list[str]) -> list[str]` — URLs `watch?v=…&list=…` viram o vídeo do `v`; o editor pode listar vídeos individualmente (sem raspagem do YouTube).
  - `build_style_profile(c: GeminiClient, s: Settings) -> StyleProfile` — uma chamada por vídeo (`Part.from_uri(url, mime_type="video/*")`), depois uma chamada de agregação; salva em `<system_dir>\perfil_estilo.json`; vídeos já analisados ficam em cache em `<system_dir>\estilo_cache\`.
  - `load_style_profile(s) -> StyleProfile | None`

- [ ] **Step 1: Testes que falham** (fake): `test_expand_playlists_pega_v`, `test_build_usa_cache` (2ª execução não chama o backend para vídeos já vistos), `test_profile_salvo_em_system_dir`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. Prompts em português pedindo descrição técnica objetiva do estilo de edição. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: perfil de estilo a partir do YouTube`

---

### Task 12: Análise de cena

**Files:**
- Create: `src/roteiro_ia/gemini/analysis.py`
- Test: `tests/gemini/test_analysis.py`

**Interfaces:**
- Consumes: `GeminiClient`, `ProjectDB`, `words_between`, `SceneAnalysis`, `StyleProfile | None`
- Produces:
  - `MOMENTOS = ["preparação noiva","preparação noivo","first look","entrada","votos","alianças","beijo","saída","ensaio","entrada na festa","valsa","discursos","pista","despedida","pré-wedding","despedida de solteiro","lua de mel","extra"]`
  - `FileAnalysis(segmentos: list[SceneAnalysis])` (schema da resposta)
  - `build_prompt(media: MediaInfo, segments: list[Segment], transcripts: dict[int,str]) -> str` — lista os segmentos com `segment_id`, início/fim e a fala transcrita do trecho; pede um item por segmento; tempos de `melhores_trechos`/`falas_chave` **relativos ao arquivo**.
  - `analyze_event(db, c: GeminiClient, p: EventPaths, model: str, on_progress=None) -> None` — uma chamada por mídia (upload do proxy; mídia só de áudio → envia o áudio da melhor fonte), pula segmentos já analisados; `QuotaPaused` propaga; resposta com `segment_id` desconhecido ou faltando → reenvio; após 3 falhas → `add_falha("analise", …)`; tempos fora de `[start_s, end_s]` do segmento são recortados ao intervalo.

- [ ] **Step 1: Testes que falham** (fake): `test_prompt_contem_falas_e_ids`, `test_analise_grava_por_segmento`, `test_pula_ja_analisados`, `test_tempos_recortados_ao_segmento`, `test_quota_propaga`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: análise de cena com Gemini`

---

### Task 13: Índice de trilhas

**Files:**
- Create: `src/roteiro_ia/music_index.py`
- Test: `tests/test_music_index.py`

**Interfaces:**
- Consumes: `TrackInfo`, `Settings`
- Produces:
  - `class MusicIndex(path: Path)` (SQLite em `<system_dir>\trilhas.db`): `upsert(t)`, `get(path) -> TrackInfo|None`, `all() -> list[TrackInfo]`, `remove_missing(existing: set[str])`
  - `analyze_track(path: Path) -> TrackInfo` — `beat_this` para beats e downbeats (tempo 1); BPM = 60 / mediana dos intervalos entre beats; energia = RMS por segundo (librosa); `perfil`: energia média do último terço > 1.3× do primeiro → `crescente`; BPM ≥ 110 ou energia média alta → `intensa`; senão `calma`; `has_vocals` via razão de energia harmônica na faixa 300–3400 Hz (heurística simples, documentada no código).
  - `update_index(s: Settings, idx: MusicIndex, on_progress=None) -> int` — varre `music_root` (`.mp3 .wav .m4a`), pula se `mtime` igual; erro de leitura → log e segue.
  - `beat_positions(t: TrackInfo) -> list[tuple[float,int]]` → (tempo_s, nº do tempo 1–4) usando os downbeats.

- [ ] **Step 1: Testes que falham:** `test_bpm_click_120` (clique sintético 120 BPM com acento no tempo 1, 20 s → bpm 120 ±2), `test_beat_positions_ciclo_1_a_4`, `test_incremental_pula_inalteradas` (2ª execução → 0 analisadas), `test_perfil_crescente` (ruído com amplitude em rampa → `crescente`).
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: índice de trilhas com BPM e tempos`

---

### Task 14: Pré-roteiro

**Files:**
- Create: `src/roteiro_ia/script/__init__.py`, `src/roteiro_ia/script/generate.py`
- Test: `tests/script/test_generate.py`

**Interfaces:**
- Consumes: `GeminiClient`, `ProjectDB`, `MusicIndex`, `StyleProfile | None`
- Produces (pydantic):
  - `SceneRef(rel_path: str, start_s: float, end_s: float, descricao: str, fala: str | None, motivo: str | None, lembranca: bool = False)`
  - `MusicSuggestion(origem: Literal["biblioteca","musicbed","popular"], path: str | None, titulo: str, bpm: float | None, clima: str, motivo: str, padrao_corte: Literal["1-3","2-4","misto"], exige_licenca: bool)`
  - `Piece(tipo: Literal["episodio","trailer","teaser","stories"], numero: int | None, titulo: str, tema: str, abertura: SceneRef, desenvolvimento: list[SceneRef], gancho: SceneRef | None, gancho_resolve_em: str | None, curva_emocao: list[int], duracao_estimada_s: float, misturas: list[str], trilhas: list[MusicSuggestion], termos_musicbed: list[str])`
  - `Roteiro(arco: str, pecas: list[Piece], alertas: list[str])`
  - `build_catalog(db) -> str` (uma linha por segmento analisado: rel_path, início–fim, momento, emoção, qualidade, descrição, falas-chave, gancho)
  - `music_shortlist(idx: MusicIndex, n: int = 80) -> str` (variedade de BPM/perfil)
  - `generate_roteiro(db, c, idx, style, model: str, n_episodios: int | None, derivados: set[str], pedido_ajuste: str | None = None) -> Roteiro` — prompt com as regras da seção 2 da spec (gancho→abertura do próximo, mistura não-cronológica com motivo, conteúdo > técnica, 360 s de média, 1-3/2-4, lembranças) + perfil + catálogo + shortlist; `pedido_ajuste` envia o roteiro anterior + o pedido do editor (sem reanalisar material).
  - `validate_refs(r: Roteiro, db, idx) -> list[str]` — cada `SceneRef` precisa de mídia existente (`media_by_rel`) e intervalo dentro da duração; trilha `biblioteca` precisa existir no índice; retorna problemas.
  - Fluxo: até 2 rodadas de correção pedindo à IA que conserte os problemas; o que sobrar é removido e listado em `alertas`; grava com `db.add_roteiro`.

- [ ] **Step 1: Testes que falham** (fake): `test_validate_ref_inexistente`, `test_validate_intervalo_fora_da_duracao`, `test_ref_usa_caminho_relativo` (`A\C0001.MP4` e `B\C0001.MP4` resolvem para mídias diferentes), `test_corrige_e_remove_refs_ruins` (fake devolve 1 ref ruim nas 3 tentativas → removida e listada em `alertas`), `test_ajuste_reaproveita_sem_reanalisar` (com `pedido_ajuste`, o prompt contém o roteiro anterior e o pedido; nenhuma chamada de upload), `test_popular_marca_exige_licenca` (sugestão `popular` com `exige_licenca=False` vira `True`).
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: geração e validação do pré-roteiro`

---

### Task 15: PDF do roteiro

**Files:**
- Create: `src/roteiro_ia/report/__init__.py`, `src/roteiro_ia/report/pdf.py`, `src/roteiro_ia/report/templates/roteiro.html`
- Test: `tests/report/test_pdf.py`

**Interfaces:**
- Consumes: `Roteiro`, `EventPaths`, `ProjectDB.list_falhas`, `AudioStats`
- Produces:
  - `emotion_svg(curva: list[int], width: int = 480, height: int = 120) -> str`
  - `render_html(r: Roteiro, p: EventPaths, alertas_tecnicos: list[str]) -> str` — capa (evento, data), arco, uma seção por peça (abertura, desenvolvimento com falas, gancho → resolve em, curva, trilhas com BPM/clima/corte/licença, termos Musicbed, misturas, lembranças), alertas (ruído, refs removidas, falhas). Referência no formato `C\C0042.MP4 · 00:12:31–00:12:40`.
  - `fmt_tc(seconds: float) -> str` (`HH:MM:SS`)
  - `html_to_pdf(html: str, out: Path, s: Settings) -> None` — grava HTML temporário na pasta `ANALISE`, roda `msedge --headless=new --disable-gpu --no-pdf-header-footer --print-to-pdf=<out> <html>`; Edge procurado em `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` e `C:\Program Files\Microsoft\Edge\Application\msedge.exe`; não achou → erro claro.

- [ ] **Step 1: Testes que falham:** `test_fmt_tc` (`751.4` → `"00:12:31"`), `test_html_tem_gancho_e_licenca` (roteiro de exemplo → HTML contém "Gancho", "exige licença", "C\\C0042.MP4 · 00:12:31"), `test_svg_pontos` (curva de 5 valores → 5 pontos no polyline), `test_pdf_gerado` (marcado `windows`: arquivo existe e começa com `%PDF`).
- [ ] **Step 2:** FAIL. **Step 3:** implementar (CSS de impressão simples, A4). **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: PDF do roteiro`

---

### Task 16: XML para o Premiere (FCP 7)

**Files:**
- Create: `src/roteiro_ia/premiere/__init__.py`, `src/roteiro_ia/premiere/fcpxml.py`
- Test: `tests/premiere/test_fcpxml.py`

**Interfaces:**
- Consumes: `Roteiro`, `ProjectDB` (mídias, sync, audio_stats, transcripts), `MusicIndex`, `gain_for`, `EventPaths`
- Produces:
  - `pathurl(p: Path) -> str` — `file://localhost/R%3a/2023/…` com `urllib.parse.quote` (UTF-8; mantém `/`)
  - `timebase(fps_num: int, fps_den: int) -> tuple[int, bool]` — (30000,1001)→(30, True); (60000,1001)→(60, True); (24000,1001)→(24, True); (25,1)→(25, False)
  - `AUDIO_TRACKS = ["MESA", "AMBIENTE", "LAPELA NOIVO", "LAPELA NOIVA", "MÚSICA"]`
  - `build_sequence(piece: Piece, db, idx, music_path_map: dict[str,str]) -> ET.Element` — sequência 1920×1080 (stories: 1080×1920), timebase do ângulo principal mais comum; para cada `SceneRef` em ordem (abertura, desenvolvimento, gancho): V1 = o próprio clipe; V2…Vn = ângulos sobrepostos na linha do tempo real (via `SyncResult`) com `<enabled>FALSE</enabled>`; áudios sobrepostos das fontes `mesa`/`audio_ambiente`/`lapela_*` nas trilhas da lista, com filtro "Audio Levels" = `10^(gain_db/20)`; trilha sugerida nº 1 (`origem="biblioteca"`) na faixa MÚSICA ocupando a duração da sequência; marcadores: `ABERTURA`, `GANCHO`, `FALA: <texto>`, `RUÍDO` (fonte `noisy`), `LEMBRANÇA: <instrução>`.
  - `build_xml(r: Roteiro, db, idx, music_path_map) -> str` — `<xmeml version="4"><project>` com bins `EPISÓDIOS` (EP01…), `DERIVADOS` (TRAILER, TEASER, STORIES), `MATERIAL\<subpasta>` (todas as mídias), `TRILHAS`.
  - `write_xml(xml: str, p: EventPaths, s: Settings) -> Path` → `ANALISE\<EVENTO> - PREMIERE.xml`

- [ ] **Step 1: Testes que falham:** `test_pathurl_acentos` (`R:\2023\VÍDEOS 2023\STYLLUS´S\C0001.MP4` → contém `R%3a/2023/V%C3%8DDEOS%202023/` e decodificar volta ao caminho), `test_timebase_ntsc` (parametrizado com os 4 casos), `test_sequencias_por_peca` (roteiro com 2 episódios + teaser → sequências `EP01`, `EP02`, `TEASER`), `test_angulos_alternativos_desativados`, `test_ganho_mesa_aplicado` (mesa com média −9 → nível ≈ 10^(6/20)), `test_marcadores_gancho_e_ruido`, `test_stories_vertical` (1080×1920), `test_xml_bem_formado` (`ET.fromstring` sem erro).
- [ ] **Step 2:** FAIL. **Step 3:** implementar com `xml.etree.ElementTree`. **Step 4:** PASS.
- [ ] **Step 5: Verificação manual:** importar o XML gerado de uma fixture pequena no Premiere 2024 (*Arquivo → Importar*) → sequências e bins aparecem, clipes ligados, sem mídia offline.
- [ ] **Step 6: Commit** `feat: XML FCP7 para o Premiere`

---

### Task 17: Pipeline, linha de comando e job do painel

**Files:**
- Create: `src/roteiro_ia/pipeline.py`, `src/roteiro_ia/premiere/job.py`, `src/roteiro_ia/cli.py`
- Test: `tests/test_pipeline.py`, `tests/premiere/test_job.py`

**Interfaces:**
- Consumes: todas as etapas acima
- Produces:
  - `@dataclass ProjectRequest(source_dir: Path, work_drive: str, assignments: list[FolderAssignment], n_episodios: int | None, derivados: set[str], gemini_mode: Literal["gratis","pago"])`
  - `STAGES = ["inventario","proxies","audio","sync","transcricao","cenas","estilo","analise","trilhas","roteiro","pdf","premiere"]`
  - `class Pipeline(req: ProjectRequest, s: Settings, gemini: GeminiClient, transcriber: Transcriber, events: Callable[[str, str, float], None] | None)` — `events(stage, mensagem_pt, fração)`
    - `prepare() -> tuple[EventPaths, float]` (cria pastas, inventário, checa espaço; devolve paths + custo estimado; modo pago: UI exige aprovação antes de `run`)
    - `run() -> Literal["concluido","pausado"]` — cada etapa: pula se `feito`; marca `rodando`; `OSError` (rede) → até 5 tentativas com espera 10/20/40/80/160 s, depois `erro` e para com mensagem; `QuotaPaused` → `pausado` + grava `resume_at` em `stages.detail` e retorna `"pausado"`.
    - `revise(pedido: str) -> None` — regera roteiro, PDF e XML a partir do que já está no banco.
  - `music_paths(r: Roteiro, p: EventPaths, s: Settings) -> dict[str, str]` — trilhas `biblioteca` do roteiro; com `s.copy_music_to_work` copia cada uma (via `safe_copy`) para `TRILHAS\` e mapeia original→cópia; senão mapeia original→original. Usado como `music_path_map` da Task 16.
  - `write_job(p: EventPaths, s: Settings, xml_path: Path) -> Path` — `ANALISE\job.json` e cópia em `<system_dir>\ultimo_job.json`, UTF-8: `{"evento", "xml", "prproj", "backup_dir", "export_dir", "proxies": [{"original": "R:\\…", "proxy": "Y:\\…"}]}`. `prproj` = `next_free_prproj(p)`.
  - `cli.py`: `roteiro-ia novo <pasta_R> [--disco Y:] [--episodios N] [--sem-trailer] [--sem-teaser] [--sem-stories]` (pede confirmação dos papéis das subpastas no terminal), `roteiro-ia continuar <pasta_R>`, `roteiro-ia ajustar <pasta_R> "<pedido>"`, `roteiro-ia trilhas` (atualiza índice), `roteiro-ia estilo` (perfil), `roteiro-ia chave` (grava chave Gemini).

- [ ] **Step 1: Testes que falham** (etapas pesadas substituídas por fakes): `test_ordem_das_etapas`, `test_retoma_apos_oserror` (etapa `proxies` lança `OSError` 2× e depois passa → concluído; `sleep` monkeypatched), `test_oserror_persistente_marca_erro`, `test_quota_pausa_e_continua` (1ª `run` → `"pausado"`; 2ª → `"concluido"` sem repetir etapas feitas), `test_revise_nao_reprocessa_midia`, `test_job_json_utf8` (caminho com `VÍDEOS`/`EDIÇÃO` volta idêntico por `json.load`), `test_job_prproj_nao_sobrescreve`, `test_music_paths_copia_quando_configurado` (com `copy_music_to_work=True` → arquivo existe em `TRILHAS\` e o mapa aponta para ele; origem inalterada).
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Teste de integração com amostra** (`tests/test_integracao.py`, marcado `integracao`): fixture cria pasta fake de evento `2023-01-01 TESTE` com `A\` (2 vídeos), `B\` (1 vídeo), `E - H4\` (1 wav), roda tudo com Gemini fake e Whisper fake, protege a pasta de origem nas `Settings` → PDF e XML existem; nenhum arquivo novo na origem (comparar listagem antes/depois).
- [ ] **Step 6: Commit** `feat: pipeline retomável, CLI e job do Premiere`

---

### Task 18: Painel "Roteiro IA" no Premiere

**Files:**
- Create: `premiere_panel/CSXS/manifest.xml`, `premiere_panel/index.html`, `premiere_panel/main.js`, `premiere_panel/host/montar.jsx`, `premiere_panel/instalar_painel.ps1`, `premiere_panel/LEIA-ME.md`

**Interfaces:**
- Consumes: `ultimo_job.json` / `job.json` (Task 17)
- Produces: extensão `com.fokuss.roteiroia` (Host `PPRO` versão `[24.0,99.9]`, CEP 11).
  - `index.html`: título "Roteiro IA", botão **Escolher job** (padrão `Y:\SISTEMA ROTEIRO\ultimo_job.json`), botão **Montar projeto**, área de log.
  - `montar.jsx` → `montarProjeto(jobPath) -> String` (JSON `{ok, mensagens[]}`):
    1. lê job (`File.encoding = "UTF-8"`);
    2. `Folder(...).create()` para pasta do `.prproj` e `export_dir`;
    3. `app.newProject(job.prproj)`; se falhar, abre o projeto atual e usa `saveAs`;
    4. `app.project.importFiles([job.xml], true, app.project.rootItem, false)`;
    5. percorre os itens do projeto recursivamente; para cada item cujo `getMediaPath()` (normalizado, minúsculas, `/`) bate com `original` → `canProxy()` e `attachProxy(proxy, 0)`; conta anexados/falhas;
    6. `app.project.save()`; copia o `.prproj` para `backup_dir` com `File.copy` (nome com data/hora);
    7. retorna resumo em português.
  - `instalar_painel.ps1`: define `HKCU:\Software\Adobe\CSXS.11\PlayerDebugMode = "1"` e copia `premiere_panel` para `%APPDATA%\Adobe\CEP\extensions\com.fokuss.roteiroia`.
  - `LEIA-ME.md`: instalação + **configurar o cache de mídia** (*Preferências → Cache de mídia* → local `Y:\TEMP PREMIERE`; desmarcar "Salvar arquivos de cache de mídia ao lado dos originais quando possível").

- [ ] **Step 1:** escrever os arquivos.
- [ ] **Step 2:** rodar `instalar_painel.ps1`; reiniciar o Premiere → *Janela → Extensões → Roteiro IA* aparece.
- [ ] **Step 3: Verificação manual com o job da amostra da Task 17:** clicar **Montar projeto** → `.prproj` criado no caminho do job; sequências importadas; *Alternar proxies* troca para o proxy do `Y:`; desligado, mostra o original; backup no `BACKUP PROJETO`; pasta do `G:` criada; segunda execução cria `_v2`.
- [ ] **Step 4:** se `attachProxy` falhar no Premiere 2024, o painel lista os clipes e o LEIA-ME documenta o plano B: selecionar a bin `MATERIAL` → *Proxy → Anexar proxies* → apontar para `PROXIES`.
- [ ] **Step 5: Commit** `feat: painel Roteiro IA para o Premiere`

---

### Task 19: Janela do programa (PySide6)

**Files:**
- Create: `src/roteiro_ia/ui/__init__.py`, `src/roteiro_ia/ui/app.py`, `src/roteiro_ia/ui/worker.py`
- Modify: `pyproject.toml` (script `roteiro-ia-janela = "roteiro_ia.ui.app:main"`)
- Test: `tests/ui/test_worker.py`

**Interfaces:**
- Consumes: `Pipeline`, `ProjectRequest`, `suggest_role`, `list_subfolders`, `GeminiClient`, `PRIVACY_NOTICE_PT`, `set_api_key`
- Produces:
  - `PipelineWorker(QObject)`: sinais `progresso(str etapa, str msg, float fração)`, `terminou(str status)`, `erro(str msg)`; roda `Pipeline.run` numa `QThread`.
  - **Visual (pedido do editor): moderno, limpo e prático.** Tema escuro por padrão (combina com o Premiere), uma fonte sem serifa, cantos arredondados, um único tom de destaque, espaçamento generoso, ícones de estado (✔ ▶ ⏸ ○ ✖) em vez de texto técnico, nada de jargão. Estilo via QSS em `src/roteiro_ia/ui/tema.qss`. O fluxo cabe numa tela sem rolagem em 1920×1080. O painel do Premiere (Task 18) usa o mesmo tema.
  - Janela em português:
    1. **Pasta do evento** (seletor iniciando em `R:\`) — mostra nome/data lidos; erro de nome sem data aparece em vermelho.
    2. **Disco de trabalho** (padrão `Y:`) e espaço livre.
    3. **Tabela de subpastas** com combo de papel (sugestão de `suggest_role`) e campo "dia" para `outro_dia`.
    4. **Episódios**: número ou "livre"; checkboxes **Trailer**, **Teaser**, **Stories/Reels** (marcados).
    5. **Gemini**: Grátis/Pago, aviso de privacidade visível no modo grátis, botão "Configurar chave".
    6. **Iniciar** → no modo pago, diálogo "Custo estimado: US$ X. Continuar?".
    7. Barra por etapa + log; estado `pausado` mostra "Limite gratuito atingido. Continua automaticamente às HH:MM" e agenda `QTimer` para `run()` de novo.
    8. Ao concluir: botões **Abrir PDF**, **Pedir ajuste no roteiro** (caixa de texto → `revise`) e a instrução "No Premiere: Janela → Extensões → Roteiro IA → Montar projeto".
  - Abas extras: **Trilhas** (atualizar índice do `M:`), **Estilo** (lista de URLs + gerar perfil), **Configurações** (unidades, cliente, preço por milhão de tokens, copiar trilhas para o Y:).

- [ ] **Step 1: Teste que falha:** `test_worker_emite_progresso_e_terminou` (Pipeline fake emitindo 2 eventos; `qtbot`/loop simples verifica sinais e status `"concluido"`).
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5: Verificação manual:** `uv run roteiro-ia-janela` → fluxo completo com a pasta de amostra da Task 17.
- [ ] **Step 6: Commit** `feat: janela do Roteiro IA`

---

### Task 20: Aceitação com um casamento real

**Files:**
- Create: `docs/ACEITACAO-FASE1.md` (resultado)

- [ ] **Step 1:** configurar chave Gemini (`roteiro-ia chave`), escolher modelos, cadastrar os links das séries publicadas e rodar `roteiro-ia estilo` → `perfil_estilo.json` coerente.
- [ ] **Step 2:** `roteiro-ia trilhas` (índice completo do `M:`, em segundo plano) → contagem ≈ número de mp3/wav/m4a.
- [ ] **Step 3:** antes de rodar, salvar listagem (nome, tamanho, data) de `R:\2023\2023-09-09 CASAMENTO NICOLE E OSNY` em `Y:\SISTEMA ROTEIRO\antes.txt`.
- [ ] **Step 4:** rodar o evento pela janela (modo grátis), deixando retomar entre dias se preciso.
- [ ] **Step 5:** comparar listagem do `R:` e do `M:` antes/depois → **idênticas**.
- [ ] **Step 6:** Montar projeto no Premiere; conferir sequências, proxies, render usando o original do `R:` (exportar 10 s e checar resolução).
- [ ] **Step 7:** editor compara o PDF com a série publicada e registra em `docs/ACEITACAO-FASE1.md`: tempo total, chamadas/custo do Gemini, qualidade do roteiro (aproveitou a maior parte da estrutura?), problemas encontrados.
- [ ] **Step 8: Commit** `docs: resultado da aceitação da Fase 1`
