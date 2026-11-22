# 내부 대시보드 실행 (http://localhost:8501, 이 PC에서만 접속)
Set-Location -LiteralPath $PSScriptRoot
# 로그 파일은 프로세스마다 따로 쓴다 (수집기 app.log 회전 충돌 방지, 2026-11-23)
$env:LOG_FILE = "dashboard.log"
& "$PSScriptRoot\.venv\Scripts\streamlit.exe" run dashboard/app.py --server.address 127.0.0.1
exit $LASTEXITCODE
