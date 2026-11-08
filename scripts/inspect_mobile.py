import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
OUTPUT_DIR = Path(r"C:\Users\Angel\.gemini\antigravity\scratch\clip-factory-pro\docs\captured_screenshots\mobile")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEVICES = [
    {"name": "android_small", "width": 360, "height": 640},
    {"name": "iphone_se", "width": 375, "height": 667},
    {"name": "iphone_14", "width": 390, "height": 844},
    {"name": "pixel_7", "width": 412, "height": 915},
]

async def capture_all_devices():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=BRAVE_PATH, headless=True)
        
        for dev in DEVICES:
            w, h, name = dev["width"], dev["height"], dev["name"]
            page = await browser.new_page(viewport={"width": w, "height": h})
            await page.goto("http://127.0.0.1:8501", wait_until="networkidle")
            await page.wait_for_timeout(500)
            
            # Check Inicio
            scroll_inicio = await page.evaluate("document.documentElement.scrollWidth")
            assert scroll_inicio <= w, f"[{name}] Inicio overflow: {scroll_inicio} > {w}"
            
            # Check Editor
            await page.evaluate("switchView('editor')")
            await page.wait_for_timeout(400)
            scroll_editor = await page.evaluate("document.documentElement.scrollWidth")
            assert scroll_editor <= w, f"[{name}] Editor overflow: {scroll_editor} > {w}"
            
            # Check FFmpeg
            await page.evaluate("switchView('ffmpeg')")
            await page.wait_for_timeout(400)
            scroll_ffmpeg = await page.evaluate("document.documentElement.scrollWidth")
            assert scroll_ffmpeg <= w, f"[{name}] FFmpeg overflow: {scroll_ffmpeg} > {w}"
            
            # Screenshots for iPhone 14
            if name == "iphone_14":
                await page.evaluate("switchView('inicio')")
                await page.wait_for_timeout(300)
                await page.screenshot(path=str(OUTPUT_DIR / "01_mobile_inicio.png"))
                
                await page.evaluate("openSettingsModal()")
                await page.wait_for_timeout(400)
                await page.screenshot(path=str(OUTPUT_DIR / "02_mobile_modal_settings.png"))
                await page.evaluate("closeInfoModal()")
                await page.wait_for_timeout(300)
                
                await page.evaluate("switchView('editor')")
                await page.wait_for_timeout(400)
                await page.screenshot(path=str(OUTPUT_DIR / "03_mobile_editor.png"))
                
                await page.evaluate("switchView('ffmpeg')")
                await page.wait_for_timeout(400)
                await page.screenshot(path=str(OUTPUT_DIR / "04_mobile_ffmpeg.png"))
                
            print(f"[{name} {w}x{h}] OK - Inicio: {scroll_inicio}px, Editor: {scroll_editor}px, FFmpeg: {scroll_ffmpeg}px")
            await page.close()
            
        await browser.close()
    print("ALL MOBILE DEVICES VERIFIED WITH ZERO OVERFLOW!")

if __name__ == "__main__":
    asyncio.run(capture_all_devices())
