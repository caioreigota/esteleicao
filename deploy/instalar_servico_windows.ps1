<#
.SYNOPSIS
    Instala o painel (Streamlit) como servico do Windows usando o NSSM.

.DESCRIPTION
    1. Cria o ambiente Python (.venv) na pasta do projeto e instala o requirements.txt
    2. Registra (ou atualiza) o servico no NSSM, com reinicio automatico e logs em .\logs
    3. Opcionalmente abre a porta no Firewall do Windows
    4. Inicia o servico e testa se respondeu

    Rode no PowerShell COMO ADMINISTRADOR, dentro da pasta do projeto:
        .\deploy\instalar_servico_windows.ps1
    O painel fica em 127.0.0.1:8503 (so interno); o Caddy publica em esteleicao.com
    (veja deploy\Caddyfile.est).

.PARAMETER Porta
    Porta em que o painel vai atender (padrao 8503). Use uma porta livre, diferente dos outros sites.
.PARAMETER Endereco
    127.0.0.1 (padrao): so interno, atras do Caddy/proxy.
    0.0.0.0: atende direto pela internet na porta escolhida (use com -AbrirFirewall).
.PARAMETER Dominio
    So necessario atras de proxy: endereco publico, ex. https://eleicao.meusite.com.br
.PARAMETER CaminhoBase
    Para publicar num subcaminho, ex. "eleicao" -> http://servidor:porta/eleicao
.PARAMETER Certificado / ChavePrivada
    Arquivos .pem para HTTPS direto no Streamlit (opcional).
.PARAMETER Python
    Caminho do python.exe usado para criar o .venv (padrao: "py -3" ou "python").
.PARAMETER Nssm
    Caminho do nssm.exe (padrao: "nssm" no PATH).
#>
param(
    [int]$Porta = 8503,
    [string]$Endereco = "127.0.0.1",
    [string]$NomeServico = "esteleicao",
    [string]$Dominio = "",
    [string]$CaminhoBase = "",
    [string]$Certificado = "",
    [string]$ChavePrivada = "",
    [string]$Python = "",
    [string]$Nssm = "nssm",
    [switch]$AbrirFirewall
)

$ErrorActionPreference = "Stop"
$Pasta = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LogArq = Join-Path (Join-Path $Pasta "logs") "servico.log"
function Passo($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Falha($t) { Write-Host "ERRO: $t" -ForegroundColor Red; exit 1 }

# --------------------------------------------------------------- verificacoes
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Falha "abra o PowerShell como Administrador." }

$nssmExe = (Get-Command $Nssm -ErrorAction SilentlyContinue).Source
if (-not $nssmExe) { Falha "nssm nao encontrado. Informe o caminho: -Nssm C:\caminho\nssm.exe" }

if (-not (Get-ChildItem (Join-Path $Pasta "dados\secoes_*.parquet") -ErrorAction SilentlyContinue)) {
    Falha "nenhum dados\secoes_*.parquet em $Pasta. Copie a pasta 'dados' (veja deploy\LEIAME_WINDOWS.md)."
}
$nLogs = (Get-ChildItem (Join-Path $Pasta "dados\logs_*.parquet") -ErrorAction SilentlyContinue).Count
Write-Host "Pasta do projeto: $Pasta"
Write-Host "Dados: secoes OK; $nLogs arquivo(s) de logs de urna"

$ocupada = Get-NetTCPConnection -LocalPort $Porta -State Listen -ErrorAction SilentlyContinue
$servicoExiste = $null -ne (Get-Service -Name $NomeServico -ErrorAction SilentlyContinue)
if ($ocupada -and -not $servicoExiste) {
    Falha "a porta $Porta ja esta em uso por outro programa. Escolha outra: -Porta 8504"
}

# --------------------------------------------------------------- ambiente Python
Passo "Ambiente Python (.venv)"
$venvPy = Join-Path $Pasta ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    if ($Python) { & $Python -m venv (Join-Path $Pasta ".venv") }
    elseif (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv (Join-Path $Pasta ".venv") }
    else { & python -m venv (Join-Path $Pasta ".venv") }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) { Falha "nao foi possivel criar o .venv" }
}
& $venvPy --version
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r (Join-Path $Pasta "requirements.txt")
if ($LASTEXITCODE -ne 0) { Falha "pip install falhou (veja a mensagem acima)" }

# --------------------------------------------------------------- servico NSSM
Passo "Servico '$NomeServico' no NSSM"
$params = @(
    "-m streamlit run painel.py",
    "--server.port $Porta",
    "--server.address $Endereco",
    "--server.headless true",
    "--server.fileWatcherType none",
    "--server.runOnSave false",
    "--browser.gatherUsageStats false",
    "--client.toolbarMode viewer"
)
if ($CaminhoBase)  { $params += "--server.baseUrlPath $CaminhoBase" }
if ($Dominio)      { $params += "--server.corsAllowedOrigins $Dominio" }
if ($Certificado -and $ChavePrivada) {
    $params += "--server.sslCertFile `"$Certificado`""
    $params += "--server.sslKeyFile `"$ChavePrivada`""
}
$appParams = $params -join " "

if ($servicoExiste) {
    Write-Host "Servico ja existe: parando para atualizar a configuracao"
    & $nssmExe stop $NomeServico confirm | Out-Null
} else {
    & $nssmExe install $NomeServico $venvPy | Out-Null
}
New-Item -ItemType Directory -Force (Join-Path $Pasta "logs") | Out-Null
& $nssmExe set $NomeServico Application $venvPy | Out-Null
& $nssmExe set $NomeServico AppParameters $appParams | Out-Null
& $nssmExe set $NomeServico AppDirectory $Pasta | Out-Null
& $nssmExe set $NomeServico DisplayName "Painel eleicao 2026 (Streamlit)" | Out-Null
& $nssmExe set $NomeServico Description "Abstencao, horario de votacao e identificacao do eleitor por secao - dados abertos do TSE" | Out-Null
& $nssmExe set $NomeServico Start SERVICE_AUTO_START | Out-Null
& $nssmExe set $NomeServico AppStdout $LogArq | Out-Null
& $nssmExe set $NomeServico AppStderr $LogArq | Out-Null
& $nssmExe set $NomeServico AppRotateFiles 1 | Out-Null
& $nssmExe set $NomeServico AppRotateOnline 1 | Out-Null
& $nssmExe set $NomeServico AppRotateBytes 10485760 | Out-Null
& $nssmExe set $NomeServico AppEnvironmentExtra "PYTHONUTF8=1" "PYTHONIOENCODING=utf-8" | Out-Null
& $nssmExe set $NomeServico AppExit Default Restart | Out-Null
& $nssmExe set $NomeServico AppRestartDelay 5000 | Out-Null
Write-Host "Comando: $venvPy $appParams"

# --------------------------------------------------------------- firewall
if ($AbrirFirewall) {
    Passo "Firewall: liberando a porta $Porta (TCP, entrada)"
    $regra = "esteleicao (porta $Porta)"
    Get-NetFirewallRule -DisplayName $regra -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $regra -Direction Inbound -Protocol TCP -LocalPort $Porta -Action Allow | Out-Null
}

# --------------------------------------------------------------- inicia e testa
Passo "Iniciando"
& $nssmExe start $NomeServico | Out-Null
$esquema = if ($Certificado -and $ChavePrivada) { "https" } else { "http" }
$sub = if ($CaminhoBase) { "/$CaminhoBase" } else { "" }
$url = "${esquema}://127.0.0.1:$Porta$sub/_stcore/health"
$ok = $false
for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
    Start-Sleep -Seconds 2
    try { $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 5; $ok = ($r.StatusCode -eq 200) } catch {}
}
if ($ok) {
    Write-Host "`nOK: o painel esta no ar." -ForegroundColor Green
    Write-Host "   Neste servidor:   ${esquema}://localhost:$Porta$sub/"
    if ($Endereco -eq "127.0.0.1") {
        Write-Host "   Pela internet:    via Caddy (deploy\Caddyfile.est) -> https://esteleicao.com/"
        Write-Host "   Depois de instalar, reinicie o servico do Caddy no NSSM para ele ler o Caddyfile.est."
    } else {
        Write-Host "   Pela internet:    ${esquema}://<IP-ou-dominio-do-servidor>:$Porta$sub/"
    }
    Write-Host "   A 1a abertura demora alguns segundos (carrega ~500 mil secoes)."
} else {
    Write-Host "`nO servico nao respondeu em 60 s. Veja o log: $LogArq" -ForegroundColor Yellow
    Write-Host "   Status: $(& $nssmExe status $NomeServico)"
}
Write-Host "`nComandos uteis:  nssm restart $NomeServico | nssm stop $NomeServico | nssm edit $NomeServico"
