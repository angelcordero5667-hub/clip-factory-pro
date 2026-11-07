import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
OUTPUT_DIR = Path(r"C:\Users\Angel\.gemini\antigravity\scratch\clip-factory-pro\docs\captured_screenshots")

async def capture_all():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=BRAVE_PATH, headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})

        # 1. Dashboard
        await page.goto("http://127.0.0.1:8501", wait_until="networkidle")
        await page.wait_for_timeout(800)
        await page.screenshot(path=str(OUTPUT_DIR / "screen_01_dashboard.png"))
        print("Captured: screen_01_dashboard.png")

        # 2. Modal Crear clips
        await page.evaluate("openCrearModal()")
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(OUTPUT_DIR / "screen_02_crear_clips.png"))
        print("Captured: screen_02_crear_clips.png")

        # Close modal
        await page.evaluate("closeCrearModal()")
        await page.wait_for_timeout(300)

        # 3. Editor de video
        await page.evaluate("switchView('editor')")
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(OUTPUT_DIR / "screen_03_editor.png"))
        print("Captured: screen_03_editor.png")

        # 4. Motor FFmpeg
        await page.evaluate("switchView('ffmpeg')")
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(OUTPUT_DIR / "screen_04_ffmpeg.png"))
        print("Captured: screen_04_ffmpeg.png")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(capture_all())
