"""
mail.sch.ac.kr 메일 자동 저장 스크립트
- 받은메일함의 모든 페이지를 순회하며 저장 버튼 자동 클릭
- 저장된 파일은 downloads/ 폴더에 보관
"""

import asyncio
import re
import urllib.parse
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

MAIL_URL = "https://mail.sch.ac.kr"
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
# 페이지당 메일 수 (기본값: 30, 메일 설정에서 변경 가능)
PAGE_SIZE = 30


async def wait_for_page_load(page):
    """메일 목록 테이블이 로드될 때까지 대기"""
    await page.wait_for_load_state("networkidle", timeout=15000)


async def get_total_mail_count(page) -> int:
    """전체 메일 수 파싱"""
    try:
        # "받은메일함 안읽은 메일 N통 / 전체메일 M통" 패턴에서 M 추출
        text = await page.inner_text("body")
        match = re.search(r"전체메일\s+(\d+)\s*통", text)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 0


async def select_all_and_save(page, page_num: int, download_dir: Path) -> bool:
    """현재 페이지: 전체선택 → 저장 클릭 → 팝업에서 다운로드 버튼 클릭"""
    print(f"\n[페이지 {page_num}] 전체선택 중...")

    try:
        # 현재 페이지 상태 확인
        row_count = 0
        try:
            row_count = await page.locator("table tbody tr").count()
        except Exception:
            pass
        print(f"  현재 테이블 행 수: {row_count}")
        print(f"  현재 URL: {page.url[:100]}")

        # 전체선택
        select_all_selectors = [
            "text=전체선택",
            "input[type='checkbox'][name*='all']",
            "input[type='checkbox'].checkAll",
            "th input[type='checkbox']",
            "#checkAll",
            ".btn-all",
        ]
        selected = False
        for sel in select_all_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    selected = True
                    print(f"  전체선택 완료 (선택자: {sel})")
                    break
            except Exception:
                continue

        if not selected:
            print("  [경고] 전체선택 버튼을 찾지 못했습니다.")
            await page.screenshot(path=str(download_dir / f"debug_page{page_num}.png"))
            return False

        await asyncio.sleep(0.5)

        # 저장 버튼 클릭 → 팝업 대기
        save_selectors = [
            "text=저장",
            "button:has-text('저장')",
            "a:has-text('저장')",
            "input[value='저장']",
            "#btnSave",
            ".btn-save",
        ]

        popup_page = None
        for sel in save_selectors:
            try:
                btn = page.locator(sel).first
                if not await btn.is_visible(timeout=2000):
                    continue
                print(f"  저장 버튼 클릭 중 (선택자: {sel})...")
                # 저장 클릭과 동시에 팝업 창 대기
                async with page.context.expect_page(timeout=30000) as popup_info:
                    await btn.click()
                popup_page = await popup_info.value
                await popup_page.wait_for_load_state("domcontentloaded")
                break
            except PlaywrightTimeout:
                print(f"  [경고] 팝업 대기 타임아웃 (선택자: {sel})")
                continue
            except Exception as e:
                print(f"  [오류] {sel}: {e}")
                continue

        if popup_page is None:
            print("  [경고] 팝업 창이 열리지 않았습니다.")
            await page.screenshot(path=str(download_dir / f"debug_page{page_num}.png"))
            return False

        # 팝업: "#btn_download" 버튼이 나타날 때까지 대기 (서버 압축 완료 시점)
        print("  팝업 대기 중 (서버 압축 완료 기다리는 중)...")
        try:
            await popup_page.wait_for_selector(
                "#btn_download:not([style*='display:none']):not([style*='display: none'])",
                timeout=120000,
            )
        except PlaywrightTimeout:
            pass  # 이미 표시된 상태일 수 있으므로 계속 진행

        # backup.zipFileName 추출 (fallback용)
        zip_filename = None
        try:
            zip_filename = await popup_page.evaluate("() => backup.zipFileName")
            print(f"  ZIP 파일명: {zip_filename}")
        except Exception:
            pass

        # 방법 1: #btn_download 클릭 + expect_download
        saved = False
        btn = popup_page.locator("#btn_download")
        try:
            await btn.wait_for(state="visible", timeout=10000)
            print("  다운로드 버튼 클릭 중 (#btn_download)...")
            async with popup_page.expect_download(timeout=60000) as dl_info:
                await btn.click()
            download = await dl_info.value
            saved = True
        except PlaywrightTimeout:
            print("  [정보] expect_download 타임아웃 → JS 직접 호출 시도...")
        except Exception as e:
            print(f"  [정보] 버튼 클릭 오류: {e} → JS 직접 호출 시도...")

        # 방법 2: backup.download() JS 직접 호출 + expect_download
        if not saved:
            try:
                async with popup_page.expect_download(timeout=60000) as dl_info:
                    await popup_page.evaluate("backup.download()")
                download = await dl_info.value
                saved = True
            except PlaywrightTimeout:
                print("  [정보] JS 호출도 타임아웃 → 네트워크 요청 인터셉트 시도...")
            except Exception as e:
                print(f"  [정보] JS 호출 오류: {e}")

        # 방법 3: 요청 인터셉트로 실제 다운로드 URL 포착
        if not saved and zip_filename:
            print("  네트워크 인터셉트로 다운로드 URL 탐색 중...")
            found_url = None

            async def intercept(route, request):
                nonlocal found_url
                if zip_filename in request.url or "download" in request.url.lower():
                    found_url = request.url
                await route.continue_()

            await popup_page.route("**/*", intercept)
            try:
                async with popup_page.expect_download(timeout=30000) as dl_info:
                    await popup_page.evaluate("backup.download()")
                download = await dl_info.value
                saved = True
            except Exception:
                pass
            finally:
                await popup_page.unroute("**/*", intercept)

            if not saved and found_url:
                print(f"  직접 URL로 다운로드 시도: {found_url}")
                try:
                    async with popup_page.expect_download(timeout=60000) as dl_info:
                        await popup_page.goto(found_url)
                    download = await dl_info.value
                    saved = True
                except Exception as e:
                    print(f"  [오류] 직접 URL 다운로드 실패: {e}")

        # 팝업 닫기
        try:
            await popup_page.close()
        except Exception:
            pass

        if not saved:
            print("  [경고] 모든 방법으로 다운로드 실패.")
            return False

        # 파일 저장
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        orig_name = download.suggested_filename or zip_filename or f"mail_page{page_num}.zip"
        save_name = f"{timestamp}_page{page_num:04d}_{orig_name}"
        save_path = download_dir / save_name

        await download.save_as(save_path)
        size_kb = save_path.stat().st_size / 1024
        print(f"  저장 완료: {save_name} ({size_kb:.1f} KB)")
        return True

    except Exception as e:
        print(f"  [오류] {e}")
        await page.screenshot(path=str(download_dir / f"error_page{page_num}.png"))
        return False


async def get_current_cpage(page) -> int | None:
    """현재 URL 해시에서 cpage 값을 추출"""
    url = page.url
    if "#" not in url:
        return None
    hash_decoded = urllib.parse.unquote(url.split("#", 1)[1])
    m = re.search(r"cpage=(\d+)", hash_decoded)
    return int(m.group(1)) if m else None


async def go_to_next_page(page, page_num: int) -> bool:
    """다음 페이지로 이동. 마지막 페이지면 False 반환.

    SCH 메일은 hash 기반 SPA: #folder=INBOX&...&cpage=N
    해시를 직접 변경하면 SPA가 무시할 수 있으므로,
    location.hash를 JS로 직접 설정하여 hashchange 이벤트를 발생시킨다.
    """
    next_page = page_num + 1
    current_url = page.url

    if "#" not in current_url:
        print(f"  [경고] URL에 해시가 없습니다: {current_url}")
        return False

    base, raw_hash = current_url.split("#", 1)
    hash_decoded = urllib.parse.unquote(raw_hash)

    if "cpage=" in hash_decoded:
        new_hash = re.sub(r"cpage=\d+", f"cpage={next_page}", hash_decoded)
    else:
        new_hash = hash_decoded.rstrip("&") + f"&cpage={next_page}&"

    print(f"  [{page_num} → {next_page}] 페이지 이동 중...")

    # JS로 location.hash를 직접 설정하여 SPA 라우터가 반응하도록 함
    await page.evaluate(f"() => {{ location.hash = '{new_hash}'; }}")
    await wait_for_page_load(page)
    await asyncio.sleep(1.5)

    # 해시 변경으로 이동이 안 된 경우 page.goto로 재시도
    actual_cpage = await get_current_cpage(page)
    if actual_cpage is not None and actual_cpage != next_page:
        print(f"  [재시도] hash 변경 실패 (cpage={actual_cpage}), goto로 재시도...")
        new_url = base + "#" + urllib.parse.quote(new_hash, safe="")
        await page.goto(new_url)
        await wait_for_page_load(page)
        await asyncio.sleep(1.5)
        actual_cpage = await get_current_cpage(page)

    if actual_cpage is not None and actual_cpage < next_page:
        print(f"  [정보] 서버가 cpage를 {actual_cpage}로 보정 → 마지막 페이지 초과")
        return False

    # 메일 행이 있는지 확인
    try:
        row_count = await page.locator("table tbody tr").count()
        if row_count == 0:
            print(f"  [정보] 페이지 {next_page}: 메일 행 없음 → 마지막 페이지")
            return False
    except Exception:
        pass

    print(f"  페이지 {next_page} 이동 완료 (cpage={actual_cpage})")
    return True


async def run(start_page: int = 1, max_pages: int = 0, folder: str = "전체메일"):
    """메인 실행 함수"""
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    print(f"다운로드 폴더: {DOWNLOAD_DIR.absolute()}")

    async with async_playwright() as p:
        # 브라우저 시작 (headless=False: 사용자가 로그인할 수 있도록 창 표시)
        browser = await p.chromium.launch(
            headless=False,
            downloads_path=str(DOWNLOAD_DIR),
        )
        context = await browser.new_context(
            accept_downloads=True,
        )
        page = await context.new_page()

        print(f"\n{MAIL_URL} 로 이동합니다...")
        await page.goto(MAIL_URL)

        # 로그인 대기
        print("\n" + "="*60)
        print("브라우저에서 로그인 해주세요.")
        print("로그인 완료 후 자동으로 시작됩니다.")
        print("="*60)

        # 로그인 완료 대기 (사이드바의 메일함 목록이 보일 때까지, 최대 5분)
        try:
            await page.wait_for_selector(
                "text=전체메일", timeout=300000
            )
            print("\n로그인 감지! 메일 목록 로드 중...")
        except PlaywrightTimeout:
            print("[오류] 5분 내에 로그인되지 않아 종료합니다.")
            await browser.close()
            return

        # 사이드바에서 원하는 메일함 클릭으로 이동
        await wait_for_page_load(page)
        await asyncio.sleep(1)

        # 사이드바 메일함 링크 클릭
        print(f"  '{folder}' 메일함으로 이동 중...")
        sidebar_link = page.locator(f"text={folder}").first
        try:
            await sidebar_link.click()
            print(f"  '{folder}' 클릭 완료")
        except Exception as e:
            print(f"  [경고] 사이드바 '{folder}' 클릭 실패: {e}")

        await wait_for_page_load(page)
        await asyncio.sleep(2)

        # 이동 후 URL 해시에서 folder 값 확인 (디버깅용)
        current_url = page.url
        if "#" in current_url:
            hash_decoded = urllib.parse.unquote(current_url.split("#", 1)[1])
            print(f"  URL 해시: {hash_decoded[:100]}")
        print(f"  메일 목록 로드 완료: {current_url[:80]}...")

        # 실제 페이지 크기 자동 감지 (현재 페이지의 행 수)
        try:
            actual_rows = await page.locator("table tbody tr").count()
            detected_page_size = actual_rows if actual_rows > 0 else PAGE_SIZE
        except Exception:
            detected_page_size = PAGE_SIZE
        print(f"  감지된 페이지 크기: {detected_page_size}통/페이지")

        # 전체 메일 수 확인 → 총 페이지 수 계산
        total = await get_total_mail_count(page)
        if total > 0:
            total_pages = (total + detected_page_size - 1) // detected_page_size
            print(f"\n전체 메일: {total}통 / 예상 페이지: {total_pages}페이지")
        else:
            print("\n전체 메일 수를 파악할 수 없습니다. 끝 페이지까지 진행합니다.")
            total_pages = 9999

        if max_pages > 0:
            total_pages = min(total_pages, start_page - 1 + max_pages)
            print(f"최대 {max_pages}페이지만 처리합니다.")

        # 시작 페이지로 직접 이동 (location.hash로 SPA 라우터 트리거)
        if start_page > 1:
            print(f"\n{start_page}페이지로 직접 이동 중...")
            current_url = page.url
            raw_hash = current_url.split("#")[1] if "#" in current_url else ""
            hash_decoded = urllib.parse.unquote(raw_hash) if raw_hash else ""

            if "cpage=" in hash_decoded:
                jump_hash = re.sub(r"cpage=\d+", f"cpage={start_page}", hash_decoded)
            else:
                jump_hash = hash_decoded.rstrip("&") + f"&cpage={start_page}&"

            # 현재 해시와 다르게 만들어 SPA가 변경을 감지하도록 함
            # 먼저 임시 해시로 이동 후 실제 해시로 이동
            temp_hash = re.sub(r"cpage=\d+", "cpage=0", hash_decoded) if "cpage=" in hash_decoded else hash_decoded
            await page.evaluate(f"() => {{ location.hash = '{temp_hash}'; }}")
            await asyncio.sleep(0.5)
            await page.evaluate(f"() => {{ location.hash = '{jump_hash}'; }}")
            await wait_for_page_load(page)
            await asyncio.sleep(3)

            # 테이블 로드 대기
            try:
                await page.wait_for_selector("table tbody tr", timeout=10000)
            except PlaywrightTimeout:
                print("  [경고] 테이블 로드 타임아웃")

            actual = await get_current_cpage(page)
            row_count = await page.locator("table tbody tr").count()
            print(f"  {start_page}페이지 이동 완료 (cpage={actual}, 행수={row_count})")

            # 디버깅: 스크린샷
            debug_path = DOWNLOAD_DIR / f"debug_jump_page{start_page}.png"
            await page.screenshot(path=str(debug_path))
            print(f"  디버그 스크린샷: {debug_path}")

        # 페이지 순회
        success_count = 0
        fail_count = 0
        current_page = start_page

        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 3

        while current_page <= total_pages:
            try:
                ok = await select_all_and_save(page, current_page, DOWNLOAD_DIR)
                if ok:
                    success_count += 1
                    consecutive_errors = 0
                else:
                    fail_count += 1
                    consecutive_errors += 1
                    print(f"  ↳ 재시작하려면: --start-page {current_page}")
            except Exception as e:
                fail_count += 1
                consecutive_errors += 1
                print(f"  [오류] 페이지 {current_page} 저장 중 예외: {e}")

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"\n[경고] {MAX_CONSECUTIVE_ERRORS}회 연속 실패. 중단합니다.")
                print(f"  ↳ 재시작하려면: --start-page {current_page + 1}")
                break

            # 다음 페이지 이동
            try:
                has_next = await go_to_next_page(page, current_page)
                if not has_next:
                    print(f"\n마지막 페이지({current_page})에 도달했습니다.")
                    break
            except Exception as e:
                print(f"  [오류] 페이지 이동 중 예외: {e}")
                print(f"  ↳ 재시작하려면: --start-page {current_page + 1}")
                # 페이지 이동 실패 시 리로드 후 재시도
                try:
                    print("  페이지 리로드 후 재시도...")
                    await page.reload()
                    await wait_for_page_load(page)
                    await asyncio.sleep(2)
                    has_next = await go_to_next_page(page, current_page)
                    if not has_next:
                        print(f"\n마지막 페이지({current_page})에 도달했습니다.")
                        break
                except Exception as e2:
                    print(f"  [오류] 재시도도 실패: {e2}")
                    break

            current_page += 1
            # 서버 부하 방지 (1초 대기)
            await asyncio.sleep(1)

        print("\n" + "="*60)
        print(f"완료! 성공: {success_count}페이지 / 실패: {fail_count}페이지")
        print(f"저장 위치: {DOWNLOAD_DIR.absolute()}")
        if fail_count > 0:
            print(f"실패한 페이지가 있습니다. 다음 명령어로 재시작 가능:")
            print(f"  ./run.sh --start-page <실패한 페이지 번호>")
        print("="*60)

        input("\nEnter를 누르면 브라우저가 종료됩니다...")
        await browser.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="mail.sch.ac.kr 메일 자동 저장")
    parser.add_argument(
        "--start-page", type=int, default=1,
        help="시작 페이지 번호 (기본값: 1)"
    )
    parser.add_argument(
        "--max-pages", type=int, default=0,
        help="최대 처리 페이지 수 (0=전체, 기본값: 0)"
    )
    parser.add_argument(
        "--page-size", type=int, default=30,
        help="페이지당 메일 수 (기본값: 30)"
    )
    parser.add_argument(
        "--folder", type=str, default="전체메일",
        help="메일함 이름 (기본값: 전체메일)"
    )
    args = parser.parse_args()
    PAGE_SIZE = args.page_size

    asyncio.run(run(start_page=args.start_page, max_pages=args.max_pages, folder=args.folder))
