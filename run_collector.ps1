# 수집 파이프라인 상주 실행 (5분마다 수집 → 집계 → 실제값 갱신 → 예측)
# 1회만 실행: .\run_collector.ps1 --once
Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" -m collector.scheduler @args
exit $LASTEXITCODE
