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
import schede_engine as ENGINE
try:
    import page_sport2, page_ets2
    _extra_routers = True
except Exception as _e:
    _extra_routers = False
    print(f"[ROUTER] sport2/ets2 non caricati: {_e}", flush=True)

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_italbandi.png")

app = FastAPI(title="ItalBandi")
if _extra_routers:
    app.include_router(page_sport2.router)
    app.include_router(page_ets2.router)

# ── Cache bandi via SQLite ────────────────────────────────────────────────────
CACHE_DB = "/data/bandi_cache.db"
os.makedirs("/data", exist_ok=True)

def init_cache_db():
    con = sqlite3.connect(CACHE_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS bandi_cache (
        object_id    TEXT PRIMARY KEY,
        titolo       TEXT,
        testo_pagina TEXT,
        permalink    TEXT,
        aggiornato   TEXT
    )""")
    con.commit(); con.close()
    print("[DB] SQLite cache init OK", flush=True)

init_cache_db()

def salva_in_cache(object_id, titolo, testo, permalink):
    try:
        con = sqlite3.connect(CACHE_DB)
        con.execute("""INSERT OR REPLACE INTO bandi_cache
            (object_id,titolo,testo_pagina,permalink,aggiornato)
            VALUES (?,?,?,?,?)""",
            (object_id, titolo, testo, permalink, datetime.now().isoformat()))
        con.commit(); con.close()
    except Exception as e:
        print(f"[DB] save error: {e}", flush=True)

def leggi_da_cache(object_id):
    try:
        con = sqlite3.connect(CACHE_DB)
        row = con.execute("SELECT testo_pagina FROM bandi_cache WHERE object_id=?",
                          (object_id,)).fetchone()
        con.close()
        return row[0] if row else None
    except: return None

def conta_cache():
    try:
        con = sqlite3.connect(CACHE_DB)
        n = con.execute("SELECT COUNT(*) FROM bandi_cache").fetchone()[0]
        con.close()
        return n
    except: return 0

@app.post("/api/messaggio")
async def api_messaggio(body: dict, session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    nome  = body.get("nome", "").strip()
    testo = body.get("testo", "").strip()
    if not nome or not testo:
        return JSONResponse({"error": "Campi mancanti"})
    try:
        import requests as req
        resp = req.post("https://api.postmarkapp.com/email",
            headers={"X-Postmark-Server-Token": POSTMARK_KEY,
                     "Content-Type": "application/json"},
            json={
                "From": "bandieincentivi@energelia.it",
                "To": "a.castagnaro@energelia.it",
                "Subject": f"ItalBandi - Richiesta da {nome}",
                "TextBody": f"Nuovo messaggio da ItalBandi:\n\nUtente: {user.get('nome','')} {user.get('cognome','')} ({user.get('email','')})\nNome/Azienda: {nome}\n\nMessaggio:\n{testo}",
            }, timeout=10)
        result = resp.json()
        if resp.status_code == 200 and result.get("ErrorCode", 0) == 0:
            print(f"[MESSAGGIO] inviato da {user.get('email')} — {nome}", flush=True)
            return JSONResponse({"ok": True})
        else:
            print(f"[MESSAGGIO] ERRORE: {result}", flush=True)
            return JSONResponse({"error": "Errore Postmark"})
    except Exception as e:
        print(f"[MESSAGGIO] eccezione: {e}", flush=True)
        return JSONResponse({"error": str(e)})

@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok"}

@app.get("/logo")
async def serve_logo():
    for nome in ["Logo Bellissimo ItalBandi.png", "logo_italbandi.png", "logo.png"]:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), nome)
        if os.path.exists(path):
            return FileResponse(path, media_type="image/png")
    return Response(status_code=404)

@app.get("/video-intro")
async def serve_video():
    for nome in ["Script_cinematografico_–_ITALB.mp4", "Script_cinematografico___ITALB.mp4",
                 "Script_cinematografico_%E2%80%93_ITALB.mp4"]:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), nome)
        if os.path.exists(path):
            return FileResponse(path, media_type="video/mp4")
    return Response(status_code=404)

DB_PATH      = "/data/italbandi.db"
CACHE_DB     = "/data/bandi_cache.db"
SESSIONS     = {}
POSTMARK_KEY = "a874721e-db42-4173-af5e-5f77a74bdfbc"
BASE_URL     = "https://italbandi.onrender.com"
DATABASE_URL = os.environ.get("DATABASE_URL", "")

_USE_PG = False
_pg_params = {}
if DATABASE_URL:
    try:
        import urllib.parse as _urlparse
        _u = _urlparse.urlparse(DATABASE_URL)
        _pg_params = dict(
            user=_u.username, password=_u.password,
            host=_u.hostname, port=_u.port or 5432,
            database=_u.path.lstrip('/'),
            ssl_context=True
        )
        import pg8000.native as _pg8000
        _conn_test = _pg8000.Connection(**_pg_params)
        _conn_test.run("SELECT 1")
        _conn_test.close()
        _USE_PG = True
        print("[DB] Neon PostgreSQL connesso OK", flush=True)
    except Exception as _e:
        print(f"[DB] Neon fallback SQLite: {_e}", flush=True)

def _db_conn():
    if _USE_PG:
        import pg8000.native as pg
        return pg.Connection(**_pg_params)
    return sqlite3.connect(DB_PATH)

# ── Stripe (disattivato finché non si inseriscono le API key) ─────────────────
STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_ATTIVO          = bool(STRIPE_SECRET_KEY and STRIPE_SECRET_KEY.startswith("sk_"))

PACCHETTI = {
    "pack_s": {"nome": "Pack S — 10 ricerche", "ricerche": 10, "prezzo_cent": 750,  "prezzo_str": "€7,50"},
    "pack_m": {"nome": "Pack M — 20 ricerche", "ricerche": 20, "prezzo_cent": 1200, "prezzo_str": "€12,00"},
    "pdf_1":  {"nome": "Scheda PDF bando",     "ricerche": 0,  "prezzo_cent": 100,  "prezzo_str": "€1,00"},
}
RICERCHE_FREE = 5

def init_db():
    if _USE_PG:
        import pg8000.native as pg
        con = pg.Connection(**_pg_params)
        con.run("""CREATE TABLE IF NOT EXISTS utenti (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL, cognome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL, telefono TEXT,
            ruolo TEXT, impresa TEXT,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            verificato INTEGER DEFAULT 0,
            token_verifica TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        pw_hash = hashlib.sha256("Samp1946,".encode()).hexdigest()
        con.run("""INSERT INTO utenti (nome,cognome,email,password_hash,is_admin,verificato)
                   VALUES (:nome,:cognome,:email,:pw,:admin,:verif)
                   ON CONFLICT (email) DO NOTHING""",
                nome="Admin", cognome="ItalBandi",
                email="admin@italbandi.it", pw=pw_hash, admin=1, verif=1)
        con.close()
    else:
        con = sqlite3.connect(DB_PATH)
        con.execute("""CREATE TABLE IF NOT EXISTS utenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL, cognome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL, telefono TEXT,
            ruolo TEXT, impresa TEXT,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            verificato INTEGER DEFAULT 0,
            token_verifica TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        try: con.execute("ALTER TABLE utenti ADD COLUMN verificato INTEGER DEFAULT 0")
        except: pass
        try: con.execute("ALTER TABLE utenti ADD COLUMN token_verifica TEXT")
        except: pass
        try: con.execute("ALTER TABLE utenti ADD COLUMN ricerche_count INTEGER DEFAULT 0")
        except: pass
        try: con.execute("ALTER TABLE utenti ADD COLUMN account_type TEXT DEFAULT 'normale'")
        except: pass
        try: con.execute("ALTER TABLE utenti ADD COLUMN ricerche_acquistate INTEGER DEFAULT 0")
        except: pass
        try: con.execute("ALTER TABLE utenti ADD COLUMN ricerche_limite INTEGER DEFAULT -2")
        except: pass
        # ricerche_limite: -2 = non impostato (usa default tipo account), -1 = illimitato, N>0 = tetto personalizzato
        try: con.execute("ALTER TABLE utenti ADD COLUMN pdf_acquistati INTEGER DEFAULT 0")
        except: pass
        con.execute("""CREATE TABLE IF NOT EXISTS eventi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utente_id INTEGER,
            tipo TEXT,
            dettaglio TEXT,
            ip TEXT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS pagamenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utente_id INTEGER,
            tipo TEXT,
            stripe_session_id TEXT,
            importo_cent INTEGER,
            stato TEXT DEFAULT 'pending',
            oggetto_id TEXT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        pw_hash = hashlib.sha256("Samp1946,".encode()).hexdigest()
        con.execute("INSERT OR REPLACE INTO utenti (nome,cognome,email,password_hash,is_admin,verificato) VALUES (?,?,?,?,?,?)",
                    ("Admin","ItalBandi","admin@italbandi.it", pw_hash, 1, 1))
        con.commit(); con.close()

init_db()

def _keepalive():
    import time, requests as req
    time.sleep(60)
    while True:
        try:
            req.get(f"{BASE_URL}/health", timeout=10)
            print("[KEEPALIVE] ping OK", flush=True)
        except Exception as e:
            print(f"[KEEPALIVE] errore: {e}", flush=True)
        time.sleep(600)

threading.Thread(target=_keepalive, daemon=True).start()

def invia_email_verifica(email, nome, token):
    try:
        import requests as req
        link = f"{BASE_URL}/verifica?token={token}"
        resp = req.post("https://api.postmarkapp.com/email",
            headers={"X-Postmark-Server-Token": POSTMARK_KEY,
                     "Content-Type": "application/json"},
            json={
                "From": "bandieincentivi@energelia.it",
                "ReplyTo": "a.castagnaro@energelia.it",
                "To": email,
                "Subject": "Conferma la tua email - ItalBandi",
                "HtmlBody": f"""
<div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px">
  <h2 style="color:#1A2A4A">Benvenuto su ItalBandi, {nome}!</h2>
  <p style="color:#444">Clicca il pulsante qui sotto per confermare la tua email e attivare il tuo account.</p>
  <a href="{link}" style="display:inline-block;background:#C9A84C;color:#1A2A4A;padding:14px 32px;border-radius:6px;font-weight:700;text-decoration:none;margin:20px 0">
    Conferma Email
  </a>
  <p style="color:#888;font-size:0.85rem">Il link e valido per 24 ore.<br>Se non ti sei registrato su ItalBandi, ignora questa email.</p>
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
  <p style="color:#888;font-size:0.8rem">ItalBandi - un servizio di Energelia S.r.l. - Genova</p>
</div>""",
                "TextBody": f"Benvenuto su ItalBandi, {nome}!\n\nConferma la tua email:\n{link}\n\nIl link e valido per 24 ore.",
            }, timeout=10)
        result = resp.json()
        if resp.status_code == 200 and result.get("ErrorCode", 0) == 0:
            print(f"[EMAIL] verifica inviata a {email}", flush=True)
        else:
            print(f"[EMAIL] ERRORE Postmark: {result}", flush=True)
    except Exception as e:
        print(f"[EMAIL] eccezione: {e}", flush=True)

def get_user(email, password):
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    if _USE_PG:
        import pg8000.native as pg
        con = pg.Connection(**_pg_params)
        rows = con.run("SELECT id,nome,cognome,email,is_admin,verificato FROM utenti WHERE email=:e AND password_hash=:p",
                       e=email, p=pw_hash)
        con.close()
        return rows[0] if rows else None
    else:
        con = sqlite3.connect(DB_PATH)
        row = con.execute("SELECT id,nome,cognome,email,is_admin,verificato FROM utenti WHERE email=? AND password_hash=?",
                          (email, pw_hash)).fetchone()
        con.close()
        return row

def register_user(nome, cognome, email, password, telefono="", ruolo="", impresa=""):
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    token   = secrets.token_urlsafe(32)
    try:
        if _USE_PG:
            import pg8000.native as pg
            con = pg.Connection(**_pg_params)
            con.run("""INSERT INTO utenti (nome,cognome,email,password_hash,telefono,ruolo,impresa,verificato,token_verifica)
                       VALUES (:nome,:cognome,:email,:pw,:tel,:ruolo,:impresa,0,:token)""",
                    nome=nome, cognome=cognome, email=email, pw=pw_hash,
                    tel=telefono, ruolo=ruolo, impresa=impresa, token=token)
            con.close()
        else:
            con = sqlite3.connect(DB_PATH)
            con.execute("INSERT INTO utenti (nome,cognome,email,password_hash,telefono,ruolo,impresa,verificato,token_verifica) VALUES (?,?,?,?,?,?,?,0,?)",
                        (nome, cognome, email, pw_hash, telefono, ruolo, impresa, token))
            con.commit(); con.close()
        threading.Thread(target=invia_email_verifica, args=(email, nome, token), daemon=True).start()
        return True, ""
    except Exception as ex:
        if "unique" in str(ex).lower() or "UNIQUE" in str(ex):
            return False, "Email gia registrata."
        return False, str(ex)

def create_session(user_row):
    sid = secrets.token_hex(32)
    SESSIONS[sid] = {"id": user_row[0], "nome": user_row[1],
                     "cognome": user_row[2], "email": user_row[3],
                     "is_admin": bool(user_row[4])}
    return sid

def get_session(session_id: str = None):
    if not session_id: return None
    return SESSIONS.get(session_id)

CSS_BASE = """
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; background: #E8EEF7; color: #1A2A3A; min-height: 100vh;
  background-image: radial-gradient(circle at 20% 50%, rgba(201,168,76,0.06) 0%, transparent 50%),
                    radial-gradient(circle at 80% 20%, rgba(26,42,74,0.08) 0%, transparent 50%);
}
a { color: #1A3A6A; text-decoration: none; }
a:hover { text-decoration: underline; }
.navbar {
  background: #1A2A4A;
  border-bottom: 3px solid #C9A84C;
  padding: 0 40px;
  display: flex; align-items: center; justify-content: space-between;
  height: 72px;
}
.navbar-brand { font-size: 1.5rem; font-weight: 800; color: #C9A84C; letter-spacing: 2px; text-transform: uppercase; }
.navbar-brand span { color: #FFFFFF; }
.navbar-links { display: flex; gap: 24px; align-items: center; font-size: 0.88rem; }
.navbar-links a { color: #A8BEDD; font-weight: 500; }
.navbar-links a:hover { color: #C9A84C; text-decoration: none; }
.btn-logout {
  background: transparent; border: 1px solid #C9A84C;
  color: #C9A84C; padding: 6px 16px; border-radius: 4px;
  font-size: 0.82rem; cursor: pointer; font-family: inherit;
}
.btn-logout:hover { background: #C9A84C; color: #1A2A4A; }
.hero {
  background: linear-gradient(135deg, #1A2A4A 0%, #243555 100%);
  border-bottom: 1px solid #C9A84C;
  padding: 24px 40px;
}
.hero h2 { font-size: 1rem; color: #C9A84C; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px; }
.hero p  { font-size: 0.85rem; color: #A8BEDD; }
.search-bar {
  background: #FFFFFF;
  border-bottom: 1px solid #D8E2EE;
  padding: 16px 40px;
  display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-end;
  box-shadow: 0 2px 8px rgba(26,42,74,0.08);
}
.search-bar input, .search-bar select {
  padding: 9px 14px;
  background: #F4F6FA; border: 1px solid #C8D4E4; border-radius: 5px;
  font-size: 0.88rem; color: #1A2A3A; font-family: inherit;
}
.search-bar input { flex: 1; min-width: 200px; }
.search-bar select { min-width: 150px; }
.search-bar input::placeholder { color: #8899AA; }
.search-bar input:focus, .search-bar select:focus { outline: none; border-color: #1A3A6A; }
.btn-cerca {
  padding: 9px 28px;
  background: #1A2A4A; color: #FFFFFF;
  border: none; border-radius: 5px;
  font-weight: 700; font-size: 0.9rem; cursor: pointer;
}
.btn-cerca:hover { background: #C9A84C; }
.container { max-width: 1000px; margin: 28px auto; padding: 0 20px 60px; }
.risultati-header { font-size: 0.8rem; color: #6A8AA8; margin-bottom: 14px; font-weight: 600; letter-spacing: 0.5px; }
.bando-card {
  background: #FFFFFF;
  border: 1px solid #D0DCF0;
  border-left: 4px solid #D0DCF0;
  border-radius: 8px;
  padding: 16px 20px 14px;
  margin-bottom: 10px;
  transition: border-left-color 0.2s, box-shadow 0.2s;
  box-shadow: 0 1px 4px rgba(26,42,74,0.06);
}
.bando-card:hover { border-left-color: #C9A84C; box-shadow: 0 3px 12px rgba(26,42,74,0.12); }
.card-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.card-cat-tag { font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; }
.card-titolo { font-size: 0.88rem; font-weight: 700; color: #1A2A3A; line-height: 1.45; margin-bottom: 8px; }
.card-info { display: flex; gap: 18px; margin-bottom: 10px; flex-wrap: wrap; }
.card-info-item { font-size: 0.78rem; color: #6A8AA8; display: flex; align-items: center; gap: 4px; }
.card-info-item strong { color: #2A4A6A; font-weight: 600; }
.card-divider { border: none; border-top: 1px solid #EEF2F8; margin: 10px 0; }
.card-actions { display: flex; gap: 8px; align-items: center; }
.btn-scheda {
  padding: 7px 18px;
  background: #1A2A4A; color: #FFFFFF;
  border: none; border-radius: 5px;
  font-size: 0.8rem; font-weight: 700; cursor: pointer;
}
.btn-scheda:hover { background: #C9A84C; }
.btn-scheda:disabled { background: #C8D4E4; color: #8899AA; cursor: not-allowed; }
.btn-preview {
  padding: 7px 12px; background: none; color: #5A7A9A;
  border: 1px solid #D0DCF0; border-radius: 5px;
  font-size: 0.73rem; font-weight: 700; cursor: pointer;
}
.btn-preview:hover { border-color: #C9A84C; color: #C9A84C; }
.badge { font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 20px; white-space: nowrap; }
.badge-aperto   { background: rgba(22,163,74,0.08); color: #15803D; border: 1px solid rgba(22,163,74,0.25); }
.badge-prossimo { background: rgba(37,99,235,0.08); color: #1D4ED8; border: 1px solid rgba(37,99,235,0.25); }
.spinner { display: none; font-size: 0.75rem; color: #8899AA; white-space: nowrap; }
.loader  { text-align: center; padding: 40px; color: #8899AA; }
.preview-panel {
  display: none; margin-bottom: 10px;
  padding: 12px 14px; background: #F4F7FC;
  border: 1px solid #D0DCF0; border-radius: 6px;
  font-size: 0.8rem; color: #3A5A7A; line-height: 1.6;
}
.auth-wrap {
  min-height: calc(100vh - 72px);
  display: flex; align-items: center; justify-content: center; padding: 40px 20px;
}
.auth-card {
  background: #FFFFFF; border: 1px solid #D8E2EE; border-radius: 12px;
  padding: 40px; width: 100%; max-width: 460px;
  box-shadow: 0 4px 20px rgba(26,42,74,0.1);
}
.auth-card h2 { font-size: 1.3rem; color: #1A2A4A; margin-bottom: 6px; font-weight: 700; }
.auth-card p.sub { font-size: 0.85rem; color: #6A8AA8; margin-bottom: 28px; }
.form-group { margin-bottom: 18px; }
.form-group label { display: block; font-size: 0.78rem; font-weight: 600; color: #5A7A9A; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 6px; }
.form-group input, .form-group select {
  width: 100%; padding: 10px 14px;
  background: #F4F6FA; border: 1px solid #C8D4E4; border-radius: 6px;
  font-size: 0.92rem; color: #1A2A3A; font-family: inherit;
}
.form-group input:focus { outline: none; border-color: #1A2A4A; }
.btn-primary {
  width: 100%; padding: 12px; background: #1A2A4A; color: #FFFFFF;
  border: none; border-radius: 6px; font-size: 1rem; font-weight: 700;
  cursor: pointer; margin-top: 8px; font-family: inherit;
}
.btn-primary:hover { background: #C9A84C; }
.err-msg { color: #DC2626; font-size: 0.84rem; margin-bottom: 16px; padding: 10px; background: #FEF2F2; border-radius: 6px; border: 1px solid #FECACA; }
.ok-msg  { color: #15803D; font-size: 0.84rem; margin-bottom: 16px; padding: 10px; background: #F0FDF4; border-radius: 6px; border: 1px solid #BBF7D0; }
.auth-footer { text-align: center; margin-top: 20px; font-size: 0.84rem; color: #6A8AA8; }
.privacy-note { font-size: 0.75rem; color: #8899AA; margin-top: 14px; text-align: center; line-height: 1.5; }
#cookie-banner {
  position: fixed; bottom: 0; left: 0; right: 0;
  background: #1A2A4A; border-top: 2px solid #C9A84C;
  padding: 16px 40px; display: flex; align-items: center;
  justify-content: space-between; gap: 20px; z-index: 9999; flex-wrap: wrap;
}
#cookie-banner p { font-size: 0.82rem; color: #A8BEDD; flex: 1; }
.btn-cookie { padding: 7px 18px; border-radius: 4px; border: none; font-weight: 600; font-size: 0.82rem; cursor: pointer; font-family: inherit; }
.btn-cookie-ok  { background: #C9A84C; color: #1A2A4A; }
.btn-cookie-no  { background: transparent; border: 1px solid #5A7A9A; color: #A8BEDD; }
footer.site-footer {
  background: #1A2A4A; border-top: 1px solid #2A3A5A;
  padding: 24px 40px; margin-top: 40px;
  text-align: center; font-size: 0.75rem; color: #7A9ABB; line-height: 1.8;
}
footer.site-footer a { color: #6A8AA8; }
.page-wrap { max-width: 800px; margin: 40px auto; padding: 0 20px 60px; }
.page-wrap h1 { color: #C9A84C; font-size: 1.5rem; margin-bottom: 20px; }
.page-wrap h2 { color: #D4E8FF; font-size: 1.05rem; margin: 28px 0 10px; }
.page-wrap p  { color: #8899AA; font-size: 0.88rem; line-height: 1.7; margin-bottom: 12px; }
.page-wrap ul { color: #8899AA; font-size: 0.88rem; line-height: 1.7; padding-left: 20px; margin-bottom: 12px; }
</style>
"""

NAVBAR_LOGGED = lambda user: f"""
<nav class="navbar">
  <a href="/" style="display:flex;align-items:center;gap:14px;text-decoration:none">
    <img src="/logo" alt="ItalBandi" style="height:68px;width:68px;object-fit:cover;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.4)">
    <span class="navbar-brand">ITAL<span>BANDI</span></span>
  </a>
  <div class="navbar-links">
    <span style="color:#6A8AA8;font-size:0.82rem">Ciao, {user['nome']}</span>
    <a href="/privacy">Privacy</a>
    <a href="/cookie">Cookie Policy</a>
    {'<a href="/area-riservata" class="navbar-keep" style="color:#C9A84C;font-weight:700;border:1px solid rgba(201,168,76,0.4);padding:5px 12px;border-radius:4px">&#9881; Area Riservata</a>' if user.get('is_admin') else ''}
    <form method="POST" action="/logout" style="margin:0">
      <button class="btn-logout navbar-keep" type="submit">Esci</button>
    </form>
  </div>
</nav>"""

FOOTER_HTML = """
<footer class="site-footer">
  <strong style="color:#C9A84C">ItalBandi</strong> — un servizio di
  <strong style="color:#D4E8FF">Energelia S.r.l.</strong><br>
  Piazza Giacomo Matteotti, 2 · 16123 Genova · P.IVA 01806600991<br>
  Tel. <a href="tel:+390107776530">010 7776530</a> ·
  <a href="mailto:bandieincentivi@energelia.it">bandieincentivi@energelia.it</a> ·
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

def login_page(error=""):
    err = f'<div class="err-msg">{error}</div>' if error else ""
    return f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ItalBandi — Accedi</title>{CSS_BASE}</head><body>
<nav class="navbar">
  <a href="/" style="display:flex;align-items:center;gap:12px;text-decoration:none">
    <img src="/logo" alt="ItalBandi" style="height:60px;width:60px;object-fit:cover;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.4)">
    <span class="navbar-brand">ITAL<span>BANDI</span></span>
  </a>
  <div class="navbar-links">
    <a href="/login">Accedi</a>
    <a href="/registrati" style="background:#C9A84C;color:#0A1628;padding:7px 18px;border-radius:5px;font-weight:700">Registrati gratis</a>
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
    <div class="auth-footer">Non hai un account? <a href="/registrati">Registrati gratis</a> &nbsp;·&nbsp; <a href="/reset-password">Password dimenticata?</a></div>
    <p class="privacy-note">Accedendo accetti la nostra <a href="/privacy">Privacy Policy</a> e la <a href="/cookie">Cookie Policy</a>.</p>
  </div>
</div>
{FOOTER_HTML}
</body></html>"""

def registrati_page(error="", ok=""):
    err = f'<div class="err-msg">{error}</div>' if error else ""
    okm = f'<div class="ok-msg">{ok}</div>' if ok else ""
    return f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ItalBandi — Registrati</title>{CSS_BASE}</head><body>
<nav class="navbar">
  <a href="/" style="display:flex;align-items:center;gap:12px;text-decoration:none">
    <img src="/logo" alt="ItalBandi" style="height:60px;width:60px;object-fit:cover;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.4)">
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
      <div class="form-group">
        <label>Password *</label>
        <div style="position:relative">
          <input type="password" name="password" id="pwd1" required placeholder="Min. 8 caratteri" style="width:100%;padding-right:40px">
          <button type="button" onclick="togglePwd('pwd1')" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);background:none;border:none;cursor:pointer;color:#8899AA;font-size:1rem">&#128065;</button>
        </div>
      </div>
      <div class="form-group">
        <label>Ripeti password *</label>
        <div style="position:relative">
          <input type="password" name="password2" id="pwd2" required placeholder="Ripeti la password" style="width:100%;padding-right:40px">
          <button type="button" onclick="togglePwd('pwd2')" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);background:none;border:none;cursor:pointer;color:#8899AA;font-size:1rem">&#128065;</button>
        </div>
        <div id="pwd-err" style="display:none;color:#DC2626;font-size:0.78rem;margin-top:4px">Le password non coincidono.</div>
      </div>
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
      <button class="btn-primary" type="submit" onclick="return validaForm()">Crea account</button>
    </form>
    <script>
    function togglePwd(inputId) {{
      const input = document.getElementById(inputId);
      input.type = input.type === 'password' ? 'text' : 'password';
    }}
    function validaForm() {{
      const p1 = document.getElementById('pwd1').value;
      const p2 = document.getElementById('pwd2').value;
      if (p1 !== p2) {{
        document.getElementById('pwd-err').style.display = 'block';
        return false;
      }}
      document.getElementById('pwd-err').style.display = 'none';
      return true;
    }}
    </script>
    <div class="auth-footer">Hai gia un account? <a href="/login">Accedi</a></div>
  </div>
</div>
{FOOTER_HTML}
</body></html>"""

def index_page(user):
    return f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ItalBandi — Bandi e Incentivi per le Imprese</title>{CSS_BASE}</head><body>
{NAVBAR_LOGGED(user)}
<div class="hero">
  <h2>Trova il bando giusto per la tua impresa</h2>
  <p>Migliaia di opportunita di finanziamento — europee, nazionali e regionali. Cerca, filtra e scarica la scheda PDF in un click.</p>
</div>
<div class="search-bar">
  <div style="display:flex;flex:0 0 280px;flex-direction:column;gap:4px">
    <input id="keyword" type="text" placeholder="Parola chiave..." style="width:100%">
    <div style="display:flex;gap:6px">
      <button id="btn-ampia" onclick="setRicerca('no')"
        style="flex:1;padding:5px 10px;background:#1A2A4A;color:#fff;border:1px solid #1A2A4A;border-radius:4px;font-size:0.72rem;font-weight:700;cursor:pointer">
        Nel testo
      </button>
      <button id="btn-precisa" onclick="setRicerca('si')"
        style="flex:1;padding:5px 10px;background:#fff;color:#1A2A4A;border:1px solid #C8D4E4;border-radius:4px;font-size:0.72rem;font-weight:700;cursor:pointer">
        Nel titolo
      </button>
    </div>
  </div>
  <select id="stato">
    <option value="aperto">Bandi aperti</option>
    <option value="prossimo">In apertura</option>
    <option value="tutti">Tutti i bandi</option>
  </select>
  <select id="livello" onchange="aggiornaFiltri()">
    <option value="">Qualsiasi livello</option>
    <option value="europeo">Europeo</option>
    <option value="nazionale">Nazionale</option>
    <option value="regionale">Regionale</option>
  </select>
  <select id="beneficiari">
    <option value="">Tutti i destinatari</option>
    <option value="Micro impresa">Micro impresa</option>
    <option value="PMI">PMI</option>
    <option value="Grande Impresa">Grande Impresa</option>
    <option value="Ente pubblico">Ente pubblico</option>
    <option value="Associazione-Ente Non profit/Terzo settore/Impresa e Cooperativa sociale">Terzo settore / No profit</option>
  </select>
  <span id="regione-wrap" style="display:none">
    <select id="regione">
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
  <button class="btn-cerca" onclick="cerca()">Cerca</button>
</div>
<div style="background:#F0F4FB;border-bottom:1px solid #D8E2EE;padding:10px 40px">
  <div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap">
    <span style="font-size:0.72rem;color:#8899AA;font-weight:700;white-space:nowrap;padding-top:2px">Come cercare:</span>
    <span style="font-size:0.75rem;color:#5A7A9A;line-height:1.6">
      Scrivi una o due parole chiave (es. energia, macchinari 4.0, formazione).
      Usa <strong>Nel testo</strong> per una ricerca ampia, <strong>Nel titolo</strong> per risultati piu precisi.
    </span>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button onclick="suggerisci('energia rinnovabile')" class="chip-sug">energia</button>
      <button onclick="suggerisci('formazione dipendenti')" class="chip-sug">formazione</button>
      <button onclick="suggerisci('macchinari 4.0')" class="chip-sug">macchinari</button>
      <button onclick="suggerisci('internazionalizzazione')" class="chip-sug">export</button>
      <button onclick="suggerisci('startup innovativa')" class="chip-sug">startup</button>
    </div>
  </div>
</div>
<style>
.chip-sug {{
  padding:4px 12px;background:#FFFFFF;border:1px solid #C8D4E4;
  border-radius:20px;font-size:0.75rem;color:#1A2A4A;cursor:pointer;
  font-family:inherit;transition:all 0.15s;white-space:nowrap;
}}
.chip-sug:hover {{ background:#1A2A4A;color:#fff;border-color:#1A2A4A; }}
</style>
<div style="background:#1A2A4A;padding:20px 40px;border-bottom:1px solid #243555">
  <div id="risultati-header" class="risultati-header"></div>
  <div id="risultati"></div>
</div>
{FOOTER_HTML}
<script>
function suggerisci(kw) {{ document.getElementById('keyword').value = kw; cerca(); }}
let _soloTitolo = 'no';
function setRicerca(val) {{
  _soloTitolo = val;
  const btnA = document.getElementById('btn-ampia');
  const btnP = document.getElementById('btn-precisa');
  if (val === 'no') {{
    btnA.style.background='#1A2A4A'; btnA.style.color='#fff'; btnA.style.borderColor='#1A2A4A';
    btnP.style.background='#fff'; btnP.style.color='#1A2A4A'; btnP.style.borderColor='#C8D4E4';
  }} else {{
    btnP.style.background='#C9A84C'; btnP.style.color='#1A2A4A'; btnP.style.borderColor='#C9A84C';
    btnA.style.background='#fff'; btnA.style.color='#1A2A4A'; btnA.style.borderColor='#C8D4E4';
  }}
}}
function aggiornaFiltri() {{
  const livello = document.getElementById('livello').value;
  document.getElementById('regione-wrap').style.display = livello==='regionale' ? 'inline' : 'none';
  document.getElementById('provincia-wrap').style.display = 'none';
  if (livello !== 'regionale') document.getElementById('regione').value = '';
}}
let _hits = {{}};
async function cerca() {{
  const params = new URLSearchParams({{
    keyword: document.getElementById('keyword').value,
    stato:   document.getElementById('stato').value,
    livello: document.getElementById('livello').value,
    regione: document.getElementById('regione').value,
    beneficiari: document.getElementById('beneficiari').value,
    solo_titolo: _soloTitolo,
  }});
  document.getElementById('risultati').innerHTML = '<div class="loader">Ricerca in corso...</div>';
  document.getElementById('risultati-header').textContent = '';
  const resp = await fetch('/api/cerca?' + params);
  const data = await resp.json();
  if (data.error === 'limite') {{
    const stripeAttivo = data.stripe_attivo;
    const btnAcquisto = stripeAttivo ? `
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-bottom:16px">
        <button onclick="acquistaPacchetto('pack_s')" style="background:#1A2A4A;color:#C9A84C;border:2px solid #C9A84C;padding:12px 20px;border-radius:8px;font-weight:700;font-size:0.88rem;cursor:pointer;text-align:center">
          Pack S<br><span style="font-size:0.78rem;font-weight:400;color:#A8BEDD">10 ricerche · €7,50</span>
        </button>
        <button onclick="acquistaPacchetto('pack_m')" style="background:#C9A84C;color:#1A2A4A;border:2px solid #C9A84C;padding:12px 20px;border-radius:8px;font-weight:700;font-size:0.88rem;cursor:pointer;text-align:center">
          Pack M<br><span style="font-size:0.78rem;font-weight:400">20 ricerche · €12,00</span>
        </button>
      </div>
      <p style="font-size:0.78rem;color:#8899AA;margin-bottom:12px">Vuoi un piano personalizzato? Chiamaci.</p>` : `
      <p style="color:#6A8AA8;font-size:0.88rem;line-height:1.6;margin-bottom:16px">Contatta Energelia per sbloccare ricerche aggiuntive.</p>`;
    document.getElementById('risultati').innerHTML = `
      <div style="background:#fff;border:1px solid #D0DCF0;border-left:4px solid #C9A84C;border-radius:8px;padding:28px 32px;text-align:center;max-width:560px;margin:40px auto">
        <div style="font-size:2rem;margin-bottom:12px">&#128274;</div>
        <h3 style="color:#1A2A4A;font-size:1.1rem;margin-bottom:8px">Hai esaurito le ricerche</h3>
        <p style="color:#6A8AA8;font-size:0.88rem;line-height:1.6;margin-bottom:20px">${{data.messaggio}}</p>
        ${{btnAcquisto}}
        <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
          <span style="background:#EEF2F8;color:#1A2A4A;padding:10px 22px;border-radius:6px;font-weight:700;font-size:0.9rem">010 7776530</span>
          <button onclick="mostraCtaDownload()" style="background:#1A2A4A;color:#fff;border:none;padding:10px 22px;border-radius:6px;font-weight:700;font-size:0.9rem;cursor:pointer">Scrivici</button>
        </div>
      </div>`;
    return;
  }}
  if (data.error) {{ document.getElementById('risultati').innerHTML = `<p style="color:#F87171">${{data.error}}</p>`; return; }}
  document.getElementById('risultati-header').textContent = `${{data.totale}} bandi trovati`;
  _hits = {{}};
  data.bandi.forEach(b => {{ _hits[b.id] = b._hit; }});
  const CATS = {{
    agric:    {{ r:/agric|rurale|biolog|animale|zootec|vitivin|vino|olio|forest/, t2:'#166534', l:'Agricoltura' }},
    energy:   {{ r:/energia|rinnovab|fotovolt|efficienza energet|solare|eolico|idrogeno/, t2:'#1D4ED8', l:'Energia' }},
    turismo:  {{ r:/turismo|albergo|hotel|agriturismo|ristorant|ricettiv/, t2:'#9D174D', l:'Turismo' }},
    digital:  {{ r:/digital|tecnolog|software|innovaz|startup|ricerca|sviluppo|cloud|cyber/, t2:'#5B21B6', l:'Digitale' }},
    industria:{{ r:/macchin|impianti|manifattur|industria|produzion|artigian/, t2:'#92400E', l:'Industria' }},
    commercio:{{ r:/commercio|negozio|bottega|retail|distribuz|fiera|duc/, t2:'#065F46', l:'Commercio' }},
    lavoro:   {{ r:/formazion|lavoro|occupaz|welfare|dipendenti|personale/, t2:'#1E40AF', l:'Formazione' }},
    intl:     {{ r:/internazion|export|estero|simest/, t2:'#4C1D95', l:'Export' }},
    sociale:  {{ r:/sociale|terzo settore|onlus|cooperat|inclusione|disabil/, t2:'#064E3B', l:'Sociale' }},
    edilizia: {{ r:/edilizia|riqualif|ristruttur|immobil|sismica/, t2:'#7C2D12', l:'Edilizia' }},
    cultura:  {{ r:/cultura|arte|musei|spettacolo|cinema|musica/, t2:'#831843', l:'Cultura' }},
    pesca:    {{ r:/pesca|mare|acquacolt|ittico/, t2:'#0C4A6E', l:'Pesca' }},
  }};
  const DEFCAT = {{ t2:'#1A2A4A', l:'Finanza Agevolata' }};
  function getCat(titolo) {{
    const t = (titolo||'').toLowerCase();
    for (const v of Object.values(CATS)) {{ if (v.r.test(t)) return v; }}
    return DEFCAT;
  }}
  document.getElementById('risultati').innerHTML = data.bandi.map(b => {{
    const cat = getCat(b.titolo);
    const aperto = !b.stato.includes('prossima');
    return `<div class="bando-card">
      <div class="card-top">
        <span class="card-cat-tag" style="color:${{cat.t2}}">${{cat.l}}</span>
        <div style="display:flex;gap:6px;align-items:center">
          <span class="badge ${{aperto?'badge-aperto':'badge-prossimo'}}">${{b.stato}}</span>
          <span style="font-size:10px;color:#8899AA">${{b.livello}}</span>
        </div>
      </div>
      <div class="card-titolo">${{b.titolo}}</div>
      <div class="card-info">
        <div class="card-info-item">&#128197; <strong>${{b.scadenza}}</strong></div>
        <div class="card-info-item">&#128100; <strong>${{(b.beneficiari||'').substring(0,50)}}</strong></div>
      </div>
      <hr class="card-divider">
      <div class="preview-panel" id="preview-${{b.id}}">
        <span id="prev-msg-${{b.id}}">Clicca Preview per scoprire se questo bando fa per te...</span>
      </div>
      <div class="card-actions">
        <button class="btn-scheda" id="btn-${{b.id}}" onclick="generaScheda('${{b.id}}')">Genera Scheda PDF</button>
        <button class="btn-preview" id="arrow-${{b.id}}" onclick="togglePreview('${{b.id}}')">PREVIEW</button>
        <span class="spinner" id="sp-${{b.id}}">elaborazione...</span>
      </div>
    </div>`;
  }}).join('');
}}
const _previewCache = {{}};
async function togglePreview(id) {{
  const el = document.getElementById('preview-'+id);
  const arrow = document.getElementById('arrow-'+id);
  const msg = document.getElementById('prev-msg-'+id);
  const apri = el.style.display==='none' || el.style.display==='';
  if (!apri) {{ el.style.display='none'; arrow.textContent='PREVIEW'; return; }}
  el.style.display='block'; arrow.textContent='CHIUDI';
  if (_previewCache[id]) {{ msg.innerHTML=_previewCache[id]; return; }}
  const hit=_hits[id];
  const titolo=hit?(hit.post_title||hit.title||''):'';
  const urlCE=hit?(hit.permalink||hit.link||hit.url||''):'';
  msg.innerHTML='<span style="color:#5A7A9A;font-style:italic">Analisi in corso...</span>';
  try {{
    let testoCE='';
    if (urlCE) {{
      const rt=await fetch('/api/fetch-testo?url='+encodeURIComponent(urlCE));
      if (rt.ok) {{ const dt=await rt.json(); testoCE=dt.testo||''; }}
    }}
    const r=await fetch('/api/preview',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{titolo,testo_ce:testoCE.substring(0,4000)}})}});
    const d=await r.json();
    if (d.html) {{ _previewCache[id]=d.html; msg.innerHTML=d.html; }}
    else msg.innerHTML='<span style="color:#F87171">Anteprima non disponibile.</span>';
  }} catch(e) {{ msg.innerHTML='<span style="color:#F87171">Errore: '+e.message+'</span>'; }}
}}
async function generaScheda(id) {{
  const btn=document.getElementById('btn-'+id);
  const sp=document.getElementById('sp-'+id);
  btn.disabled=true; sp.style.display='inline'; sp.textContent='Lettura bando...';
  const hit=_hits[id];
  const urlCE=(hit&&(hit.permalink||hit.link||hit.url))||'';
  let testoCE='';
  if (urlCE) {{
    try {{
      const rt=await fetch('/api/fetch-testo?url='+encodeURIComponent(urlCE));
      if (rt.ok) {{ const dt=await rt.json(); testoCE=dt.testo||''; }}
    }} catch(e) {{}}
  }}
  sp.textContent='Avvio elaborazione...';
  try {{
    const r1=await fetch('/api/scheda/'+encodeURIComponent(id),{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{hit:hit,testo_ce:testoCE}})}});
    const j1=await r1.json();
    if (!j1.job_id) {{ alert('Errore avvio: '+JSON.stringify(j1)); btn.disabled=false; sp.style.display='none'; return; }}
    const jobId=j1.job_id;
    let secondi=0;
    const poll=setInterval(async()=>{{
      secondi+=5; sp.textContent='Generazione in corso... ('+secondi+'s)';
      try {{
        const r2=await fetch('/api/job/'+jobId);
        const j2=await r2.json();
        if (j2.status==='ready') {{
          clearInterval(poll); sp.textContent='Pronto! Download in corso...';
          const r3=await fetch('/api/download/'+jobId);
          const blob=await r3.blob();
          const url=URL.createObjectURL(blob);
          const a=document.createElement('a'); a.href=url; a.download=j2.nome||('Energelia_'+id+'.pdf');
          document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
          sp.style.display='none'; btn.disabled=false;
          setTimeout(()=>mostraCtaDownload(),800);
        }} else if (j2.status==='error') {{
          clearInterval(poll); alert('Errore generazione scheda.'); sp.style.display='none'; btn.disabled=false;
        }} else if (secondi>180) {{
          clearInterval(poll); alert('Timeout. Riprova tra un momento.'); sp.style.display='none'; btn.disabled=false;
        }}
      }} catch(e) {{ clearInterval(poll); alert('Errore: '+e.message); btn.disabled=false; sp.style.display='none'; }}
    }},5000);
  }} catch(e) {{ alert('Errore: '+e.message); btn.disabled=false; sp.style.display='none'; }}
}}
function mostraCtaDownload() {{
  document.getElementById('cta-modal').style.display='flex';
  document.getElementById('cta-main').style.display='block';
  document.getElementById('cta-form').style.display='none';
}}
function chiudiCta() {{ document.getElementById('cta-modal').style.display='none'; }}
function mostraFormMsg() {{
  document.getElementById('cta-main').style.display='none';
  document.getElementById('cta-form').style.display='block';
}}
async function acquistaPacchetto(tipo) {{
  try {{
    const r = await fetch('/api/stripe/checkout', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{tipo}})
    }});
    const d = await r.json();
    if (d.url) {{ window.location.href = d.url; }}
    else {{ alert(d.error || 'Errore nel checkout'); }}
  }} catch(e) {{ alert('Errore di rete'); }}
}}
async function inviaMessaggio() {{
  const nome=document.getElementById('msg-nome').value.trim();
  const testo=document.getElementById('msg-testo').value.trim();
  const esito=document.getElementById('msg-esito');
  if (!nome||!testo) {{ esito.style.display='block'; esito.style.background='#2D1515'; esito.style.color='#F87171'; esito.textContent='Compila tutti i campi.'; return; }}
  try {{
    const r=await fetch('/api/messaggio',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{nome,testo}})}});
    const d=await r.json();
    if (d.ok) {{ esito.style.display='block'; esito.style.background='#0D3321'; esito.style.color='#4ADE80'; esito.textContent='Messaggio inviato! Ti contatteremo presto.'; document.getElementById('msg-nome').value=''; document.getElementById('msg-testo').value=''; }}
    else throw new Error(d.error||'Errore');
  }} catch(e) {{ esito.style.display='block'; esito.style.background='#2D1515'; esito.style.color='#F87171'; esito.textContent='Errore invio. Riprova o chiama il 010 7776530.'; }}
}}
window.onload = cerca;
</script>
<div id="cta-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:9999;align-items:center;justify-content:center">
  <div style="background:#0F2035;border:1px solid #C9A84C;border-radius:12px;padding:36px 40px;max-width:480px;width:90%;text-align:center;position:relative">
    <button onclick="chiudiCta()" style="position:absolute;top:12px;right:16px;background:none;border:none;color:#6A8AA8;font-size:1.2rem;cursor:pointer">X</button>
    <div id="cta-main">
      <div style="font-size:2rem;margin-bottom:12px">&#128203;</div>
      <h3 style="color:#C9A84C;font-size:1.2rem;margin-bottom:12px">Hai trovato un bando interessante?</h3>
      <p style="color:#A8C8E8;font-size:0.92rem;line-height:1.6;margin-bottom:24px">
        I nostri consulenti valuteranno <strong>gratuitamente</strong> la candidatura della tua azienda.
      </p>
      <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
        <span style="background:#C9A84C;color:#0A1628;padding:12px 24px;border-radius:6px;font-weight:700;font-size:0.92rem">010 7776530</span>
        <button onclick="mostraFormMsg()" style="background:transparent;color:#C9A84C;border:1px solid #C9A84C;padding:12px 24px;border-radius:6px;font-weight:700;font-size:0.92rem;cursor:pointer">Scrivici</button>
      </div>
      <p style="color:#3A5A7A;font-size:0.75rem;margin-top:16px">a.castagnaro@energelia.it</p>
    </div>
    <div id="cta-form" style="display:none;text-align:left">
      <h3 style="color:#C9A84C;font-size:1.1rem;margin-bottom:16px;text-align:center">Invia un messaggio</h3>
      <div style="margin-bottom:12px">
        <label style="display:block;font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#6A8AA8;margin-bottom:4px">Nome e Azienda</label>
        <input id="msg-nome" type="text" placeholder="Mario Rossi - Rossi S.r.l." style="width:100%;padding:9px 12px;background:#162840;border:1px solid #2A4A6B;border-radius:5px;color:#E8E8E8;font-size:0.88rem;font-family:inherit;outline:none">
      </div>
      <div style="margin-bottom:12px">
        <label style="display:block;font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#6A8AA8;margin-bottom:4px">Messaggio</label>
        <textarea id="msg-testo" rows="4" placeholder="Descrivici la tua azienda e cosa ti interessa..." style="width:100%;padding:9px 12px;background:#162840;border:1px solid #2A4A6B;border-radius:5px;color:#E8E8E8;font-size:0.88rem;font-family:inherit;outline:none;resize:vertical"></textarea>
      </div>
      <div id="msg-esito" style="display:none;font-size:0.82rem;margin-bottom:10px;padding:8px 12px;border-radius:5px"></div>
      <div style="display:flex;gap:10px">
        <button onclick="inviaMessaggio()" style="flex:1;padding:10px;background:#C9A84C;color:#0A1628;border:none;border-radius:5px;font-weight:700;cursor:pointer;font-family:inherit">Invia</button>
        <button onclick="document.getElementById('cta-form').style.display='none';document.getElementById('cta-main').style.display='block'" style="padding:10px 16px;background:none;color:#6A8AA8;border:1px solid #2A4A6B;border-radius:5px;cursor:pointer;font-family:inherit">Indietro</button>
      </div>
    </div>
  </div>
</div>
</body></html>"""

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
  <p><strong>Energelia S.r.l.</strong><br>Piazza Giacomo Matteotti, 2 — 16123 Genova<br>P.IVA: 01806600991<br>Tel: 010 7776530<br>Email: <a href="mailto:bandieincentivi@energelia.it">bandieincentivi@energelia.it</a><br><strong>Responsabile Privacy: Bruno Massimo Legger</strong></p>
  <h2>2. Dati raccolti</h2>
  <ul><li>Nome e cognome</li><li>Indirizzo email</li><li>Numero di telefono (facoltativo)</li><li>Ruolo professionale (facoltativo)</li><li>Nome azienda (facoltativo)</li></ul>
  <h2>3. Finalita del trattamento</h2>
  <p>Fornire accesso al servizio ItalBandi; inviare comunicazioni su bandi e opportunita di finanziamento; rispondere a richieste di consulenza; adempiere a obblighi di legge.</p>
  <h2>4. Base giuridica</h2>
  <p>Consenso esplicito (art. 6, par. 1, lett. a GDPR) e esecuzione di un contratto (art. 6, par. 1, lett. b GDPR).</p>
  <h2>5. Conservazione dei dati</h2>
  <p>I dati sono conservati per il tempo necessario all'erogazione del servizio e comunque non oltre 5 anni dall'ultimo accesso.</p>
  <h2>6. Diritti dell'interessato</h2>
  <p>Accesso, rettifica, cancellazione, portabilita e opposizione: <a href="mailto:bandieincentivi@energelia.it">bandieincentivi@energelia.it</a></p>
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
  <h2>Cookie tecnici (necessari)</h2>
  <ul><li><strong>session_id</strong> — cookie di sessione per mantenere il login.</li><li><strong>cookie_consent</strong> — memorizza la tua scelta sui cookie. Durata: 12 mesi.</li></ul>
  <h2>Cookie analitici (con consenso)</h2>
  <p>Previo consenso, potremmo utilizzare Google Analytics per analisi aggregate degli accessi.</p>
  <h2>Contatti</h2>
  <p><a href="mailto:bandieincentivi@energelia.it">bandieincentivi@energelia.it</a> — Energelia S.r.l., Piazza Giacomo Matteotti, 2, 16123 Genova.</p>
</div>
{FOOTER_HTML}</body></html>"""

# ── ROUTES ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def splash(session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    dest = "/home" if user else "/login"
    return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>ItalBandi</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:100%;height:100%;overflow:hidden;background:#0A1628}}
#splash{{position:fixed;top:0;left:0;width:100%;height:100%;display:flex;align-items:center;justify-content:center;flex-direction:column}}
#splash-intro{{text-align:center;padding:24px;width:100%;max-width:480px}}
#splash-video-wrap{{display:none;width:100%;height:100%;position:absolute;top:0;left:0;background:#000;align-items:center;justify-content:center}}
video{{width:100%;height:100%;object-fit:contain}}
.btn-entra{{background:#C9A84C;color:#1A2A4A;border:none;border-radius:30px;padding:14px 48px;font-size:clamp(1rem,4vw,1.1rem);font-weight:700;cursor:pointer;font-family:inherit;box-shadow:0 4px 16px rgba(201,168,76,0.4);-webkit-tap-highlight-color:transparent}}
.btn-salta{{position:absolute;top:16px;right:16px;background:rgba(255,255,255,0.15);color:#fff;border:1px solid rgba(255,255,255,0.4);border-radius:20px;padding:8px 20px;font-size:0.82rem;cursor:pointer;font-family:inherit;-webkit-tap-highlight-color:transparent;z-index:10}}
</style></head><body>
<div id="splash">
  <div id="splash-intro">
    <img src="/logo" style="height:64px;border-radius:10px;margin-bottom:24px;box-shadow:0 4px 24px rgba(0,0,0,0.5)">
    <h1 style="color:#C9A84C;font-family:Georgia,serif;font-size:clamp(1.5rem,5vw,2.2rem);margin-bottom:10px;letter-spacing:1px">ItalBandi</h1>
    <p style="color:#A8BEDD;font-size:clamp(0.85rem,3vw,1rem);margin-bottom:36px;line-height:1.5">Il portale dei bandi e incentivi per le imprese italiane</p>
    <button class="btn-entra" onclick="avviaVideo()">▶ &nbsp;Entra</button>
  </div>
  <div id="splash-video-wrap">
    <video id="splash-video" playsinline webkit-playsinline>
      <source src="/video-intro" type="video/mp4">
    </video>
    <button class="btn-salta" onclick="vai()">Salta ›</button>
  </div>
</div>
<script>
function avviaVideo(){{
  document.getElementById('splash-intro').style.display='none';
  var wrap=document.getElementById('splash-video-wrap');
  wrap.style.display='flex';
  var v=document.getElementById('splash-video');
  v.play();
  v.addEventListener('ended',vai);
}}
function vai(){{ window.location.href='{dest}'; }}
setTimeout(vai, 35000);
</script>
</body></html>""")

@app.get("/home", response_class=HTMLResponse)
async def index(session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user:
        return HTMLResponse(LANDING_HTML())
    return index_page(user)

@app.get("/login", response_class=HTMLResponse)
async def login_get(session_id: str = Cookie(default=None)):
    if get_session(session_id):
        return RedirectResponse("/home")
    return login_page()

@app.post("/login")
async def login_post(email: str = Form(""), password: str = Form("")):
    if email.lower() == "admin" and password == "Samp1946,":
        user_row = (0, "Admin", "ItalBandi", "admin@italbandi.it", 1, 1)
    else:
        user_row = get_user(email, password)
    if not user_row:
        return HTMLResponse(login_page("Email o password non corretti."))
    if len(user_row) > 5 and not user_row[5]:
        return HTMLResponse(login_page("Email non ancora verificata. Controlla la tua casella di posta."))
    sid = create_session(user_row)
    resp = RedirectResponse("/home", status_code=302)
    resp.set_cookie("session_id", sid, max_age=86400*7, httponly=True)
    return resp

@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_get(request: Request):
    return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ItalBandi — Password dimenticata</title>{CSS_BASE}</head><body>
<nav class="navbar">
  <a href="/" style="display:flex;align-items:center;gap:12px;text-decoration:none">
    <img src="/logo" style="height:60px;width:60px;object-fit:cover;border-radius:6px">
    <span class="navbar-brand">ITAL<span>BANDI</span></span>
  </a>
  <div class="navbar-links"><a href="/login">Accedi</a></div>
</nav>
<div class="auth-wrap"><div class="auth-card">
  <h2>Password dimenticata</h2>
  <p class="sub">Inserisci la tua email e ti mandiamo un link per reimpostare la password.</p>
  <form method="POST" action="/reset-password">
    <div class="form-group"><label>Email *</label><input type="email" name="email" required placeholder="tuaemail@esempio.it"></div>
    <button class="btn-primary" type="submit">Invia link di reset</button>
  </form>
  <div class="auth-footer"><a href="/login">Torna al login</a></div>
</div></div>
{FOOTER_HTML}</body></html>""")

@app.post("/reset-password", response_class=HTMLResponse)
async def reset_password_post(email: str = Form("")):
    msg_ok = f"""<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><title>ItalBandi</title>{CSS_BASE}</head><body>
<div class="auth-wrap"><div class="auth-card">
  <div class="ok-msg">Se questa email e registrata, riceverai a breve il link per reimpostare la password.</div>
  <div class="auth-footer"><a href="/login">Torna al login</a></div>
</div></div>{FOOTER_HTML}</body></html>"""
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute("SELECT id, nome FROM utenti WHERE email=?", (email,)).fetchone()
        if row:
            token = secrets.token_urlsafe(32)
            con.execute("UPDATE utenti SET token_verifica=? WHERE email=?", (token, email))
            con.commit()
            link = f"{BASE_URL}/nuova-password?token={token}"
            import requests as req
            req.post("https://api.postmarkapp.com/email",
                headers={"X-Postmark-Server-Token": POSTMARK_KEY, "Content-Type": "application/json"},
                json={"From": "bandieincentivi@energelia.it", "To": email,
                      "Subject": "Reset password — ItalBandi",
                      "TextBody": f"Reimposta la tua password:\n{link}\n\nIl link e valido per 24 ore."}, timeout=10)
        con.close()
    except Exception as e:
        print(f"[RESET] errore: {e}", flush=True)
    return HTMLResponse(msg_ok)

@app.get("/nuova-password", response_class=HTMLResponse)
async def nuova_password_get(token: str = ""):
    if not token:
        return RedirectResponse("/login")
    return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><title>ItalBandi — Nuova password</title>{CSS_BASE}</head><body>
<div class="auth-wrap"><div class="auth-card">
  <h2>Scegli la nuova password</h2>
  <form method="POST" action="/nuova-password">
    <input type="hidden" name="token" value="{token}">
    <div class="form-group"><label>Nuova password *</label><input type="password" name="password" id="npwd1" required placeholder="Min. 8 caratteri"></div>
    <div class="form-group"><label>Ripeti password *</label><input type="password" name="password2" id="npwd2" required placeholder="Ripeti la password">
      <div id="npwd-err" style="display:none;color:#DC2626;font-size:0.78rem;margin-top:4px">Le password non coincidono.</div>
    </div>
    <button class="btn-primary" type="submit" onclick="if(document.getElementById('npwd1').value!==document.getElementById('npwd2').value){{document.getElementById('npwd-err').style.display='block';return false;}}">Salva nuova password</button>
  </form>
</div></div>{FOOTER_HTML}</body></html>""")

@app.post("/nuova-password", response_class=HTMLResponse)
async def nuova_password_post(token: str = Form(""), password: str = Form(""), password2: str = Form("")):
    if not token or not password or password != password2 or len(password) < 8:
        return HTMLResponse("<p>Dati non validi. <a href='/login'>Torna al login</a></p>")
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute("UPDATE utenti SET password_hash=?, token_verifica=NULL WHERE token_verifica=?", (pw_hash, token))
        con.commit(); con.close()
        return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8"><title>ItalBandi</title>{CSS_BASE}</head><body>
<div class="auth-wrap"><div class="auth-card">
  <div class="ok-msg">Password aggiornata con successo!</div>
  <div class="auth-footer"><a href="/login" class="btn-primary" style="display:block;text-align:center;text-decoration:none;margin-top:12px">Accedi ora</a></div>
</div></div></body></html>""")
    except Exception as e:
        return HTMLResponse(f"<p>Errore: {e}. <a href='/login'>Torna al login</a></p>")

@app.get("/verifica", response_class=HTMLResponse)
async def verifica_email(token: str = ""):
    if not token:
        return HTMLResponse("<h2>Link non valido.</h2>")
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT id, nome FROM utenti WHERE token_verifica=?", (token,)).fetchone()
    if not row:
        con.close()
        return HTMLResponse("<body style='font-family:Arial;text-align:center;padding:60px'><h2 style='color:#DC2626'>Link non valido o gia utilizzato.</h2><a href='/login'>Vai al login</a></body>")
    con.execute("UPDATE utenti SET verificato=1, token_verifica=NULL WHERE id=?", (row[0],))
    con.commit(); con.close()
    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Email confermata</title></head>
<body style="font-family:Arial;text-align:center;padding:60px;background:#0A1628;color:#E8E8E8">
<div style="max-width:480px;margin:0 auto;background:#0F2035;border:1px solid #C9A84C;border-radius:12px;padding:40px">
  <div style="font-size:3rem;margin-bottom:16px">&#10003;</div>
  <h2 style="color:#C9A84C;margin-bottom:12px">Email confermata!</h2>
  <p style="color:#A8C8E8;margin-bottom:24px">Benvenuto su ItalBandi, <strong>{row[1]}</strong>!</p>
  <a href="/login" style="background:#C9A84C;color:#0A1628;padding:12px 32px;border-radius:6px;font-weight:700;text-decoration:none">Accedi ora</a>
</div></body></html>""")

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
    return HTMLResponse(registrati_page(ok=f"Account creato! Controlla la tua email per attivare l'account."))

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
    <img src="/logo" style="height:60px;width:60px;object-fit:cover;border-radius:6px">
    <span class="navbar-brand">ITAL<span>BANDI</span></span>
  </a>
  <div class="navbar-links">
    <a href="/login">Accedi</a>
    <a href="/registrati" style="background:#C9A84C;color:#0A1628;padding:7px 18px;border-radius:5px;font-weight:700">Registrati gratis</a>
  </div>
</nav>"""
    return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><title>Chi Siamo — ItalBandi</title>{CSS_BASE}</head><body>
{nav}
<div class="page-wrap">
  <h1>Dal 2006 al fianco delle imprese italiane</h1>
  <p>Energelia accompagna le aziende nell'accesso ai bandi pubblici, alla finanza agevolata e agli incentivi nazionali ed europei.</p>
  <h2>Il nostro team</h2>
  <p><strong>Bruno Massimo Legger</strong> — Amministratore Unico<br>
  <strong>Alberto Augusti</strong> — Responsabile Business Development<br>
  <strong>Antonio Castagnaro</strong> — Responsabile Commerciale</p>
  <div style="background:#0F2035;border:1px solid #C9A84C;border-radius:10px;padding:32px;text-align:center;margin-top:32px">
    <h2 style="color:#C9A84C;margin-bottom:12px">Vuoi sapere se la tua azienda puo accedere a un bando?</h2>
    <div style="display:flex;justify-content:center;gap:16px;flex-wrap:wrap;margin-top:20px">
      <a href="/registrati" style="background:#C9A84C;color:#0A1628;padding:12px 32px;border-radius:6px;font-weight:700;font-size:1rem">Registrati gratis</a>
      <a href="tel:+390107776530" style="background:transparent;color:#C9A84C;border:1px solid #C9A84C;padding:12px 32px;border-radius:6px;font-weight:700;font-size:1rem">010 7776530</a>
    </div>
  </div>
</div>
{FOOTER_HTML}</body></html>""")

LANDING_HTML = lambda: f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ItalBandi — Bandi e Incentivi per le Imprese</title>{CSS_BASE}
<style>
.hero-landing {{
  min-height: 100vh;
  background: linear-gradient(160deg, #0A1628 0%, #0F2035 60%, #0A1628 100%);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; padding: 40px 20px; position: relative; overflow: hidden;
}}
.hero-landing::before {{
  content: ''; position: absolute; inset: 0;
  background: radial-gradient(ellipse at 50% 40%, rgba(201,168,76,0.07) 0%, transparent 65%);
  pointer-events: none;
}}
.hero-logo {{ width: 140px; height: 140px; object-fit: cover; border-radius: 16px; margin-bottom: 28px; box-shadow: 0 0 50px rgba(201,168,76,0.35), 0 16px 40px rgba(0,0,0,0.5); position:relative; }}
.hero-title {{ font-size: 2.4rem; font-weight: 900; color: #FFFFFF; letter-spacing: -1px; line-height: 1.15; margin-bottom: 14px; position:relative; }}
.hero-title span {{ color: #C9A84C; }}
.hero-sub {{ font-size: 1rem; color: #8899AA; max-width: 440px; line-height: 1.65; margin-bottom: 36px; position:relative; }}
.hero-cta {{ display: flex; gap: 14px; flex-wrap: wrap; justify-content: center; position:relative; }}
.btn-accedi {{ padding: 14px 36px; background: #C9A84C; color: #0A1628; border: none; border-radius: 7px; font-size: 1rem; font-weight: 800; cursor: pointer; text-decoration: none; }}
.btn-accedi:hover {{ background: #E0BF6A; text-decoration: none; }}
.btn-registrati {{ padding: 14px 36px; background: transparent; color: #C9A84C; border: 2px solid #C9A84C; border-radius: 7px; font-size: 1rem; font-weight: 700; text-decoration: none; }}
.btn-registrati:hover {{ background: rgba(201,168,76,0.1); text-decoration: none; }}
@media (max-width: 480px) {{
  .hero-title {{ font-size: 1.8rem; }}
  .hero-logo {{ width: 100px; height: 100px; }}
  .btn-accedi, .btn-registrati {{ padding: 12px 28px; font-size: 0.95rem; width: 100%; text-align: center; }}
  .hero-cta {{ flex-direction: column; align-items: center; }}
}}
</style>
</head><body>
<div class="hero-landing">
  <img src="/logo" class="hero-logo" alt="ItalBandi">
  <h1 class="hero-title">Bandi e incentivi<br><span>per la tua impresa.</span></h1>
  <p class="hero-sub">Cerca tra migliaia di opportunita di finanziamento europee, nazionali e regionali.</p>
  <div class="hero-cta">
    <a href="/login" class="btn-accedi">Accedi</a>
    <a href="/registrati" class="btn-registrati">Registrati gratis</a>
  </div>
</div>
{FOOTER_HTML}
</body></html>"""

import requests as _req
_ce_session = _req.Session()
_ce_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
})
_ce_logged_in = False
_ce_login_time = 0  # timestamp ultimo login riuscito

def _ce_login():
    global _ce_logged_in, _ce_login_time
    import time
    # Ri-autentica se: mai loggato, o sessione scaduta (> 20 minuti)
    if _ce_logged_in and (time.time() - _ce_login_time) < 1200:
        return True
    # Reset per forzare nuovo login
    _ce_logged_in = False
    try:
        _ce_session.get("https://www.contributieuropa.com/login/", timeout=15)
        r = _ce_session.post("https://www.contributieuropa.com/wp-login.php", data={
            "log": "Alberto Augusti",
            "pwd": "Samp1946,",
            "wp-submit": "Accedi",
            "redirect_to": "https://www.contributieuropa.com/area-riservata/",
            "testcookie": "1",
        }, timeout=15, allow_redirects=True)
        _ce_logged_in = "area-riservata" in r.url or "logout" in r.text.lower()
        if _ce_logged_in:
            _ce_login_time = time.time()  # salva timestamp login riuscito
        print(f"[CE LOGIN] {'OK' if _ce_logged_in else 'FAILED'} — {r.url[:60]}", flush=True)
        return _ce_logged_in
    except Exception as e:
        print(f"[CE LOGIN] error: {e}", flush=True)
        return False

@app.get("/api/fetch-testo")
async def fetch_testo(url: str = Query(""), session_id: str = Cookie(default=None)):
    if not get_session(session_id):
        return JSONResponse({"testo": ""})
    if not url:
        return JSONResponse({"testo": ""})
    try:
        _ce_login()
        r = _ce_session.get(url, timeout=15, allow_redirects=True)
        html = r.text
        html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL|re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL|re.IGNORECASE)
        testo = re.sub(r'<[^>]+>', ' ', html)
        testo = re.sub(r'\s+', ' ', testo).strip()
        print(f"[FETCH] {url[:60]} — {len(testo)} chars", flush=True)
        return JSONResponse({"testo": testo[:20000]})
    except Exception as e:
        print(f"[FETCH] error: {e}", flush=True)
        return JSONResponse({"testo": ""})

@app.post("/api/preview")
async def api_preview(body: dict, session_id: str = Cookie(default=None)):
    if not get_session(session_id):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    titolo   = body.get("titolo", "")
    testo_ce = body.get("testo_ce", "")
    if not titolo:
        return JSONResponse({"html": ""})
    try:
        prompt = f"""Sei un esperto di finanza agevolata. Leggi questo bando e rispondi in modo ULTRA SINTETICO.
TITOLO: {titolo}
TESTO: {testo_ce[:3000]}
Rispondi SOLO con un JSON:
{{"chi":"Chi puo partecipare","cosa":"Cosa si finanzia","numeri":"Cifre chiave","scadenza":"Scadenza","fa_per_te":"Frase diretta"}}
Solo JSON, nient'altro."""
        import requests as req
        resp = req.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": be.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]},
            timeout=30)
        blocks = resp.json().get("content", [])
        testo  = "\n".join(b.get("text","") for b in blocks if b.get("type")=="text").strip()
        raw = re.sub(r'```(?:json)?\s*','',testo); raw = re.sub(r'```','',raw).strip()
        s = raw.find('{'); e = raw.rfind('}')
        d = json.loads(raw[s:e+1]) if s!=-1 else {}
        html = f"""
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
  <div><span style="color:#C9A84C;font-size:10px;font-weight:700;text-transform:uppercase">Chi puo partecipare</span><br><span style="font-size:12px">{d.get('chi','')}</span></div>
  <div><span style="color:#C9A84C;font-size:10px;font-weight:700;text-transform:uppercase">Cosa si finanzia</span><br><span style="font-size:12px">{d.get('cosa','')}</span></div>
  <div><span style="color:#C9A84C;font-size:10px;font-weight:700;text-transform:uppercase">Cifre chiave</span><br><span style="font-size:12px">{d.get('numeri','')}</span></div>
  <div><span style="color:#C9A84C;font-size:10px;font-weight:700;text-transform:uppercase">Scadenza</span><br><span style="font-size:12px">{d.get('scadenza','')}</span></div>
</div>
<div style="border-top:1px solid #1E3A5F;padding-top:8px;font-size:12px;color:#4ADE80">
  {d.get('fa_per_te','')}
</div>"""
        return JSONResponse({"html": html})
    except Exception as ex:
        return JSONResponse({"html": f'<span style="color:#F87171">Errore: {ex}</span>'})

@app.get("/api/cerca")
async def cerca(
    request: Request,
    keyword: str = Query(""), stato: str = Query("aperto"),
    livello: str = Query(""), regione: str = Query(""),
    beneficiari: str = Query(""),
    solo_titolo: str = Query("no"),
    session_id: str = Cookie(default=None)
):
    user = get_session(session_id)
    if not user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)

    if not user.get("is_admin"):
        con = sqlite3.connect(DB_PATH)
        row = con.execute("SELECT ricerche_count, COALESCE(account_type,'normale'), COALESCE(ricerche_acquistate,0), COALESCE(ricerche_limite,-2) FROM utenti WHERE id=?", (user["id"],)).fetchone()
        count      = row[0] if row else 0
        atype      = row[1] if row else 'normale'
        acquistate = row[2] if row else 0
        rlimite    = row[3] if row else -2

        # Calcola tetto effettivo
        if rlimite == -1:
            # admin ha impostato illimitato su questo utente
            limite = 999999
        elif rlimite > 0:
            # admin ha impostato un numero personalizzato
            limite = rlimite
            atype  = 'custom'
        elif atype == 'servizio':
            limite = 999999
        elif atype == 'pack':
            limite = acquistate
        else:
            limite = RICERCHE_FREE

        if atype not in ('servizio',) and rlimite != -1 and count >= limite:
            con.close()
            if atype == 'normale':
                msg = f"Hai esaurito le tue {RICERCHE_FREE} ricerche gratuite."
            elif atype == 'custom':
                msg = f"Hai esaurito le {limite} ricerche assegnate al tuo account."
            else:
                msg = "Hai esaurito le ricerche del tuo pacchetto."
            return JSONResponse({"error": "limite", "messaggio": msg, "stripe_attivo": STRIPE_ATTIVO}, status_code=429)
        if rlimite != -1 and atype not in ('servizio',):
            con.execute("UPDATE utenti SET ricerche_count = ricerche_count + 1 WHERE id=?", (user["id"],))
        # Log evento
        try:
            ip = request.client.host if request.client else ""
            con.execute("INSERT INTO eventi (utente_id,tipo,dettaglio,ip) VALUES (?,?,?,?)",
                (user["id"], "ricerca", f"kw={keyword}|livello={livello}|regione={regione}|ben={beneficiari}", ip))
        except: pass
        con.commit()
        con.close()

    try:
        hits, totale = be.cerca_bandi_web(
            keyword=keyword, stato=stato, livello=livello,
            regione=regione, beneficiari=beneficiari,
            max_hits=50, solo_titolo=(solo_titolo == "si"))
        bandi = [be.hit_to_card(h) for h in hits]
        return JSONResponse({"bandi": bandi, "totale": totale})
    except Exception as e:
        return JSONResponse({"error": str(e), "bandi": [], "totale": 0})

# ── Debug beneficiari ────────────────────────────────────────────────────────
@app.get("/api/debug-hit")
async def debug_hit():
    hits, _ = be.cerca_bandi_web(keyword="", stato="aperto", max_hits=10)
    risultati = []
    for h in hits:
        taxh = h.get("taxonomies_hierarchical", {})
        ben = taxh.get("beneficiari", {})
        risultati.append({"titolo": h.get("post_title","")[:60], "beneficiari": ben})
    return JSONResponse(risultati)

@app.get("/api/debug-province")
async def debug_province(regione: str = Query("")):
    hits, _ = be.cerca_bandi_web(keyword="", stato="tutti", livello="regionale", regione=regione, max_hits=20)
    valori = set()
    for h in hits:
        taxh = h.get("taxonomies_hierarchical", {})
        ag = taxh.get("area_geografica", {}) or {}
        for v in (ag.get("lvl1") or []):
            valori.add(v)
    return JSONResponse(sorted(valori))

# ── Stripe Checkout ───────────────────────────────────────────────────────────

@app.post("/api/stripe/checkout")
async def stripe_checkout(request: Request, session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    if not STRIPE_ATTIVO:
        return JSONResponse({"error": "Pagamenti non ancora attivi. Contattaci per info."}, status_code=503)

    body = await request.json()
    tipo = body.get("tipo", "")  # pack_s | pack_m | pdf_1
    oggetto_id = body.get("oggetto_id", "")  # per pdf: objectID del bando

    if tipo not in PACCHETTI:
        return JSONResponse({"error": "Prodotto non valido"}, status_code=400)

    pack = PACCHETTI[tipo]
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        checkout = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": pack["nome"]},
                    "unit_amount": pack["prezzo_cent"],
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{BASE_URL}/stripe/success?session_id={{CHECKOUT_SESSION_ID}}&tipo={tipo}&oggetto_id={oggetto_id}",
            cancel_url=f"{BASE_URL}/home",
            metadata={"utente_id": str(user["id"]), "tipo": tipo, "oggetto_id": oggetto_id},
        )
        # Salva pagamento pending
        con = sqlite3.connect(DB_PATH)
        con.execute("INSERT INTO pagamenti (utente_id,tipo,stripe_session_id,importo_cent,stato,oggetto_id) VALUES (?,?,?,?,?,?)",
            (user["id"], tipo, checkout.id, pack["prezzo_cent"], "pending", oggetto_id))
        con.commit(); con.close()
        return JSONResponse({"url": checkout.url})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/stripe/success", response_class=HTMLResponse)
async def stripe_success(request: Request, session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user:
        return RedirectResponse("/login")

    tipo = request.query_params.get("tipo", "")
    oggetto_id = request.query_params.get("oggetto_id", "")
    stripe_session = request.query_params.get("session_id", "")

    if STRIPE_ATTIVO and tipo in PACCHETTI:
        try:
            import stripe
            stripe.api_key = STRIPE_SECRET_KEY
            sess = stripe.checkout.Session.retrieve(stripe_session)
            if sess.payment_status == "paid":
                con = sqlite3.connect(DB_PATH)
                con.execute("UPDATE pagamenti SET stato='pagato' WHERE stripe_session_id=?", (stripe_session,))
                if tipo == "pack_s":
                    con.execute("UPDATE utenti SET account_type='pack', ricerche_acquistate=10, ricerche_count=0 WHERE id=?", (user["id"],))
                elif tipo == "pack_m":
                    con.execute("UPDATE utenti SET account_type='pack', ricerche_acquistate=20, ricerche_count=0 WHERE id=?", (user["id"],))
                elif tipo == "pdf_1":
                    con.execute("UPDATE utenti SET pdf_acquistati=COALESCE(pdf_acquistati,0)+1 WHERE id=?", (user["id"],))
                # Log evento
                con.execute("INSERT INTO eventi (utente_id,tipo,dettaglio,ip) VALUES (?,?,?,?)",
                    (user["id"], "pagamento", f"tipo={tipo}|stripe={stripe_session}", ""))
                con.commit(); con.close()
        except Exception as e:
            print(f"[STRIPE SUCCESS ERROR] {e}", flush=True)

    if tipo == "pdf_1" and oggetto_id:
        return RedirectResponse(f"/home?pdf_ready={oggetto_id}")
    return RedirectResponse("/home?pagamento=ok")

@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_ATTIVO:
        return JSONResponse({"ok": True})
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        if event["type"] == "checkout.session.completed":
            sess = event["data"]["object"]
            meta = sess.get("metadata", {})
            utente_id = int(meta.get("utente_id", 0))
            tipo = meta.get("tipo", "")
            oggetto_id = meta.get("oggetto_id", "")
            if utente_id and tipo:
                con = sqlite3.connect(DB_PATH)
                con.execute("UPDATE pagamenti SET stato='pagato' WHERE stripe_session_id=?", (sess["id"],))
                if tipo == "pack_s":
                    con.execute("UPDATE utenti SET account_type='pack', ricerche_acquistate=10, ricerche_count=0 WHERE id=?", (utente_id,))
                elif tipo == "pack_m":
                    con.execute("UPDATE utenti SET account_type='pack', ricerche_acquistate=20, ricerche_count=0 WHERE id=?", (utente_id,))
                elif tipo == "pdf_1":
                    con.execute("UPDATE utenti SET pdf_acquistati=COALESCE(pdf_acquistati,0)+1 WHERE id=?", (utente_id,))
                con.execute("INSERT INTO eventi (utente_id,tipo,dettaglio,ip) VALUES (?,?,?,?)",
                    (utente_id, "pagamento_webhook", f"tipo={tipo}|stripe={sess['id']}", ""))
                con.commit(); con.close()
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}", flush=True)
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"ok": True})

# ── Job system asincrono ──────────────────────────────────────────────────────
JOBS = {}

def _esegui_job(job_id, hit, testo_ce=""):
    try:
        object_id = hit.get("objectID", "")

        # Controlla se testo_ce è contenuto reale del bando (non pagina login/redirect)
        def _testo_valido(t):
            if not t or len(t) < 300:
                return False
            t_lower = t[:800].lower()
            # Scarta se sembra una pagina di login o redirect CE
            if any(k in t_lower for k in ("inserisci la tua email", "accedi al tuo account",
                                           "username or email", "lost your password",
                                           "wp-login", "effettua il login")):
                return False
            return True

        if testo_ce and _testo_valido(testo_ce):
            print(f"[TESTO CE] {object_id} — {len(testo_ce)} chars", flush=True)
            content, titolo = be.genera_scheda_da_testo(hit, testo_ce)
        else:
            if testo_ce and not _testo_valido(testo_ce):
                print(f"[TESTO CE] {object_id} — testo non valido (login/redirect?), uso cache/web", flush=True)
            testo_cache = leggi_da_cache(object_id) if object_id else None
            if testo_cache and _testo_valido(testo_cache) and "allowlist" not in testo_cache:
                print(f"[CACHE HIT] {object_id}", flush=True)
                content, titolo = be.genera_scheda_da_testo(hit, testo_cache)
            else:
                if testo_cache and not _testo_valido(testo_cache):
                    print(f"[CACHE] {object_id} — testo cache non valido, uso web_search", flush=True)
                else:
                    print(f"[CACHE MISS] {object_id} — uso web_search", flush=True)
                content, titolo = be.genera_scheda_web(hit)

        api_error = content.pop("_api_error", "")
        if api_error:
            print(f"[CLAUDE API ERROR] {api_error}", flush=True)

        base = os.path.dirname(os.path.abspath(__file__))
        logo_energelia = None
        for nome_logo in ["Logo_Energelia_realistico.png", "Logo Energelia realistico.png", "logo_energelia.png"]:
            candidato = os.path.join(base, nome_logo)
            if os.path.exists(candidato):
                logo_energelia = candidato
                break

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        print(f"[PDF] generazione avviata", flush=True)
        ENGINE.generate(content, tmp_path, None)
        print(f"[PDF] generazione completata", flush=True)

        titolo_corto = re.sub(r'[^\w\s]', '', titolo)[:40].strip().replace(' ', '_')
        nome_file = f"Energelia_{titolo_corto}_{datetime.now().strftime('%Y%m%d')}.pdf"
        JOBS[job_id] = {"status": "ready", "path": tmp_path, "nome": nome_file}
    except Exception as e:
        print(f"[PDF] ERRORE: {traceback.format_exc()}", flush=True)
        JOBS[job_id] = {"status": "error", "error": traceback.format_exc()}

# ── Cache admin ───────────────────────────────────────────────────────────────
CACHE_STATUS = {"running": False, "totale": 0, "fatti": 0, "errori": 0, "messaggio": ""}

def _aggiorna_cache():
    import requests as req
    CACHE_STATUS.update({"running": True, "fatti": 0, "errori": 0, "messaggio": "Avvio..."})
    session = req.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Language": "it-IT,it;q=0.9"})
    try:
        hits, totale = be.cerca_bandi_web(stato="tutti", max_hits=500)
        CACHE_STATUS["totale"] = totale
        CACHE_STATUS["messaggio"] = f"Trovati {totale} bandi. Scaricamento in corso..."
        for i, hit in enumerate(hits):
            oid   = hit.get("objectID", "")
            titolo = hit.get("post_title", "") or ""
            link  = hit.get("permalink", "") or hit.get("link", "") or ""
            if not oid or not link:
                continue
            try:
                r = session.get(link, timeout=12)
                html = r.text
                html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL|re.IGNORECASE)
                html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL|re.IGNORECASE)
                testo = re.sub(r'<[^>]+>', ' ', html)
                testo = re.sub(r'\s+', ' ', testo).strip()
                if len(testo) > 200:
                    salva_in_cache(oid, titolo, testo[:15000], link)
                    CACHE_STATUS["fatti"] += 1
            except:
                CACHE_STATUS["errori"] += 1
            CACHE_STATUS["messaggio"] = f"{i+1}/{totale} — salvati: {CACHE_STATUS['fatti']}, errori: {CACHE_STATUS['errori']}"
        CACHE_STATUS["messaggio"] = f"Completato! {CACHE_STATUS['fatti']} bandi in cache."
    except Exception as e:
        CACHE_STATUS["messaggio"] = f"Errore: {e}"
    finally:
        CACHE_STATUS["running"] = False

@app.get("/area-riservata", response_class=HTMLResponse)
async def area_riservata(session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user or not user.get("is_admin"):
        return RedirectResponse("/login")

    con = sqlite3.connect(DB_PATH)
    utenti = con.execute("""SELECT id, nome, cognome, email, impresa, ruolo, telefono,
            verificato, created_at, COALESCE(ricerche_count,0), COALESCE(account_type,'normale'),
            COALESCE(ricerche_limite,-2)
            FROM utenti ORDER BY created_at DESC""").fetchall()
    con.close()

    n_verificati = sum(1 for u in utenti if u[7])
    n_non_verif  = len(utenti) - n_verificati

    # Analytics
    con2 = sqlite3.connect(DB_PATH)
    n_ricerche_oggi = con2.execute("SELECT COUNT(*) FROM eventi WHERE tipo='ricerca' AND ts >= date('now')").fetchone()[0]
    n_pdf_oggi = con2.execute("SELECT COUNT(*) FROM eventi WHERE tipo='pagamento' AND dettaglio LIKE '%pdf_1%' AND ts >= date('now')").fetchone()[0]
    n_pagamenti_totali = con2.execute("SELECT COUNT(*) FROM pagamenti WHERE stato='pagato'").fetchone()[0]
    ricavi_totali = con2.execute("SELECT COALESCE(SUM(importo_cent),0) FROM pagamenti WHERE stato='pagato'").fetchone()[0]
    ultime_ricerche = con2.execute("""SELECT e.ts, u.email, e.dettaglio FROM eventi e
        LEFT JOIN utenti u ON u.id=e.utente_id WHERE e.tipo='ricerca'
        ORDER BY e.ts DESC LIMIT 20""").fetchall()
    con2.close()

    righe_html = ""
    for u in utenti:
        id_, nome, cognome, email, impresa, ruolo, tel, verif, created, ricerche, atype, rlimite = u
        stato = '<span style="color:#15803D;font-weight:700">&#10003;</span>' if verif else '<span style="color:#DC2626">&#10007;</span>'
        is_servizio = atype == 'servizio'
        is_pack = atype == 'pack'
        is_custom = rlimite > 0 or rlimite == -1  # admin ha impostato qualcosa
        if is_servizio or rlimite == -1:
            badge_tipo = '<span style="background:#1A2A4A;color:#C9A84C;font-size:0.65rem;font-weight:700;padding:2px 6px;border-radius:10px;margin-left:4px">SERVIZIO</span>' if is_servizio else '<span style="background:#059669;color:#fff;font-size:0.65rem;font-weight:700;padding:2px 6px;border-radius:10px;margin-left:4px">ILLIMITATO</span>'
            colore_r = '#059669'
            ricerche_txt = 'illimitate'
        elif is_pack:
            badge_tipo = '<span style="background:#7C3AED;color:#fff;font-size:0.65rem;font-weight:700;padding:2px 6px;border-radius:10px;margin-left:4px">PACK</span>'
            colore_r = '#7C3AED'
            ricerche_txt = f'{ricerche} usate'
        elif rlimite > 0:
            badge_tipo = '<span style="background:#D97706;color:#fff;font-size:0.65rem;font-weight:700;padding:2px 6px;border-radius:10px;margin-left:4px">CUSTOM</span>'
            colore_r = '#D97706' if ricerche < rlimite else '#DC2626'
            ricerche_txt = f'{ricerche}/{rlimite}'
        else:
            badge_tipo = ''
            colore_r = '#DC2626' if ricerche >= RICERCHE_FREE else '#1A2A4A'
            ricerche_txt = f'{ricerche}/{RICERCHE_FREE}'
        btn_reset = f'<button onclick="resetRicerche({id_},\'{email}\')" style="margin-left:4px;background:none;border:1px solid #C8D4E4;border-radius:4px;padding:2px 6px;font-size:0.68rem;color:#5A7A9A;cursor:pointer">reset</button>' if not is_servizio else ''
        btn_assegna = f'<button onclick="assegnaRicerche({id_},\'{email}\',{rlimite})" style="margin-left:4px;background:#D97706;color:#fff;border:none;border-radius:4px;padding:2px 6px;font-size:0.68rem;cursor:pointer">assegna</button>' if not is_servizio and not is_pack else ''
        righe_html += f"""<tr>
          <td>{nome} {cognome}{badge_tipo}</td>
          <td style="color:#1A3A6A">{email}</td>
          <td>{impresa or '—'}</td>
          <td>{tel or '—'}</td>
          <td style="text-align:center">{stato}</td>
          <td style="text-align:center;font-weight:700;color:{colore_r}">{ricerche_txt}{btn_reset}{btn_assegna}</td>
          <td style="color:#8899AA;font-size:0.75rem">{(created or '')[:10]}</td>
          <td><button onclick="eliminaUtente({id_},'{email}')"
            style="background:#FEF2F2;color:#DC2626;border:1px solid #FECACA;border-radius:4px;padding:3px 10px;font-size:0.73rem;cursor:pointer">
            Elimina</button></td>
        </tr>"""

    righe_ricerche = ""
    for ts, email, dettaglio in ultime_ricerche:
        kw = ""
        for part in dettaglio.split("|"):
            if part.startswith("kw="):
                kw = part[3:] or "—"
        righe_ricerche += f'<tr><td style="color:#8899AA;font-size:0.73rem">{ts[:16]}</td><td>{email or "?"}</td><td>{kw}</td></tr>'

    stripe_banner = ""
    if not STRIPE_ATTIVO:
        stripe_banner = '<div style="background:#FEF3C7;border:1px solid #F59E0B;border-radius:6px;padding:10px 14px;font-size:0.78rem;color:#92400E;margin-bottom:20px">⚠️ <strong>Stripe non attivo.</strong> Aggiungi STRIPE_SECRET_KEY e STRIPE_PUBLISHABLE_KEY nelle variabili d\'ambiente di Render per attivare i pagamenti.</div>'

    return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Area Riservata — ItalBandi</title>{CSS_BASE}
<style>
.ar-wrap {{ max-width:1100px;margin:32px auto;padding:0 24px 60px }}
.ar-grid {{ display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px }}
.ar-card {{ background:#fff;border:1px solid #D0DCF0;border-radius:10px;padding:20px 24px;box-shadow:0 2px 8px rgba(26,42,74,0.06) }}
.ar-card h3 {{ font-size:0.72rem;text-transform:uppercase;letter-spacing:0.1em;color:#8899AA;margin-bottom:6px }}
.ar-card .val {{ font-size:2rem;font-weight:800;color:#1A2A4A }}
.ar-card .sub {{ font-size:0.75rem;color:#8899AA;margin-top:4px }}
.ar-section {{ background:#fff;border:1px solid #D0DCF0;border-radius:10px;padding:24px;box-shadow:0 2px 8px rgba(26,42,74,0.06);margin-bottom:24px }}
.ar-section h2 {{ font-size:1rem;font-weight:700;color:#1A2A4A;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between }}
table {{ width:100%;border-collapse:collapse }}
th {{ font-size:0.7rem;text-transform:uppercase;letter-spacing:0.06em;color:#8899AA;padding:8px 12px;text-align:left;border-bottom:2px solid #EEF2F8 }}
td {{ padding:10px 12px;font-size:0.82rem;border-bottom:1px solid #EEF2F8;color:#1A2A3A }}
tr:last-child td {{ border-bottom:none }}
tr:hover td {{ background:#F8FAFF }}
.btn-ar {{ padding:7px 16px;border-radius:5px;font-size:0.8rem;font-weight:700;cursor:pointer;font-family:inherit;border:none }}
.btn-ar-primary {{ background:#1A2A4A;color:#fff }}
.btn-ar-primary:hover {{ background:#C9A84C }}
.btn-ar-gold {{ background:#C9A84C;color:#1A2A4A }}
</style>
</head><body>
{NAVBAR_LOGGED(user)}
<div class="ar-wrap">
  <h1 style="font-size:1.4rem;font-weight:800;color:#1A2A4A;margin-bottom:20px">&#9881; Area Riservata</h1>
  {stripe_banner}
  <div class="ar-grid">
    <div class="ar-card">
      <h3>Utenti totali</h3>
      <div class="val">{len(utenti)}</div>
      <div class="sub">{n_verificati} verificati · {n_non_verif} in attesa</div>
    </div>
    <div class="ar-card">
      <h3>Ricerche oggi</h3>
      <div class="val">{n_ricerche_oggi}</div>
      <div class="sub">ricerche effettuate</div>
    </div>
    <div class="ar-card">
      <h3>Pagamenti totali</h3>
      <div class="val">{n_pagamenti_totali}</div>
      <div class="sub">€{ricavi_totali/100:.2f} incassati</div>
    </div>
    <div class="ar-card">
      <h3>Cache bandi</h3>
      <div class="val" id="n-cache">...</div>
      <div class="sub">bandi in cache</div>
    </div>
  </div>
  <div class="ar-section">
    <h2>Ultime ricerche</h2>
    <table>
      <thead><tr><th>Quando</th><th>Utente</th><th>Keyword</th></tr></thead>
      <tbody>{righe_ricerche or '<tr><td colspan="3" style="color:#8899AA;text-align:center">Nessuna ricerca ancora</td></tr>'}</tbody>
    </table>
  </div>
  <div class="ar-section">
    <h2>Utenti registrati ({len(utenti)})
      <a href="/area-riservata/utenti/export" style="font-size:0.8rem;font-weight:600;color:#1A3A6A;text-decoration:none;border:1px solid #C8D4E4;padding:5px 12px;border-radius:5px">Scarica CSV</a>
    </h2>
    <div style="background:#FEF3C7;border:1px solid #F59E0B;border-radius:6px;padding:10px 14px;font-size:0.78rem;color:#92400E;margin-bottom:16px">
      Il database si svuota ad ogni deploy Render. Scarica il CSV regolarmente.
    </div>
    <table>
      <thead><tr>
        <th>Nome</th><th>Email</th><th>Azienda</th><th>Telefono</th>
        <th style="text-align:center">Verif.</th><th style="text-align:center">Ricerche</th><th>Registrato</th><th></th>
      </tr></thead>
      <tbody>{righe_html}</tbody>
    </table>
  </div>
  <div class="ar-section">
    <h2>Crea account di servizio</h2>
    <p style="font-size:0.85rem;color:#6A8AA8;margin-bottom:16px">Account senza limite di ricerche, attivi subito.</p>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:10px;align-items:end">
      <div>
        <label style="display:block;font-size:0.72rem;font-weight:600;color:#8899AA;text-transform:uppercase;margin-bottom:4px">Nome e Cognome</label>
        <input id="sv-nome" type="text" placeholder="Mario Rossi" style="width:100%;padding:8px 12px;border:1px solid #D0DCF0;border-radius:6px;font-size:0.85rem;font-family:inherit;outline:none">
      </div>
      <div>
        <label style="display:block;font-size:0.72rem;font-weight:600;color:#8899AA;text-transform:uppercase;margin-bottom:4px">Email</label>
        <input id="sv-email" type="email" placeholder="mario@esempio.it" style="width:100%;padding:8px 12px;border:1px solid #D0DCF0;border-radius:6px;font-size:0.85rem;font-family:inherit;outline:none">
      </div>
      <div>
        <label style="display:block;font-size:0.72rem;font-weight:600;color:#8899AA;text-transform:uppercase;margin-bottom:4px">Password</label>
        <input id="sv-pwd" type="text" placeholder="Password" style="width:100%;padding:8px 12px;border:1px solid #D0DCF0;border-radius:6px;font-size:0.85rem;font-family:inherit;outline:none">
      </div>
      <button onclick="creaAccountServizio()" style="padding:8px 20px;background:#1A2A4A;color:#C9A84C;border:none;border-radius:6px;font-weight:700;font-size:0.85rem;cursor:pointer">Crea account</button>
    </div>
    <div id="sv-esito" style="display:none;margin-top:12px;font-size:0.82rem;padding:8px 12px;border-radius:6px"></div>
  </div>
  <div class="ar-section">
    <h2>Azioni rapide</h2>
    <div style="display:flex;gap:12px;flex-wrap:wrap">
      <button class="btn-ar btn-ar-primary" onclick="window.location='/area-riservata/cache'">Aggiorna cache bandi</button>
      <button class="btn-ar btn-ar-gold" onclick="window.location='/area-riservata/utenti/export'">Scarica CSV utenti</button>
    </div>
  </div>
</div>
<script>
async function creaAccountServizio() {{
  const nome=document.getElementById('sv-nome').value.trim();
  const email=document.getElementById('sv-email').value.trim();
  const pwd=document.getElementById('sv-pwd').value.trim();
  const esito=document.getElementById('sv-esito');
  if (!nome||!email||!pwd) {{ esito.style.display='block'; esito.style.background='#FEF2F2'; esito.style.color='#DC2626'; esito.textContent='Compila tutti i campi.'; return; }}
  const r=await fetch('/admin/utenti/crea-servizio',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{nome,email,password:pwd}})}});
  const d=await r.json();
  if (d.ok) {{ esito.style.display='block'; esito.style.background='#F0FDF4'; esito.style.color='#15803D'; esito.textContent='Account creato per '+email; setTimeout(()=>location.reload(),1500); }}
  else {{ esito.style.display='block'; esito.style.background='#FEF2F2'; esito.style.color='#DC2626'; esito.textContent=d.error||'Errore'; }}
}}
async function assegnaRicerche(id, email, limiteAttuale) {{
  // Costruisce il dialog
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9999;display:flex;align-items:center;justify-content:center';
  overlay.innerHTML = `
    <div style="background:#fff;border-radius:10px;padding:32px;min-width:340px;box-shadow:0 8px 32px rgba(0,0,0,0.2)">
      <h3 style="color:#1A2A4A;margin-bottom:6px;font-size:1rem">Assegna ricerche</h3>
      <p style="color:#6A8AA8;font-size:0.82rem;margin-bottom:20px">${{email}}</p>
      <label style="display:flex;align-items:center;gap:10px;margin-bottom:14px;cursor:pointer">
        <input type="checkbox" id="ar-illimitato" style="width:16px;height:16px">
        <span style="font-size:0.88rem;color:#1A2A4A;font-weight:600">Ricerche illimitate</span>
      </label>
      <div id="ar-numero-wrap">
        <label style="display:block;font-size:0.78rem;font-weight:600;color:#8899AA;text-transform:uppercase;margin-bottom:4px">Numero ricerche</label>
        <input id="ar-numero" type="number" min="1" max="99999"
          value="${{limiteAttuale > 0 ? limiteAttuale : 10}}"
          style="width:100%;padding:8px 12px;border:1px solid #D0DCF0;border-radius:6px;font-size:0.92rem;outline:none">
        <p style="font-size:0.75rem;color:#8899AA;margin-top:4px">Il contatore viene azzerato automaticamente.</p>
      </div>
      <div style="display:flex;gap:10px;margin-top:20px">
        <button id="ar-ok" style="flex:1;padding:10px;background:#1A2A4A;color:#fff;border:none;border-radius:6px;font-weight:700;cursor:pointer">Salva</button>
        <button id="ar-cancel" style="padding:10px 16px;background:none;color:#6A8AA8;border:1px solid #D0DCF0;border-radius:6px;cursor:pointer">Annulla</button>
      </div>
      <div id="ar-esito" style="display:none;margin-top:10px;font-size:0.82rem;padding:8px;border-radius:5px"></div>
    </div>`;
  document.body.appendChild(overlay);

  const chk = overlay.querySelector('#ar-illimitato');
  const wrap = overlay.querySelector('#ar-numero-wrap');
  chk.addEventListener('change', () => {{ wrap.style.display = chk.checked ? 'none' : 'block'; }});
  overlay.querySelector('#ar-cancel').onclick = () => overlay.remove();

  overlay.querySelector('#ar-ok').onclick = async () => {{
    const illimitato = chk.checked;
    const numero = illimitato ? -1 : parseInt(overlay.querySelector('#ar-numero').value);
    if (!illimitato && (isNaN(numero) || numero < 1)) {{
      const es = overlay.querySelector('#ar-esito');
      es.style.display='block'; es.style.background='#FEF2F2'; es.style.color='#DC2626';
      es.textContent='Inserisci un numero valido maggiore di 0.'; return;
    }}
    const r = await fetch('/admin/utenti/' + id + '/assegna-ricerche', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{limite: numero}})
    }});
    const d = await r.json();
    if (d.ok) {{ overlay.remove(); location.reload(); }}
    else {{
      const es = overlay.querySelector('#ar-esito');
      es.style.display='block'; es.style.background='#FEF2F2'; es.style.color='#DC2626';
      es.textContent = d.error || 'Errore';
    }}
  }};
}}

async function resetRicerche(id, email) {{
  if (!confirm('Azzerare le ricerche per ' + email + '?')) return;
  const r = await fetch('/admin/utenti/' + id + '/reset-ricerche', {{method:'POST'}});
  const d = await r.json();
  if (d.ok) location.reload();
  else alert('Errore: ' + d.error);
}}
async function eliminaUtente(id, email) {{
  if (!confirm('Eliminare definitivamente ' + email + '?')) return;
  const r = await fetch('/admin/utenti/' + id, {{method:'DELETE'}});
  const d = await r.json();
  if (d.ok) location.reload();
  else alert('Errore: ' + d.error);
}}
fetch('/admin/cache/status').then(r=>r.json()).then(d=>{{
  document.getElementById('n-cache').textContent=d.totale||0;
}}).catch(()=>{{document.getElementById('n-cache').textContent='—'}});
</script>
</body></html>""")

@app.get("/area-riservata/utenti/export")
async def area_riservata_export(session_id: str = Cookie(default=None)):
    return await admin_utenti_export(session_id=session_id)

@app.get("/area-riservata/cache", response_class=HTMLResponse)
async def area_riservata_cache(session_id: str = Cookie(default=None)):
    return await admin_cache_page(session_id=session_id)

@app.get("/admin/utenti/export")
async def admin_utenti_export(session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user or not user.get("is_admin"):
        return RedirectResponse("/login")
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("SELECT id,nome,cognome,email,impresa,ruolo,telefono,verificato,created_at FROM utenti ORDER BY created_at DESC").fetchall()
    con.close()
    lines = ["ID,Nome,Cognome,Email,Azienda,Ruolo,Telefono,Verificato,Registrato"]
    for r in rows:
        lines.append(",".join(f'"{str(v or "")}"' for v in r))
    return Response(content="\n".join(lines), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=italbandi_utenti_{datetime.now().strftime('%Y%m%d')}.csv"})

@app.post("/admin/utenti/crea-servizio")
async def admin_crea_servizio(body: dict, session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user or not user.get("is_admin"):
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    nome     = body.get("nome", "").strip()
    email    = body.get("email", "").strip().lower()
    password = body.get("password", "").strip()
    if not nome or not email or not password:
        return JSONResponse({"error": "Campi mancanti"})
    parti = nome.split(' ', 1)
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute("INSERT INTO utenti (nome,cognome,email,password_hash,is_admin,verificato,account_type,ricerche_count) VALUES (?,?,?,?,0,1,'servizio',0)",
                    (parti[0], parti[1] if len(parti)>1 else '—', email, pw_hash))
        con.commit(); con.close()
        return JSONResponse({"ok": True})
    except Exception as ex:
        if "UNIQUE" in str(ex) or "unique" in str(ex):
            return JSONResponse({"error": "Email gia registrata."})
        return JSONResponse({"error": str(ex)})

@app.post("/admin/utenti/{user_id}/reset-ricerche")
async def admin_reset_ricerche(user_id: int, session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user or not user.get("is_admin"):
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    con = sqlite3.connect(DB_PATH)
    con.execute("UPDATE utenti SET ricerche_count=0 WHERE id=?", (user_id,))
    con.commit(); con.close()
    return JSONResponse({"ok": True})


@app.post("/admin/utenti/{user_id}/assegna-ricerche")
async def admin_assegna_ricerche(user_id: int, body: dict, session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user or not user.get("is_admin"):
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    limite = body.get("limite")
    if limite is None or not isinstance(limite, int):
        return JSONResponse({"error": "Parametro limite mancante o non valido"})
    if limite != -1 and limite < 1:
        return JSONResponse({"error": "Limite deve essere -1 (illimitato) o un numero >= 1"})
    try:
        con = sqlite3.connect(DB_PATH)
        # Imposta il limite e azzera il contatore
        con.execute(
            "UPDATE utenti SET ricerche_limite=?, ricerche_count=0, "
            "account_type=CASE WHEN account_type NOT IN ('servizio','pack') THEN 'custom' ELSE account_type END "
            "WHERE id=? AND is_admin=0",
            (limite, user_id)
        )
        con.commit(); con.close()
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.delete("/admin/utenti/{user_id}")
async def admin_elimina_utente(user_id: int, session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user or not user.get("is_admin"):
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM utenti WHERE id=? AND is_admin=0", (user_id,))
    con.commit(); con.close()
    return JSONResponse({"ok": True})

@app.get("/admin/cache", response_class=HTMLResponse)
async def admin_cache_page(session_id: str = Cookie(default=None)):
    user = get_session(session_id)
    if not user or not user.get("is_admin"):
        return RedirectResponse("/login")
    n = conta_cache()
    return HTMLResponse(f"""<!DOCTYPE html><html lang="it"><head>
<meta charset="UTF-8"><title>Admin Cache — ItalBandi</title>{CSS_BASE}</head><body>
{NAVBAR_LOGGED(user)}
<div class="container" style="max-width:700px;margin-top:40px">
  <h2 style="color:#C9A84C;margin-bottom:20px">Gestione Cache Bandi</h2>
  <div style="background:#0F2035;border:1px solid #1E3A5F;border-radius:8px;padding:24px;margin-bottom:20px">
    <p style="color:#A8C8E8;margin-bottom:8px">Bandi in cache: <strong style="color:#C9A84C">{n}</strong></p>
    <p style="color:#6A8AA8;font-size:0.85rem">Aggiornare la cache scarica tutte le pagine dei bandi aperti. Costo schede ridotto a 1-2 centesimi invece di 8-12.</p>
  </div>
  <button onclick="avviaCache()" id="btn-cache" style="background:#C9A84C;color:#0A1628;border:none;padding:14px 32px;border-radius:6px;font-weight:700;font-size:1rem;cursor:pointer">
    Aggiorna Cache Adesso
  </button>
  <div id="stato" style="margin-top:20px;padding:16px;background:#0F2035;border-radius:6px;display:none">
    <p id="msg" style="color:#A8C8E8;font-size:0.9rem"></p>
    <div style="margin-top:8px;height:6px;background:#1E3A5F;border-radius:3px">
      <div id="bar" style="height:6px;background:#C9A84C;border-radius:3px;width:0%;transition:width 0.5s"></div>
    </div>
  </div>
</div>
<script>
async function avviaCache() {{
  document.getElementById('btn-cache').disabled=true;
  document.getElementById('stato').style.display='block';
  document.getElementById('msg').textContent='Avvio...';
  await fetch('/admin/cache/avvia',{{method:'POST'}});
  const poll=setInterval(async()=>{{
    const r=await fetch('/admin/cache/status');
    const d=await r.json();
    document.getElementById('msg').textContent=d.messaggio;
    if (d.totale>0) document.getElementById('bar').style.width=Math.round(d.fatti/d.totale*100)+'%';
    if (!d.running) {{ clearInterval(poll); document.getElementById('btn-cache').disabled=false; setTimeout(()=>location.reload(),2000); }}
  }},2000);
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
    hit      = body.get("hit", {})
    testo_ce = body.get("testo_ce", "")
    job_id   = secrets.token_hex(8)
    JOBS[job_id] = {"status": "pending"}
    threading.Thread(target=_esegui_job, args=(job_id, hit, testo_ce), daemon=True).start()
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
