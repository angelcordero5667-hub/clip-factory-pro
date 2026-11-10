import pytest
from playwright.sync_api import sync_playwright

def test_ui_effects_elements_and_mobile_layout():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Desktop
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto("http://127.0.0.1:8501", wait_until="networkidle")
        page.evaluate("switchView('create')")  # las opciones viven en la vista Create
        page.wait_for_selector("#progress-bar-check", state="visible")
        assert page.is_visible("#progress-bar-check")
        assert page.is_visible("#dynamic-zoom-check")
        assert page.is_visible("#split-glow-check")
        assert page.is_visible("#hook-headline-input")
        # el color grading ahora es un <select> dentro del Editor
        page.evaluate("switchView('editor')")
        assert page.query_selector("#editor-color-filter") is not None

        # Mobile
        mob_page = browser.new_page(viewport={"width": 375, "height": 812})
        mob_page.goto("http://127.0.0.1:8501", wait_until="networkidle")
        mob_page.evaluate("switchView('create')")
        mob_page.wait_for_selector("#progress-bar-check", state="visible")
        overflow = mob_page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
        assert not overflow, "Mobile has horizontal overflow"
        # el contenido de la vista no debe quedar recortado a la derecha
        right = mob_page.evaluate("() => document.querySelector('#view-create').getBoundingClientRect().right")
        assert right <= 376, f"Create se sale del ancho del móvil ({right}px)"
        browser.close()
