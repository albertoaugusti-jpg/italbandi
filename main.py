"""
ItalBandi — main.py
Web app FastAPI: form HTML → genera scheda PDF Energelia → download browser
"""
import io
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse
import uvicorn

# Importa il motore PDF esistente
import energelia_scheda_engine as engine

app = FastAPI(title="ItalBandi")

# ── HTML del form ─────────────────────────────────────────────────────────────
FORM_HTML = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ItalBandi — Genera Scheda</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', Arial, sans-serif; background: #F0F4F8; color: #1F2937; }

  header {
    background: #1F4E79; color: white; padding: 20px 40px;
    display: flex; align-items: center; gap: 16px;
  }
  header h1 { font-size: 1.6rem; font-weight: 700; }
  header p  { font-size: 0.85rem; opacity: 0.8; margin-top: 2px; }

  .container { max-width: 860px; margin: 40px auto; padding: 0 20px 60px; }

  .card {
    background: white; border-radius: 10px; padding: 32px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08); margin-bottom: 24px;
  }
  .card h2 {
    font-size: 1rem; font-weight: 700; color: #1F4E79;
    border-left: 4px solid #2E75B6; padding-left: 10px;
    margin-bottom: 20px;
  }

  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
  .full   { grid-column: 1 / -1; }

  label { display: block; font-size: 0.78rem; font-weight: 600;
          color: #6B7280; text-transform: uppercase; letter-spacing: 0.04em;
          margin-bottom: 5px; }
  input, select, textarea {
    width: 100%; padding: 10px 12px; border: 1.5px solid #D1D5DB;
    border-radius: 6px; font-size: 0.92rem; color: #1F2937;
    transition: border-color 0.2s;
  }
  input:focus, select:focus, textarea:focus {
    outline: none; border-color: #2E75B6;
  }
  textarea { resize: vertical; min-height: 80px; }

  .btn-genera {
    display: block; width: 100%; padding: 16px;
    background: #1F4E79; color: white; border: none;
    border-radius: 8px; font-size: 1.05rem; font-weight: 700;
    cursor: pointer; transition: background 0.2s; margin-top: 8px;
  }
  .btn-genera:hover { background: #2E75B6; }

  .note {
    font-size: 0.78rem; color: #9CA3AF; text-align: center;
    margin-top: 12px;
  }

  footer {
    text-align: center; font-size: 0.75rem; color: #9CA3AF;
    margin-top: 40px;
  }
</style>
</head>
<body>

<header>
  <div>
    <h1>ItalBandi</h1>
    <p>Energelia S.r.l. — Generatore Schede Bandi</p>
  </div>
</header>

<div class="container">

  <form method="POST" action="/genera">

    <!-- METRICHE -->
    <div class="card">
      <h2>Dati principali</h2>
      <div class="grid-3">
        <div>
          <label>Dotazione</label>
          <input name="dotazione" placeholder="es. EUR 5.000.000" required>
        </div>
        <div>
          <label>Intensità contributo</label>
          <input name="intensita" placeholder="es. 50%">
        </div>
        <div>
          <label>Stato bando</label>
          <select name="stato">
            <option value="Aperto">Aperto</option>
            <option value="Prossima\napertura">Prossima apertura</option>
          </select>
        </div>
        <div class="full">
          <label>Apertura / Scadenza</label>
          <input name="apertura_scadenza" placeholder="es. 01/06/2026 — 31/12/2026">
        </div>
      </div>
    </div>

    <!-- INTESTAZIONE -->
    <div class="card">
      <h2>Intestazione bando</h2>
      <div style="display:grid; gap:16px;">
        <div>
          <label>Titolo bando *</label>
          <input name="titolo" placeholder="Titolo completo del bando" required>
        </div>
        <div class="grid-2">
          <div>
            <label>Livello geografico</label>
            <input name="livello" placeholder="es. Regione / Ente locale · Lombardia">
          </div>
          <div>
            <label>Stato bando (etichetta)</label>
            <input name="stato_label" placeholder="es. Bandi aperti · Bandi prossima apertura">
          </div>
        </div>
      </div>
    </div>

    <!-- CONTENUTO SINISTRO -->
    <div class="card">
      <h2>Colonna sinistra</h2>
      <div style="display:grid; gap:16px;">
        <div>
          <label>Ente / Finalità</label>
          <textarea name="ente_finalita" placeholder="Un punto per riga. Es:&#10;Camera di Commercio di Bergamo&#10;Finalità del bando..."></textarea>
        </div>
        <div>
          <label>Chi può partecipare</label>
          <textarea name="chi_partecipa" placeholder="Un punto per riga"></textarea>
        </div>
        <div>
          <label>Cosa è finanziabile</label>
          <textarea name="cosa_finanziabile" placeholder="Un punto per riga"></textarea>
        </div>
        <div>
          <label>Spese non ammissibili</label>
          <textarea name="spese_non_ammissibili" placeholder="Un punto per riga"></textarea>
        </div>
      </div>
    </div>

    <!-- CONTENUTO DESTRO -->
    <div class="card">
      <h2>Colonna destra</h2>
      <div style="display:grid; gap:16px;">
        <div>
          <label>Contributo / Intensità (dettaglio)</label>
          <textarea name="contributo_dettaglio" placeholder="Un punto per riga"></textarea>
        </div>
        <div>
          <label>Criteri / Valutazione</label>
          <textarea name="criteri" placeholder="Un punto per riga"></textarea>
        </div>
        <div>
          <label>Fasi e Tempi</label>
          <textarea name="fasi_tempi" placeholder="Un punto per riga"></textarea>
        </div>
        <div>
          <label>Come presentare</label>
          <textarea name="come_presentare" placeholder="Un punto per riga"></textarea>
        </div>
      </div>
    </div>

    <!-- BOX FINALI -->
    <div class="card">
      <h2>Box finali</h2>
      <div style="display:grid; gap:16px;">
        <div>
          <label>✅ Perché è interessante (punti di forza)</label>
          <textarea name="punti_forza" placeholder="Un punto per riga"></textarea>
        </div>
        <div>
          <label>⚠️ Criticità e attenzioni</label>
          <textarea name="criticita" placeholder="Un punto per riga"></textarea>
        </div>
        <div>
          <label>Fonte URL (opzionale)</label>
          <input name="fonte_url" placeholder="https://www.contributieuropa.com/bandi/...">
        </div>
      </div>
    </div>

    <button type="submit" class="btn-genera">📄 Genera Scheda PDF</button>
    <p class="note">Il PDF verrà scaricato automaticamente nel tuo browser.</p>

  </form>
</div>

<footer>
  Energelia S.r.l. · Largo XII Ottobre 1/3, Torre WTC · 16121 Genova · www.energelia.it
</footer>

</body>
</html>"""


def _split(text: str) -> list:
    """Converte testo multiriga in lista di bullet."""
    if not text or not text.strip():
        return []
    return [line.strip() for line in text.strip().splitlines() if line.strip()]


@app.get("/", response_class=HTMLResponse)
async def index():
    return FORM_HTML


@app.post("/genera")
async def genera(
    titolo:                str = Form(""),
    livello:               str = Form(""),
    stato_label:           str = Form(""),
    dotazione:             str = Form(""),
    intensita:             str = Form(""),
    stato:                 str = Form("Aperto"),
    apertura_scadenza:     str = Form(""),
    ente_finalita:         str = Form(""),
    chi_partecipa:         str = Form(""),
    cosa_finanziabile:     str = Form(""),
    spese_non_ammissibili: str = Form(""),
    contributo_dettaglio:  str = Form(""),
    criteri:               str = Form(""),
    fasi_tempi:            str = Form(""),
    come_presentare:       str = Form(""),
    punti_forza:           str = Form(""),
    criticita:             str = Form(""),
    fonte_url:             str = Form(""),
):
    # Costruisce il dizionario CONTENT compatibile con il motore
    stato_bg = "blue" if "prossima" in stato.lower() else "orange"
    mese_anno = datetime.now().strftime("%B %Y").capitalize()

    content = {
        "titolo":      titolo.upper(),
        "sottotitolo": f"{livello or 'Regione / Ente locale'} · {stato_label or ('Bandi aperti' if stato == 'Aperto' else 'Bandi prossima apertura')}",

        "metriche": [
            {"label": "DOTAZIONE",             "valore": dotazione or "—",         "bg": "blue"},
            {"label": "INTENSITÀ CONTRIBUTO",  "valore": intensita or "—",         "bg": "orange"},
            {"label": "STATO",                 "valore": stato,                    "bg": stato_bg},
            {"label": "APERTURA / SCADENZA",   "valore": apertura_scadenza or "—", "bg": "blue"},
        ],

        "sinistra": [
            {"titolo": "ENTE / FINALITÀ",        "voci": _split(ente_finalita)      or ["—"]},
            {"titolo": "CHI PUÒ PARTECIPARE",    "voci": _split(chi_partecipa)      or ["—"]},
            {"titolo": "COSA È FINANZIABILE",    "voci": _split(cosa_finanziabile)  or ["—"]},
            {"titolo": "SPESE NON AMMISSIBILI",  "voci": _split(spese_non_ammissibili) or ["—"]},
        ],

        "tabella_contributi": None,

        "destra": [
            {"titolo": "CONTRIBUTO / INTENSITÀ", "voci": _split(contributo_dettaglio) or ["—"]},
            {"titolo": "CRITERI / VALUTAZIONE",  "voci": _split(criteri)            or ["—"]},
            {"titolo": "FASI E TEMPI",           "voci": _split(fasi_tempi)         or ["—"]},
            {"titolo": "COME PRESENTARE",        "voci": _split(come_presentare)    or ["—"]},
        ],

        "punti_forza": _split(punti_forza) or ["Da definire"],
        "criticita":   _split(criticita)   or ["Da definire"],

        "cta_testo": f"Questo bando fa al caso tuo? Contattaci ora!",
        "cta_tel":   "Tel. 010 8078800",
        "cta_email": "a.augusti@energelia.it",

        "fonte":     f"Fonte: {fonte_url}" if fonte_url else f"Fonte: Energelia S.r.l.",
        "mese_anno": mese_anno,
    }

    # Inietta CONTENT nel motore e genera il PDF in un file temporaneo
    engine.CONTENT = content

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    engine.generate(output_path=tmp_path, verbose=False)

    # Nome file pulito dal titolo
    nome_file = titolo[:50].strip().replace(" ", "_").replace("/", "-") or "scheda_bando"
    nome_file = f"Scheda_{nome_file}_{datetime.now().strftime('%Y%m%d')}.pdf"

    return FileResponse(
        path=tmp_path,
        media_type="application/pdf",
        filename=nome_file,
        background=None,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
