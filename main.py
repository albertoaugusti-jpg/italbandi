"""
ItalBandi — main.py
Portale web: ricerca bandi Algolia → genera scheda PDF con Claude
"""
import os, tempfile, traceback
from datetime import datetime
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import uvicorn

import bandi_engine as be
import energelia_scheda_engine as engine

app = FastAPI(title="ItalBandi")

REGIONI = [
    "Abruzzo","Basilicata","Calabria","Campania","Emilia-Romagna",
    "Friuli-Venezia-Giulia","Lazio","Liguria","Lombardia","Marche",
    "Molise","Piemonte","Puglia","Sardegna","Sicilia","Toscana",
    "Trentino-Alto-Adige","Umbria","Valle d'Aosta","Veneto",
]

# ── Pagina principale ─────────────────────────────────────────────────────────
INDEX_HTML = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ItalBandi — Bandi e Incentivi per le Imprese</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; background: #F0F4F8; color: #1F2937; }

header { background: #1F4E79; color: white; padding: 18px 40px; display: flex; align-items: center; gap: 16px; }
header h1 { font-size: 1.7rem; font-weight: 800; letter-spacing: -0.5px; }
header p  { font-size: 0.85rem; opacity: 0.75; margin-top: 3px; }

.search-bar {
  background: #2E75B6; padding: 24px 40px; display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end;
}
.search-bar input, .search-bar select {
  padding: 10px 14px; border: none; border-radius: 6px;
  font-size: 0.92rem; color: #1F2937;
}
.search-bar input { flex: 1; min-width: 200px; }
.search-bar select { min-width: 150px; }
.btn-cerca {
  padding: 10px 28px; background: #F59E0B; color: #1F2937;
  border: none; border-radius: 6px; font-weight: 700; font-size: 0.95rem; cursor: pointer;
}
.btn-cerca:hover { background: #FBBF24; }

.container { max-width: 1000px; margin: 32px auto; padding: 0 20px 60px; }

.risultati-header {
  font-size: 0.85rem; color: #6B7280; margin-bottom: 16px; font-weight: 600;
}

.bando-card {
  background: white; border-radius: 10px; padding: 20px 24px;
  box-shadow: 0 1px 6px rgba(0,0,0,0.07); margin-bottom: 14px;
  border-left: 4px solid #2E75B6;
}
.bando-card:hover { box-shadow: 0 3px 14px rgba(0,0,0,0.12); }

.card-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.card-titolo {
  font-size: 0.95rem; font-weight: 700; color: #1F4E79;
  cursor: pointer; flex: 1; line-height: 1.4;
}
.card-titolo:hover { color: #2E75B6; text-decoration: underline; }

.badge {
  font-size: 0.7rem; font-weight: 700; padding: 3px 10px; border-radius: 20px;
  white-space: nowrap;
}
.badge-aperto   { background: #D1FAE5; color: #065F46; }
.badge-prossimo { background: #DBEAFE; color: #1E40AF; }

.card-meta { display: flex; gap: 24px; margin-top: 10px; flex-wrap: wrap; }
.meta-item label { display: block; font-size: 0.68rem; font-weight: 700; color: #9CA3AF;
                   text-transform: uppercase; letter-spacing: 0.04em; }
.meta-item span  { font-size: 0.82rem; color: #374151; font-weight: 500; }

.btn-scheda {
  display: inline-block; margin-top: 14px;
  padding: 8px 20px; background: #1F4E79; color: white;
  border: none; border-radius: 6px; font-size: 0.85rem; font-weight: 700;
  cursor: pointer; text-decoration: none;
}
.btn-scheda:hover { background: #2E75B6; }
.btn-scheda:disabled { background: #9CA3AF; cursor: not-allowed; }

.spinner { display: none; margin-left: 10px; font-size: 0.8rem; color: #6B7280; }

footer { text-align: center; font-size: 0.75rem; color: #9CA3AF; margin-top: 40px; }

.loader { text-align: center; padding: 40px; color: #6B7280; }
</style>
</head>
<body>

<header>
  <div>
    <h1>ItalBandi</h1>
    <p>Energelia S.r.l. — Trova il bando giusto, scarica la scheda PDF professionale</p>
  </div>
</header>

<div class="search-bar">
  <input id="keyword" type="text" placeholder="Parola chiave (es. formazione, energia, PMI...)">
  <select id="stato">
    <option value="aperto">Bandi aperti</option>
    <option value="prossimo">Prossima apertura</option>
    <option value="tutti">Tutti</option>
  </select>
  <select id="livello">
    <option value="">Tutti i livelli</option>
    <option value="europeo">Europeo</option>
    <option value="nazionale">Nazionale</option>
    <option value="regionale">Regionale</option>
  </select>
  <select id="regione">
    <option value="">Tutte le regioni</option>
    <option>Abruzzo</option><option>Basilicata</option><option>Calabria</option>
    <option>Campania</option><option>Emilia-Romagna</option><option>Friuli-Venezia-Giulia</option>
    <option>Lazio</option><option>Liguria</option><option>Lombardia</option>
    <option>Marche</option><option>Molise</option><option>Piemonte</option>
    <option>Puglia</option><option>Sardegna</option><option>Sicilia</option>
    <option>Toscana</option><option>Trentino-Alto-Adige</option><option>Umbria</option>
    <option>Valle d'Aosta</option><option>Veneto</option>
  </select>
  <button class="btn-cerca" onclick="cerca()">🔍 Cerca</button>
</div>

<div class="container">
  <div id="risultati-header" class="risultati-header"></div>
  <div id="risultati"></div>
</div>

<footer>Energelia S.r.l. · Largo XII Ottobre 1/3, Torre WTC · 16121 Genova · Tel. 010 8078800 · www.energelia.it</footer>

<script>
let _hits = {};

async function cerca() {
  const kw      = document.getElementById('keyword').value;
  const stato   = document.getElementById('stato').value;
  const livello = document.getElementById('livello').value;
  const regione = document.getElementById('regione').value;

  document.getElementById('risultati').innerHTML = '<div class="loader">Ricerca in corso...</div>';
  document.getElementById('risultati-header').textContent = '';

  const params = new URLSearchParams({keyword: kw, stato, livello, regione});
  const resp   = await fetch('/api/cerca?' + params);
  const data   = await resp.json();

  if (data.error) {
    document.getElementById('risultati').innerHTML = `<p style="color:red">${data.error}</p>`;
    return;
  }

  document.getElementById('risultati-header').textContent =
    `${data.totale} bandi trovati — clicca il titolo per i dettagli, poi scarica la scheda PDF`;

  _hits = {};
  data.bandi.forEach(b => { _hits[b.id] = b._hit; });

  document.getElementById('risultati').innerHTML = data.bandi.map(b => `
    <div class="bando-card">
      <div class="card-top">
        <div class="card-titolo" onclick="toggleDettaglio('${b.id}')">${b.titolo}</div>
        <span class="badge ${b.stato.includes('prossima') ? 'badge-prossimo' : 'badge-aperto'}">${b.stato}</span>
      </div>
      <div class="card-meta">
        <div class="meta-item"><label>Livello</label><span>${b.livello}</span></div>
        <div class="meta-item"><label>Dotazione</label><span>${b.dotazione}</span></div>
        <div class="meta-item"><label>Scadenza</label><span>${b.scadenza}</span></div>
        <div class="meta-item"><label>Destinatari</label><span>${b.beneficiari.substring(0,60)}</span></div>
      </div>
      <div id="det-${b.id}" style="display:none; margin-top:14px; padding-top:12px; border-top:1px solid #E5E7EB;">
        <p style="font-size:0.82rem; color:#6B7280;">Clicca il pulsante per generare la scheda PDF completa.</p>
      </div>
      <div style="display:flex; align-items:center; gap:12px; margin-top:12px;">
        <button class="btn-scheda" id="btn-${b.id}" onclick="generaScheda('${b.id}', '${escapeTitle(b.titolo)}')">
          📄 Genera Scheda PDF
        </button>
        <span class="spinner" id="sp-${b.id}">⏳ Generazione in corso (30-60 sec)...</span>
      </div>
    </div>
  `).join('');
}

function escapeTitle(t) {
  return t.replace(/'/g, "\\'").replace(/"/g, '&quot;').substring(0, 80);
}

function toggleDettaglio(id) {
  const det = document.getElementById('det-' + id);
  det.style.display = det.style.display === 'none' ? 'block' : 'none';
}

async function generaScheda(id, titolo) {
  const btn = document.getElementById('btn-' + id);
  const sp  = document.getElementById('sp-'  + id);
  btn.disabled = true;
  sp.style.display = 'inline';

  try {
    const resp = await fetch('/api/scheda/' + encodeURIComponent(id), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({hit: _hits[id]})
    });

    if (!resp.ok) {
      const err = await resp.text();
      alert('Errore generazione: ' + err.substring(0, 200));
      return;
    }

    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'Scheda_' + id + '.pdf';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch(e) {
    alert('Errore: ' + e.message);
  } finally {
    btn.disabled = false;
    sp.style.display = 'none';
  }
}

// Cerca subito al caricamento con i bandi aperti
window.onload = cerca;
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return INDEX_HTML


@app.get("/api/cerca")
async def cerca(
    keyword: str = Query(""),
    stato:   str = Query("aperto"),
    livello: str = Query(""),
    regione: str = Query(""),
    provincia: str = Query(""),
):
    try:
        hits, totale = be.cerca_bandi(
            keyword=keyword, stato=stato,
            livello=livello, regione=regione,
            provincia=provincia, max_hits=50
        )
        bandi = [be.hit_to_card(h) for h in hits]
        return JSONResponse({"bandi": bandi, "totale": totale})
    except Exception as e:
        return JSONResponse({"error": str(e), "bandi": [], "totale": 0})


@app.post("/api/scheda/{bando_id}")
async def genera_scheda(bando_id: str, body: dict):
    try:
        hit    = body.get("hit", {})
        titolo = hit.get("post_title") or hit.get("title") or bando_id

        # Recupera testo dalla pagina ContributiEuropa
        fonte_url, testo = be.get_testo_bando(hit)

        # Costruisce il CONTENT con Claude
        content = be.build_content(titolo, hit, testo, fonte_url)

        # Genera il PDF
        engine.CONTENT = content
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        engine.generate(output_path=tmp_path, verbose=False)

        nome_file = f"Scheda_{bando_id[:30]}_{datetime.now().strftime('%Y%m%d')}.pdf"
        return FileResponse(path=tmp_path, media_type="application/pdf", filename=nome_file)

    except Exception as e:
        return JSONResponse({"error": traceback.format_exc()}, status_code=500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
