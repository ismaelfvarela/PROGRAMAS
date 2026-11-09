# Formatura 2.4: clipes de abertura e encerramento da colação (design)

Data: 2026-11-09. Esta etapa vem depois da íntegra (2.3). As decisões do usuário estão no
briefing: a colação, a pergunta 3 ("grande final" = fecho da abertura, resposta B) e o logo da
produtora no encerramento. O usuário autorizou ir até o fim. Há outro chat (séries de casamento)
mexendo no master ao mesmo tempo, por isso esta etapa **não toca em código comum**.

## Objetivo

No mesmo projeto da colação, além das partes da íntegra, o sistema entrega dois clipes:

- **"00 - Abertura"** (até cerca de 180 s), nesta ordem:
  1. cartela, com os primeiros 5 s reservados (o visual da cartela é a 2.5);
  2. decoração;
  3. bastidores;
  4. **grande final:** os melhores momentos da formatura inteira, com trechos curtos de **falas
     marcantes de alunos e paraninfos**.
- **"NN - Encerramento"** (60 a 90 s): **bem animado**, com os momentos de comemoração, e termina
  com o **logo da produtora** (4 s).

Os dois saem com música comercial da pasta de músicas do projeto, com marcadores, e entram na lista
de entregas no G: a Abertura antes das partes e o Encerramento depois.

## Decisões

1. **A mesa de corte passa a ser analisada pelo Gemini**, além das imagens frias, com os momentos
   da colação. O grande final precisa saber onde estão a emoção, as falas e a comemoração. Com os
   pacotes de até 30 min de vídeo, uma cerimônia de 3 h custa cerca de 6 a 8 chamadas. As câmeras
   ISO **não** são analisadas, porque o custo seria alto.
2. **Um pedido de roteiro só** para os dois clipes. O roteiro tem duas peças:
   - `tipo "trailer"` = Abertura;
   - `tipo "teaser"` = Encerramento.

   São os tipos que o roteiro comum já aceita. Os nomes das sequências quem decide é a
   Formatura.
3. **Logo da produtora:** fica num ajuste próprio da Formatura,
   `<system_dir>\FORMATURAS\_ajustes.json` (`logo_produtora`), editado no topo da janela
   "Formaturas…". Assim as Configurações comuns não mudam. Sem logo, o encerramento sai sem ele e
   com o marcador "LOGO DA PRODUTORA: escolha o arquivo em Formaturas…".
4. **Música:** a etapa "trilhas" volta a rodar na colação, mas **não para** o processamento se o
   HD de músicas estiver desconectado e o índice vazio. Nesse caso os clipes saem sem trilha, com
   aviso.
5. **Falha nos clipes não derruba a íntegra.** Se o roteiro dos clipes der erro (que não seja de
   cota), a íntegra é entregue com o aviso "Clipes de abertura e encerramento não gerados: …". A
   pausa de cota continua sendo pausa.

## Componentes (`areas/formatura/`)

- **`ajustes.py`:** `AjustesFormatura(logo_produtora: str | None)`, com `carregar_ajustes(s)` e
  `salvar_ajustes(s, a)`.
- **`colacao/clipes.py`:**
  - `contexto_abertura_encerramento(pf, ficha, partes)`: o contexto do roteiro, com os dados do
    evento (instituição, curso e turmas, data, local e cidade), as regras dos dois clipes, a regra
    de qualidade, a música comercial e as partes com os horários (para achar o fim da cerimônia,
    as colações e os paraninfos).
  - `nomes_clipes(n_partes) -> ("00 - Abertura", f"{n_partes + 1:02d} - Encerramento")`.
- **`colacao/xml_integra.py`:** `build_xml_integra(plano, db, source_root, clipes=None, idx=None,
  musicas=None, logo=None)`. Os clipes são montados com o `build_sequence` comum (com o mesmo
  contexto de arquivos), na bin ÍNTEGRA, antes e depois das partes. O logo entra como imagem
  parada de 4 s no fim do Encerramento, com marcador.
- **`colacao/entrega.py`:** as entregas incluem os clipes, na ordem Abertura, partes e
  Encerramento.
- **`pipeline.py` (colação):**
  - a análise inclui a mesa de corte e as frias;
  - as trilhas são tolerantes;
  - o roteiro faz o plano da íntegra e o roteiro dos clipes, com `generate_roteiro(...,
    n_episodios=None, derivados={"trailer", "teaser"}, contexto=...)` e o índice filtrado pela
    pasta de músicas;
  - o pdf é o relatório, com uma seção dos clipes;
  - o premiere monta o XML com os clipes e o logo.
- **`ui_cadastro.DialogoCadastro`:** campo "Logo da produtora" no topo, com o botão Escolher…;
  grava ao escolher.

## Testes

- Ajustes: gravar e ler; sem arquivo = sem logo.
- Contexto: cita as duas peças, os 180 s, a cartela de 5 s, a decoração, os bastidores, o grande
  final com as falas de alunos e paraninfos, o encerramento animado com o logo nos últimos 4 s,
  os dados do evento e as partes com os horários.
- XML: "00 - Abertura" primeiro e "NN - Encerramento" por último; o logo no fim do encerramento
  (clipitem com o arquivo do logo); o marcador quando falta o logo.
- Entregas na ordem certa.
- Pipeline:
  - a análise inclui a mesa de corte;
  - a falha comum nos clipes mantém a íntegra, com o aviso;
  - sem o HD de músicas, a colação segue.
- Diálogo: o campo do logo grava.
- Integração da colação estendida: as duas sequências extras e as entregas.
