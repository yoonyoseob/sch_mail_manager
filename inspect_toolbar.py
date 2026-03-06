"""
메일 목록 화면의 툴바 버튼 구조를 분석하는 진단 스크립트
- 로그인 후 메일 목록 화면에서 전체선택 → 툴바 버튼 목록을 덤프
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

MAIL_URL = "https://mail.sch.ac.kr"
OUT_DIR = Path(__file__).parent / "inspect_out"


async def run():
    OUT_DIR.mkdir(exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(MAIL_URL)

        print("=" * 60)
        print("1) 브라우저에서 로그인 해주세요.")
        print("2) 받은메일함이 보이면 자동으로 분석을 시작합니다.")
        print("=" * 60)

        try:
            await page.wait_for_selector("text=전체메일", timeout=300000)
            print("\n로그인 감지!")
        except PlaywrightTimeout:
            print("[오류] 로그인 타임아웃")
            await browser.close()
            return

        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(3)

        # 전체선택 클릭 (선택 후 활성화되는 버튼 확인 용)
        try:
            select_btn = page.locator("text=전체선택").first
            if await select_btn.is_visible(timeout=3000):
                await select_btn.click()
                print("전체선택 클릭 완료")
                await asyncio.sleep(1)
        except Exception as e:
            print(f"전체선택 실패: {e}")

        # 스크린샷
        ss_path = OUT_DIR / "toolbar_screenshot.png"
        await page.screenshot(path=str(ss_path), full_page=False)
        print(f"스크린샷: {ss_path}")

        # 전체 HTML 저장
        html = await page.content()
        html_path = OUT_DIR / "maillist_page.html"
        html_path.write_text(html, encoding="utf-8")
        print(f"HTML 저장: {html_path}")

        # 모든 버튼, 링크, input 요소 목록
        print("\n" + "=" * 60)
        print("=== 페이지 내 클릭 가능한 요소 목록 ===")
        print("=" * 60)

        elements = await page.query_selector_all(
            "button, input[type=button], input[type=submit], a, [onclick]"
        )
        for i, el in enumerate(elements):
            try:
                tag = await el.evaluate("el => el.tagName")
                text = ""
                try:
                    text = (await el.inner_text()).strip()
                except Exception:
                    pass
                text = text.replace("\n", " ")[:50]
                value = await el.get_attribute("value") or ""
                href = await el.get_attribute("href") or ""
                onclick = await el.get_attribute("onclick") or ""
                cls = await el.get_attribute("class") or ""
                el_id = await el.get_attribute("id") or ""
                visible = await el.is_visible()

                # "삭제" 또는 "저장" 텍스트가 포함된 요소 강조
                highlight = ""
                if "삭제" in text or "삭제" in onclick or "delete" in onclick.lower():
                    highlight = " <<<< 삭제 관련"
                elif "저장" in text or "save" in onclick.lower() or "backup" in onclick.lower():
                    highlight = " <<<< 저장 관련"

                if text or onclick or el_id:  # 빈 요소 제외
                    vis_str = "V" if visible else "H"
                    print(
                        f"  [{vis_str}] [{tag}] "
                        f"id={el_id!r} class={cls[:40]!r} "
                        f"text={text!r} value={value!r} "
                        f"onclick={onclick[:60]!r}{highlight}"
                    )
            except Exception:
                continue

        # "삭제" 텍스트를 포함하는 모든 요소 상세 분석
        print("\n" + "=" * 60)
        print("=== '삭제' 텍스트 포함 요소 상세 분석 ===")
        print("=" * 60)

        delete_els = await page.query_selector_all("*")
        for el in delete_els:
            try:
                text = await el.evaluate("el => el.textContent")
                own_text = await el.evaluate(
                    "el => Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('')"
                )
                if "삭제" in own_text:
                    tag = await el.evaluate("el => el.tagName")
                    cls = await el.get_attribute("class") or ""
                    el_id = await el.get_attribute("id") or ""
                    onclick = await el.get_attribute("onclick") or ""
                    parent_tag = await el.evaluate("el => el.parentElement ? el.parentElement.tagName : 'none'")
                    parent_cls = await el.evaluate(
                        "el => el.parentElement ? (el.parentElement.className || '') : ''"
                    )
                    visible = await el.is_visible()
                    vis_str = "VISIBLE" if visible else "HIDDEN"
                    print(
                        f"  [{vis_str}] <{tag}> id={el_id!r} class={cls[:50]!r}\n"
                        f"    own_text={own_text!r}\n"
                        f"    onclick={onclick[:80]!r}\n"
                        f"    parent=<{parent_tag}> class={parent_cls[:50]!r}\n"
                    )
            except Exception:
                continue

        print(f"\n결과물이 {OUT_DIR} 에 저장되었습니다.")
        print("이 출력 내용을 공유해주세요!")

        input("\nEnter를 누르면 종료...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
