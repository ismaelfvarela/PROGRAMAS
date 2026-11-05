# Painel Roteiro IA para o Premiere Pro

Depois que o pipeline (Python) termina, este painel monta o projeto no Premiere:
cria o `.prproj` no caminho do job, importa o XML (uma sequência por episódio),
anexa os proxies leves do `Y:` a cada clipe original, salva, copia um backup para
o `Y:` e cria a pasta de exportação no `G:`.

## Instalação

1. No PowerShell, rode: `premiere_panel\instalar_painel.ps1`
   (liga o modo de depuração do CEP 11 em `HKCU:\Software\Adobe\CSXS.11` e copia o painel
   para `%APPDATA%\Adobe\CEP\extensions\com.fokuss.roteiroia`).
2. Feche e abra o Premiere Pro (2024 ou mais novo).
3. Menu **Janela → Extensões → Roteiro IA**.

Para remover: `instalar_painel.ps1 -Desinstalar`.

## Uso

1. Rode o pipeline até o fim (gera `ultimo_job.json` em `Y:\SISTEMA ROTEIRO`).
2. No painel, confira o job (padrão `Y:\SISTEMA ROTEIRO\ultimo_job.json`) ou use **Escolher job**.
3. Clique em **Montar projeto** e aguarde. O log mostra cada etapa com ✔ / ✖.
4. Se o `.prproj` já existir, o job já traz um nome livre (`_v2`, `_v3`...). Nada é sobrescrito.

## Configurar o cache de mídia (faça uma vez)

*Preferências → Cache de mídia*:

- Local dos arquivos de cache: `Y:\TEMP PREMIERE`
- **Desmarcar** "Salvar arquivos de cache de mídia ao lado dos originais quando possível"
  (senão o Premiere tenta gravar ao lado dos originais, que são protegidos).

## Plano B (proxies)

Se o painel avisar que não conseguiu anexar proxies: no painel Projeto, selecione a bin
`MATERIAL` → botão direito → **Proxy → Anexar proxies** e aponte para a pasta `PROXIES`
do evento. Depois use o botão **Alternar proxies** na janela do programa.

## Problemas comuns

- **O painel não aparece em Extensões:** confirme que rodou `instalar_painel.ps1` e reiniciou o Premiere.
  Verifique o valor `PlayerDebugMode = 1` em `HKCU:\Software\Adobe\CSXS.11`.
- **"Não consegui ler o job":** o pipeline ainda não gerou `ultimo_job.json`, ou o `Y:` não está
  montado. Use **Escolher job**.
- **"XML do Premiere não encontrado":** rode o pipeline até a etapa do XML.
- **O Premiere não conseguiu criar o projeto:** a pasta no `E:` pode estar sem permissão ou cheia.
- **Proxies anexados: 0:** os caminhos dos originais no job não batem com os do XML importado
  (por exemplo, a unidade mudou de letra). Gere o job de novo.
