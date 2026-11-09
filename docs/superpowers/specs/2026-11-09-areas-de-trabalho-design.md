# Áreas de trabalho (Casamento | Formatura): design

Data: 2026-11-09. Parte 1 de 3 da expansão do Roteiro IA para outros serviços da Fokuss.

## Contexto e objetivo

Hoje o Roteiro IA só conhece casamento. A Fokuss vai usá-lo também para formaturas (briefing em
`docs/formaturas/briefing.md`) e, no futuro, para outros serviços. O objetivo desta parte é
separar o programa em **áreas de trabalho**, uma por tipo de serviço, sem mexer no que já
funciona para casamento.

O trabalho foi dividido em três partes, nesta ordem (decisão do usuário):

1. **Áreas de trabalho + fila** (este documento).
2. **Formatura funcionando:** questionário completo, cartela, clipes e colação (spec própria,
   depende das perguntas em aberto do briefing).
3. **Várias máquinas:** programa instalado em vários PCs, com uma pasta central na rede para o
   que é comum (estilos, índice das trilhas, logos, vinhetas e modelos). Cada máquina guarda só
   o próprio disco de trabalho, a chave do Gemini e os recentes. Spec própria.

## Princípios (o que o usuário pediu)

- **O Casamento não se mexe.** Código, formulário, regras do roteiro, momentos, Premiere e
  projetos existentes ficam como estão. A única mudança no fluxo do casamento é a **escolha da
  pasta de músicas** (abaixo).
- **Tudo o que der para usar em comum é comum:** etapas do pipeline (inventário, proxies, áudio,
  sincronização, transcrição, cenas, índice de trilhas, envio ao Gemini, PDF, painel do
  Premiere), técnicas de edição e de sensibilidade e o **padrão visual dos vídeos**.
- **Diferente por área:** os **estilos** (links dos vídeos de referência) e os **questionários**
  (campos do formulário do projeto). Na Formatura também muda **o que se entrega** (clipes e
  colação em partes, em vez da série de episódios), mas não o jeito de editar.
- **Nomes seguem o padrão Fokuss:** tudo o que se refere a um evento tem a data antes do assunto,
  no formato `AAAA-MM-DD NOME` (ano-mês-dia com traço). Vale para a pasta do evento em todas as
  áreas (como o Casamento já exige hoje em `paths.parse_event_name`) e para todo nome que o
  sistema gerar ligado ao evento (projetos, arquivos, sequências e entregas).
- **Áreas futuras** seguem a mesma receita da Formatura.

## Arquitetura

### Pacote de áreas

Novo pacote `src/roteiro_ia/areas/`:

- `areas/__init__.py`: registro das áreas (`AREAS`), em ordem de exibição, e
  `area_por_id(id) -> Area`.
- `areas/base.py`: a descrição de uma área (`Area`), com:
  - `id` (`"casamento"`, `"formatura"`) e `nome` para exibir;
  - `cor`/ícone do botão no seletor;
  - `formulario`: a classe do formulário do projeto daquela área;
  - `pode_iniciar: bool` e `aviso_iniciar: str` (Formatura: `False`, "chega na próxima etapa");
  - `musicas_padrao_cfg`: de onde vem a pasta de músicas padrão (config da área).
- `areas/casamento.py`: aponta para o que já existe (`ui/formulario.FormularioEvento`,
  pipeline atual). Não copia nem altera nada do casamento.
- `areas/formatura/`: as versões próprias da Formatura. Nesta parte, só o formulário base
  (`formulario.py`) e a lista de momentos do briefing (`momentos.py`), que a parte 2 usa.

Se uma etapa "comum" tiver algo de casamento fixo por dentro (por exemplo, `gemini/analysis.py`
usa a lista `MOMENTOS`), a Formatura faz a própria versão dessa etapa na parte 2, em
`areas/formatura/`, em vez de alterar a original.

### Janela

`ui/app.MainWindow` passa a ter, acima das abas, um **seletor de área**: um botão por área de
`AREAS`, com ícone e nome. O programa abre na última área usada (gravada nas configurações).

Dentro de cada área ficam as abas:

| Aba | Casamento | Formatura |
|---|---|---|
| Projeto | formulário atual + pasta de músicas | formulário base da Formatura + pasta de músicas |
| Estilo | links de casamento (os atuais) | links de formatura (começa vazio) |
| Trilhas | aba comum (a mesma instância) | aba comum (a mesma instância) |
| Configurações | aba comum (a mesma instância) | aba comum (a mesma instância) |

Implementação: um `QStackedWidget` com uma página por área. Cada página tem as próprias
`ProjetoTab` e `EstiloTab`. Trilhas e Configurações são widgets únicos: ao trocar de área, eles
são tirados das abas da área anterior e colocados nas abas da área nova, na mesma posição, para
existir uma só instância de cada. A barra geral (Pausar/Continuar/Parar tudo) continua única e age em todas
as áreas.

O seletor mostra uma marca na área que **não** está à vista quando ela tem projeto rodando ou na
fila.

### Formulário base da Formatura (nesta parte)

Mesmo comportamento do formulário do casamento nas partes comuns: pasta do evento (validada no
padrão `AAAA-MM-DD NOME`), disco de trabalho e espaço livre, funções das pastas, modo Gemini e
pasta de músicas. As funções das pastas e as perguntas específicas (dados da cartela, turmas…)
ficam para a parte 2. **Iniciar** fica desligado com o aviso "chega na próxima etapa". O
formulário deve ser feito de modo que a parte 2 só acrescente campos.

### Pasta de músicas por projeto (Casamento e Formatura)

- No formulário, campo **Pasta de músicas** com botão para escolher qualquer pasta. Vale a pasta
  e **todas as subpastas**. A pasta pode estar fora do M:, por exemplo uma pasta do próprio evento
  com as músicas já definidas.
- O campo já vem preenchido com a **pasta padrão da área** (configuração da área; se não houver,
  `music_root`).
- O índice das trilhas continua **um só**. A pasta escolhida vira um **filtro**: na hora de
  sugerir músicas para o roteiro, só entram as que estão dentro dela.
- Antes do roteiro, o projeto analisa as músicas da pasta escolhida que ainda não estão no índice
  ou mudaram, com a mesma rotina do índice (`music_index`). Hoje ela varre só `music_root`; passa
  a aceitar uma pasta específica.
- A pasta escolhida é **somente leitura** (entra na proteção de `safety`, como R: e M:).
- Projetos sem o campo usam a pasta padrão. No Casamento isso dá exatamente o comportamento
  atual (`music_root` inteiro).

### Fila no mesmo PC

- Novo `ui/fila.FilaProjetos`, dono da ordem de execução dos projetos de **todas** as áreas.
- Ao clicar em Iniciar/Continuar com outro projeto rodando, o novo entra na fila e mostra:
  "Na fila — começa quando *2023-09-09 CASAMENTO NICOLE E OSNY* terminar".
- Quando o projeto da vez **termina, para ou dá erro**, o próximo da fila começa sozinho.
- Quando o projeto da vez **pausa esperando a cota do Gemini**, o próximo da fila começa e
  adianta as etapas que não usam o Gemini. Quando chegar a uma etapa que precisa do Gemini, ele
  também espera a cota. Quando a cota volta, a prioridade é de quem entrou primeiro.
- Tirar da fila: botão "Tirar da fila" no projeto que espera.
- A fila fica só na memória. Ao fechar o programa, cada projeto continua de onde parou pelo
  "Continuar", como hoje.
- Tarefas que não são projeto (indexar trilhas, estudar estilo) não entram na fila; continuam
  como hoje.

## Dados

### `config.json` (`Settings`)

- Novo `areas: dict[str, ConfigArea]`, com `ConfigArea` contendo `style_urls: list[str]` e
  `pasta_musicas: str` (vazio = `music_root`).
- Novo `area_atual: str = "casamento"`.
- **Migração automática:** se `areas["casamento"]` não existir, ele é criado com o
  `style_urls` atual. O campo antigo `style_urls` continua lido e gravado para não quebrar o
  código do casamento, que segue lendo `s.style_urls`. As duas cópias ficam sincronizadas ao
  salvar.
- O perfil de estilo gerado (cache do estudo de estilo) passa a ser por área. O arquivo do
  casamento mantém o nome atual.

### `projeto.json` (`ProjectRequest`)

- Novos campos `area: str = "casamento"` e `pasta_musicas: str | None = None`.
- `from_dict` aceita arquivos antigos sem esses campos (lidos como Casamento, pasta padrão).

### `recentes.json`

- Cada item ganha `area`. Itens antigos sem área contam como Casamento.
- Projetos achados no disco de trabalho tomam a área do próprio `projeto.json`.
- A lista de "Continuar projeto existente" de cada área mostra só os projetos dela.

## Erros e casos de borda

- Pasta de músicas escolhida que não existe mais ou está vazia: aviso no formulário; o roteiro
  segue sem sugestão de música dessa pasta (mesmo comportamento de hoje sem trilhas).
- Pasta do evento fora do padrão `AAAA-MM-DD NOME`: recusada, com a mensagem de hoje, nas duas
  áreas.
- Trocar de área com projeto rodando: permitido; o projeto continua e a marca aparece no seletor.
- Fechar o programa com fila: o aviso atual de tarefas em andamento passa a citar também os
  projetos na fila.

## Testes

- **Todos os testes atuais continuam passando sem mudança.** É a prova de que o Casamento não
  mudou.
- Novos testes:
  - seletor: troca de área, área lembrada ao reabrir, Trilhas e Configurações são as mesmas
    instâncias nas duas áreas;
  - Formatura: Iniciar desligado com o aviso; pasta fora do padrão recusada;
  - recentes separados por área; item antigo lido como Casamento;
  - `projeto.json` antigo lido como Casamento com a pasta padrão;
  - migração do `config.json` antigo (`style_urls` vira os do Casamento);
  - filtro da pasta de músicas: subpastas incluídas; pasta fora do M: indexada e protegida;
  - fila: o segundo espera; começa quando o primeiro termina, para ou dá erro; adianta quando o
    primeiro pausa pela cota; "Tirar da fila".
- Por último, abrir o programa de verdade e conferir o seletor e as duas áreas.

## Fora desta parte

- Questionário completo da Formatura, cartela, clipes, colação, funções das pastas da
  Formatura e a versão da análise com os momentos da Formatura (parte 2).
- Pasta central na rede e instalação em várias máquinas (parte 3).
