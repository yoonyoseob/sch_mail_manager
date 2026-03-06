# SCH Mail Manager

순천향대학교 웹메일(mail.sch.ac.kr) 백업 및 삭제 자동화 도구입니다.

Playwright 브라우저 자동화를 통해 메일을 EML/ZIP 형식으로 백업하고, 완전삭제를 수행합니다.
Flask 기반 웹 UI에서 백업/삭제를 제어하고 실시간 로그를 확인할 수 있습니다.

## 주요 기능

- **메일 백업** — 메일함의 모든 메일을 페이지 단위로 자동 저장 (EML → ZIP)
- **메일 삭제** — 전체선택 → 완전삭제를 페이지 반복으로 자동 수행
- **웹 UI** — 브라우저에서 백업/삭제 제어, 실시간 로그, 파일 관리, 메일 검색
- **CLI** — 셸 스크립트 또는 직접 Python 실행

## 구조

```
├── web_app.py              # Flask 웹 서비스 (메인)
├── mail_downloader.py      # 메일 백업 스크립트 (Playwright)
├── mail_deleter.py         # 메일 삭제 스크립트 (Playwright)
├── templates/
│   └── index.html          # 웹 UI (백업/삭제 탭, 실시간 로그, 메일 검색)
├── run_web.sh              # 웹 서비스 실행
├── run.sh                  # CLI 백업 실행
├── run_delete.sh           # CLI 삭제 실행
├── downloads/              # 백업된 ZIP 파일 저장 경로
└── venv/                   # Python 가상환경
```

## 설치

```bash
# 가상환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install flask playwright

# Playwright 브라우저 설치
playwright install chromium
```

## 사용법

### 웹 UI (권장)

```bash
./run_web.sh
# 또는
source venv/bin/activate && python3 web_app.py
```

`http://localhost:8080` 에서 접속하여 백업/삭제를 제어합니다.

1. **백업 탭** — 메일함, 시작 페이지, 최대 페이지 등 설정 후 시작
2. **삭제 탭** — 시작/종료 페이지 설정 후 삭제 시작

시작 버튼을 누르면 Playwright 브라우저 창이 열리며, 해당 창에서 로그인하면 자동으로 동작합니다.

### CLI

```bash
# 백업
./run.sh                              # 전체 백업
./run.sh --start-page 5               # 5페이지부터
./run.sh --max-pages 10               # 최대 10페이지만

# 삭제
./run_delete.sh                       # 전체 삭제 (메일 소진까지)
./run_delete.sh --start-page 4 --end-page 122   # 4~122페이지 분량 삭제
./run_delete.sh --folder 받은메일함    # 특정 메일함 지정
```

### 삭제 동작 방식

삭제 시 메일이 앞으로 당겨지므로, 시작 페이지에 머물면서 반복 삭제합니다.

- `--start-page 4 --end-page 122` → 4페이지에서 119회 반복 삭제 (4~122페이지 분량)
- `--end-page 0` (기본값) → 메일이 소진될 때까지 무한 반복

## 참고

- 삭제된 메일은 복구할 수 없습니다. 반드시 백업을 먼저 완료한 후 삭제하세요.
- 웹 UI의 메일 검색 기능은 백업된 ZIP 내 EML 파일을 파싱하여 검색합니다.
- 브라우저 로그인 대기 시간은 5분이며, 초과 시 자동 종료됩니다.
