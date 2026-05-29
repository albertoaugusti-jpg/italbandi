"""
page_sport2.py — Pagina standalone ricerca bandi sportivi
Route: /sport2
"""
from fastapi import APIRouter, Query, Cookie
from fastapi.responses import HTMLResponse, JSONResponse
import sqlite3, db_sport2 as DB, scraper_sport2 as SC
import threading

router = APIRouter()

CSS = """
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#E8EEF7;color:#1A2A3A;min-height:100vh}
.header{background:linear-gradient(135deg,#1A2A4A,#243555);padding:28px 40px;border-bottom:3px solid #7C3AED}
.header h1{font-size:1.6rem;font-weight:900;color:#fff;margin-bottom:4px}
.header h1 span{color:#7C3AED}
.header p{font-size:0.88rem;color:#A8BEDD}
.header a{font-size:0.78rem;color:#6A8AA8;text-decoration:none;margin-top:8px;display:inline-block}
.header a:hover{color:#C9A84C}
.search-bar{background:#fff;border-bottom:1px solid #D8E2EE;padding:14px 40px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;box-shadow:0 2px 8px rgba(26,42,74,0.08)}
.search-bar input{flex:0 0 260px;padding:9px 14px;background:#F4F6FA;border:1px solid #C8D4E4;border-radius:6px;font-size:0.88rem;color:#1A2A3A;font-family:inherit;outline:none}
.search-bar select{padding:9px 14px;background:#F4F6FA;border:1px solid #C8D4E4;border-radius:6px;font-size:0.88rem;color:#1A2A3A;font-family:inherit}
.btn{padding:9px 24px;background:#7C3AED;color:#fff;border:none;border-radius:6px;font-size:0.9rem;font-weight:700;cursor:pointer}
.btn:hover{background:#6D28D9}
.container{max-width:1000px;margin:28px auto;padding:0 20px 60px}
.header-ris{font-size:0.8rem;color:#6A8AA8;margin-bottom:14px;font-weight:600}
.card{background:#fff;border:1px solid #D0DCF0;border-left:4px solid #D0DCF0;border-radius:8px;padding:16px 20px;margin-bottom:10px;transition:border-left-color 0.2s,box-shadow 0.2s;box-shadow:0 1px 4px rgba(26,42,74,0.06)}
.card:hover{border-left-color:#7C3AED;box-shadow:0 3px 12px rgba(26,42,74,0.12)}
.card-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.card-tag{font-size:10px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:#7C3AED}
.card-titolo{font-size:0.88rem;font-weight:700;color:#1A2A3A;line-height:1.45;margin-bottom:8px}
.card-info{display:flex;gap:18px;margin-bottom:8px;flex-wrap:wrap}
.card-info span{font-size:0.78rem;color:#6A8AA8}
.card-info strong{color:#2A4A6A}
.card-desc{font-size:0.78rem;color:#5A7A9A;line-height:1.5;margin-bottom:10px}
.badge{font-size:10px;font-weight:700;padding:3px 8px;border-radius:20px}
.badge-aperto{background:rgba(22,163,74,0.08);color:#15803D;border:1px solid rgba(22,163,74,0.25)}
.badge-prossimo{background:rgba(37,99,235,0.08);color:#1D4ED8;border:1px solid rgba(37,99,235,0.25)}
.btn-fonte{padding:6px 12px;background:none;color:#7C3AED;border:1px solid #D0DCF0;border-radius:5px;font-size:0.73rem;font-weight:700;cursor:pointer;text-decoration:none}
.btn-fonte:hover{border-color:#7C3AED}
.loader{text-align:center;padding:40px;color:#8899AA}
footer{background:#1A2A4A;padding:20px 40px;text-align:center;font-size:0.75rem;color:#7A9ABB;margin-top:40px}
</style>
"""

HTML = f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ItalBandi Sport — Bandi per ASD e SSD</title>{CSS}
</head><body>
<div class="header">
  <h1>🏋️ Bandi <span>Sport</span></h1>
  <p>Finanziamenti per ASD, SSD, impianti sportivi e promozione dell'attività fisica</p>
  <a href="/">← Torna alla ricerca principale</a>
</div>
<div class="search-bar">
  <input id="kw" type="text" placeholder="🔍 Parola chiave...">
  <select id="stato">
    <option value="aperto">✅ Aperti</option>
    <option value="prossima_apertura">🔜 In apertura</option>
    <option value="tutti">📋 Tutti</option>
  </select>
  <select id="livello">
    <option value="">🌐 Tutti i livelli</option>
    <option value="europeo">🇪🇺 Europeo</option>
    <option value="nazionale">🇮🇹 Nazionale</option>
    <option value="regionale">📍 Regionale</option>
  </select>
  <button class="btn" onclick="cerca()">Cerca</button>
</div>
<div class="container">
  <div id="hdr" class="header-ris"></div>
  <div id="ris"><div class="loader">⏳ Caricamento...</div></div>
</div>
<footer>ItalBandi Sport — un servizio di <strong>Energelia S.r.l.</strong> · 010 8078800</footer>
<script>
async function cerca() {{
  const p = new URLSearchParams({{
    keyword: document.getElementById('kw').value,
    stato:   document.getElementById('stato').value,
    livello: document.getElementById('livello').value,
  }});
  document.getElementById('ris').innerHTML = '<div class="loader">⏳ Ricerca...</div>';
  const r = await fetch('/api/sport2?' + p);
  const d = await r.json();
  document.getElementById('hdr').textContent = d.totale + ' bandi trovati';
  if (!d.bandi.length) {{
    document.getElementById('ris').innerHTML = '<p style="color:#8899AA;padding:20px">Nessun risultato. Prova a cambiare i filtri.</p>';
    return;
  }}
  document.getElementById('ris').innerHTML = d.bandi.map(b => {{
    const aperto = b.stato === 'aperto';
    const badge = aperto
      ? '<span class="badge badge-aperto">Aperto</span>'
      : '<span class="badge badge-prossimo">In apertura</span>';
    const fonte_btn = b.url
      ? `<a href="${{b.url}}" target="_blank" class="btn-fonte">Fonte →</a>`
      : '';
    return `<div class="card">
      <div class="card-top">
        <span class="card-tag">🏋️ Sport</span>
        <div style="display:flex;gap:6px;align-items:center">${{badge}}<span style="font-size:10px;color:#8899AA">${{b.livello}}</span></div>
      </div>
      <div class="card-titolo">${{b.titolo}}</div>
      ${{b.descrizione ? `<div class="card-desc">${{b.descrizione}}</div>` : ''}}
      <div class="card-info">
        <span>📅 <strong>${{b.scadenza}}</strong></span>
        <span>👥 <strong>${{b.beneficiari.substring(0,60)}}</strong></span>
        ${{b.fonte ? `<span>📌 ${{b.fonte}}</span>` : ''}}
      </div>
      ${{fonte_btn}}
    </div>`;
  }}).join('');
}}
window.onload = cerca;
</script>
</body></html>"""


@router.get("/sport2", response_class=HTMLResponse)
async def sport2_page(session_id: str = Cookie(default=None)):
    import main
    if not main.SESSIONS.get(session_id):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/login")
    return HTMLResponse(HTML)


@router.get("/api/sport2")
async def sport2_api(
    keyword: str = Query(""),
    stato:   str = Query("aperto"),
    livello: str = Query(""),
    session_id: str = Cookie(default=None),
):
    import main
    if not main.SESSIONS.get(session_id):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    bandi, totale = DB.cerca(keyword=keyword, stato=stato, livello=livello)
    return JSONResponse({"bandi": bandi, "totale": totale})


@router.post("/api/sport2/scrapa")
async def sport2_scrapa(session_id: str = Cookie(default=None)):
    import main
    user = main.SESSIONS.get(session_id)
    if not user or not user.get("is_admin"):
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    threading.Thread(target=SC.scrapa, daemon=True).start()
    return JSONResponse({"ok": True, "messaggio": "Scraper sport2 avviato"})
