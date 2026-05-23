"""
ItalBandi — main.py
Portale web con autenticazione, registrazione, privacy, cookie policy
Proprietà: Energelia S.r.l. — Responsabile privacy: Bruno Massimo Legger
"""
import os, tempfile, traceback, sqlite3, hashlib, secrets, json
from datetime import datetime, timedelta
from fastapi import FastAPI, Query, Request, Form, Cookie
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
import uvicorn

import bandi_engine as be
import energelia_scheda_engine as ENGINE

app = FastAPI(title="ItalBandi")

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
  <span class="navbar-brand">ITAL<span>BANDI</span></span>
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
  <span class="navbar-brand">ITAL<span>BANDI</span></span>
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
  <span class="navbar-brand">ITAL<span>BANDI</span></span>
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
        <div class="card-titolo">${{b.titolo}}</div>
        <span class="badge ${{b.stato.includes('prossima') ? 'badge-prossimo' : 'badge-aperto'}}">${{b.stato}}</span>
      </div>
      <div class="card-meta">
        <div class="meta-item"><label>Livello</label><span>${{b.livello}}</span></div>
        <div class="meta-item"><label>Dotazione</label><span>${{b.dotazione}}</span></div>
        <div class="meta-item"><label>Scadenza</label><span>${{b.scadenza}}</span></div>
        <div class="meta-item"><label>Destinatari</label><span>${{(b.beneficiari||'').substring(0,60)}}</span></div>
      </div>
      <div style="display:flex;align-items:center;gap:12px">
        <button class="btn-scheda" id="btn-${{b.id}}" onclick="generaScheda('${{b.id}}')">📄 Genera Scheda PDF</button>
        <span class="spinner" id="sp-${{b.id}}">⏳ Generazione in corso (30-60 sec)...</span>
      </div>
    </div>`).join('');
}}
async function generaScheda(id) {{
  const btn = document.getElementById('btn-' + id);
  const sp  = document.getElementById('sp-'  + id);
  btn.disabled = true; sp.style.display = 'inline';
  try {{
    const resp = await fetch('/api/scheda/' + encodeURIComponent(id), {{
      method: 'POST', headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{hit: _hits[id]}})
    }});
    if (!resp.ok) {{ alert('Errore: ' + (await resp.text()).substring(0,200)); return; }}
    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = 'Scheda_' + id + '.pdf';
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  }} catch(e) {{ alert('Errore: ' + e.message); }}
  finally {{ btn.disabled = false; sp.style.display = 'none'; }}
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
        return RedirectResponse("/login")
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

@app.post("/api/scheda/{bando_id}")
async def genera_scheda(bando_id: str, body: dict, session_id: str = Cookie(default=None)):
    if not get_session(session_id):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    try:
        hit = body.get("hit", {})
        content, titolo = be.genera_scheda_web(hit)
        ENGINE.CONTENT = content
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        ENGINE.generate(output_path=tmp_path, verbose=False)
        nome_file = f"Scheda_{bando_id[:30]}_{datetime.now().strftime('%Y%m%d')}.pdf"
        return FileResponse(path=tmp_path, media_type="application/pdf", filename=nome_file)
    except Exception as e:
        return JSONResponse({"error": traceback.format_exc()}, status_code=500)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
