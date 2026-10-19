from __future__ import annotations
import sys
from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"

JS = r"""
() => {
  const out = [];
  const push = (s) => out.push(s);
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width>0 && r.height>0; };
  const cls = (el) => (el.className && typeof el.className === 'string')
      ? '.' + el.className.split(' ').filter(Boolean).slice(0,3).join('.') : '';
  const desc = (el) => el.tagName.toLowerCase() + cls(el);

  push('=== BOTONES ===');
  document.querySelectorAll('button').forEach((b,i) => {
    const r = b.getBoundingClientRect();
    push('['+i+'] aria='+JSON.stringify(b.getAttribute('aria-label'))
      +' title='+JSON.stringify(b.getAttribute('title'))
      +' testid='+JSON.stringify(b.getAttribute('data-testid'))
      +' dis='+b.disabled+' vis='+vis(b)+' y='+Math.round(r.y)
      +' txt='+JSON.stringify((b.textContent||'').slice(0,30))+' cls='+desc(b));
  });

  push('');
  push('=== CONTENTEDITABLE ===');
  document.querySelectorAll('[contenteditable="true"]').forEach((e,i) => {
    push('['+i+'] '+desc(e)+' vis='+vis(e));
    let p = e.parentElement, chain = [];
    for (let k=0; k<6 && p; k++) { chain.push(desc(p)); p = p.parentElement; }
    push('    padres: ' + chain.join(' < '));
    push('    html: ' + JSON.stringify(e.outerHTML.slice(0,300)));
  });

  push('');
  push('=== PRE / CODE ===');
  document.querySelectorAll('pre, code').forEach((e,i) => {
    push('['+i+'] '+desc(e)+' vis='+vis(e)+' len='+(e.textContent||'').length
      +' txt='+JSON.stringify((e.textContent||'').slice(0,100)));
  });

  push('');
  push('=== CONTENEDORES CON SCROLL ===');
  document.querySelectorAll('div,section,main').forEach((d) => {
    const st = getComputedStyle(d);
    if ((st.overflowY==='auto'||st.overflowY==='scroll') && d.children.length>1 && vis(d)) {
      push('SCROLL '+desc(d)+' hijos='+d.children.length+' h='+Math.round(d.getBoundingClientRect().height));
      [...d.children].slice(-4).forEach((c,i) => {
        push('   hijo['+i+'] '+desc(c)+' len='+(c.textContent||'').length
          +' txt='+JSON.stringify((c.textContent||'').slice(0,90)));
      });
    }
  });

  push('');
  push('=== ATRIBUTOS data-* y aria-* EN USO ===');
  const attrs = new Set();
  document.querySelectorAll('*').forEach(e => {
    for (const a of e.attributes) {
      if (a.name.startsWith('data-') || a.name.startsWith('aria-')) attrs.add(a.name);
    }
  });
  push([...attrs].sort().join(', '));

  push('');
  push('=== TEXTO GLOBAL ===');
  push('len body=' + document.body.innerText.length
     + ' contieneStop=' + /stop|detener/i.test(document.body.innerText));
  return out.join('\n');
}
"""

def main() -> int:
    with sync_playwright() as pw:
        try:
            nav = pw.chromium.connect_over_cdp(CDP)
        except Exception as e:
            print(f"[X] No conecto a {CDP}: {e}")
            return 1
        pgs = [p for p in nav.contexts[0].pages if "arena" in p.url.lower()]
        if not pgs:
            print("[X] No hay pestaña de arena abierta.")
            return 1
        salida = pgs[-1].evaluate(JS)
    with open("inspeccion.txt", "w", encoding="utf-8") as f:
        f.write(salida)
    print(salida[:2000])
    print("\n-> Escrito inspeccion.txt (" + str(len(salida)) + " chars)")
    return 0

if __name__ == "__main__":
    sys.exit(main())