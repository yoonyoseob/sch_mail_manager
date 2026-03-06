#!/bin/bash
# mail.sch.ac.kr 메일 저장 웹 서비스 실행

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

source venv/bin/activate

echo "========================================"
echo " SCH 메일 자동 저장 - 웹 서비스"
echo " http://localhost:8080"
echo "========================================"
echo ""

python3 web_app.py
