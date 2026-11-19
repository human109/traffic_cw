# 내부 대시보드 실행 (http://localhost:8501, 이 PC에서만 접속)
Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\streamlit.exe" run dashboard/app.py --server.address 127.0.0.1
exit $LASTEXITCODE
