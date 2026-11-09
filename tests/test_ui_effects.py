import pytest
from playwright.sync_api import sync_playwright

def test_ui_effects_elements_and_mobile_layout():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Desktop
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto("http://127.0.0.1:8501", wait_until="networkidle")
        page.wait_for_selector("#progress-bar-check")
        assert page.is_visible("#progress-bar-check")
        assert page.is_visible("#dynamic-zoom-check")
        assert page.is_visible("#split-glow-check")
        assert page.is_visible("#hook-headline-input")
        page.click(".color-filter-pill[data-colorfilter='pop']")
        page.click(".broll-theme-pill[data-brolltheme='minecraft']")

        # Mobile
        mob_page = browser.new_page(viewport={"width": 375, "height": 812})
        mob_page.goto("http://127.0.0.1:8501", wait_until="networkidle")
        mob_page.wait_for_selector("#progress-bar-check")
        overflow = mob_page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
        assert not overflow, "Mobile has horizontal overflow"
        browser.close()
