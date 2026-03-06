"""
팝업 창의 HTML 구조를 분석하는 진단 스크립트
- 로그인 후 저장 버튼을 직접 클릭하면 팝업 HTML과 스크린샷을 저장합니다
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
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        # 팝업 감지 핸들러 등록 (열리는 즉시 캡처)
        captured_popups = []

        async def on_page(popup):
            captured_popups.append(popup)
            print(f"\n[팝업 감지] URL: {popup.url}")

        context.on("page", on_page)

        await page.goto(MAIL_URL)

        print("="*60)
        print("1) 브라우저에서 로그인 해주세요.")
        print("2) 받은메일함에서 메일 1~2개 체크박스 선택 후")
        print("   저장 버튼을 직접 클릭해 주세요.")
        print("3) 팝업이 뜨면 아무것도 하지 말고 기다리세요.")
        print("="*60)

        # 팝업이 열릴 때까지 최대 3분 대기
        deadline = 180
        for _ in range(deadline):
            await asyncio.sleep(1)
            if captured_popups:
                break
        else:
            print("[오류] 팝업이 감지되지 않았습니다.")
            await browser.close()
            return

        popup = captured_popups[-1]
        await asyncio.sleep(2)  # 팝업 내용 완전 로드 대기

        # HTML 저장
        html = await popup.content()
        html_path = OUT_DIR / "popup.html"
        html_path.write_text(html, encoding="utf-8")
        print(f"\nHTML 저장: {html_path}")

        # 스크린샷 저장
        ss_path = OUT_DIR / "popup_screenshot.png"
        await popup.screenshot(path=str(ss_path))
        print(f"스크린샷 저장: {ss_path}")

        # 모든 버튼/링크 목록 출력
        print("\n--- 팝업 내 버튼/링크 목록 ---")
        elements = await popup.query_selector_all("button, input[type=button], input[type=submit], a")
        for el in elements:
            tag = await el.evaluate("el => el.tagName")
            text = (await el.inner_text()).strip() if tag != "INPUT" else ""
            value = await el.get_attribute("value") or ""
            href = await el.get_attribute("href") or ""
            onclick = await el.get_attribute("onclick") or ""
            cls = await el.get_attribute("class") or ""
            print(f"  [{tag}] text={text!r} value={value!r} href={href!r} onclick={onclick!r} class={cls!r}")

        print(f"\n팝업 URL: {popup.url}")
        print(f"\n결과물이 {OUT_DIR} 에 저장되었습니다.")
        print("이 파일들을 Claude에게 보여주세요!")

        input("\nEnter를 누르면 종료...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
