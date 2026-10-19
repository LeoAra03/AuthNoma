from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
TXT = "LINEA UNO\nLINEA DOS\nLINEA TRES\nResponde solo: @@FASE_OK@@"

with sync_playwright() as pw:
    nav = pw.chromium.connect_over_cdp(CDP)
    pg = [p for p in nav.contexts[0].pages if "arena" in p.url.lower()][-1]
    comp = pg.locator("div[contenteditable='true']").last
    comp.click()
    pg.keyboard.press("Control+A")
    pg.keyboard.press("Backspace")
    pg.keyboard.insert_text(TXT)
    pg.wait_for_timeout(300)
    print("ANTES  -> inner_text:", repr(comp.inner_text()))
    print("ANTES  -> text_content:", repr(comp.text_content()))
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(2000)
    print("DESPUES-> inner_text:", repr(comp.inner_text()))
    print("")
    print("Si DESPUES esta vacio => Enter ENVIA. Perfecto.")
    print("Si DESPUES sigue con texto => Enter hace salto de linea, hay que buscar boton.")
    print("Si ANTES no tiene saltos de linea => insert_text los pierde, hay que usar otra via.")