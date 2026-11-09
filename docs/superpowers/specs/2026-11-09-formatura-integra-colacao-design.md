# Formatura 2.3: íntegra da colação (design)

Data: 2026-11-09. Esta etapa vem depois dos clipes (`2026-11-09-formatura-cadastro-design.md`). As
decisões do usuário estão no briefing (`docs/formaturas/briefing.md`, perguntas 6, 6b, 7 e 8 e a
conversão final para o G). O usuário autorizou ir até o fim sem interferir no Casamento.

## Objetivo

A partir da gravação da **mesa de corte (PGM)**, que já sai "praticamente pronta", o sistema
entrega a **íntegra corrigida** no Premiere:

1. tira os **espaços mortos** entre um assunto e outro;
2. troca os trechos com **defeito** (chicote, escuro, desfocado, tremido) pela **câmera ISO** do
   mesmo momento. Se nenhuma ISO cobrir o trecho, usa uma **imagem fria** do assunto;
3. **separa as partes** da cerimônia, uma sequência por parte e **uma por turma** na colação;
4. marca **cada mudança** com um marcador, para o editor revisar;
5. prepara a **entrega no G**: o painel do Premiere manda cada sequência para o Media Encoder com o
   nome de entrega.

O **áudio da mesa** continua por baixo, sem cortes além dos espaços mortos.

## Entrada (projeto de Colação, preparado na 2.1)

- Pastas: **Mesa de corte (PGM)** (`Role.mesa`, vídeo + áudio), **Câmera ISO**, **Câmera com áudio
  principal**, **Gravador / lapela** e **Imagens extras / frias**.
- `formatura.json`: formatura, local, cidade, **turmas da noite** (na ordem) e **canais da mesa**.
- Sem nenhuma pasta de Mesa de corte, a etapa pára com a mensagem "Marque a pasta da mesa de
  corte (PGM, CORTE ou ATEM).".

## Etapas (as comuns, com estas trocas no `PipelineFormatura` para a colação)

| Etapa comum | Na colação |
|---|---|
| inventário, proxies, áudio, sincronização, transcrição, cenas, trilhas | iguais (a sincronização já usa a mesa como referência) |
| estilo | não roda ("não usado na colação") |
| análise (Gemini) | **só as imagens frias**, com os momentos da colação |
| roteiro | **plano da íntegra**: defeitos, espaços mortos e partes |
| pdf | **relatório da íntegra**: partes, horários, trocas e avisos |
| premiere | **XML da íntegra** e `job.json` com as entregas |

O "Pedir ajuste" (texto livre) refaz só as partes, levando o pedido do editor. Por exemplo: "o hino
começa em 0:12:30" ou "falta a turma T107".

## Componentes (`src/roteiro_ia/areas/formatura/colacao/`)

### `defeitos.py`: defeitos de imagem (no computador, sem Gemini)

- Lê o **proxy 480p** do PGM pelo ffmpeg, em **4 quadros/s**, cinza, 96×54, **em fluxo** (não
  guarda o vídeo na memória).
- Mede por amostra o brilho médio, a nitidez (média do gradiente) e a diferença para a amostra
  anterior.
- `classificar(amostras, fps) -> list[Defeito]`, com `Defeito(inicio_s, fim_s, tipo)`. Os tipos:
  - **escuro:** brilho < 28 por ≥ 1 s;
  - **desfocado:** nitidez < 40% da mediana do arquivo por ≥ 1 s (e não escuro);
  - **chicote:** diferença > 30 em **duas ou mais** amostras seguidas. Uma amostra só é corte de
    câmera, não defeito;
  - **tremido:** diferença média > 12 numa janela de 2 s, com nitidez < 70% da mediana, fora de
    chicote.
- Intervalos a menos de 0,5 s se juntam, e cada intervalo ganha 0,25 s de folga de cada lado.
- O resultado fica em `ANALISE\defeitos.json`, por arquivo, e não é recalculado no ajuste.

### `silencio.py`: espaços mortos

- Usa o ffmpeg `silencedetect` no áudio do PGM, com limite = média do arquivo − 25 dB (de
  `db.get_audio_stats`; sem medida, −45 dB) e duração mínima de **4 s**.
- Cada espaço morto vira um corte que mantém **0,5 s** de cada lado.

### `partes.py`: partes da cerimônia (Gemini, só texto)

- Partes, na ordem padrão, com os nomes de entrega (pergunta 8):
  1. "Abertura do Mestre de Cerimônias e Entrada dos Professores"
  2. "Entrada das Turmas"
  3. "Hino Nacional"
  4. "Fala do Diretor"
  5. "Colação - <Curso> - <Turma>" (uma por turma da noite)
  6. "Oradores"
  7. "Paraninfos"
  8. "Homenagens"
  9. "Fala Final do Diretor"
  10. "Hino e Encerramento"
- A **transcrição do PGM** vai em linhas `[H:MM:SS] texto` de cerca de 15 s, junto com as turmas
  da noite. O pedido é o início de cada parte; uma parte que não aconteceu fica de fora.
- **Validação:**
  - os inícios ficam em ordem crescente e dentro da duração;
  - código desconhecido sai;
  - turma da colação que não está na ficha vira alerta.
- Se o Gemini falhar (erro que não é de cota), sai **uma parte só**, "Cerimônia Completa", com
  alerta. A pausa de cota continua sendo pausa.
- No ajuste, o pedido do editor vai no prompt.

### `frias.py`: banco de imagens frias

- As mídias da função **Imagens extras / frias** são analisadas pelo `analyze_event`, só elas, com
  `TEXTOS_POR_TIPO[colacao]`.
- `escolher(assunto, duracao_s, usadas) -> list[(midia, inicio, fim)]` prefere, pelo assunto:
  - hinos: "decoração" e "bastidores";
  - colação: "plateia e família", "emoção" e "comemoração";
  - o resto: "plateia e família" e "decoração".

  Depois vale a maior qualidade, sem repetir trecho já usado. Se faltar, junta trechos.

### `plano.py`: o plano da íntegra

`PlanoIntegra`, gravado em `ANALISE\integra.json`, traz uma lista de `ParteIntegra`. Cada parte
tem:

- `nome` e `numero` (01, 02…);
- `inicio_s` e `fim_s` na linha do tempo da mesa;
- `trechos`: os pedaços mantidos depois dos espaços mortos;
- `trocas`: o intervalo, o motivo (o tipo de defeito) e a fonte (`iso:<rel_path>`,
  `fria:<rel_path>` ou `sem cobertura`).

Também traz os `alertas`.

- **ISO escolhida:** a de maior sobreposição com o intervalo do defeito (pela sincronização). As
  outras ISOs do momento entram desligadas em V2 e V3, como as alternativas do Casamento.
- Trechos com menos de 0,5 s entre duas trocas viram uma troca só.

### `xml_integra.py`: XML do Premiere

- Reaproveita os blocos de `premiere/fcpxml.py` (arquivos, clipitems, áudio L/R, marcadores e
  bins) sem mudar o que o Casamento usa.
- Uma sequência por parte, com o nome `NN - <Nome>`, na bin **ÍNTEGRA**, mais a bin **MATERIAL**.
- **V1:** PGM, ou a ISO ou a fria nas trocas. **V2 e V3:** ISOs alternativas, desligadas. **Áudio
  MESA L/R:** o PGM contínuo nos trechos mantidos. **AMBIENTE:** gravador e câmera com áudio
  principal, desligados (reserva).
- **Marcadores** em cada troca ("TROCA: chicote → CAM B", "IMAGEM FRIA: plateia", "SEM COBERTURA:
  escuro") e em cada espaço morto cortado ("CORTE: 6 s sem fala").

### `entrega.py` e o painel

- O `job.json` ganha `entregas: [{sequencia: "03 - Hino Nacional", arquivo:
  "G:\<ano>\<cliente>\<evento>\03 - Hino Nacional.mp4"}]`.
- **Painel do Premiere:** botão novo **"Exportar entregas para o G"** e função
  `exportarEntregas(job)` em `montar.jsx`.
  - Acha cada sequência pelo nome.
  - Pede **uma vez** o preset de exportação (`.epr`) e o guarda em
    `Folder.userData/RoteiroIA/preset_exportacao.txt`.
  - Põe cada sequência na fila do Media Encoder (`app.encoder.encodeSequence`) e inicia a fila.
  - Sequência que não existe vira aviso.

### Relatório (PDF)

Uma página com as partes (início, duração final, trocas e cortes) e os alertas. Usa o
`html_to_pdf` comum.

## Ganchos no código comum (acréscimos com padrão)

- `gemini/analysis.analyze_event(..., incluir: Callable[[MediaInfo], bool] | None = None)`. `None`
  = todas, como hoje.
- O resto fica em `areas/formatura/colacao/`. O pipeline troca as etapas sobrescrevendo os
  métodos no `PipelineFormatura` quando o tipo é colação.

## Interface

- A colação passa a **iniciar**. O aviso "chega na próxima etapa" sai.
- O motivo de bloqueio "Marque a pasta da mesa de corte (PGM)." aparece quando nenhuma pasta tem
  essa função.

## Erros

- PGM sem proxy: os defeitos não são medidos (alerta), e o resto segue.
- Ffmpeg falhou num arquivo: alerta, e esse arquivo fica sem trocas.
- Gemini das partes falhou: uma parte só, com alerta.
- Sem imagens frias: trechos sem ISO ficam "SEM COBERTURA", com marcador.

## Testes

- Classificador de defeitos com amostras sintéticas, um para cada tipo, mais o corte de câmera
  que não deve ser defeito.
- Leitura real de um vídeo curto, gerado com uma parte preta e outra normal.
- `silencedetect` num áudio com um silêncio de 6 s no meio.
- Partes: validação, ordem, turma desconhecida, plano B sem Gemini e o pedido de ajuste no
  prompt.
- Frias: preferência por assunto e sem repetir.
- Plano: trechos depois dos espaços mortos, troca por ISO, troca por fria, sem cobertura e
  junção de trocas próximas.
- XML: as sequências com os nomes de entrega, V1 com a troca, áudio MESA contínuo e os
  marcadores.
- `job.json` com as entregas no G e o painel com `exportarEntregas` (ASCII, ES3).
- Pipeline da colação de ponta a ponta com Gemini e Whisper falsos.
- Interface: a colação inicia e o aviso de PGM faltando aparece.
