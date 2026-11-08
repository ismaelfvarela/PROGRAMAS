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
- **Divisão proposta**, cada parte com spec e entrega próprias. O usuário ainda não
  confirmou explicitamente, mas não objetou.
  1. **Base:** tipo de trabalho no formulário, campos de dados do evento (cartela), logo da
     produtora e lista de momentos por tipo.
  2. **Clipes:** Oficina, Prova de toga, Escolha do paraninfo.
  3. **Colação:** partes da cerimônia (uma por turma), clipe de abertura e clipe de
     encerramento.

  As partes 1 e 2 juntas entregam o clipe de Oficina funcionando.

## Perguntas em aberto (fazer uma por vez)

1. **Pasta das músicas comerciais:** onde fica (M:? outra?) e se é separada das trilhas de
   casamento.
2. **Cartela de abertura ("layout preparado padrão"):** existe um modelo no Premiere (MOGRT,
   Essential Graphics, sequência modelo)? O sistema preenche os textos nele, ou só gera os
   dados para o editor colar?
3. **"Grande final no início da colação":** o que é exatamente? Um teaser do clímax?
4. **Clipes no dia da formatura:** quanto tempo há entre gravar e exibir? Isso afeta a cota
   grátis do Gemini (20 chamadas/dia por modelo) e a necessidade da IA local (planejada como
   reserva).
5. **Dados da formatura:** quais campos são obrigatórios e se valem por projeto ou por turma
   (várias turmas na colação). Onde fica o logo da escola: arquivo escolhido no formulário?
6. **Funções das pastas na formatura:** substituir lapela noivo/noiva por mesa de som, lapela
   do orador, câmera etc.?
7. **Separação das partes da cerimônia:** a IA detecta onde começa cada parte (pelas falas do
   mestre de cerimônias na transcrição) e o editor confirma? E a saída no Premiere: uma
   sequência por parte, com nomes padronizados para exportar?
8. **Nomes dos arquivos e pastas de entrega** das partes (padrão de nomes para o Drive).
