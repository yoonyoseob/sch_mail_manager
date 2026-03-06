"""
mail.sch.ac.kr 메일 삭제 스크립트
- 백업 완료 후, 받은메일함의 모든 페이지를 순회하며 전체선택 → 삭제
- 삭제 전 확인 프롬프트 제공
"""

import asyncio
import re
import urllib.parse
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

MAIL_URL = "https://mail.sch.ac.kr"
PAGE_SIZE = 30


async def wait_for_page_load(page):
    """메일 목록 테이블이 로드될 때까지 대기"""
    await page.wait_for_load_state("networkidle", timeout=15000)


async def get_total_mail_count(page) -> int:
    """전체 메일 수 파싱"""
    try:
        text = await page.inner_text("body")
        match = re.search(r"전체메일\s+(\d+)\s*통", text)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 0


async def get_current_cpage(page) -> int | None:
    """현재 URL 해시에서 cpage 값을 추출"""
    url = page.url
    if "#" not in url:
        return None
    hash_decoded = urllib.parse.unquote(url.split("#", 1)[1])
    m = re.search(r"cpage=(\d+)", hash_decoded)
    return int(m.group(1)) if m else None


async def select_all_and_delete(page, page_num: int) -> bool:
    """현재 페이지: 전체선택 → 삭제 클릭 → 확인 다이얼로그 수락"""
    print(f"\n[페이지 {page_num}] 전체선택 중...")

    try:
        row_count = 0
        try:
            row_count = await page.locator("table tbody tr").count()
        except Exception:
            pass
        print(f"  현재 테이블 행 수: {row_count}")

        if row_count == 0:
            print("  [정보] 메일이 없습니다. 건너뜁니다.")
            return True

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
            return False

        await asyncio.sleep(0.5)

        # 툴바의 "완전삭제" 버튼 클릭
        deleted = False
        delete_selectors = [
            "a:has-text('완전삭제')",
            "button:has-text('완전삭제')",
            "[onclick*='completeDel']",
            "[onclick*='completeRemove']",
            "[onclick*='permanentDel']",
        ]
        for sel in delete_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    btn_text = (await btn.inner_text()).strip()[:30]
                    print(f"  완전삭제 버튼 클릭: {btn_text!r}")
                    await btn.click()
                    deleted = True
                    break
            except Exception:
                continue

        if not deleted:
            print("  [경고] 삭제 버튼을 찾지 못했습니다.")
            return False

        # HTML 확인 모달이 나타날 때까지 대기 후 "확인" 버튼 클릭
        confirmed = False
        try:
            # 모달이 나타날 때까지 대기 (모달 내 "확인" 버튼)
            confirm_btn = page.locator("button:has-text('확인')").last
            await confirm_btn.wait_for(state="visible", timeout=5000)
            await asyncio.sleep(0.3)
            await confirm_btn.click()
            confirmed = True
            print(f"  확인 모달 버튼 클릭 완료")
        except Exception:
            pass

        if not confirmed:
            # 다른 형태의 확인 버튼 시도
            fallback_selectors = [
                "a:has-text('확인')",
                "input[value='확인']",
                "button.ok",
                ".btn_ok",
            ]
            for sel in fallback_selectors:
                try:
                    btn = page.locator(sel).last
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        confirmed = True
                        print(f"  확인 버튼 클릭 (fallback: {sel})")
                        break
                except Exception:
                    continue

        if not confirmed:
            print("  [경고] 확인 모달을 찾지 못했습니다.")

        # 삭제 처리 대기
        await asyncio.sleep(2)
        await wait_for_page_load(page)

        print(f"  삭제 완료 (페이지 {page_num}, {row_count}통)")
        return True

    except Exception as e:
        print(f"  [오류] {e}")
        return False


async def go_to_next_page(page, page_num: int) -> bool:
    """다음 페이지로 이동. 마지막 페이지면 False 반환."""
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

    await page.evaluate(f"() => {{ location.hash = '{new_hash}'; }}")
    await wait_for_page_load(page)
    await asyncio.sleep(1.5)

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

    try:
        row_count = await page.locator("table tbody tr").count()
        if row_count == 0:
            print(f"  [정보] 페이지 {next_page}: 메일 행 없음 → 마지막 페이지")
            return False
    except Exception:
        pass

    print(f"  페이지 {next_page} 이동 완료 (cpage={actual_cpage})")
    return True


async def run(start_page: int = 1, end_page: int = 0, folder: str = "전체메일",
              auto_confirm: bool = False):
    """메인 실행 함수

    삭제 후 메일이 앞으로 당겨지므로 항상 start_page에서 반복 삭제합니다.
    end_page: 종료 페이지 (0=메일 소진까지). 예: start=4, end=122 → 119회 반복.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        print(f"\n{MAIL_URL} 로 이동합니다...")
        await page.goto(MAIL_URL)

        # 로그인 대기
        print("\n" + "=" * 60)
        print("브라우저에서 로그인 해주세요.")
        print("로그인 완료 후 자동으로 시작됩니다.")
        print("=" * 60)

        try:
            await page.wait_for_selector("text=전체메일", timeout=300000)
            print("\n로그인 감지!")
        except PlaywrightTimeout:
            print("[오류] 5분 내에 로그인되지 않아 종료합니다.")
            await browser.close()
            return

        await wait_for_page_load(page)
        await asyncio.sleep(1)

        # 네이티브 confirm/alert 다이얼로그 자동 수락 (fallback)
        page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))

        # 사이드바에서 원하는 메일함 클릭
        print(f"  '{folder}' 메일함으로 이동 중...")
        sidebar_link = page.locator(f"text={folder}").first
        try:
            await sidebar_link.click()
            print(f"  '{folder}' 클릭 완료")
        except Exception as e:
            print(f"  [경고] 사이드바 '{folder}' 클릭 실패: {e}")

        await wait_for_page_load(page)
        await asyncio.sleep(2)

        # 전체 메일 수 확인
        total = await get_total_mail_count(page)
        try:
            actual_rows = await page.locator("table tbody tr").count()
            detected_page_size = actual_rows if actual_rows > 0 else PAGE_SIZE
        except Exception:
            detected_page_size = PAGE_SIZE

        if total > 0:
            total_pages = (total + detected_page_size - 1) // detected_page_size
            print(f"\n전체 메일: {total}통 / 예상 페이지: {total_pages}페이지")
        else:
            print("\n전체 메일 수를 파악할 수 없습니다.")
            total_pages = 9999

        # 사용자 확인
        if end_page > 0:
            range_str = f"{start_page}~{end_page}페이지 ({end_page - start_page + 1}회 반복)"
        else:
            range_str = f"{start_page}페이지부터 메일 소진까지"
        print("\n" + "=" * 60)
        print(f"  대상: '{folder}' 메일함")
        print(f"  메일 수: {total}통")
        print(f"  삭제 범위: {range_str}")
        print("=" * 60)
        if not auto_confirm:
            confirm = input("\n정말 삭제하시겠습니까? (yes/no): ").strip().lower()
            if confirm != "yes":
                print("취소되었습니다.")
                await browser.close()
                return
        else:
            print("\n[자동 확인] 삭제를 시작합니다...")

        # 시작 페이지로 이동 (1이 아닌 경우)
        if start_page > 1:
            print(f"\n{start_page}페이지로 직접 이동 중...")
            current_url = page.url
            raw_hash = current_url.split("#")[1] if "#" in current_url else ""
            hash_decoded = urllib.parse.unquote(raw_hash) if raw_hash else ""

            if "cpage=" in hash_decoded:
                jump_hash = re.sub(r"cpage=\d+", f"cpage={start_page}", hash_decoded)
            else:
                jump_hash = hash_decoded.rstrip("&") + f"&cpage={start_page}&"

            temp_hash = re.sub(r"cpage=\d+", "cpage=0", hash_decoded) if "cpage=" in hash_decoded else hash_decoded
            await page.evaluate(f"() => {{ location.hash = '{temp_hash}'; }}")
            await asyncio.sleep(0.5)
            await page.evaluate(f"() => {{ location.hash = '{jump_hash}'; }}")
            await wait_for_page_load(page)
            await asyncio.sleep(3)

        # 반복 횟수 계산: end_page가 지정되면 (end - start + 1)회, 아니면 무제한
        if end_page > 0:
            repeat_count = end_page - start_page + 1
            print(f"\n[삭제] {start_page}~{end_page}페이지 분량 삭제 ({repeat_count}회 반복)")
        else:
            repeat_count = 0
            print(f"\n[삭제] {start_page}페이지부터 메일 소진까지 삭제")

        success_count = 0
        fail_count = 0
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 3

        while True:
            # 반복 횟수 제한 확인
            if repeat_count > 0 and success_count >= repeat_count:
                print(f"\n{start_page}~{end_page}페이지 분량 삭제 완료 ({success_count}회)")
                break

            # 현재 페이지의 메일 행 수 확인
            try:
                row_count = await page.locator("table tbody tr").count()
                if row_count == 0:
                    print("\n모든 메일이 삭제되었습니다.")
                    break
            except Exception:
                pass

            ok = await select_all_and_delete(page, success_count + fail_count + 1)
            if ok:
                success_count += 1
                consecutive_errors = 0
            else:
                fail_count += 1
                consecutive_errors += 1

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"\n[경고] {MAX_CONSECUTIVE_ERRORS}회 연속 실패. 중단합니다.")
                break

            # 삭제 후 페이지 새로고침하여 남은 메일 확인
            await page.reload()
            await wait_for_page_load(page)
            await asyncio.sleep(2)

            # 서버 부하 방지
            await asyncio.sleep(1)

        print("\n" + "=" * 60)
        print(f"완료! 성공: {success_count}회 / 실패: {fail_count}회")
        print("=" * 60)

        input("\nEnter를 누르면 브라우저가 종료됩니다...")
        await browser.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="mail.sch.ac.kr 메일 삭제")
    parser.add_argument(
        "--start-page", type=int, default=1,
        help="시작 페이지 번호 (기본값: 1)"
    )
    parser.add_argument(
        "--end-page", type=int, default=0,
        help="종료 페이지 번호 (0=메일 소진까지, 기본값: 0)"
    )
    parser.add_argument(
        "--page-size", type=int, default=30,
        help="페이지당 메일 수 (기본값: 30)"
    )
    parser.add_argument(
        "--folder", type=str, default="전체메일",
        help="메일함 이름 (기본값: 전체메일)"
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="확인 프롬프트 없이 바로 삭제 시작"
    )
    args = parser.parse_args()
    PAGE_SIZE = args.page_size

    asyncio.run(run(
        start_page=args.start_page,
        end_page=args.end_page,
        folder=args.folder,
        auto_confirm=args.yes,
    ))
