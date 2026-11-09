# Formaturas: briefing (brainstorming em andamento)

Este arquivo é a passagem de bastão da conversa de 2026-11-08 sobre o novo tipo de trabalho
**Formatura** no Roteiro IA. O brainstorming está **em andamento**, ainda sem especificação
aprovada. Siga o processo do skill `superpowers:brainstorming`, caminho **arquitetural**:
perguntas uma por vez → abordagens → design por seções → spec em `docs/superpowers/specs/`
→ revisão do usuário → `writing-plans`. Nada de código antes disso.

Responda ao usuário em português. Ele é editor da produtora Fokuss.

## Contexto do sistema hoje

O sistema hoje só conhece **casamento**, fixo em vários pontos:

- `gemini/analysis.py`: lista `MOMENTOS` (preparação noiva, votos, valsa…).
- `script/generate.py`:
  - `REGRAS_FOKUSS`: série de episódios com gancho, ~6 min cada.
  - `Piece.tipo`: episodio/trailer/teaser/stories.
- `models.Role`: lapela_noivo/lapela_noiva.
- `inventory.py`: sugere o papel pelo nome da pasta.
- `premiere/fcpxml.py`: grupos de áudio "LAPELA NOIVO/NOIVA"; sequências por episódio.

O que já existe e serve igual: o pipeline de inventário, proxies, áudio, sincronização,
transcrição (Whisper na GPU), cenas, índice de trilhas (BPM, clima, voz, CLAP), análise
Gemini por trecho, roteiro, PDF e XML/painel do Premiere.

Estava na lista de adiados do usuário: "tipo de evento (Casamento/Formatura/Outro) com lista
de momentos própria" e "estilos com nome".

## O que o usuário descreveu

### Clipes

Os clipes são **Oficina**, **Prova de toga** e **Escolha do paraninfo**.

- **Oficina:** gravação dos alunos na oficina de trabalho ou sala de aula, mais alguns
  depoimentos.
- **Formato:** um clipe de **3 a 5 min**. Pode passar disso se a produtora liberar, então a
  duração deve ser configurável.
- **Entrega:** é editado e exibido **no dia da formatura**, então rapidez importa.
- **Prova de toga e Escolha do paraninfo:** também são clipes, só com trilha e os áudios de
  assuntos importantes.
- **Música:** comercial, popular, o mais moderna possível (público jovem). Ver
  "Decisões já tomadas" para a origem.
- **Abertura da Oficina** com dados do evento: logo da escola, nome da instituição, nome do
  curso, turma, semestre e ano de formatura. O sistema precisa de campos para esses dados.

### Colação de grau

É uma sequência de **vídeos separados**, para o envio pelo Drive não ficar pesado.

1. **Clipe de abertura**, no máximo ~3 min:
   1. Cartela com os dados, num layout padrão já preparado. Os dados são os da Oficina mais
      **local do evento, data, cidade e turmas que estão se formando**.
   2. Vídeo da decoração.
   3. Bastidores.
   4. Pequeno resumo de toda a colação, ou de outro assunto que houver.

   O usuário citou "a edição de um grande final no início da colação" (a confirmar; ver
   perguntas em aberto).
2. **Cerimônia**, cada parte num arquivo próprio, em ordem:
   1. Abertura do mestre de cerimônias com entrada dos professores.
   2. Entrada das turmas.
   3. Hino Nacional.
   4. Fala do diretor ou representante.
   5. **Colações: um vídeo por turma.** Se houver orador no mesmo momento da colação daquela
      turma, ele fica junto no vídeo da turma. Segue assim até acabarem as colações.
   6. Oradores.
   7. Paraninfos.
   8. Homenagens.
   9. Fala do diretor.
   10. Hino e encerramento.
3. **Clipe de encerramento**, bem animado, terminando com a **logo da produtora**. O caminho
   do arquivo da logo fica numa configuração do sistema.

O processo da colação é o mesmo do casamento: trilhas, sincronização, roteiro dos melhores
momentos (nos clipes) e montagem.

## Decisões já tomadas

- **Música dos clipes: opção C.** O sistema escolhe da pasta de músicas comerciais/populares
  da produtora, analisando-as como as trilhas, e também sugere novidades pelo nome. O usuário
  foi avisado de que a IA não sabe as músicas da semana, então a sugestão pode sair um pouco
  desatualizada.
- **Pasta das músicas comerciais (pergunta 1): ainda não existe.** O usuário vai montá-la.
  O caminho fica numa configuração do sistema, separada das trilhas de casamento, com índice
  próprio. Enquanto a pasta estiver vazia ou não configurada, o clipe só recebe sugestões de
  músicas pelo nome.
  - **Complemento:** a raiz das músicas é sempre o HD M:. No formulário do projeto, o editor
    pode **direcionar uma pasta de músicas** (a pasta do ano ou a da playlist exata) para o
    sistema não procurar no M: inteiro. Isso vale **também para casamentos** e entra na
    parte Base. Ideia técnica: o índice continua cobrindo o M: inteiro, e o projeto só filtra
    pelas músicas dentro da pasta escolhida (indexando antes o que faltar nela).
- **Cartela e dados do evento (pergunta 2):** hoje é uma mistura de modelo de texto animado
  (MOGRT/Essential Graphics) com sequência modelo no Premiere. O usuário está aberto a uma
  novidade proposta. Requisitos firmes:
  - Um **questionário de dados do evento no início do projeto**. O editor preenche logo no
    começo e o sistema leva esses dados para a edição.
  - Um **campo para direcionar as vinhetas e logos** usadas no projeto.
  - Ideia técnica em avaliação: o painel do Premiere (`premiere_panel/host/montar.jsx`, CEP +
    ExtendScript) importaria um MOGRT da cartela e preencheria os textos sozinho
    (`importMGT` + propriedades do componente).
- **Divisão proposta inicialmente**, substituída pela divisão aprovada, mais abaixo.
  1. **Base:** tipo de trabalho no formulário, campos de dados do evento (cartela), logo da
     produtora e lista de momentos por tipo.
  2. **Clipes:** Oficina, Prova de toga, Escolha do paraninfo.
  3. **Colação:** partes da cerimônia (uma por turma), clipe de abertura e clipe de
     encerramento.

  As partes 1 e 2 juntas entregam o clipe de Oficina funcionando.

- **Arquitetura e divisão aprovadas (2026-11-08):**
  - **Perfis de tipo de trabalho.** Casamento e Formatura viram perfis, cada um com
    momentos, regras do roteiro, tipos de peça, funções de pasta e nomes de grupos de áudio.
    O resto do código consulta o perfil do projeto em vez de valores fixos.
  - **Cinco partes, nesta ordem**, cada uma com spec, entrega e teste próprios:
    1. **Base:** perfis, tipo no formulário, ficha do evento (cursos → turmas), campo de
       grafismos, logo da produtora na configuração, **pasta de músicas por projeto
       (casamento também)** e novas funções de pasta.
    2. **Clipes:** Oficina, Prova de toga e Escolha do paraninfo, com a pasta de músicas
       comerciais.
    3. **Íntegra da colação:** programa da mesa de corte como linha mestra, ISOs, detecção
       de defeitos, imagens frias, separação em partes e turmas, marcadores e arquivos de
       entrega.
    4. **Abertura e encerramento da colação:** grande final com falas marcantes e logo da
       produtora no fim.
    5. **Cartela:** depois dos vídeos de referência.
  - **Conversão final para o G (pedido do usuário):** quando um arquivo estiver pronto, ele
    precisa ser **exportado ou convertido para o G**. Hoje o painel só cria a pasta
    `G:\<ano>\<cliente>\<projeto>` (`paths.export_dir`), e a exportação é manual. A
    exportação entra na Base, valendo para todo tipo de trabalho: o painel enfileira as
    sequências finais no Media Encoder (`app.encoder.encodeSequence`) com um preset
    escolhido, gravando no G com os nomes de entrega. A "pasta ENTREGA" da pergunta 8 é
    esta pasta do G.

- **Conversão final para o G:** quando cada arquivo de entrega estiver pronto, ele é exportado
  ou convertido para a pasta de exportação no G (`paths.export_dir` =
  `G:\<ano>\<cliente>\<evento>`), com os nomes de entrega da pergunta 8. O usuário pediu para
  não esquecer.
- **Encaixe com a spec das áreas de trabalho** (`docs/superpowers/specs/2026-11-09-areas-de-trabalho-design.md`,
  feita em outro chat): a parte 1 de lá (áreas + fila + pasta de músicas por projeto) vem
  primeiro. As subdivisões abaixo são da **parte 2 ("Formatura funcionando")**, seguindo a
  regra de lá: o Casamento não se mexe, e a Formatura faz as próprias versões em
  `areas/formatura/`.
  1. Questionário (ficha do evento com cursos e turmas, grafismos, logo), funções das pastas
     da Formatura e momentos.
  2. Clipes: Oficina, Prova de toga, Escolha do paraninfo.
  3. Íntegra da colação: correção automática, imagens frias, separação em partes, entrega no G.
  4. Clipes de abertura (com o grande final) e de encerramento da colação.
  5. Cartela, quando chegarem os vídeos de referência.

- **Organização das gravações (pergunta 11):** hoje todas as oficinas ficam numa **pasta
  de oficinas no R:**, e o trabalho começa por lá. Cada colação tem **várias oficinas**,
  gravadas e editadas antes, às vezes **com 1 ano de antecedência**. A colação é **a
  última coisa** que chega de cada evento. O usuário propôs, dentro da área Formatura, uma
  **sub-aba de Clipes** (ou de Oficinas). Nela as oficinas e os clipes de um evento ou de um
  ano vão sendo acrescentados conforme aparecem, sem interferir no projeto da colação.
  - **Proposta aceita em princípio:** a área Formatura tem as sub-abas **Clipes** e
    **Colação** e um **cadastro da formatura** (a ficha). Clipes e colação escolhem a qual
    formatura pertencem. Dados só da colação (local, data, cidade) ficam na própria colação.
  - **Pergunta 12 (respondida, opção A):** normalmente é **uma oficina por turma**, gravada
    em **vários dias** e editada **de uma vez só**. Um projeto de Oficina recebe então
    gravações de várias datas.
  - **Novo tipo de clipe:** vídeos das **feiras das escolas** (pergunta 13, opção B). São
    **mais longos e documentais**: mostram os projetos expostos, com mais falas de alunos
    explicando o trabalho. A seleção é guiada pela fala, como num depoimento, e não pela
    música.

## Perguntas em aberto (fazer uma por vez)

1. ~~Pasta das músicas comerciais~~ (respondida: ainda não existe; ver decisões).
2. ~~Cartela de abertura~~ (respondida: mistura de MOGRT com sequência modelo; ver decisões).
   Falta confirmar a forma de preenchimento automático (ver pergunta 2b).
   - **2b (respondida):** o usuário não sabe como está o processo hoje e pediu que a gente
     crie algo prático, com base nos **vídeos de referência dos perfis**, que ele vai enviar
     depois. Decisão: a ficha do evento e o campo de grafismos entram já. O visual e a forma
     de gerar a cartela ficam em aberto até os vídeos chegarem. O design deve tratar a
     cartela como uma peça trocável: preencher um MOGRT pelo painel, ou o próprio sistema
     gerar a cartela como vídeo com transparência a partir da ficha.
3. ~~"Grande final no início da colação"~~ (respondida, opção B): é o **fecho do clipe de
   abertura**, ou seja, o item 4 ("pequeno resumo") editado como grande final. São os
   melhores momentos da formatura inteira, podendo usar **trechos curtos de falas marcantes
   de alunos e paraninfos**. Consequência: o clipe de abertura depende da cerimônia toda já
   gravada e transcrita. A IA escolhe as falas marcantes pela transcrição, como faz nos
   casamentos.
4. ~~Clipes no dia da formatura~~ (respondida, opção A): a Oficina é gravada **dias antes**,
   e "no dia" quer dizer só que ela é exibida na formatura. Não precisa de modo rápido, e o
   fluxo completo atual serve. A cota do Gemini e a IA local não mudam por causa disso.
5. ~~Dados da formatura~~ (respondida, opção A): **um projeto por formatura.** Estrutura:
   - **Gerais:** instituição, logo da escola, local, data, cidade, **ano e semestre**. O ano e
     o semestre são o fechamento daquela formatura e valem para todas as turmas.
   - **Lista de cursos, cada um com suas turmas abaixo.** Exemplo: "Curso Técnico em
     Eletrônica" → turmas "Manhã", "Tarde", "T106", "T107". O nome da turma é texto livre.
   - Logo da escola: assumido **um por formatura**, um arquivo escolhido na ficha. O usuário
     não respondeu sobre logo por curso. Corrigir se precisar.
6. ~~Funções das pastas na formatura~~ (respondida, opção D). **Muda o entendimento da
   íntegra da colação:**
   - Na maioria das formaturas a colação passa por uma **mesa de corte central**, que recebe
     todas as câmeras e já gera o **vídeo do programa praticamente pronto**.
   - Cada câmera também grava no próprio cartão (**ISO**), para cobrir erros do corte.
   - A edição da **íntegra** (parte separada, depois da abertura) é uma **edição de
     correção**. Ela tira o que está ruim tecnicamente (chicotes, cenas escuras, cenas
     tremidas, espaços mortos entre um assunto e outro) e **separa os arquivos** pelas partes
     da cerimônia.
   - **Áudio:** o principal é gravado na mesa de corte e também numa das câmeras. O ambiente
     vem junto na gravação da mesa: ou já misturado e nivelado, ou com **L e R separados**
     (um lado o áudio limpo da mesa de som, o outro o ambiente).
   - Consequências para o design:
     - Novas funções de pasta: "gravação da mesa de corte (programa)", "câmera ISO
       (reserva)" e "câmera com áudio principal". Também uma opção de canais
       "L = mesa / R = ambiente".
     - Na íntegra, o programa da mesa é a **linha mestra**. As ISOs são sincronizadas a ele
       (a sincronização atual serve) para substituir os trechos com defeito.
     - A detecção de defeitos numa cerimônia de 2 a 3 h deve ser **local**, por medidas de
       imagem e som (brilho, movimento brusco ou tremido, silêncio). Analisar com o Gemini
       trecho a trecho estouraria a cota grátis. O Gemini já marca "problemas" por trecho em
       `gemini/analysis.py`, mas fica para os clipes.
   - **Depoimentos da Oficina (respondida, opção B):** são gravados com **microfone
     direcional na câmera**, com o áudio já embutido no vídeo. Não há lapela para
     sincronizar.
6b. ~~Até onde vai a correção automática da íntegra~~ (respondida, opção A): o sistema
   **entrega o corte corrigido**. Ele tira os espaços mortos, troca os trechos com defeito
   pela melhor ISO do mesmo momento e separa as partes (uma sequência por parte e uma por
   turma). Cada mudança leva um **marcador colorido** no Premiere para o editor revisar e
   desfazer.
   - **Acréscimo do usuário, imagens frias:** o sistema separa um **banco de imagens frias**
     (decoração, palco, plateia, ambiente…), classificadas por assunto. Quando nenhuma
     câmera tiver imagem boa naquele momento, ele cobre o trecho com uma imagem fria
     **de acordo com o assunto**. Exemplos: no Hino, bandeira ou palco; numa colação de
     turma, plateia ou família. O áudio da mesa continua por baixo. Como o banco é pequeno,
     a classificação pode usar o Gemini.
7. ~~Separação das partes~~ (respondida, opção A): o mestre de cerimônias quase sempre
   anuncia cada parte, e a ordem segue a lista do briefing. A IA acha os pontos de corte
   pelos anúncios na transcrição. Os nomes das turmas vêm da ficha do evento e ajudam a
   reconhecer "convidamos a turma T106…". O editor confirma ou ajusta a lista de cortes
   antes da montagem. Texto original da pergunta, mantido como registro:
   **Separação das partes da cerimônia:** a IA detecta onde começa cada parte (pelas falas do
   mestre de cerimônias na transcrição) e o editor confirma? E a saída no Premiere: uma
   sequência por parte, com nomes padronizados para exportar?
8. ~~Nomes de entrega~~ (respondida, opção A). Os arquivos vão para a pasta `ENTREGA\` do
   projeto, com número de ordem e nome. As sequências no Premiere têm os mesmos nomes.
   Exemplo:
   `00 - Abertura`, `01 - Abertura do Mestre de Cerimônias e Entrada dos Professores`,
   `02 - Entrada das Turmas`, `03 - Hino Nacional`, `04 - Fala do Diretor`,
   `05 - Colação - <Curso> - <Turma>` (uma por turma)…, `NN - Hino e Encerramento`,
   `NN+1 - Encerramento`. Texto original da pergunta, mantido como registro:
   **Nomes dos arquivos e pastas de entrega** das partes (padrão de nomes para o Drive).
