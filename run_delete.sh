#!/bin/bash
# mail.sch.ac.kr 메일 삭제 실행 스크립트

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 가상환경 활성화
source venv/bin/activate

echo "========================================"
echo " mail.sch.ac.kr 메일 삭제 도구"
echo "========================================"
echo ""
echo "사용법:"
echo "  전체 삭제:              ./run_delete.sh"
echo "  4~122페이지 삭제:       ./run_delete.sh --start-page 4 --end-page 122"
echo "  특정 메일함 지정:       ./run_delete.sh --folder 받은메일함"
echo ""
echo "※ 반드시 백업(run.sh)을 먼저 실행한 후 사용하세요!"
echo ""

python3 mail_deleter.py "$@"
