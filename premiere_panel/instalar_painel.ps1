param([switch]$Desinstalar)

$ErrorActionPreference = "Stop"
$destino = Join-Path $env:APPDATA "Adobe\CEP\extensions\com.fokuss.roteiroia"

if ($Desinstalar) {
    if (Test-Path $destino) {
        Remove-Item -Recurse -Force $destino
        Write-Host "Painel Roteiro IA removido de $destino"
    } else {
        Write-Host "O painel nao estava instalado."
    }
    Write-Host "(O modo de depuracao do CEP foi mantido; outros paineis podem depender dele.)"
    exit 0
}

$origem = Split-Path -Parent $MyInvocation.MyCommand.Path

# Permite carregar paineis nao assinados no CEP 11 (Premiere 2024)
$chave = "HKCU:\Software\Adobe\CSXS.11"
if (-not (Test-Path $chave)) { New-Item -Path $chave -Force | Out-Null }
New-ItemProperty -Path $chave -Name "PlayerDebugMode" -Value "1" -PropertyType String -Force | Out-Null

# Copia o painel (substitui copia antiga)
if (Test-Path $destino) { Remove-Item -Recurse -Force $destino }
New-Item -ItemType Directory -Force -Path $destino | Out-Null
foreach ($item in @("CSXS", "host", "index.html", "main.js")) {
    Copy-Item -Recurse -Force (Join-Path $origem $item) $destino
}

Write-Host "Painel Roteiro IA instalado em: $destino"
Write-Host ""
Write-Host "Proximos passos:"
Write-Host "  1. Feche e abra o Premiere Pro."
Write-Host "  2. Menu Janela > Extensoes > Roteiro IA."
Write-Host "  3. Configure o cache de midia (veja o LEIA-ME.md)."
Write-Host "  4. Deixe o painel aberto: ele atende os botoes 'Abrir no Premiere' e 'Puxar roteiro' do Roteiro IA."
