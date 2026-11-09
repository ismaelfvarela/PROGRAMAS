# Painel Roteiro IA para o Premiere Pro

O painel cria e organiza o projeto do Premiere no padrão de pastas da Fokuss:
COISAS, CREDITOS, EPS (na Formatura: PARTES DA COLAÇÃO), SEQUENCIA, TRILHA e VÍDEOS (uma
subpasta por pasta de câmera/áudio do evento).

- **Abrir projeto** (no começo do trabalho): cria o `.prproj` no E: com as pastas, ou só abre
  se ele já existe.
- **Puxar roteiro (XML)** (quando o roteiro fica pronto): traz as timelines do roteiro para EPS,
  os clipes para VÍDEOS/<pasta>, as músicas para TRILHA, importa do disco as mídias não usadas,
  junta os repetidos e anexa os proxies do Y:. Pode ser repetido depois de um ajuste no roteiro:
  as timelines antigas vão para EPS/ANTERIORES.
- Os botões **Abrir no Premiere** e **Puxar roteiro** do Roteiro IA deixam um pedido que o
  painel atende sozinho (ele confere a cada 2 s), desde que esteja aberto no Premiere.

## Instalação

1. No PowerShell, rode: `premiere_panel\instalar_painel.ps1`
   (liga o modo de depuração do CEP 11 em `HKCU:\Software\Adobe\CSXS.11` e copia o painel
   para `%APPDATA%\Adobe\CEP\extensions\com.fokuss.roteiroia`).
2. Feche e abra o Premiere Pro (2024 ou mais novo).
3. Menu **Janela → Extensões → Roteiro IA**.

Para remover: `instalar_painel.ps1 -Desinstalar`.

## Uso

1. Na primeira vez, abra o painel (**Janela → Extensões → Roteiro IA**) e deixe-o encaixado
   no espaço de trabalho: nas próximas vezes ele abre junto com o Premiere.
2. No Roteiro IA, use **Abrir no Premiere** e, com o roteiro pronto, **Puxar roteiro (XML)**.
   Os mesmos botões existem no painel (usam o job mostrado nele, padrão
   `Y:\SISTEMA ROTEIRO\ultimo_job.json`, ou **Escolher job**).
3. O projeto nunca é sobrescrito: se já existe, é aberto.

## Configurar o cache de mídia (faça uma vez)

*Preferências → Cache de mídia*:

- Local dos arquivos de cache: `Y:\TEMP PREMIERE`
- **Desmarcar** "Salvar arquivos de cache de mídia ao lado dos originais quando possível"
  (senão o Premiere tenta gravar ao lado dos originais, que são protegidos).

## Plano B (proxies)

Se o painel avisar que não conseguiu anexar proxies: no painel Projeto, selecione a pasta
`VÍDEOS` → botão direito → **Proxy → Anexar proxies** e aponte para a pasta `PROXIES`
do evento. Depois use o botão **Alternar proxies** na janela do programa.

## Problemas comuns

- **O painel não aparece em Extensões:** confirme que rodou `instalar_painel.ps1` e reiniciou o Premiere.
  Verifique o valor `PlayerDebugMode = 1` em `HKCU:\Software\Adobe\CSXS.11`.
- **"Não consegui ler o job":** o pipeline ainda não gerou `ultimo_job.json`, ou o `Y:` não está
  montado. Use **Escolher job**.
- **"O roteiro (XML) ainda não foi gerado":** rode o processamento até a etapa Premiere.
- **O Premiere não conseguiu criar o projeto:** a pasta no `E:` pode estar sem permissão ou cheia.
- **Proxies anexados: 0:** os caminhos dos originais no job não batem com os do XML importado
  (por exemplo, a unidade mudou de letra). Gere o job de novo.
