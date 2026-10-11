# Publicar o painel num servidor Windows (NSSM)

O painel roda como um serviço do Windows (via NSSM), numa porta própria, igual
aos seus outros sites Python. O servidor **não precisa baixar nada do TSE**: ele
só usa os arquivos já processados (`.parquet`) que você gerou no Mac.

## 1. No Mac: gerar o pacote

Na pasta do projeto, com o ambiente ativado:

```bash
python deploy/empacotar.py
```

Isso cria `pacote_servidor.zip` (código + `dados/secoes_*.parquet` +
`dados/logs_*.parquet`). Copie esse arquivo para o servidor.

## 2. No servidor: extrair

Extraia, por exemplo, em `C:\sites\` — vai ficar `C:\sites\esteleicao\`.

Requisitos: Python 3.10 ou mais novo (o mesmo dos outros sites serve) e o
`nssm.exe` no PATH. A máquina precisa de **~1,5 GB de RAM livre** para o painel
(a base tem ~500 mil seções e fica carregada em memória, compartilhada entre os
visitantes).

## 3. No servidor: instalar o serviço

Abra o **PowerShell como Administrador**:

```powershell
cd C:\sites\esteleicao
Get-ChildItem -Recurse | Unblock-File
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\deploy\instalar_servico_windows.ps1 -Porta 8503 -AbrirFirewall
```

O script cria o `.venv`, instala as dependências, registra o serviço
`esteleicao` no NSSM (início automático, reinício em caso de falha, logs em
`logs\servico.log`), libera a porta no firewall e testa se o painel respondeu.

Use uma porta que os outros dois sites não usam. Para ver as portas ocupadas:

```powershell
Get-NetTCPConnection -State Listen | Sort-Object LocalPort | Select-Object LocalPort, OwningProcess
```

Depois disso o painel fica em `http://IP-DO-SERVIDOR:8503/`. Se o servidor
estiver atrás de um roteador/nuvem, libere a mesma porta lá também (ex.: grupo
de segurança da VM ou redirecionamento de porta).

### Opções do script

| Opção | Para quê |
|---|---|
| `-Porta 8504` | outra porta |
| `-NomeServico eleicao2026` | outro nome de serviço |
| `-Certificado C:\certs\cert.pem -ChavePrivada C:\certs\key.pem` | HTTPS direto no Streamlit |
| `-CaminhoBase eleicao` | publicar em `http://servidor:porta/eleicao/` |
| `-Endereco 127.0.0.1 -Dominio https://eleicao.seusite.com.br` | se um dia colocar IIS/nginx na frente (o `-Dominio` é obrigatório nesse caso, senão o navegador é recusado) |
| `-Python C:\Python312\python.exe` | escolher qual Python cria o `.venv` |
| `-Nssm C:\tools\nssm.exe` | se o nssm não estiver no PATH |

Rodar o script de novo **atualiza** o serviço existente (não duplica).

## 4. Atualizar os dados ou o código

1. No Mac: `python deploy/empacotar.py`
2. No servidor: extraia por cima de `C:\sites\esteleicao\`
3. No servidor: `nssm restart esteleicao`

## Comandos úteis no servidor

```powershell
nssm status esteleicao
nssm restart esteleicao
nssm stop esteleicao
nssm edit esteleicao
Get-Content C:\sites\esteleicao\logs\servico.log -Tail 50
```

## Problemas comuns

- **Página abre mas fica "Connecting..." / "Please wait"**: algo entre o
  navegador e o servidor está bloqueando WebSocket (proxy, firewall corporativo).
  Se houver um proxy na frente, reinstale com `-Endereco 127.0.0.1 -Dominio https://seu-endereco`.
- **Serviço para sozinho**: veja `logs\servico.log`. Falta de memória aparece
  como `MemoryError`.
- **"Nenhum dado encontrado"**: faltou a pasta `dados` com os `.parquet`.
