# Roteiro IA — Fase 1: Análise e Pré-Roteiro

**Data:** 2026-11-03
**Empresa:** Fokuss
**Status:** aguardando revisão

---

## 1. Objetivo

Automatizar a parte mais demorada da edição de séries de casamento (e eventos
narrativos): **organizar 12h+ de material bruto e montar a sequência pela emoção,
não pela ordem cronológica**.

O sistema analisa todo o material de um evento, monta um **pré-roteiro em
episódios** (cada episódio com abertura e gancho que se resolve no próximo), além
do roteiro de **trailer, teaser e stories/redes sociais**, sugere **trilhas** e
entrega:

- um **PDF** com o roteiro completo;
- um **projeto Premiere** já organizado, com uma timeline de pré-montagem por
  episódio/derivado.

**Ponto humano desta fase:** o editor **aprova (ou ajusta) o roteiro**. Todo o
resto é automático.

### Visão geral do projeto (3 fases)

| Fase | Entrega | Ponto humano |
|---|---|---|
| **1. Análise e roteiro** (este documento) | Catálogo do material, perfil de estilo, pré-roteiro, PDF, Premiere organizado | Aprovar roteiro |
| 2. Edição automática | Cortes na batida, escolha de ângulo, mixagem de áudio, LUT | Revisar edição |
| 3. Finalização e derivados | Efeitos de lembrança, trailer/teaser/stories montados, render para o G: | Aprovar vídeo final |

As Fases 2 e 3 terão especificações próprias.

---

## 2. Estilo de edição da Fokuss (regras que o sistema segue)

- **Narrativa em série:** o evento é contado em episódios; cada episódio termina num
  **gancho** que só se resolve na **abertura do episódio seguinte**.
- **Ordem não-cronológica controlada:** a cronologia é a base, mas quando um trecho
  vai baixar a emoção, puxa-se um momento de outra parte do evento (preparação,
  despedida de solteiro, pré-wedding, lua de mel…) para manter a intensidade.
- **Áudio real como fio condutor:** falas que contam a história de verdade (votos,
  discursos, depoimentos).
- **Prioridade das imagens:** 1º **conteúdo/história** (se só existe um take ruim de
  um momento importante, ele é usado); 2º **técnica/qualidade** entre opções
  equivalentes.
- **Episódios:** média de **6 min**, flexível. Quantidade informada no início
  (conforme contrato) ou livre.
- **Cortes na trilha** (usado nas sugestões desta fase; aplicado na Fase 2):
  músicas lentas → tempos **1 e 3**; músicas rápidas ou trechos de mais intensidade
  → tempos **2 e 4**.
- **Áudio** (alvos registrados agora, mixagem completa na Fase 2):
  - mesa de som (limpo): fonte preferida para falas, **−3 dB média e pico**,
    limitador de proteção em −1 dB;
  - ambiente: sempre presente, **−18 dB**, corte de graves (passa-alta ~100–120 Hz);
  - lapelas dos noivos: **primeiro plano quando eles falam**; o ambiente nunca sai;
  - compressor + equalização; redução de ruído quando houver ruído detectado.
- **Poucos efeitos:** cor viva, transições suaves só quando necessário.
- **Criatividade:** a IA pode sugerir momentos de **lembrança/flashback** (outra
  tonalidade, áudio filtrado/reverb) e "momentos extras" fora da lista base.

---

## 3. Pastas e regras de segurança

### Regra de ouro
**`R:` (material bruto) e `M:` (músicas) são somente leitura.** O sistema nunca
cria, renomeia, move ou apaga nada nessas unidades. Isso é verificado em código
(toda escrita passa por uma função que recusa caminhos de origem) e em teste.

### Convenção
- O **nome do evento** vem da pasta escolhida no `R:`, ex.:
  `R:\2023\2023-09-09 CASAMENTO NICOLE E OSNY` → `2023-09-09 CASAMENTO NICOLE E OSNY`.
- O **ano** usado em todas as pastas é o **ano do evento** (os 4 primeiros
  dígitos do nome).
- Cliente padrão para casamentos: **`01 - FOKUSS`**.
- Pastas de ano/cliente inexistentes são criadas.

### Onde fica cada coisa

| Conteúdo | Local |
|---|---|
| Material bruto | `R:\<ANO>\<EVENTO>\` (leitura) |
| Músicas | `M:\` (leitura) |
| Pasta de trabalho | `<DISCO LOCAL>\EDIÇÃO <ANO>\<EVENTO>\` (padrão `Y:`) |
| ├ `PROXIES\` | proxies 480p |
| ├ `ANALISE\` | transcrições, análises, banco do projeto |
| ├ `TRILHAS\` | cópia das trilhas escolhidas (opcional, se a rede pesar) |
| ├ `BACKUP PROJETO\` | cópia de backup do `.prproj` |
| └ `<EVENTO> - ROTEIRO.pdf` | roteiro |
| Projeto Premiere (original) | `E:\VÍDEOS <ANO>\01 - FOKUSS\<EVENTO>\<EVENTO>.prproj` |
| Pasta de exports (criada vazia) | `G:\<ANO>\01 - FOKUSS\<EVENTO>\` |
| Cache de mídia do Premiere (global) | `Y:\TEMP PREMIERE\` — configurado uma vez nas Preferências |
| Índice de trilhas e config. do sistema | `Y:\SISTEMA ROTEIRO\` |

Antes de começar, o sistema **verifica o espaço livre** no disco de trabalho e
avisa se não couber (estimativa: ~12–15 GB de proxies por 12h de material).

---

## 4. Fluxo de uso

1. Editor abre o programa **Roteiro IA**.
2. Escolhe a **pasta do evento no `R:`** e o **disco de trabalho** (padrão `Y:`).
3. O sistema lista as subpastas encontradas e sugere o tipo de cada uma; o editor
   confirma:
   `câmera` · `drone` · `câmera pocket/celular` · `gravador de áudio (ambiente)` ·
   `mesa de som` · `lapela noivo` · `lapela noiva` · `outro dia do evento (nome)` ·
   `ignorar`.
   Ex.: `A, B, C, D` → câmeras; `E - H4` → gravador ambiente;
   `H - DESPEDIDA DE SOLTEIRO` → outro dia; `TRILHAS` → ignorar.
4. Informa **nº de episódios** (ou "livre") e marca quais derivados quer
   (trailer, teaser, stories/reels).
5. Escolhe **Gemini: Grátis ou Pago**. No pago, vê a **estimativa de custo** e
   aprova antes de enviar.
6. **Iniciar.** As etapas rodam sozinhas, com barra de progresso, e podem rodar à
   noite / ao longo de dias (plano grátis).
7. Ao final: PDF pronto e aviso para clicar **"Montar projeto"** no painel do
   Premiere.
8. **Editor revisa o roteiro.** Pode pedir ajustes em texto livre
   ("troca o gancho do ep. 2", "inclui o discurso do pai da noiva") → o sistema
   regera o roteiro e o projeto **sem reanalisar o material**.

---

## 5. Etapas de processamento

Cada etapa grava seu resultado no banco do projeto (`ANALISE\projeto.db`). Se o
processo cair, travar ou bater no limite do Gemini, **retoma de onde parou**,
arquivo por arquivo.

### 5.1 Inventário
- Varre as pastas confirmadas; ignora caches do Premiere (`.pek`, `.cfa`, `.pkf`,
  pastas `Proxies` antigas) e arquivos não-mídia.
- Lê metadados com `ffprobe`: duração, fps, resolução, orientação, canais de áudio,
  data/hora de gravação, timecode.

### 5.2 Proxies 480p
- `ffmpeg` com codificação NVIDIA (NVENC), H.264, altura 480 px (proporção
  preservada, verticais continuam verticais).
- **Mesmo fps e mesmo número de canais de áudio do original** (exigência do
  Premiere para alternar proxy/original).
- Arquivos `.LRF` (DJI) são reaproveitados quando compatíveis com o original
  (fps, proporção, duração); senão gera-se proxy novo.
- Nome do proxy = nome do original + sufixo `_Proxy`, em `PROXIES\<subpasta>\`.

### 5.3 Linha do tempo real do evento (sincronização)
- Primeira estimativa pela data/hora de gravação de cada arquivo.
- Refinamento por **correlação cruzada do áudio** entre câmeras, lapelas, mesa e
  gravador.
- Resultado: cada clipe posicionado numa linha do tempo única por dia do evento;
  o sistema sabe quais clipes são o **mesmo momento** em ângulos diferentes.
- Clipes sem áudio útil (ex.: drone) ficam posicionados só pela hora.

### 5.4 Transcrição (local, grátis)
- `faster-whisper` (modelo large-v3 quantizado) na RTX 3070 Ti, português,
  com tempo por palavra.
- Para cada momento, usa a **melhor fonte**: mesa de som > lapela > gravador
  ambiente > câmera.
- Medição do **nível de ruído** de cada fonte; trechos com ruído (chiado, zumbido,
  vento) são marcados.

### 5.5 Detecção de cenas
- `PySceneDetect` divide clipes longos em trechos, para a análise não tratar 20
  min de câmera parada como uma coisa só.

### 5.6 Perfil de estilo (YouTube)
- O editor cadastra links de séries já publicadas (playlists).
- O Gemini assiste os vídeos pela URL e gera um **perfil de estilo** (texto
  estruturado): duração média de episódio, ritmo de corte, padrões de abertura e
  gancho, uso de falas, tipo de trilha, visual de cor, estrutura de teaser/trailer.
- Fica salvo em `Y:\SISTEMA ROTEIRO\perfil_estilo.json` e é reutilizado em todos
  os projetos; pode ser regerado quando novas séries forem adicionadas.

### 5.7 Análise de cena (Gemini)
Para cada trecho: proxy 480p + transcrição correspondente → Gemini devolve JSON:

- `momento`: preparação noiva/noivo, first look, entrada, votos, alianças, beijo,
  saída, ensaio, entrada na festa, valsa, discursos, pista, despedida,
  pré-wedding, despedida de solteiro, lua de mel… ou `extra` (com descrição);
- `descricao` (1 frase) e `pessoas`;
- `emocao`: intensidade 0–10 e tipo (choro, riso, tensão, alegria, ternura…);
- `qualidade`: tremido, foco, exposição (nota 0–10);
- `melhores_trechos`: lista de entrada/saída com motivo;
- `falas_chave`: trechos de fala relevantes (texto + tempo);
- `potencial_gancho`: sim/não + motivo;
- `sugestao_lembranca`: se o trecho serve como flashback em outro ponto.

Respostas são validadas contra o esquema; inválidas são reenviadas.

### 5.8 Índice de trilhas (local, grátis)
- Varre `M:\` (mp3, wav, m4a); ignora caches do Premiere.
- Para cada música: **BPM, compassos e tempos 1-2-3-4** (detecção de batidas e
  tempos fortes), curva de energia, se cresce/é calma, duração, instrumental ou
  cantada.
- Índice incremental em `Y:\SISTEMA ROTEIRO\trilhas.db`: só analisa músicas novas
  ou alteradas. Primeira varredura (~4.600 arquivos) pode levar horas e roda em
  segundo plano.

### 5.9 Pré-roteiro
A IA recebe: catálogo completo + perfil de estilo + regras da seção 2 + nº de
episódios (ou livre) e gera:

1. **Arco da série** (resumo da história e divisão em episódios).
2. **Cada episódio:** título, tema, **abertura**, **desenvolvimento** (cenas em
   ordem, com falas-chave), **gancho** e onde ele se resolve, curva de emoção,
   duração estimada, momentos de lembrança sugeridos, e o motivo de cada mistura
   não-cronológica.
3. **Trailer, teaser e stories/reels:** mesma estrutura, focados nos momentos de
   maior impacto, sem entregar os ganchos dos episódios.
4. **Trilhas por peça:** 2–3 opções da biblioteca `M:` (com BPM, clima, motivo e
   padrão de corte sugerido 1-3 / 2-4 por trecho) + termos de busca para Musicbed
   + sugestões de músicas populares marcadas **"exige licença"**.

Cada cena referencia arquivo e tempo reais (ex.: `C\C0042.MP4 · 00:12:31–00:12:40`).
O sistema **confere que toda referência existe** no catálogo antes de aceitar o
roteiro.

### 5.10 PDF
- Capa com nome do evento e data; arco da série; uma seção por episódio e por
  derivado; gráfico da curva de emoção; tabela de trilhas; lista de alertas
  (ruído, momentos sem take bom, referências corrigidas).
- Gerado a partir de HTML → PDF, salvo na pasta de trabalho.

### 5.11 Projeto Premiere
**Programa** gera um XML (formato FCP 7, importável pelo Premiere) com:
- uma **sequência por episódio** e por derivado (`EP01`, `EP02`…, `TRAILER`,
  `TEASER`, `STORIES` em 1080×1920);
- trechos na ordem do roteiro na faixa V1 (ângulo principal escolhido) e os
  **ângulos alternativos sincronizados** empilhados em V2…Vn (desativados);
- áudio em faixas por função: mesa · ambiente · lapela noivo · lapela noiva ·
  música; ganho de cada clipe ajustado pela medição para se aproximar dos alvos
  (−3 dB mesa, −18 dB ambiente);
- trilha sugerida (opção 1) na faixa de música;
- **marcadores**: abertura, momentos-chave, gancho, ruído detectado, sugestão de
  lembrança (com a instrução no comentário);
- bins organizadas: `EPISÓDIOS`, `DERIVADOS`, `MATERIAL\<subpasta>`, `TRILHAS`.

**Painel "Roteiro IA" no Premiere** (extensão CEP + ExtendScript, Premiere 2024),
botão **Montar projeto**:
1. cria o projeto em `E:\VÍDEOS <ANO>\01 - FOKUSS\<EVENTO>\<EVENTO>.prproj`
   (se já existir, cria `<EVENTO>_v2.prproj`, nunca sobrescreve);
2. importa o XML;
3. **anexa os proxies** do `Y:` a cada clipe;
4. salva e copia para `Y:\…\BACKUP PROJETO\`;
5. cria a pasta de exports em `G:\<ANO>\01 - FOKUSS\<EVENTO>\`.

A instalação do painel (liberar extensões não assinadas no Windows) é feita uma
vez pelo instalador do sistema.

---

## 6. Configuração do Gemini

- Chave de API guardada só no computador (cofre de credenciais do Windows).
- Modo **Grátis**: respeita os limites de requisições/tokens; ao atingir o limite,
  pausa e retoma automaticamente quando liberar (pode levar dias por evento).
- Modo **Pago**: mostra estimativa de custo antes de enviar e exige aprovação.
- Modelo configurável (ex.: Flash para análise de cena, Pro para o roteiro).
- **Aviso exibido na tela:** no plano grátis o Google pode usar o conteúdo
  enviado para melhorar seus produtos; recomenda-se testar com eventos com
  autorização e usar o plano pago para clientes novos.

---

## 7. Tratamento de erros

| Situação | Comportamento |
|---|---|
| NAS/rede indisponível | Pausa, tenta de novo com intervalos crescentes, avisa na tela |
| Arquivo corrompido/ilegível | Registra no relatório, segue com os demais |
| Espaço insuficiente no disco de trabalho | Bloqueia antes de começar; se acabar no meio, pausa e avisa |
| Limite do Gemini (grátis) | Pausa e agenda retomada |
| Resposta inválida do Gemini | Reenvia até 3x; depois marca o trecho como "não analisado" e segue |
| Sincronização de áudio sem confiança | Usa só a hora de gravação e marca no PDF |
| Roteiro com referência inexistente | Pede correção à IA; se persistir, remove a cena e lista no PDF |
| Projeto `.prproj` já existe | Cria nova versão, nunca sobrescreve |
| Qualquer tentativa de escrita em `R:`/`M:` | Bloqueada em código (erro fatal + log) |

Log completo por projeto em `ANALISE\log.txt`.

---

## 8. Tecnologia

- **Python 3.12** em ambiente isolado (a versão 3.15 instalada é nova demais para
  algumas bibliotecas de áudio/IA).
- `ffmpeg`/`ffprobe` (NVENC) · `faster-whisper` · `PySceneDetect` ·
  `numpy`/`scipy` (sincronização) · biblioteca de detecção de batidas e tempos
  fortes · `librosa` (energia) · SDK `google-genai` · SQLite · HTML→PDF.
- Interface: janela desktop simples (PySide6).
- Premiere: XML FCP 7 + painel CEP com ExtendScript.
- Roda em qualquer máquina de edição da Fokuss com GPU NVIDIA; caminhos de
  unidades configuráveis.

---

## 9. Testes

- **Unidade:** convenções de nomes e pastas; regra somente-leitura (tentar
  escrever em `R:`/`M:` tem que falhar); validação dos JSON do Gemini; geração do
  XML; verificação de referências do roteiro.
- **Integração com amostra pequena:** uma pasta de teste com poucos clipes curtos
  (cópias, fora do `R:`), rodando todas as etapas com Gemini real no plano grátis.
- **Teste de aceitação:** rodar com **um casamento antigo completo** (ex.:
  `R:\2023\2023-09-09 CASAMENTO NICOLE E OSNY`) e comparar o roteiro com a série
  que foi publicada.
- Verificação no Premiere: importar, alternar proxy/original, conferir que o
  render usa o original do `R:`.

---

## 10. Critérios de sucesso

1. Nada é escrito em `R:` ou `M:` em nenhuma situação.
2. Um casamento de ~12h é processado do início ao fim **sem intervenção** (exceto
   confirmar subpastas e aprovar custo, quando pago).
3. O PDF traz episódios com abertura e gancho encadeados, trailer/teaser/stories,
   e trilhas reais da biblioteca.
4. O projeto Premiere abre com as sequências montadas, proxies anexados, original
   no `E:` e backup no `Y:`.
5. No teste com um casamento antigo, o editor considera o roteiro um **bom ponto de
   partida** (aproveita a maior parte da estrutura sugerida).

---

## 11. Fora do escopo da Fase 1

- Cortes na batida, escolha final de ângulos, mixagem com efeitos, LUT (Fase 2).
- Efeitos de lembrança aplicados, montagem final de trailer/teaser/stories, render
  e export para o `G:` (Fase 3).
- Busca e download automáticos de trilhas em sites externos (Jamendo etc.).

---

## 12. Riscos e pontos a validar no planejamento

- **Anexar proxies e aplicar efeitos por script** no Premiere 2024: confirmar o
  que a API de ExtendScript permite; plano B documentado (passo manual guiado).
- **Limites do plano grátis do Gemini** para vídeo e URLs do YouTube: medir
  quanto de um casamento cabe por dia.
- **Precisão da sincronização** com 6 câmeras + pockets + drone em ambientes com
  música alta.
- **Leitura pela rede** do NAS: tempo de geração de proxies de ~290 GB.
- **Espaço no `Y:`** (48 GB livres hoje).
