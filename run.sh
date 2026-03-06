#!/bin/bash
# mail.sch.ac.kr 메일 자동 저장 실행 스크립트

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 가상환경 활성화
source venv/bin/activate

echo "========================================"
echo " mail.sch.ac.kr 메일 자동 저장 도구"
echo "========================================"
echo ""
echo "사용법:"
echo "  전체 다운로드:        ./run.sh"
echo "  특정 페이지부터:      ./run.sh --start-page 5"
echo "  최대 10페이지만:      ./run.sh --max-pages 10"
echo "  페이지당 50통 설정:   ./run.sh --page-size 50"
echo ""

python3 mail_downloader.py "$@"
