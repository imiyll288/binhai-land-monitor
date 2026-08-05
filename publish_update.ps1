$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'C:\Users\andon\AppData\Local\Programs\Python\Python314\python.exe'

Set-Location -LiteralPath $root
& $python (Join-Path $root 'collector.py')
if ($LASTEXITCODE -ne 0) {
    throw "采集程序运行失败，退出代码：$LASTEXITCODE"
}

git add --all
if ($LASTEXITCODE -ne 0) {
    throw "Git 暂存失败，退出代码：$LASTEXITCODE"
}

git diff --cached --quiet
$diffExitCode = $LASTEXITCODE
if ($diffExitCode -eq 0) {
    exit 0
}
if ($diffExitCode -ne 1) {
    throw "Git 差异检查失败，退出代码：$diffExitCode"
}

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'
git commit -m "Daily update $stamp"
if ($LASTEXITCODE -ne 0) {
    throw "Git 提交失败，退出代码：$LASTEXITCODE"
}

git push origin main
if ($LASTEXITCODE -ne 0) {
    throw "Git 发布失败，退出代码：$LASTEXITCODE"
}
