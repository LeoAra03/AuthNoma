# \# Proyecto: PokeMod Studio — Fire Ash Edition

# 

# Editor tipo RPG Maker para Pokémon Fire Ash, en PWA. \*\*JS de navegador puro, sin build.\*\*

# 

# Estructura:

# \- `web/` PWA: `marshal.js` (Ruby Marshal), `rmxp.js`, `render.js`, `pbs.js`, `fs.js`,

# &#x20; `app.js`, `history.js`, `create.js`, `ui.js`, `editors.js`, `createUI.js`, `helpers.js`, `demo.js`

# \- `android/` APK WebView (Kotlin, minSdk 24)

# \- `tools/` CLI Python (solo stdlib) y adaptadores `.mjs`

# \- `docs/` documentación; `content/`, `xml/`, `assets\\\_r14/`, `reference/` datos y referencias

# 

# Reglas:

# \- Todo en español (identificadores, comentarios y textos de UI).

# \- Nada de dependencias nuevas salvo las que ya estén en `package.json`.

# \- \*\*No tocar partidas\*\*: `Save\\\*.rxdata` y `Game.rxdata` nunca se escriben ni se borran.

# \- Los formatos que consume el juego (`rxdata`, PBS) se preservan byte a byte salvo justificación.

# \- Cada cambio deja la suite en verde: `npm test`.

# \- Tests con `node:test`, en un archivo `<modulo>.test.mjs` junto al módulo.

# \- Empieza por `docs/PROMPT\\\_MAESTRO\\\_Y\\\_ESTADO.md` para el contexto del juego.

