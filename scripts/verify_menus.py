import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
OUTPUT_DIR = Path(r"C:\Users\Angel\.gemini\antigravity\scratch\clip-factory-pro\docs\captured_screenshots\menus")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

async def test_menus():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=BRAVE_PATH, headless=True)
        
        # 1. Desktop Test (1440x900)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.goto("http://127.0.0.1:8501", wait_until="networkidle")
        await page.wait_for_timeout(600)
        
        # Test Avatar Dropdown
        avatar = page.locator("#header-user-avatar")
        await avatar.click()
        await page.wait_for_timeout(300)
        dropdown = page.locator("#user-dropdown-menu")
        is_dropdown_visible = await dropdown.is_visible()
        print(f"[Desktop] User dropdown visible: {is_dropdown_visible}")
        assert is_dropdown_visible, "User dropdown menu should be visible after clicking avatar"
        await page.screenshot(path=str(OUTPUT_DIR / "01_user_dropdown.png"))
        
        # Click Mis Proyectos in Dropdown
        await page.click("button:has-text('Mis Proyectos')")
        await page.wait_for_timeout(500)
        assert await page.locator("#view-proyectos").is_visible(), "#view-proyectos should be active"
        print("[Desktop] Successfully switched to #view-proyectos via dropdown")
        await page.screenshot(path=str(OUTPUT_DIR / "02_proyectos_view.png"))
        
        # Click Historial in Header Tab
        await page.click("#tab-nav-historial")
        await page.wait_for_timeout(500)
        assert await page.locator("#view-historial").is_visible(), "#view-historial should be active"
        print("[Desktop] Successfully switched to #view-historial via header tab")
        await page.screenshot(path=str(OUTPUT_DIR / "03_historial_view.png"))
        
        # Click Analytics in Header Tab
        await page.click("#tab-nav-analytics")
        await page.wait_for_timeout(500)
        assert await page.locator("#view-analytics").is_visible(), "#view-analytics should be active"
        print("[Desktop] Successfully switched to #view-analytics via header tab")
        await page.screenshot(path=str(OUTPUT_DIR / "04_analytics_view.png"))
        
        # Test Sidebar links
        await page.click("#nav-proyectos")
        await page.wait_for_timeout(300)
        assert await page.locator("#view-proyectos").is_visible(), "Sidebar nav-proyectos works"
        
        await page.click("#nav-editor")
        await page.wait_for_timeout(300)
        assert await page.locator("#view-editor").is_visible(), "Sidebar nav-editor works"
        
        await page.close()
        
        # 2. Mobile Test (390x844)
        m_page = await browser.new_page(viewport={"width": 390, "height": 844})
        await m_page.goto("http://127.0.0.1:8501", wait_until="networkidle")
        await m_page.wait_for_timeout(600)
        
        # Click Proyectos on bottom nav
        await m_page.click("#mob-nav-proyectos")
        await m_page.wait_for_timeout(400)
        assert await m_page.locator("#view-proyectos").is_visible(), "Mobile #mob-nav-proyectos switches to proyectos"
        print("[Mobile] Proyectos view visible via bottom nav")
        await m_page.screenshot(path=str(OUTPUT_DIR / "05_mobile_proyectos.png"))
        
        # Click "Más" on bottom nav
        await m_page.click("#mob-nav-mas")
        await m_page.wait_for_timeout(300)
        assert await m_page.locator("#mobile-more-overlay").is_visible(), "Mobile more overlay opens"
        await m_page.screenshot(path=str(OUTPUT_DIR / "06_mobile_more_sheet.png"))
        
        # Click Historial inside sheet
        await m_page.click(".mobile-more-sheet button:has-text('Historial de Trabajos')")
        await m_page.wait_for_timeout(400)
        assert await m_page.locator("#view-historial").is_visible(), "Mobile switches to historial from sheet"
        print("[Mobile] Historial view visible from more sheet")
        await m_page.screenshot(path=str(OUTPUT_DIR / "07_mobile_historial.png"))
        
        await m_page.close()
        await browser.close()
        
    print("ALL MENUS, TABS, DROPDOWNS AND REAL VIEWS VERIFIED 100% SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(test_menus())
