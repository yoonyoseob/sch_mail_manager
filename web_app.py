"""
mail.sch.ac.kr 메일 자동 저장 - 웹 서비스
Flask 기반 웹 UI: 실행 제어, 실시간 로그, 다운로드 파일 관리
"""

import email
import email.policy
import json
import os
import re
import subprocess
import threading
import time
import zipfile
from collections import deque
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_UNREAD_DIR = BASE_DIR / "downloads_안읽은메일"
SCRIPT_PATH = BASE_DIR / "mail_downloader.py"
DELETE_SCRIPT_PATH = BASE_DIR / "mail_deleter.py"
PYTHON_PATH = BASE_DIR / "venv" / "bin" / "python3"

app = Flask(__name__)

# 백업 프로세스 상태
process: subprocess.Popen | None = None
process_lock = threading.Lock()
log_buffer: deque[str] = deque(maxlen=500)
log_buffer_lock = threading.Lock()
process_status = {"running": False, "start_time": None, "pid": None}

# 삭제 프로세스 상태
del_process: subprocess.Popen | None = None
del_process_lock = threading.Lock()
del_log_buffer: deque[str] = deque(maxlen=500)
del_log_buffer_lock = threading.Lock()
del_process_status = {"running": False, "start_time": None, "pid": None}


def append_log(msg: str):
    ts = time.strftime("%H:%M:%S")
    with log_buffer_lock:
        log_buffer.append(f"[{ts}] {msg}")


def stream_output(proc: subprocess.Popen):
    """서브프로세스 stdout/stderr를 log_buffer로 수집"""
    for line in proc.stdout:
        text = line.rstrip()
        if text:
            append_log(text)
    proc.wait()
    with process_lock:
        global process
        process = None
        process_status["running"] = False
        process_status["pid"] = None
    append_log("=== 프로세스가 종료되었습니다 ===")


def del_append_log(msg: str):
    ts = time.strftime("%H:%M:%S")
    with del_log_buffer_lock:
        del_log_buffer.append(f"[{ts}] {msg}")


def del_stream_output(proc: subprocess.Popen):
    """삭제 서브프로세스 stdout/stderr를 del_log_buffer로 수집"""
    for line in proc.stdout:
        text = line.rstrip()
        if text:
            del_append_log(text)
    proc.wait()
    with del_process_lock:
        global del_process
        del_process = None
        del_process_status["running"] = False
        del_process_status["pid"] = None
    del_append_log("=== 삭제 프로세스가 종료되었습니다 ===")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def api_start():
    global process
    with process_lock:
        if process and process.poll() is None:
            return jsonify({"ok": False, "error": "이미 실행 중입니다."})

        data = request.get_json(silent=True) or {}
        start_page = int(data.get("start_page", 1))
        max_pages = int(data.get("max_pages", 0))
        page_size = int(data.get("page_size", 30))
        folder = data.get("folder", "전체메일")

        # 다운로드 폴더 결정
        dl_dir = DOWNLOADS_UNREAD_DIR if folder == "안읽은메일함" else DOWNLOADS_DIR
        dl_dir.mkdir(exist_ok=True)

        cmd = [
            str(PYTHON_PATH), str(SCRIPT_PATH),
            "--start-page", str(start_page),
            "--max-pages", str(max_pages),
            "--page-size", str(page_size),
            "--folder", folder,
        ]

        env = os.environ.copy()
        env["DOWNLOAD_DIR_OVERRIDE"] = str(dl_dir)

        with log_buffer_lock:
            log_buffer.clear()

        append_log(f"시작: {' '.join(cmd)}")
        append_log(f"폴더: {folder}  |  시작 페이지: {start_page}  |  최대 페이지: {max_pages or '전체'}  |  페이지 크기: {page_size}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=str(BASE_DIR),
        )

        process_status["running"] = True
        process_status["start_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        process_status["pid"] = process.pid

        t = threading.Thread(target=stream_output, args=(process,), daemon=True)
        t.start()

    return jsonify({"ok": True, "pid": process_status["pid"]})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    global process
    with process_lock:
        if not process or process.poll() is not None:
            return jsonify({"ok": False, "error": "실행 중인 프로세스가 없습니다."})
        process.terminate()
        append_log("=== 사용자가 프로세스를 중단했습니다 ===")
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    with process_lock:
        running = process is not None and process.poll() is None
        process_status["running"] = running
    return jsonify(process_status)


@app.route("/api/logs")
def api_logs():
    """SSE: 실시간 로그 스트리밍"""
    last_idx = [0]

    def generate():
        # 기존 버퍼 먼저 전송
        with log_buffer_lock:
            snapshot = list(log_buffer)
        for line in snapshot:
            yield f"data: {json.dumps(line)}\n\n"
        last_idx[0] = len(snapshot)

        while True:
            with log_buffer_lock:
                current = list(log_buffer)
            new_lines = current[last_idx[0]:]
            for line in new_lines:
                yield f"data: {json.dumps(line)}\n\n"
            last_idx[0] = len(current)
            time.sleep(0.3)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


## ── 삭제 API ──


@app.route("/api/delete/start", methods=["POST"])
def api_delete_start():
    global del_process
    with del_process_lock:
        if del_process and del_process.poll() is None:
            return jsonify({"ok": False, "error": "이미 삭제 프로세스가 실행 중입니다."})

        data = request.get_json(silent=True) or {}
        start_page = int(data.get("start_page", 1))
        end_page = int(data.get("end_page", 0))
        page_size = int(data.get("page_size", 30))
        folder = data.get("folder", "전체메일")

        cmd = [
            str(PYTHON_PATH), str(DELETE_SCRIPT_PATH),
            "--start-page", str(start_page),
            "--end-page", str(end_page),
            "--page-size", str(page_size),
            "--folder", folder,
            "--yes",
        ]

        with del_log_buffer_lock:
            del_log_buffer.clear()

        range_str = f"{start_page}~{end_page}페이지" if end_page > 0 else f"{start_page}페이지부터 전체"
        del_append_log(f"삭제 시작: {' '.join(cmd)}")
        del_append_log(f"폴더: {folder}  |  삭제 범위: {range_str}  |  페이지 크기: {page_size}")

        del_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(BASE_DIR),
        )

        del_process_status["running"] = True
        del_process_status["start_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        del_process_status["pid"] = del_process.pid

        t = threading.Thread(target=del_stream_output, args=(del_process,), daemon=True)
        t.start()

    return jsonify({"ok": True, "pid": del_process_status["pid"]})


@app.route("/api/delete/stop", methods=["POST"])
def api_delete_stop():
    global del_process
    with del_process_lock:
        if not del_process or del_process.poll() is not None:
            return jsonify({"ok": False, "error": "실행 중인 삭제 프로세스가 없습니다."})
        del_process.terminate()
        del_append_log("=== 사용자가 삭제 프로세스를 중단했습니다 ===")
    return jsonify({"ok": True})


@app.route("/api/delete/status")
def api_delete_status():
    with del_process_lock:
        running = del_process is not None and del_process.poll() is None
        del_process_status["running"] = running
    return jsonify(del_process_status)


@app.route("/api/delete/logs")
def api_delete_logs():
    """SSE: 삭제 실시간 로그 스트리밍"""
    last_idx = [0]

    def generate():
        with del_log_buffer_lock:
            snapshot = list(del_log_buffer)
        for line in snapshot:
            yield f"data: {json.dumps(line)}\n\n"
        last_idx[0] = len(snapshot)

        while True:
            with del_log_buffer_lock:
                current = list(del_log_buffer)
            new_lines = current[last_idx[0]:]
            for line in new_lines:
                yield f"data: {json.dumps(line)}\n\n"
            last_idx[0] = len(current)
            time.sleep(0.3)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/files")
def api_files():
    """다운로드된 ZIP 파일 목록"""
    result = []
    for folder, label in [(DOWNLOADS_DIR, "받은메일함"), (DOWNLOADS_UNREAD_DIR, "안읽은메일함")]:
        if not folder.exists():
            continue
        for f in sorted(folder.glob("*.zip"), reverse=True):
            stat = f.stat()
            result.append({
                "name": f.name,
                "folder": label,
                "size": stat.st_size,
                "size_kb": round(stat.st_size / 1024, 1),
                "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                "path": str(f.relative_to(BASE_DIR)),
            })
    return jsonify(result)


def _parse_eml(data: bytes) -> dict:
    """EML 바이트를 파싱하여 제목/발신자/수신자/날짜/본문을 반환"""
    msg = email.message_from_bytes(data, policy=email.policy.default)
    # 텍스트 본문 추출
    body = ""
    body_obj = msg.get_body(preferencelist=("plain",))
    if body_obj:
        body = body_obj.get_content()
    if not body:
        body_obj = msg.get_body(preferencelist=("html",))
        if body_obj:
            body = body_obj.get_content()
    return {
        "subject": msg["subject"] or "(제목 없음)",
        "from": msg["from"] or "",
        "to": msg["to"] or "",
        "date": msg["date"] or "",
        "body": body,
    }


def _get_all_zips():
    """다운로드 폴더들에서 모든 ZIP 파일 목록 반환"""
    zips = []
    for folder in [DOWNLOADS_DIR, DOWNLOADS_UNREAD_DIR]:
        if folder.exists():
            zips.extend(folder.glob("*.zip"))
    return sorted(zips)


@app.route("/api/search")
def api_search():
    """메일 검색: 모든 ZIP 내 EML을 파싱하여 키워드 검색"""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    query_lower = query.lower()
    results = []

    for zip_path in _get_all_zips():
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for name in zf.namelist():
                    if not name.lower().endswith(".eml"):
                        continue
                    try:
                        parsed = _parse_eml(zf.read(name))
                        # 제목, 발신자, 수신자, 본문에서 검색
                        searchable = (
                            parsed["subject"] + parsed["from"]
                            + parsed["to"] + parsed["body"]
                        ).lower()
                        if query_lower in searchable:
                            # 본문 미리보기 (200자)
                            # HTML 태그 제거
                            preview = re.sub(r"<[^>]+>", "", parsed["body"])
                            preview = re.sub(r"\s+", " ", preview).strip()[:200]
                            results.append({
                                "zip": str(zip_path.relative_to(BASE_DIR)),
                                "eml": name,
                                "subject": parsed["subject"],
                                "from": parsed["from"],
                                "to": parsed["to"],
                                "date": parsed["date"],
                                "preview": preview,
                            })
                    except Exception:
                        continue
        except Exception:
            continue

    return jsonify(results)


@app.route("/api/mail/content")
def api_mail_content():
    """특정 EML 파일의 전체 내용 반환"""
    zip_rel = request.args.get("zip", "")
    eml_name = request.args.get("eml", "")
    if not zip_rel or not eml_name:
        return jsonify({"error": "zip, eml 파라미터가 필요합니다."}), 400

    zip_path = (BASE_DIR / zip_rel).resolve()
    if BASE_DIR not in zip_path.parents and zip_path != BASE_DIR:
        return jsonify({"error": "Invalid path"}), 403
    if not zip_path.exists():
        return jsonify({"error": "ZIP not found"}), 404

    try:
        with zipfile.ZipFile(zip_path) as zf:
            data = zf.read(eml_name)
        parsed = _parse_eml(data)
        return jsonify(parsed)
    except KeyError:
        return jsonify({"error": "EML not found in ZIP"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download/<path:rel_path>")
def api_download(rel_path: str):
    """파일 다운로드"""
    target = (BASE_DIR / rel_path).resolve()
    # 경로 탈출 방지
    if BASE_DIR not in target.parents and target != BASE_DIR:
        return jsonify({"error": "Invalid path"}), 403
    if not target.exists() or not target.is_file():
        return jsonify({"error": "File not found"}), 404
    return send_file(target, as_attachment=True)


if __name__ == "__main__":
    print("=" * 50)
    print(" mail.sch.ac.kr 메일 저장 웹 서비스")
    print(" http://localhost:8080 에서 접속하세요")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
