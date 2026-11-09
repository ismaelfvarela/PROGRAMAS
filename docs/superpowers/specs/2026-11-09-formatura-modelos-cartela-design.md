# Formatura 2.5: modelos do ano e cartela (design)

Data: 2026-11-09. Decisões do usuário:

- criar um **espaço para os vídeos modelo**, porque a versão pode mudar a cada ano;
- cartela pela **opção C**: usar o **MOGRT** do ano quando houver; senão, o sistema monta uma
  **cartela simples** com os dados.

Há outro chat (séries de casamento) no master: **nenhum arquivo comum** é alterado, só o painel do
Premiere, que é da plataforma mas só ganha código novo.

## 1. Modelos do ano

- Ficam nos ajustes da Formatura (`FORMATURAS\_ajustes.json`):
  `modelos: dict[str, ModeloAno]`, com chave = ano e
  `ModeloAno(pasta: str | None, mogrt: str | None)`.
- **Janela "Formaturas…":** seção "Modelos do ano", com uma tabela Ano | Pasta dos vídeos modelo
  | Cartela MOGRT e os botões Adicionar ano, Escolher pasta…, Escolher MOGRT… e Remover. Grava na
  hora.
- `modelos_do_ano(s, ano) -> ModeloAno | None`: o do ano. Sem ele, usa o do **ano mais recente que
  não passe do ano pedido**. Sem nenhum, `None`.
- Os arquivos são **só lidos**.

## 2. Estilo a partir dos vídeos modelo

- `estudar_modelos(c, s, ano, pasta) -> StyleProfile | None`, em `areas/formatura/modelos.py`.
  - Cada vídeo da pasta (extensões de vídeo do inventário, sem subpastas) é enviado ao Gemini
    (`c.upload`) e descrito com o `PROMPT_VIDEO` da Formatura.
  - Cache por arquivo (caminho, tamanho e data) em
    `estilo_cache\formatura_modelos\<chave>.json`. Um vídeo trocado é estudado de novo.
  - O perfil agregado (`PROMPT_AGG`) fica em `perfil_estilo_formatura_<ano>.json`. Ele é refeito só
    quando a lista de vídeos muda.
  - Vídeo que falhou → aviso no log, e os outros seguem. Nenhum vídeo → `None`.
- **Pipeline:**
  - `_st_estilo`: se o ano da formatura tem pasta de modelos, estuda os modelos e não roda o
    estudo por links. Na colação, o estilo **passa a rodar** (os clipes de abertura e encerramento
    usam).
  - `_perfil`: o perfil do ano, quando existe. Senão, o de sempre, o dos links da aba Estilo.

## 3. Cartela

**Onde entra:** no início do clipe (Oficina, Feira, Prova de toga, Paraninfo) e no início do
"00 - Abertura" da colação, por **5 s**.

**Campos** (`campos_cartela(pf, ficha, data)`), nesta ordem: Instituição, Curso, Turma,
Formatura ("2026/2"), Semestre ("2º semestre"), Ano, Turmas (colação: "Curso — Turma; …"),
Local, Cidade e Data. Os vazios ficam de fora.

**Com MOGRT no ano (opção B):**

- O `job.json` ganha `cartela: {mogrt, sequencias: [...], campos: {nome: valor}}`.
- O painel do Premiere, no fim do "Montar projeto", insere o MOGRT no início de cada sequência
  listada, numa faixa de vídeo acima das usadas (`seq.importMGT`), e preenche cada campo do MOGRT
  cujo **nome de exibição** é igual a um nome da lista (`getMGTComponent().properties.
  getParamForDisplayName(nome).setValue(valor)`).
- Campo do MOGRT sem dado, ou dado sem campo, vira aviso no registro do painel.

**Sem MOGRT (opção A, cartela simples):**

- `gerar_cartela_png(campos, logo_escola, saida)`: um PNG 1920×1080 com **fundo transparente**,
  gerado pelo ffmpeg (`drawtext`, fonte Segoe UI do Windows; sem ela, a padrão).
  - O logo da escola vai no alto, centralizado (até 300 px de altura), quando o arquivo existe.
  - A instituição fica grande, e o resto uma linha por campo.
  - Texto branco com sombra.
  - O PNG fica em `ANALISE\cartela.png`.
- `colocar_cartela(xml, nomes, png, dur_s=5)`: põe o PNG como imagem parada numa **faixa de vídeo
  nova, por cima**, no início das sequências nomeadas, com o marcador "CARTELA" e uma bin
  GRAFISMOS.
- Falha do ffmpeg → aviso, e o XML segue sem cartela.

## Componentes

- `ajustes.py`: `ModeloAno`, `AjustesFormatura.modelos` e `modelos_do_ano`.
- `modelos.py`: o estudo dos modelos.
- `cartela.py`: `campos_cartela`, `gerar_cartela_png`, `colocar_cartela` e `job_cartela`.
- `ui_cadastro.py`: a seção "Modelos do ano".
- `pipeline.py`:
  - `_st_estilo` e `_perfil`, como acima;
  - o `_st_premiere` dos clipes (depois do comum) e o da colação aplicam a cartela, com o MOGRT no
    job ou o PNG no XML.
- `premiere_panel/host/montar.jsx`: `_ri_cartela(job, msgs)`, chamado no fim de `montarProjeto`.

## Testes

- Modelos: gravar e ler, o ano mais recente que não passe do pedido, nenhum ano.
- Estudo:
  - envia cada vídeo uma vez;
  - o cache por arquivo funciona (um vídeo trocado é estudado de novo);
  - o perfil é gravado por ano;
  - a falha de um vídeo não derruba os outros;
  - a pasta vazia dá `None`.
- Pipeline: o `_perfil` usa o do ano; a colação estuda o estilo.
- Cartela:
  - campos de um clipe e de uma colação;
  - o PNG é gerado e transparente (ffprobe: `rgba`, 1920×1080);
  - `colocar_cartela` cria uma faixa nova com o clipitem do PNG no início e o marcador;
  - `job_cartela` com o MOGRT.
- Painel: `_ri_cartela`, `importMGT`, `getMGTComponent` e `getParamForDisplayName` no jsx (ASCII e
  ES3).
- Interface: a seção de modelos grava ano, pasta e MOGRT.
- Integração: a oficina e a colação com a cartela no XML.
