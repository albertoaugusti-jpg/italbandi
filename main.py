"""
ItalBandi — main.py
Portale web con autenticazione, registrazione, privacy, cookie policy
Proprietà: Energelia S.r.l. — Responsabile privacy: Bruno Massimo Legger
"""
import os, tempfile, traceback, sqlite3, hashlib, secrets, json, re, threading
from datetime import datetime, timedelta
from fastapi import FastAPI, Query, Request, Form, Cookie
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse, Response
import uvicorn

import bandi_engine as be
import energelia_scheda_engine as ENGINE

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_italbandi.png")

app = FastAPI(title="ItalBandi")

# ── Database Neon (cache bandi) ───────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

def _run_async(coro):
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    except RuntimeError:
        import asyncio
        return asyncio.run(coro)

def init_cache_db():
    if not DATABASE_URL: return
    async def _f():
        import asyncpg
        con = await asyncpg.connect(DATABASE_URL)
        await con.execute("""CREATE TABLE IF NOT EXISTS bandi_cache (
            object_id    TEXT PRIMARY KEY,
            titolo       TEXT,
            testo_pagina TEXT,
            permalink    TEXT,
            aggiornato   TIMESTAMP DEFAULT NOW()
        )""")
        await con.close()
        print("[DB] init OK", flush=True)
    try:
        _run_async(_f())
    except Exception as e:
        print(f"[DB] init error: {e}", flush=True)

init_cache_db()

def salva_in_cache(object_id, titolo, testo, permalink):
    if not DATABASE_URL: return
    async def _f():
        import asyncpg
        con = await asyncpg.connect(DATABASE_URL)
        await con.execute("""INSERT INTO bandi_cache (object_id,titolo,testo_pagina,permalink,aggiornato)
            VALUES ($1,$2,$3,$4,NOW())
            ON CONFLICT (object_id) DO UPDATE
            SET testo_pagina=$3,titolo=$2,permalink=$4,aggiornato=NOW()""",
            object_id, titolo, testo, permalink)
        await con.close()
    try:
        _run_async(_f())
    except Exception as e:
        print(f"[DB] save error: {e}", flush=True)

def leggi_da_cache(object_id):
    if not DATABASE_URL: return None
    async def _f():
        import asyncpg
        con = await asyncpg.connect(DATABASE_URL)
        row = await con.fetchrow("SELECT testo_pagina FROM bandi_cache WHERE object_id=$1", object_id)
        await con.close()
        return row["testo_pagina"] if row else None
    try:
        return _run_async(_f())
    except:
        return None

def conta_cache():
    if not DATABASE_URL: return 0
    async def _f():
        import asyncpg
        con = await asyncpg.connect(DATABASE_URL)
        n = await con.fetchval("SELECT COUNT(*) FROM bandi_cache")
        await con.close()
        return n or 0
    try:
        return _run_async(_f())
    except:
        return 0

@app.get("/logo")
async def serve_logo():
    for nome in ["Logo Bellissimo ItalBandi.png", "logo_italbandi.png", "logo.png"]:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), nome)
        if os.path.exists(path):
            return FileResponse(path, media_type="image/png")
    return Response(status_code=404)

DB_PATH  = "/tmp/italbandi.db"
SESSIONS = {}  # session_id → {user_id, username, is_admin}

# ── Database ───────────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS utenti (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL, cognome TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL, telefono TEXT,
        ruolo TEXT, impresa TEXT,
        password_hash TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    # Admin fisso
    pw_hash = hashlib.sha256("Samp1946,".encode()).hexdigest()
    con.execute("INSERT OR IGNORE INTO utenti (nome,cognome,email,password_hash,is_admin) VALUES (?,?,?,?,?)",
                ("Admin","ItalBandi","admin@italbandi.it", pw_hash, 1))
    con.commit(); con.close()

init_db()

def get_user(email, password):
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT id,nome,cognome,email,is_admin FROM utenti WHERE email=? AND password_hash=?",
                      (email, pw_hash)).fetchone()
    con.close()
    return row

def register_user(nome, cognome, email, password, telefono="", ruolo="", impresa=""):
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute("INSERT INTO utenti (nome,cognome,email,password_hash,telefono,ruolo,impresa) VALUES (?,?,?,?,?,?,?)",
                    (nome, cognome, email, pw_hash, telefono, ruolo, impresa))
        con.commit(); con.close()
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Email già registrata."

def create_session(user_row):
    sid = secrets.token_hex(32)
    SESSIONS[sid] = {"id": user_row[0], "nome": user_row[1],
                     "cognome": user_row[2], "email": user_row[3],
                     "is_admin": bool(user_row[4])}
    return sid

def get_session(session_id: str = None):
    if not session_id: return None
    return SESSIONS.get(session_id)

# ── STILI COMUNI ───────────────────────────────────────────────────────────────
CSS_BASE = """
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; background: #0D1B2A; color: #E8E8E8; min-height: 100vh; }
a { color: #C9A84C; text-decoration: none; }
a:hover { text-decoration: underline; }

.navbar {
  background: #0A1628;
  border-bottom: 2px solid #C9A84C;
  padding: 0 40px;
  display: flex; align-items: center; justify-content: space-between;
  height: 64px;
}
.navbar-brand {
  font-size: 1.5rem; font-weight: 800; color: #C9A84C;
  letter-spacing: 2px; text-transform: uppercase;
}
.navbar-brand span { color: #FFFFFF; }
.navbar-links { display: flex; gap: 24px; align-items: center; font-size: 0.88rem; }
.navbar-links a { color: #B0B8C8; font-weight: 500; }
.navbar-links a:hover { color: #C9A84C; text-decoration: none; }
.btn-logout {
  background: transparent; border: 1px solid #C9A84C;
  color: #C9A84C; padding: 6px 16px; border-radius: 4px;
  font-size: 0.82rem; cursor: pointer; font-family: inherit;
}
.btn-logout:hover { background: #C9A84C; color: #0A1628; }

.hero {
  background: linear-gradient(135deg, #0A1628 0%, #1A2F4E 100%);
  border-bottom: 1px solid #1E3A5F;
  padding: 28px 40px;
}
.hero h2 { font-size: 1.05rem; color: #C9A84C; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px; }
.hero p  { font-size: 0.88rem; color: #8899AA; }

.search-bar {
  background: #0F2035;
  border-bottom: 1px solid #1E3A5F;
  padding: 18px 40px;
  display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end;
}
.search-bar input, .search-bar select {
  padding: 9px 14px;
  background: #162840; border: 1px solid #2A4A6B; border-radius: 5px;
  font-size: 0.9rem; color: #E8E8E8;
}
.search-bar input { flex: 1; min-width: 200px; }
.search-bar select { min-width: 150px; }
.search-bar input::placeholder { color: #5A7A9A; }
.btn-cerca {
  padding: 9px 28px;
  background: #C9A84C; color: #0A1628;
  border: none; border-radius: 5px;
  font-weight: 700; font-size: 0.92rem; cursor: pointer;
  white-space: nowrap;
}
.btn-cerca:hover { background: #E0BF6A; }

.container { max-width: 1000px; margin: 32px auto; padding: 0 20px 60px; }

.risultati-header { font-size: 0.82rem; color: #6A8AA8; margin-bottom: 16px; font-weight: 600; letter-spacing: 0.5px; }

.bando-card {
  background: #0F2035;
  border: 1px solid #1E3A5F;
  border-left: 4px solid #C9A84C;
  border-radius: 8px; padding: 20px 24px;
  margin-bottom: 12px;
  transition: border-color 0.2s;
}
.bando-card:hover { border-color: #C9A84C; box-shadow: 0 0 20px rgba(201,168,76,0.1); }
.card-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.card-titolo { font-size: 0.95rem; font-weight: 700; color: #D4E8FF; flex: 1; line-height: 1.4; }
.badge { font-size: 0.68rem; font-weight: 700; padding: 3px 10px; border-radius: 20px; white-space: nowrap; }
.badge-aperto   { background: #0D3321; color: #4ADE80; border: 1px solid #4ADE80; }
.badge-prossimo { background: #0D1F40; color: #60A5FA; border: 1px solid #60A5FA; }
.card-meta { display: flex; gap: 24px; margin-top: 10px; flex-wrap: wrap; }
.meta-item label { display: block; font-size: 0.65rem; font-weight: 700; color: #5A7A9A; text-transform: uppercase; letter-spacing: 0.05em; }
.meta-item span  { font-size: 0.82rem; color: #A8C8E8; font-weight: 500; }
.btn-scheda {
  margin-top: 14px; padding: 8px 20px;
  background: #C9A84C; color: #0A1628;
  border: none; border-radius: 5px;
  font-size: 0.85rem; font-weight: 700; cursor: pointer;
}
.btn-scheda:hover { background: #E0BF6A; }
.btn-scheda:disabled { background: #3A4A5A; color: #6A8AA8; cursor: not-allowed; }
.spinner { display: none; margin-left: 10px; font-size: 0.8rem; color: #6A8AA8; }
.loader  { text-align: center; padding: 40px; color: #5A7A9A; }

/* Auth forms */
.auth-wrap {
  min-height: calc(100vh - 64px);
  display: flex; align-items: center; justify-content: center;
  padding: 40px 20px;
}
.auth-card {
  background: #0F2035; border: 1px solid #1E3A5F; border-radius: 12px;
  padding: 40px; width: 100%; max-width: 460px;
}
.auth-card h2 { font-size: 1.3rem; color: #C9A84C; margin-bottom: 6px; font-weight: 700; }
.auth-card p.sub { font-size: 0.85rem; color: #6A8AA8; margin-bottom: 28px; }
.form-group { margin-bottom: 18px; }
.form-group label { display: block; font-size: 0.78rem; font-weight: 600; color: #7A9ABB; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 6px; }
.form-group input, .form-group select {
  width: 100%; padding: 10px 14px;
  background: #162840; border: 1px solid #2A4A6B; border-radius: 6px;
  font-size: 0.92rem; color: #E8E8E8; font-family: inherit;
}
.form-group input:focus { outline: none; border-color: #C9A84C; }
.btn-primary {
  width: 100%; padding: 12px;
  background: #C9A84C; color: #0A1628;
  border: none; border-radius: 6px;
  font-size: 1rem; font-weight: 700; cursor: pointer;
  margin-top: 8px; font-family: inherit;
}
.btn-primary:hover { background: #E0BF6A; }
.err-msg { color: #F87171; font-size: 0.84rem; margin-bottom: 16px; padding: 10px; background: #2D1515; border-radius: 6px; }
.ok-msg  { color: #4ADE80; font-size: 0.84rem; margin-bottom: 16px; padding: 10px; background: #0D3321; border-radius: 6px; }
.auth-footer { text-align: center; margin-top: 20px; font-size: 0.84rem; color: #5A7A9A; }
.privacy-note { font-size: 0.75rem; color: #4A6A8A; margin-top: 14px; text-align: center; line-height: 1.5; }

/* Cookie banner */
#cookie-banner {
  position: fixed; bottom: 0; left: 0; right: 0;
  background: #0A1628; border-top: 1px solid #C9A84C;
  padding: 16px 40px; display: flex; align-items: center;
  justify-content: space-between; gap: 20px; z-index: 9999;
  flex-wrap: wrap;
}
#cookie-banner p { font-size: 0.82rem; color: #8899AA; flex: 1; }
.btn-cookie { padding: 7px 18px; border-radius: 4px; border: none; font-weight: 600; font-size: 0.82rem; cursor: pointer; font-family: inherit; }
.btn-cookie-ok  { background: #C9A84C; color: #0A1628; }
.btn-cookie-no  { background: transparent; border: 1px solid #4A6A8A; color: #8899AA; }

footer.site-footer {
  background: #0A1628; border-top: 1px solid #1E3A5F;
  padding: 24px 40px; margin-top: 40px;
  text-align: center; font-size: 0.75rem; color: #4A6A8A; line-height: 1.8;
}
footer.site-footer a { color: #6A8AA8; }

/* Pagine statiche */
.page-wrap { max-width: 800px; margin: 40px auto; padding: 0 20px 60px; }
.page-wrap h1 { color: #C9A84C; font-size: 1.5rem; margin-bottom: 20px; }
.page-wrap h2 { color: #D4E8FF; font-size: 1.05rem; margin: 28px 0 10px; }
.page-wrap p  { color: #8899AA; font-size: 0.88rem; line-height: 1.7; margin-bottom: 12px; }
.page-wrap ul { color: #8899AA; font-size: 0.88rem; line-height: 1.7; padding-left: 20px; margin-bottom: 12px; }
</style>
"""

NAVBAR_LOGGED = lambda user: f"""
<nav class="navbar">
  <a href="/" style="display:flex;align-items:center;gap:12px;text-decoration:none">
    <img src="/logo" alt="ItalBandi" style="height:44px;width:44px;object-fit:cover;border-radius:4px">
    <span class="navbar-brand">ITAL<span>BANDI</span></span>
  </a>
  <div class="navbar-links">
    <span style="color:#6A8AA8;font-size:0.82rem">Ciao, {user['nome']}</span>
    <a href="/privacy">Privacy</a>
    <a href="/cookie">Cookie Policy</a>
    <form method="POST" action="/logout" style="margin:0">
      <button class="btn-logout" type="submit">Esci</button>
    </form>
  </div>
</nav>"""

FOOTER_HTML = """
<footer class="site-footer">
  <strong style="color:#C9A84C">ItalBandi</strong> — un servizio di
  <strong style="color:#D4E8FF">Energelia S.r.l.</strong><br>
  Largo XII Ottobre 1/3, Torre WTC · 16121 Genova · P.IVA 01806600991<br>
  Tel. <a href="tel:+390108078800">010 8078800</a> ·
  <a href="mailto:a.augusti@energelia.it">a.augusti@energelia.it</a> ·
  <a href="mailto:b.legger@energelia.it">b.legger@energelia.it</a> ·
  <a href="mailto:a.castagnaro@energelia.it">a.castagnaro@energelia.it</a><br>
  <a href="/privacy">Privacy Policy</a> · <a href="/cookie">Cookie Policy</a> ·
  Responsabile Privacy: Bruno Massimo Legger
</footer>
<div id="cookie-banner" style="display:none">
  <p>Utilizziamo cookie tecnici necessari al funzionamento del sito e, previo consenso,
  cookie analitici per migliorare il servizio. Vedi la <a href="/cookie">Cookie Policy</a>.</p>
  <button class="btn-cookie btn-cookie-ok" onclick="accettaCookie()">Accetta tutti</button>
  <button class="btn-cookie btn-cookie-no" onclick="rifiutaCookie()">Solo necessari</button>
</div>
<script>
if (!localStorage.getItem('cookie_consent')) {
  document.getElementById('cookie-banner').style.display = 'flex';
}
function accettaCookie() {
  localStorage.setItem('cookie_consent','all');
  document.getElementById('cookie-banner').style.display = 'none';
}
function rifiutaCookie() {
  localStorage.setItem('cookie_consent','minimal');
  document.getElementById('cookie-banner').style.display = 'none';
}
</script>"""

# ── PAGINA LOGIN ───────────────────────────────────────────────────────────────
def login_page(error=""):
    err = f'<div class="err-msg">{error}</div>' if error else ""
    return f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ItalBandi — Accedi</title>{CSS_BASE}</head><body>
<nav class="navbar">
  <a href="/" style="display:flex;align-items:center;gap:12px;text-decoration:none">
    <img src="/logo" alt="ItalBandi" style="height:44px;width:44px;object-fit:cover;border-radius:4px">
    <span class="navbar-brand">ITAL<span>BANDI</span></span>
  </a>
  <div class="navbar-links">
    <a href="/registrati">Registrati</a>
  </div>
</nav>
<div class="auth-wrap">
  <div class="auth-card">
    <h2>Accedi a ItalBandi</h2>
    <p class="sub">Inserisci le tue credenziali per continuare</p>
    {err}
    <form method="POST" action="/login">
      <div class="form-group"><label>Email *</label><input type="email" name="email" required placeholder="tuaemail@esempio.it"></div>
      <div class="form-group"><label>Password *</label><input type="password" name="password" required placeholder="••••••••"></div>
      <button class="btn-primary" type="submit">Accedi</button>
    </form>
    <div class="auth-footer">Non hai un account? <a href="/registrati">Registrati gratis</a></div>
    <p class="privacy-note">Accedendo accetti la nostra <a href="/privacy">Privacy Policy</a>
    e la <a href="/cookie">Cookie Policy</a>.</p>
  </div>
</div>
{FOOTER_HTML}
</body></html>"""

# ── PAGINA REGISTRAZIONE ───────────────────────────────────────────────────────
def registrati_page(error="", ok=""):
    err = f'<div class="err-msg">{error}</div>' if error else ""
    okm = f'<div class="ok-msg">{ok}</div>' if ok else ""
    return f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ItalBandi — Registrati</title>{CSS_BASE}</head><body>
<nav class="navbar">
  <a href="/" style="display:flex;align-items:center;gap:12px;text-decoration:none">
    <img src="/logo" alt="ItalBandi" style="height:44px;width:44px;object-fit:cover;border-radius:4px">
    <span class="navbar-brand">ITAL<span>BANDI</span></span>
  </a>
  <div class="navbar-links"><a href="/login">Accedi</a></div>
</nav>
<div class="auth-wrap">
  <div class="auth-card" style="max-width:520px">
    <h2>Crea il tuo account</h2>
    <p class="sub">Accedi gratuitamente a tutti i bandi e genera schede PDF professionali</p>
    {err}{okm}
    <form method="POST" action="/registrati">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div class="form-group"><label>Nome *</label><input type="text" name="nome" required placeholder="Mario"></div>
        <div class="form-group"><label>Cognome *</label><input type="text" name="cognome" required placeholder="Rossi"></div>
      </div>
      <div class="form-group"><label>Email *</label><input type="email" name="email" required placeholder="mario.rossi@azienda.it"></div>
      <div class="form-group"><label>Password *</label><input type="password" name="password" required placeholder="Min. 8 caratteri"></div>
      <div class="form-group"><label>Telefono</label><input type="tel" name="telefono" placeholder="+39 010 000000"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div class="form-group">
          <label>Ruolo</label>
          <select name="ruolo">
            <option value="">-- Seleziona --</option>
            <option>Imprenditore / Titolare</option>
            <option>Consulente</option>
            <option>Responsabile finanziario</option>
            <option>Commercialista / CAF</option>
            <option>Ente pubblico</option>
            <option>Altro</option>
          </select>
        </div>
        <div class="form-group"><label>Azienda</label><input type="text" name="impresa" placeholder="Nome azienda"></div>
      </div>
      <div style="margin-bottom:16px">
        <label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer">
          <input type="checkbox" name="privacy" required style="width:auto;margin-top:3px">
          <span style="font-size:0.78rem;color:#6A8AA8">
            Ho letto e accetto la <a href="/privacy" target="_blank">Privacy Policy</a>
            e la <a href="/cookie" target="_blank">Cookie Policy</a> di ItalBandi / Energelia S.r.l. *
          </span>
        </label>
      </div>
      <button class="btn-primary" type="submit">Crea account</button>
    </form>
    <div class="auth-footer">Hai già un account? <a href="/login">Accedi</a></div>
  </div>
</div>
{FOOTER_HTML}
</body></html>"""

# ── PAGINA PRINCIPALE (ricerca bandi) ─────────────────────────────────────────
def index_page(user):
    return f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ItalBandi — Bandi e Incentivi per le Imprese</title>{CSS_BASE}</head><body>
{NAVBAR_LOGGED(user)}
<div class="hero">
  <h2>Ricerca Bandi</h2>
  <p>Trova le opportunità di finanziamento per la tua impresa. Filtra per livello geografico e scarica la scheda PDF professionale.</p>
</div>
<div class="search-bar">
  <input id="keyword" type="text" placeholder="Parola chiave (es. formazione, energia, PMI...)">
  <select id="stato">
    <option value="aperto">Bandi aperti</option>
    <option value="prossimo">Prossima apertura</option>
    <option value="tutti">Tutti</option>
  </select>
  <select id="livello" onchange="aggiornaFiltri()">
    <option value="">Tutti i bandi</option>
    <option value="europeo">Europeo</option>
    <option value="nazionale">Nazionale</option>
    <option value="regionale">Regionale</option>
  </select>
  <span id="regione-wrap" style="display:none">
    <select id="regione" onchange="aggiornaProvince()">
      <option value="">-- Scegli regione --</option>
      <option>Abruzzo</option><option>Basilicata</option><option>Calabria</option>
      <option>Campania</option><option>Emilia-Romagna</option><option>Friuli-Venezia-Giulia</option>
      <option>Lazio</option><option>Liguria</option><option>Lombardia</option>
      <option>Marche</option><option>Molise</option><option>Piemonte</option>
      <option>Puglia</option><option>Sardegna</option><option>Sicilia</option>
      <option>Toscana</option><option>Trentino-Alto-Adige</option><option>Umbria</option>
      <option>Valle d'Aosta</option><option>Veneto</option>
    </select>
  </span>
  <span id="provincia-wrap" style="display:none">
    <select id="provincia"><option value="">(tutte le province)</option></select>
  </span>
  <button class="btn-cerca" onclick="cerca()">🔍 Cerca</button>
</div>
<div class="container">
  <div id="risultati-header" class="risultati-header"></div>
  <div id="risultati"></div>
</div>
{FOOTER_HTML}
<script>
const PROVINCE = {{
  "Liguria":    ["Provincia di Genova","Provincia di Imperia","Provincia di La-Spezia","Provincia di Savona"],
  "Lombardia":  ["Provincia di Bergamo","Provincia di Brescia","Provincia di Como","Provincia di Cremona","Provincia di Lecco","Provincia di Lodi","Provincia di Mantova","Provincia di Milano","Provincia di Monza-Brianza","Provincia di Pavia","Provincia di Sondrio","Provincia di Varese"],
  "Piemonte":   ["Provincia di Alessandria","Provincia di Asti","Provincia di Biella","Provincia di Cuneo","Provincia di Novara","Provincia di Torino","Provincia di Verbano-Cusio-Ossola","Provincia di Vercelli"],
  "Veneto":     ["Provincia di Belluno","Provincia di Padova","Provincia di Rovigo","Provincia di Treviso","Provincia di Venezia","Provincia di Verona","Provincia di Vicenza"],
  "Toscana":    ["Provincia di Arezzo","Provincia di Firenze","Provincia di Grosseto","Provincia di Livorno","Provincia di Lucca","Provincia di Massa-Carrara","Provincia di Pisa","Provincia di Pistoia","Provincia di Prato","Provincia di Siena"],
  "Lazio":      ["Provincia di Frosinone","Provincia di Latina","Provincia di Rieti","Provincia di Roma","Provincia di Viterbo"],
  "Campania":   ["Provincia di Avellino","Provincia di Benevento","Provincia di Caserta","Provincia di Napoli","Provincia di Salerno"],
  "Emilia-Romagna": ["Provincia di Bologna","Provincia di Ferrara","Provincia di Forli-Cesena","Provincia di Modena","Provincia di Parma","Provincia di Piacenza","Provincia di Ravenna","Provincia di Reggio-Emilia","Provincia di Rimini"],
  "Puglia":     ["Provincia di Bari","Provincia di Barletta-Andria-Trani","Provincia di Brindisi","Provincia di Foggia","Provincia di Lecce","Provincia di Taranto"],
  "Sicilia":    ["Provincia di Agrigento","Provincia di Caltanissetta","Provincia di Catania","Provincia di Enna","Provincia di Messina","Provincia di Palermo","Provincia di Ragusa","Provincia di Siracusa","Provincia di Trapani"],
  "Sardegna":   ["Provincia di Cagliari","Provincia di Nuoro","Provincia di Oristano","Provincia di Sassari"],
  "Abruzzo":    ["Provincia di Chieti","Provincia di L'Aquila","Provincia di Pescara","Provincia di Teramo"],
  "Marche":     ["Provincia di Ancona","Provincia di Ascoli Piceno","Provincia di Fermo","Provincia di Macerata","Provincia di Pesaro Urbino"],
  "Friuli-Venezia-Giulia": ["Provincia di Gorizia","Provincia di Pordenone","Provincia di Trieste","Provincia di Udine"],
  "Calabria":   ["Provincia di Catanzaro","Provincia di Cosenza","Provincia di Crotone","Provincia di Reggio-Calabria","Provincia di Vibo-Valentia"],
  "Umbria":     ["Provincia di Perugia","Provincia di Terni"],
  "Basilicata": ["Provincia di Matera","Provincia di Potenza"],
  "Molise":     ["Provincia di Campobasso","Provincia di Isernia"],
  "Trentino-Alto-Adige": ["Provincia di Bolzano","Provincia di Trento"],
  "Valle d'Aosta": ["Provincia di Aosta"],
}};
let _hits = {{}};
function aggiornaFiltri() {{
  const livello = document.getElementById('livello').value;
  document.getElementById('regione-wrap').style.display   = livello === 'regionale' ? 'inline' : 'none';
  document.getElementById('provincia-wrap').style.display = 'none';
  if (livello !== 'regionale') {{ document.getElementById('regione').value = ''; }}
}}
function aggiornaProvince() {{
  const regione = document.getElementById('regione').value;
  const wrap = document.getElementById('provincia-wrap');
  const sel  = document.getElementById('provincia');
  if (regione && PROVINCE[regione]) {{
    sel.innerHTML = '<option value="">(tutte le province)</option>' +
      PROVINCE[regione].map(p => `<option value="${{p}}">${{p}}</option>`).join('');
    wrap.style.display = 'inline';
  }} else {{ wrap.style.display = 'none'; }}
}}
async function cerca() {{
  const params = new URLSearchParams({{
    keyword:  document.getElementById('keyword').value,
    stato:    document.getElementById('stato').value,
    livello:  document.getElementById('livello').value,
    regione:  document.getElementById('regione').value,
    provincia:document.getElementById('provincia').value,
  }});
  document.getElementById('risultati').innerHTML = '<div class="loader">⏳ Ricerca in corso...</div>';
  document.getElementById('risultati-header').textContent = '';
  const resp = await fetch('/api/cerca?' + params);
  const data = await resp.json();
  if (data.error) {{ document.getElementById('risultati').innerHTML = `<p style="color:#F87171">${{data.error}}</p>`; return; }}
  document.getElementById('risultati-header').textContent = `${{data.totale}} bandi trovati`;
  _hits = {{}};
  data.bandi.forEach(b => {{ _hits[b.id] = b._hit; }});
  document.getElementById('risultati').innerHTML = data.bandi.map(b => `
    <div class="bando-card">
      <div class="card-top">
        <div class="card-titolo" onclick="togglePreview('${{b.id}}')" style="cursor:pointer" title="Clicca per dettagli">${{b.titolo}}</div>
        <span class="badge ${{b.stato.includes('prossima') ? 'badge-prossimo' : 'badge-aperto'}}">${{b.stato}}</span>
      </div>
      <div class="card-meta">
        <div class="meta-item"><label>Livello</label><span>${{b.livello}}</span></div>
        <div class="meta-item"><label>Dotazione</label><span>${{b.dotazione}}</span></div>
        <div class="meta-item"><label>Scadenza</label><span>${{b.scadenza}}</span></div>
        <div class="meta-item"><label>Destinatari</label><span>${{(b.beneficiari||'').substring(0,60)}}</span></div>
      </div>
      <div id="preview-${{b.id}}" style="display:none;margin-top:14px;padding:14px;background:#0A1628;border-radius:6px;border:1px solid #1E3A5F">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:0.82rem;color:#A8C8E8">
          <div><span style="color:#C9A84C;font-weight:700">Stato:</span> ${{b.stato}}</div>
          <div><span style="color:#C9A84C;font-weight:700">Livello:</span> ${{b.livello}}</div>
          <div><span style="color:#C9A84C;font-weight:700">Dotazione:</span> ${{b.dotazione}}</div>
          <div><span style="color:#C9A84C;font-weight:700">Scadenza:</span> ${{b.scadenza}}</div>
          <div style="grid-column:1/-1"><span style="color:#C9A84C;font-weight:700">Destinatari:</span> ${{b.beneficiari || '—'}}</div>
        </div>
        <p style="font-size:0.78rem;color:#5A7A9A;margin-top:10px">👆 Clicca "Genera Scheda PDF" per la scheda completa con tutti i dettagli del bando.</p>
      </div>
      <div style="display:flex;align-items:center;gap:12px;margin-top:12px">
        <button class="btn-scheda" id="btn-${{b.id}}" onclick="generaScheda('${{b.id}}')">📄 Genera Scheda PDF</button>
        <span class="spinner" id="sp-${{b.id}}">⏳ Generazione in corso (30-60 sec)...</span>
      </div>
    </div>`).join('');
}}
function togglePreview(id) {{
  const el = document.getElementById('preview-' + id);
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}}
async function generaScheda(id) {{
  const btn = document.getElementById('btn-' + id);
  const sp  = document.getElementById('sp-'  + id);
  btn.disabled = true;
  sp.style.display = 'inline';
  sp.textContent = '⏳ Avvio elaborazione...';

  try {{
    // 1. Avvia job
    const r1 = await fetch('/api/scheda/' + encodeURIComponent(id), {{
      method: 'POST', headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{hit: _hits[id]}})
    }});
    const j1 = await r1.json();
    if (!j1.job_id) {{ alert('Errore avvio: ' + JSON.stringify(j1)); return; }}
    const jobId = j1.job_id;

    // 2. Polling ogni 5 secondi
    let secondi = 0;
    const poll = setInterval(async () => {{
      secondi += 5;
      sp.textContent = '⏳ Generazione in corso... (' + secondi + 's)';
      try {{
        const r2  = await fetch('/api/job/' + jobId);
        const j2  = await r2.json();
        if (j2.status === 'ready') {{
          clearInterval(poll);
          sp.textContent = '✅ Pronto! Download in corso...';
          // 3. Scarica
          const r3   = await fetch('/api/download/' + jobId);
          const blob = await r3.blob();
          const url  = URL.createObjectURL(blob);
          const a    = document.createElement('a');
          a.href     = url;
          a.download = j2.nome || ('Energelia_' + id + '.pdf');
          document.body.appendChild(a); a.click(); a.remove();
          URL.revokeObjectURL(url);
          sp.style.display = 'none';
          btn.disabled = false;
        }} else if (j2.status === 'error') {{
          clearInterval(poll);
          alert('Errore generazione scheda. Riprova.');
          sp.style.display = 'none';
          btn.disabled = false;
        }} else if (secondi > 180) {{
          clearInterval(poll);
          alert('Timeout — la generazione sta impiegando troppo. Riprova tra un momento.');
          sp.style.display = 'none';
          btn.disabled = false;
        }}
      }} catch(e) {{ clearInterval(poll); alert('Errore polling: ' + e.message); btn.disabled=false; sp.style.display='none'; }}
    }}, 5000);

  }} catch(e) {{
    alert('Errore: ' + e.message);
    btn.disabled = false;
    sp.style.display = 'none';
  }}
}}
window.onload = cerca;
</script>
</body></html>"""

# ── PRIVACY POLICY ─────────────────────────────────────────────────────────────
PRIVACY_HTML = f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><title>Privacy Policy — ItalBandi</title>{CSS_BASE}</head><body>
<nav class="navbar">
  <span class="navbar-brand">ITAL<span>BANDI</span></span>
  <div class="navbar-links"><a href="/">Home</a></div>
</nav>
<div class="page-wrap">
  <h1>Privacy Policy</h1>
  <p>Ultimo aggiornamento: {datetime.now().strftime("%d/%m/%Y")}</p>
  <h2>1. Titolare del trattamento</h2>
  <p><strong>Energelia S.r.l.</strong><br>
  Largo XII Ottobre 1/3, Torre WTC — 16121 Genova<br>
  P.IVA: 01806600991<br>
  Tel: 010 8078800<br>
  Email: <a href="mailto:b.legger@energelia.it">b.legger@energelia.it</a><br>
  <strong>Responsabile Privacy: Bruno Massimo Legger</strong></p>
  <h2>2. Dati raccolti</h2>
  <p>ItalBandi raccoglie i seguenti dati personali al momento della registrazione:</p>
  <ul><li>Nome e cognome</li><li>Indirizzo email</li><li>Numero di telefono (facoltativo)</li>
  <li>Ruolo professionale (facoltativo)</li><li>Nome azienda (facoltativo)</li></ul>
  <h2>3. Finalità del trattamento</h2>
  <p>I dati sono trattati per: fornire accesso al servizio ItalBandi; inviare comunicazioni su bandi e opportunità di finanziamento pertinenti; rispondere a richieste di consulenza; adempiere a obblighi di legge.</p>
  <h2>4. Base giuridica</h2>
  <p>Il trattamento è basato sul consenso esplicito dell'interessato (art. 6, par. 1, lett. a GDPR) e sull'esecuzione di un contratto (art. 6, par. 1, lett. b GDPR).</p>
  <h2>5. Conservazione dei dati</h2>
  <p>I dati sono conservati per il tempo necessario all'erogazione del servizio e comunque non oltre 5 anni dall'ultimo accesso, salvo obblighi di legge.</p>
  <h2>6. Diritti dell'interessato</h2>
  <p>L'interessato ha diritto di accesso, rettifica, cancellazione, portabilità e opposizione al trattamento. Per esercitare tali diritti: <a href="mailto:b.legger@energelia.it">b.legger@energelia.it</a></p>
  <h2>7. Comunicazione a terzi</h2>
  <p>I dati non vengono ceduti a terzi. Possono essere condivisi con fornitori tecnici (hosting Render.com, USA) nel rispetto delle garanzie GDPR.</p>
</div>
{FOOTER_HTML}</body></html>"""

COOKIE_HTML = f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><title>Cookie Policy — ItalBandi</title>{CSS_BASE}</head><body>
<nav class="navbar">
  <span class="navbar-brand">ITAL<span>BANDI</span></span>
  <div class="navbar-links"><a href="/">Home</a></div>
</nav>
<div class="page-wrap">
  <h1>Cookie Policy</h1>
  <p>ItalBandi (Energelia S.r.l.) utilizza i seguenti cookie:</p>
  <h2>Cookie tecnici (necessari)</h2>
  <ul><li><strong>session_id</strong> — cookie di sessione per mantenere il login. Durata: sessione browser.</li>
  <li><strong>cookie_consent</strong> — memorizza la tua scelta sui cookie. Durata: 12 mesi.</li></ul>
  <h2>Cookie analitici (con consenso)</h2>
  <p>Previo consenso, potremmo utilizzare Google Analytics per analisi aggregate degli accessi. Nessun dato personale viene condiviso.</p>
  <h2>Gestione dei cookie</h2>
  <p>Puoi rifiutare i cookie non essenziali cliccando "Solo necessari" nel banner. Puoi sempre modificare la scelta svuotando la cache del browser.</p>
  <h2>Contatti</h2>
  <p>Per informazioni: <a href="mailto:b.legger@energelia.it">b.legger@energelia.it</a> — Energelia S.r.l., Largo XII Ottobre 1/3, Torre WTC, 16121 Genova.</p>
</div>
{FOOTER_HTML}</body></html>"""

# ── ROUTES ─────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user:
        return HTMLResponse(LANDING_HTML())
    return index_page(user)

@app.get("/login", response_class=HTMLResponse)
async def login_get(session_id: str = Cookie(default=None)):
    if get_session(session_id):
        return RedirectResponse("/")
    return login_page()

@app.post("/login")
async def login_post(email: str = Form(""), password: str = Form("")):
    # Admin speciale
    if email.lower() == "admin" and password == "Samp1946,":
        user_row = (0, "Admin", "ItalBandi", "admin@italbandi.it", 1)
    else:
        user_row = get_user(email, password)
    if not user_row:
        return HTMLResponse(login_page("Email o password non corretti."))
    sid = create_session(user_row)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie("session_id", sid, max_age=86400*7, httponly=True)
    return resp

@app.post("/logout")
async def logout(session_id: str = Cookie(default=None)):
    if session_id and session_id in SESSIONS:
        del SESSIONS[session_id]
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("session_id")
    return resp

@app.get("/registrati", response_class=HTMLResponse)
async def registrati_get():
    return registrati_page()

@app.post("/registrati")
async def registrati_post(
    nome: str = Form(""), cognome: str = Form(""),
    email: str = Form(""), password: str = Form(""),
    telefono: str = Form(""), ruolo: str = Form(""),
    impresa: str = Form(""), privacy: str = Form(None)
):
    if not nome or not cognome or not email or not password:
        return HTMLResponse(registrati_page(error="Compila tutti i campi obbligatori."))
    if len(password) < 8:
        return HTMLResponse(registrati_page(error="La password deve essere di almeno 8 caratteri."))
    ok, err = register_user(nome, cognome, email, password, telefono, ruolo, impresa)
    if not ok:
        return HTMLResponse(registrati_page(error=err))
    return HTMLResponse(registrati_page(ok=f"Account creato! <a href='/login'>Accedi ora</a>"))

@app.get("/privacy", response_class=HTMLResponse)
async def privacy():
    return PRIVACY_HTML

@app.get("/cookie", response_class=HTMLResponse)
async def cookie_policy():
    return COOKIE_HTML

@app.get("/chi-siamo", response_class=HTMLResponse)
async def chi_siamo(session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    nav = NAVBAR_LOGGED(user) if user else f"""
<nav class="navbar">
  <a href="/" style="display:flex;align-items:center;gap:12px;text-decoration:none">
    <img src="/logo" alt="ItalBandi" style="height:44px;width:44px;object-fit:cover;border-radius:4px">
    <span class="navbar-brand">ITAL<span>BANDI</span></span>
  </a>
  <div class="navbar-links">
    <a href="/chi-siamo">Chi siamo</a>
    <a href="/login">Accedi</a>
    <a href="/registrati" style="background:#C9A84C;color:#0A1628;padding:7px 18px;border-radius:5px;font-weight:700">Registrati gratis</a>
  </div>
</nav>"""
    return f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chi Siamo — ItalBandi | Energelia S.r.l.</title>{CSS_BASE}</head><body>
{nav}
<div style="background:linear-gradient(135deg,#0A1628 0%,#1A2F4E 100%);padding:48px 40px;text-align:center;border-bottom:1px solid #1E3A5F">
  <h1 style="font-size:2rem;color:#C9A84C;font-weight:800;letter-spacing:1px;margin-bottom:12px">
    Dal 2006 al fianco delle imprese italiane
  </h1>
  <p style="color:#8899AA;font-size:1.05rem;max-width:600px;margin:0 auto;line-height:1.7">
    Energelia accompagna le aziende nell'accesso ai bandi pubblici, alla finanza agevolata
    e agli incentivi nazionali ed europei. ItalBandi è il nostro strumento digitale aperto a tutti.
  </p>
</div>

<div class="page-wrap">

  <h2 style="color:#C9A84C;border-left:4px solid #C9A84C;padding-left:12px;margin-bottom:20px">La nostra missione</h2>
  <p>Aiutiamo le aziende a non perdere le opportunità di crescita che lo Stato e l'Europa mettono a disposizione.
  Lo facciamo con un metodo strutturato, fonti verificate, e seguendo il cliente in ogni fase:
  dalla ricerca del bando giusto, alla presentazione della domanda, fino alla rendicontazione dei finanziamenti ottenuti.</p>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:32px 0">
    <div style="background:#0F2035;border:1px solid #1E3A5F;border-left:3px solid #C9A84C;border-radius:8px;padding:20px">
      <div style="font-size:1.4rem;margin-bottom:8px">🔍</div>
      <strong style="color:#D4E8FF">Ricerca mirata</strong>
      <p style="margin-top:6px">Selezioniamo solo i bandi davvero applicabili alla tua azienda, evitando di farti perdere tempo su opportunità non compatibili.</p>
    </div>
    <div style="background:#0F2035;border:1px solid #1E3A5F;border-left:3px solid #C9A84C;border-radius:8px;padding:20px">
      <div style="font-size:1.4rem;margin-bottom:8px">📋</div>
      <strong style="color:#D4E8FF">Gestione pratica</strong>
      <p style="margin-top:6px">Compiliamo, presentiamo e seguiamo per te la domanda. Niente moduli incomprensibili, niente scadenze perse.</p>
    </div>
    <div style="background:#0F2035;border:1px solid #1E3A5F;border-left:3px solid #C9A84C;border-radius:8px;padding:20px">
      <div style="font-size:1.4rem;margin-bottom:8px">🤝</div>
      <strong style="color:#D4E8FF">Consulenza dedicata</strong>
      <p style="margin-top:6px">Un referente per ogni cliente, sempre raggiungibile per chiarimenti, aggiornamenti e nuove opportunità.</p>
    </div>
    <div style="background:#0F2035;border:1px solid #1E3A5F;border-left:3px solid #C9A84C;border-radius:8px;padding:20px">
      <div style="font-size:1.4rem;margin-bottom:8px">✅</div>
      <strong style="color:#D4E8FF">Rendicontazione</strong>
      <p style="margin-top:6px">Ti seguiamo anche dopo l'approvazione: rendicontiamo le spese secondo le regole del bando, in tempo, senza errori.</p>
    </div>
  </div>

  <h2 style="color:#C9A84C;border-left:4px solid #C9A84C;padding-left:12px;margin:32px 0 20px">Il nostro team</h2>

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-bottom:40px">
    <div style="background:#0F2035;border:1px solid #1E3A5F;border-radius:8px;padding:24px;text-align:center">
      <div style="width:64px;height:64px;background:#1A3A5A;border-radius:50%;margin:0 auto 12px;display:flex;align-items:center;justify-content:center;font-size:1.6rem">👔</div>
      <strong style="color:#C9A84C;display:block;margin-bottom:4px">Bruno Massimo Legger</strong>
      <span style="font-size:0.78rem;color:#5A7A9A;text-transform:uppercase;letter-spacing:0.05em">Amministratore Unico</span>
      <p style="margin-top:10px;font-size:0.82rem">Laurea in Scienze Politiche. Carriera internazionale tra cosmetica (Estée Lauder, Shiseido) e settore energetico. Dal 2014 guida Energelia.</p>
    </div>
    <div style="background:#0F2035;border:1px solid #1E3A5F;border-radius:8px;padding:24px;text-align:center">
      <div style="width:64px;height:64px;background:#1A3A5A;border-radius:50%;margin:0 auto 12px;display:flex;align-items:center;justify-content:center;font-size:1.6rem">🚀</div>
      <strong style="color:#C9A84C;display:block;margin-bottom:4px">Alberto Augusti</strong>
      <span style="font-size:0.78rem;color:#5A7A9A;text-transform:uppercase;letter-spacing:0.05em">Responsabile Business Development</span>
      <p style="margin-top:10px;font-size:0.82rem">Laurea in Scienze Internazionali, Master Sole 24 Ore. Fondatore di Generelia, esperto certificato Bureau Veritas. Giovane Imprenditore Ligure 2011.</p>
    </div>
    <div style="background:#0F2035;border:1px solid #1E3A5F;border-radius:8px;padding:24px;text-align:center">
      <div style="width:64px;height:64px;background:#1A3A5A;border-radius:50%;margin:0 auto 12px;display:flex;align-items:center;justify-content:center;font-size:1.6rem">📞</div>
      <strong style="color:#C9A84C;display:block;margin-bottom:4px">Antonio Castagnaro</strong>
      <span style="font-size:0.78rem;color:#5A7A9A;text-transform:uppercase;letter-spacing:0.05em">Responsabile Commerciale</span>
      <p style="margin-top:10px;font-size:0.82rem">Diplomato classico, fondatore di AC Eventi Genova. Oggi dedica tutta la sua attività allo sviluppo commerciale di Energelia.</p>
    </div>
  </div>

  <div style="background:#0F2035;border:1px solid #C9A84C;border-radius:10px;padding:32px;text-align:center">
    <h2 style="color:#C9A84C;font-size:1.3rem;margin-bottom:12px">Vuoi sapere se la tua azienda può accedere a un bando?</h2>
    <p style="color:#8899AA;margin-bottom:24px">Registrati gratis su ItalBandi, cerca tra i bandi disponibili e scarica la scheda PDF professionale.<br>I nostri consulenti sono a disposizione per una valutazione gratuita.</p>
    <div style="display:flex;justify-content:center;gap:16px;flex-wrap:wrap">
      <a href="/registrati" style="background:#C9A84C;color:#0A1628;padding:12px 32px;border-radius:6px;font-weight:700;font-size:1rem">Registrati gratis</a>
      <a href="tel:+390108078800" style="background:transparent;color:#C9A84C;border:1px solid #C9A84C;padding:12px 32px;border-radius:6px;font-weight:700;font-size:1rem">📞 010 8078800</a>
    </div>
  </div>

</div>
{FOOTER_HTML}
</body></html>"""


LANDING_HTML = lambda: f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ItalBandi — Trova i bandi giusti per la tua impresa</title>{CSS_BASE}
<style>
.hero-landing {{
  min-height: calc(100vh - 64px);
  background: linear-gradient(160deg, #0A1628 0%, #0F2035 50%, #0A1628 100%);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; padding: 60px 20px;
  position: relative; overflow: hidden;
}}
.hero-landing::before {{
  content: '';
  position: absolute; inset: 0;
  background: radial-gradient(ellipse at 50% 40%, rgba(201,168,76,0.08) 0%, transparent 60%);
}}
.hero-logo {{ width: 120px; height: 120px; object-fit: cover; border-radius: 12px; margin-bottom: 32px; box-shadow: 0 0 40px rgba(201,168,76,0.3); }}
.hero-title {{ font-size: 3rem; font-weight: 900; color: #FFFFFF; letter-spacing: -1px; line-height: 1.1; margin-bottom: 16px; }}
.hero-title span {{ color: #C9A84C; }}
.hero-sub {{ font-size: 1.15rem; color: #8899AA; max-width: 560px; line-height: 1.7; margin-bottom: 40px; }}
.hero-cta {{ display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; }}
.btn-cta-primary {{ padding: 16px 40px; background: #C9A84C; color: #0A1628; border: none; border-radius: 8px; font-size: 1.05rem; font-weight: 800; cursor: pointer; text-decoration: none; letter-spacing: 0.5px; }}
.btn-cta-primary:hover {{ background: #E0BF6A; text-decoration: none; }}
.btn-cta-secondary {{ padding: 16px 40px; background: transparent; color: #C9A84C; border: 2px solid #C9A84C; border-radius: 8px; font-size: 1.05rem; font-weight: 700; text-decoration: none; }}
.btn-cta-secondary:hover {{ background: rgba(201,168,76,0.1); text-decoration: none; }}
.features {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 24px; max-width: 900px; margin: 60px auto 0; padding: 0 20px; }}
.feature {{ background: #0F2035; border: 1px solid #1E3A5F; border-top: 3px solid #C9A84C; border-radius: 8px; padding: 28px 24px; text-align: left; }}
.feature-icon {{ font-size: 2rem; margin-bottom: 12px; }}
.feature h3 {{ color: #D4E8FF; font-size: 1rem; margin-bottom: 8px; }}
.feature p {{ color: #6A8AA8; font-size: 0.85rem; line-height: 1.6; }}
.section-how {{ background: #0A1628; padding: 80px 20px; border-top: 1px solid #1E3A5F; }}
.section-how h2 {{ text-align: center; color: #C9A84C; font-size: 1.8rem; margin-bottom: 48px; }}
.steps {{ display: flex; gap: 0; max-width: 800px; margin: 0 auto; position: relative; }}
.step {{ flex: 1; text-align: center; padding: 0 20px; }}
.step-num {{ width: 44px; height: 44px; background: #C9A84C; color: #0A1628; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 1.1rem; margin: 0 auto 16px; }}
.step h4 {{ color: #D4E8FF; font-size: 0.95rem; margin-bottom: 8px; }}
.step p  {{ color: #6A8AA8; font-size: 0.82rem; line-height: 1.6; }}
.section-cta {{ background: linear-gradient(135deg,#0F2035,#1A3A5E); padding: 80px 20px; text-align: center; border-top: 1px solid #1E3A5F; }}
.section-cta h2 {{ color: #FFFFFF; font-size: 1.8rem; margin-bottom: 16px; }}
.section-cta p {{ color: #8899AA; font-size: 1rem; margin-bottom: 32px; }}
</style>
</head><body>
<nav class="navbar">
  <a href="/" style="display:flex;align-items:center;gap:12px;text-decoration:none">
    <img src="/logo" alt="ItalBandi" style="height:44px;width:44px;object-fit:cover;border-radius:4px">
    <span class="navbar-brand">ITAL<span>BANDI</span></span>
  </a>
  <div class="navbar-links">
    <a href="/chi-siamo">Chi siamo</a>
    <a href="/login">Accedi</a>
    <a href="/registrati" style="background:#C9A84C;color:#0A1628;padding:7px 18px;border-radius:5px;font-weight:700">Registrati gratis</a>
  </div>
</nav>

<div class="hero-landing">
  <img src="/logo" class="hero-logo" alt="ItalBandi">
  <h1 class="hero-title">Trova il bando.<br><span>Trova il consulente.</span></h1>
  <p class="hero-sub">ItalBandi raccoglie tutti i bandi italiani ed europei in un unico posto.
  Registrati gratis, cerca le opportunità per la tua impresa e scarica la scheda PDF professionale.
  I nostri consulenti sono pronti ad aiutarti.</p>
  <div class="hero-cta">
    <a href="/registrati" class="btn-cta-primary">Registrati gratis →</a>
    <a href="/chi-siamo" class="btn-cta-secondary">Chi siamo</a>
  </div>
</div>

<div class="features">
  <div class="feature">
    <div class="feature-icon">🗂️</div>
    <h3>Tutti i bandi in un posto</h3>
    <p>Bandi europei, nazionali e regionali sempre aggiornati. Filtri per regione, settore e stato del bando.</p>
  </div>
  <div class="feature">
    <div class="feature-icon">📄</div>
    <h3>Schede PDF professionali</h3>
    <p>Per ogni bando generiamo una scheda sintetica professionale pronta da condividere con il tuo commercialista o cliente.</p>
  </div>
  <div class="feature">
    <div class="feature-icon">🤝</div>
    <h3>Consulenti qualificati</h3>
    <p>Dietro ItalBandi c'è Energelia S.r.l., dal 2006 specializzata in finanza agevolata. Siamo a tua disposizione.</p>
  </div>
</div>

<div class="section-how">
  <h2>Come funziona</h2>
  <div class="steps">
    <div class="step">
      <div class="step-num">1</div>
      <h4>Registrati</h4>
      <p>Crea il tuo account gratuito in 30 secondi. Solo nome, email e password.</p>
    </div>
    <div class="step">
      <div class="step-num">2</div>
      <h4>Cerca</h4>
      <p>Filtra per regione, livello e parola chiave. Trova i bandi pertinenti alla tua impresa.</p>
    </div>
    <div class="step">
      <div class="step-num">3</div>
      <h4>Scarica la scheda</h4>
      <p>Genera e scarica la scheda PDF professionale del bando che ti interessa.</p>
    </div>
    <div class="step">
      <div class="step-num">4</div>
      <h4>Contattaci</h4>
      <p>I nostri consulenti valutano gratuitamente la tua candidatura al bando.</p>
    </div>
  </div>
</div>

<div class="section-cta">
  <h2>È completamente gratuito</h2>
  <p>Registrarsi, cercare bandi e scaricare schede PDF non costa nulla.<br>
  Il nostro guadagno è aiutarti concretamente a ottenere finanziamenti.</p>
  <a href="/registrati" class="btn-cta-primary">Inizia adesso →</a>
  <p style="margin-top:24px;font-size:0.85rem;color:#4A6A8A">
    Hai già un account? <a href="/login">Accedi qui</a>
  </p>
</div>

{FOOTER_HTML}
</body></html>"""


@app.get("/api/cerca")
async def cerca(
    request: Request,
    keyword: str = Query(""), stato: str = Query("aperto"),
    livello: str = Query(""), regione: str = Query(""),
    provincia: str = Query(""),
    session_id: str = Cookie(default=None)
):
    if not get_session(session_id):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    try:
        hits, totale = be.cerca_bandi_web(
            keyword=keyword, stato=stato, livello=livello,
            regione=regione, provincia=provincia, max_hits=50)
        bandi = [be.hit_to_card(h) for h in hits]
        return JSONResponse({"bandi": bandi, "totale": totale})
    except Exception as e:
        return JSONResponse({"error": str(e), "bandi": [], "totale": 0})


# ── Job system asincrono ─────────────────────────────────────────────────────
JOBS = {}

def _esegui_job(job_id, hit):
    try:
        object_id = hit.get("objectID", "")

        # 1. Cerca testo in cache locale
        testo_cache = leggi_da_cache(object_id) if object_id else None

        if testo_cache:
            print(f"[CACHE HIT] {object_id}", flush=True)
            # Usa testo dalla cache — chiama Claude SENZA web_search
            content, titolo = be.genera_scheda_da_testo(hit, testo_cache)
        else:
            print(f"[CACHE MISS] {object_id} — uso web_search", flush=True)
            content, titolo = be.genera_scheda_web(hit)

        api_error = content.pop("_api_error", "")
        if api_error:
            print(f"[CLAUDE API ERROR] {api_error}", flush=True)

        base = os.path.dirname(os.path.abspath(__file__))
        for nome_logo in ["Logo Energelia realistico.png", "logo_energelia.png", "logo.png"]:
            logo_energelia = os.path.join(base, nome_logo)
            if os.path.exists(logo_energelia):
                ENGINE.LOGO = logo_energelia
                break

        ENGINE.CONTENT = content
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        ENGINE.generate(output_path=tmp_path, verbose=False)

        titolo_corto = re.sub(r'[^\w\s]', '', titolo)[:40].strip().replace(' ', '_')
        nome_file = f"Energelia_{titolo_corto}_{datetime.now().strftime('%Y%m%d')}.pdf"
        JOBS[job_id] = {"status": "ready", "path": tmp_path, "nome": nome_file}
    except Exception as e:
        JOBS[job_id] = {"status": "error", "error": traceback.format_exc()}


# ── Cache admin ───────────────────────────────────────────────────────────────
CACHE_STATUS = {"running": False, "totale": 0, "fatti": 0, "errori": 0, "messaggio": ""}

def _aggiorna_cache():
    """Scarica le pagine CE di tutti i bandi aperti e le salva in Neon."""
    import requests as req
    CACHE_STATUS.update({"running": True, "fatti": 0, "errori": 0, "messaggio": "Avvio..."})

    session = req.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Language": "it-IT,it;q=0.9"})

    try:
        # Prende tutti i bandi aperti + prossima apertura
        hits, totale = be.cerca_bandi_web(stato="tutti", max_hits=500)
        CACHE_STATUS["totale"] = totale
        CACHE_STATUS["messaggio"] = f"Trovati {totale} bandi. Scaricamento in corso..."

        for i, hit in enumerate(hits):
            oid      = hit.get("objectID", "")
            titolo   = hit.get("post_title", "") or ""
            link     = hit.get("permalink", "") or hit.get("link", "") or ""
            if not oid or not link:
                continue
            try:
                r = session.get(link, timeout=12)
                html  = r.text
                # Pulisce l'HTML
                html  = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL|re.IGNORECASE)
                html  = re.sub(r'<style[^>]*>.*?</style>',  ' ', html, flags=re.DOTALL|re.IGNORECASE)
                testo = re.sub(r'<[^>]+>', ' ', html)
                testo = re.sub(r'\s+', ' ', testo).strip()
                if len(testo) > 200:
                    salva_in_cache(oid, titolo, testo[:15000], link)
                    CACHE_STATUS["fatti"] += 1
            except:
                CACHE_STATUS["errori"] += 1

            CACHE_STATUS["messaggio"] = f"{i+1}/{totale} — salvati: {CACHE_STATUS['fatti']}, errori: {CACHE_STATUS['errori']}"

        CACHE_STATUS["messaggio"] = f"✅ Completato! {CACHE_STATUS['fatti']} bandi in cache."
    except Exception as e:
        CACHE_STATUS["messaggio"] = f"❌ Errore: {e}"
    finally:
        CACHE_STATUS["running"] = False


@app.get("/admin/db-check")
async def db_check(session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user or not user.get("is_admin"):
        return RedirectResponse("/login")
    risultati = {}
    # Test connessione
    try:
        con = get_pg()
        rows = con.run("SELECT COUNT(*) FROM bandi_cache")
        n = rows[0][0] if rows else 0
        risultati["connessione"] = "✅ OK"
        risultati["bandi_in_cache"] = n
        # Mostra 3 esempi
        esempi = con.run("SELECT object_id, titolo, LENGTH(testo_pagina) FROM bandi_cache LIMIT 3")
        risultati["esempi"] = [{"id": r[0], "titolo": r[1], "chars": r[2]} for r in esempi]
        con.close()
    except Exception as e:
        risultati["connessione"] = f"❌ ERRORE: {e}"
        risultati["bandi_in_cache"] = 0
        risultati["esempi"] = []
    return JSONResponse(risultati)
async def admin_cache_page(session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user or not user.get("is_admin"):
        return RedirectResponse("/login")
    n = conta_cache()
    return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><title>Admin Cache — ItalBandi</title>{CSS_BASE}</head><body>
{NAVBAR_LOGGED(user)}
<div class="container" style="max-width:700px;margin-top:40px">
  <h2 style="color:#C9A84C;margin-bottom:20px">⚙️ Gestione Cache Bandi</h2>
  <div style="background:#0F2035;border:1px solid #1E3A5F;border-radius:8px;padding:24px;margin-bottom:20px">
    <p style="color:#A8C8E8;margin-bottom:8px">Bandi attualmente in cache: <strong style="color:#C9A84C">{n}</strong></p>
    <p style="color:#6A8AA8;font-size:0.85rem">Aggiornare la cache scarica le pagine di tutti i bandi aperti da ContributiEuropa e le salva nel database. Le schede generate useranno questi dati senza cercare su internet — costo API ridotto a 1-2 centesimi per scheda.</p>
  </div>
  <button onclick="avviaCache()" id="btn-cache" style="background:#C9A84C;color:#0A1628;border:none;padding:14px 32px;border-radius:6px;font-weight:700;font-size:1rem;cursor:pointer">
    🔄 Aggiorna Cache Adesso
  </button>
  <div id="stato" style="margin-top:20px;padding:16px;background:#0F2035;border-radius:6px;display:none">
    <p id="msg" style="color:#A8C8E8;font-size:0.9rem"></p>
    <div id="progress" style="margin-top:8px;height:6px;background:#1E3A5F;border-radius:3px">
      <div id="bar" style="height:6px;background:#C9A84C;border-radius:3px;width:0%;transition:width 0.5s"></div>
    </div>
  </div>
</div>
<script>
async function avviaCache() {{
  document.getElementById('btn-cache').disabled = true;
  document.getElementById('stato').style.display = 'block';
  await fetch('/admin/cache/avvia', {{method:'POST'}});
  const poll = setInterval(async () => {{
    const r = await fetch('/admin/cache/status');
    const d = await r.json();
    document.getElementById('msg').textContent = d.messaggio;
    if (d.totale > 0) {{
      const pct = Math.round(d.fatti / d.totale * 100);
      document.getElementById('bar').style.width = pct + '%';
    }}
    if (!d.running) {{
      clearInterval(poll);
      document.getElementById('btn-cache').disabled = false;
    }}
  }}, 2000);
}}
</script>
</body></html>""")


@app.post("/admin/cache/avvia")
async def avvia_cache(session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user or not user.get("is_admin"):
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    if not CACHE_STATUS["running"]:
        threading.Thread(target=_aggiorna_cache, daemon=True).start()
    return JSONResponse({"ok": True})


@app.get("/admin/cache/status")
async def cache_status(session_id: str = Cookie(default=None)):
    return JSONResponse(CACHE_STATUS)


@app.post("/api/scheda/{bando_id}")
async def genera_scheda(bando_id: str, body: dict, session_id: str = Cookie(default=None)):
    if not get_session(session_id):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    hit    = body.get("hit", {})
    job_id = secrets.token_hex(8)
    JOBS[job_id] = {"status": "pending"}
    threading.Thread(target=_esegui_job, args=(job_id, hit), daemon=True).start()
    return JSONResponse({"job_id": job_id})


@app.get("/api/job/{job_id}")
async def check_job(job_id: str, session_id: str = Cookie(default=None)):
    if not get_session(session_id):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    job = JOBS.get(job_id)
    if not job:
        return JSONResponse({"status": "error", "error": "Job non trovato"})
    if job["status"] == "ready":
        return JSONResponse({"status": "ready", "nome": job["nome"]})
    if job["status"] == "error":
        return JSONResponse({"status": "error", "error": job.get("error","")})
    return JSONResponse({"status": "pending"})


@app.get("/api/download/{job_id}")
async def download_job(job_id: str, session_id: str = Cookie(default=None)):
    if not get_session(session_id):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    job = JOBS.get(job_id)
    if not job or job["status"] != "ready":
        return JSONResponse({"error": "File non pronto"}, status_code=404)
    return FileResponse(path=job["path"], media_type="application/pdf", filename=job["nome"])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
