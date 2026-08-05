$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'C:\Users\andon\AppData\Local\Programs\Python\Python314\python.exe'

Set-Location -LiteralPath $root
& $python (Join-Path $root 'collector.py')
if ($LASTEXITCODE -ne 0) {
    throw "采集程序运行失败，退出代码：$LASTEXITCODE"
}

git add -- 'index.html' '滨海新区土地信息.html' 'dashboard_data.json'
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    exit 0
}

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'
git commit -m "Daily update $stamp"
git push origin main
