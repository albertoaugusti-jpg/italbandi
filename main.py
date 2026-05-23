#!/usr/bin/env python3
"""
ItalBandi Web App - FastAPI
Form per compilare i dati di un bando → genera PDF tramite energelia_scheda_engine.py
"""

from fastapi import FastAPI, Form
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import io
import os
from datetime import datetime
import energelia_scheda_engine as engine

app = FastAPI()

# ─────────────────────────────────────────────────────────────────────────────
# HTML FORM
# ─────────────────────────────────────────────────────────────────────────────

HTML_FORM = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ItalBandi - Generatore Schede</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }

        .container {
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 900px;
            width: 100%;
            padding: 50px;
        }

        h1 {
            color: #2d3748;
            margin-bottom: 10px;
            font-size: 32px;
        }

        .subtitle {
            color: #718096;
            margin-bottom: 40px;
            font-size: 16px;
        }

        .form-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
            margin-bottom: 30px;
        }

        .form-grid.full {
            grid-template-columns: 1fr;
        }

        .form-group {
            display: flex;
            flex-direction: column;
        }

        label {
            color: #2d3748;
            font-weight: 600;
            margin-bottom: 8px;
            font-size: 14px;
        }

        input, textarea, select {
            padding: 12px;
            border: 2px solid #e2e8f0;
            border-radius: 6px;
            font-size: 14px;
            font-family: inherit;
            transition: border-color 0.3s;
        }

        input:focus, textarea:focus, select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        textarea {
            resize: vertical;
            min-height: 80px;
        }

        .button-group {
            display: flex;
            gap: 12px;
            margin-top: 40px;
        }

        button {
            flex: 1;
            padding: 14px 24px;
            font-size: 16px;
            font-weight: 600;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.3s;
        }

        .btn-genera {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }

        .btn-genera:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(102, 126, 234, 0.3);
        }

        .btn-genera:active {
            transform: translateY(0);
        }

        .btn-reset {
            background: #e2e8f0;
            color: #4a5568;
        }

        .btn-reset:hover {
            background: #cbd5e0;
        }

        .info {
            background: #edf2f7;
            color: #2d3748;
            padding: 16px;
            border-radius: 6px;
            margin-bottom: 30px;
            font-size: 14px;
            line-height: 1.6;
        }

        .info strong {
            color: #667eea;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 ItalBandi</h1>
        <p class="subtitle">Generatore di Schede Bandi in PDF</p>

        <div class="info">
            <strong>Istruzioni:</strong> Compila tutti i campi sottostanti. Il sistema genererà automaticamente una scheda PDF bella e professionale con i tuoi dati.
        </div>

        <form method="POST" action="/genera" id="bandoForm">
            <!-- RIGA 1: Titolo e Ente -->
            <div class="form-grid">
                <div class="form-group">
                    <label for="titolo">Titolo del Bando *</label>
                    <input type="text" id="titolo" name="titolo" placeholder="Es. BANDO DISTRETTI DEL COMMERCIO 2026" required>
                </div>
                <div class="form-group">
                    <label for="ente">Ente Erogatore *</label>
                    <input type="text" id="ente" name="ente" placeholder="Es. Regione Lombardia" required>
                </div>
            </div>

            <!-- RIGA 2: Regione e Dotazione -->
            <div class="form-grid">
                <div class="form-group">
                    <label for="regione">Regione *</label>
                    <input type="text" id="regione" name="regione" placeholder="Es. Lombardia" required>
                </div>
                <div class="form-group">
                    <label for="dotazione">Dotazione Totale *</label>
                    <input type="text" id="dotazione" name="dotazione" placeholder="Es. EUR 63.000.000" required>
                </div>
            </div>

            <!-- RIGA 3: Intensità e Stato -->
            <div class="form-grid">
                <div class="form-group">
                    <label for="intensita">Intensità Contributo *</label>
                    <input type="text" id="intensita" name="intensita" placeholder="Es. 80% del costo" required>
                </div>
                <div class="form-group">
                    <label for="stato">Stato del Bando *</label>
                    <select id="stato" name="stato" required>
                        <option value="">-- Seleziona --</option>
                        <option value="Aperto">Aperto</option>
                        <option value="Prossima apertura">Prossima apertura</option>
                        <option value="Chiuso">Chiuso</option>
                        <option value="In valutazione">In valutazione</option>
                    </select>
                </div>
            </div>

            <!-- RIGA 4: Data scadenza -->
            <div class="form-grid">
                <div class="form-group">
                    <label for="scadenza">Data Scadenza (opzionale)</label>
                    <input type="date" id="scadenza" name="scadenza">
                </div>
            </div>

            <!-- RIGA 5: Descrizione generale -->
            <div class="form-grid full">
                <div class="form-group">
                    <label for="descrizione">Descrizione Generale *</label>
                    <textarea id="descrizione" name="descrizione" placeholder="Descrivi brevemente l'obiettivo e il contesto del bando..." required></textarea>
                </div>
            </div>

            <!-- RIGA 6: Chi può partecipare -->
            <div class="form-grid full">
                <div class="form-group">
                    <label for="destinatari">Chi Può Partecipare *</label>
                    <textarea id="destinatari" name="destinatari" placeholder="Enti pubblici, MPMI, Associazioni..." required></textarea>
                </div>
            </div>

            <!-- RIGA 7: Cosa è finanziabile -->
            <div class="form-grid full">
                <div class="form-group">
                    <label for="finanziabile">Cosa È Finanziabile *</label>
                    <textarea id="finanziabile" name="finanziabile" placeholder="Immobili, opere, impianti, servizi, consulenze..." required></textarea>
                </div>
            </div>

            <!-- PULSANTI -->
            <div class="button-group">
                <button type="submit" class="btn-genera">📄 Genera Scheda PDF</button>
                <button type="reset" class="btn-reset">🔄 Cancella</button>
            </div>
        </form>
    </div>

    <script>
        document.getElementById('bandoForm').addEventListener('submit', function(e) {
            const btn = document.querySelector('.btn-genera');
            btn.disabled = true;
            btn.textContent = '⏳ Generazione in corso...';
        });
    </script>
</body>
</html>
"""

# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: GET / (mostra form)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def get_form():
    """Mostra il form per compilare i dati del bando."""
    return HTML_FORM


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT: POST /genera (genera PDF)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/genera")
def genera_scheda(
    titolo: str = Form(...),
    ente: str = Form(...),
    regione: str = Form(...),
    dotazione: str = Form(...),
    intensita: str = Form(...),
    stato: str = Form(...),
    scadenza: str = Form(None),
    descrizione: str = Form(...),
    destinatari: str = Form(...),
    finanziabile: str = Form(...),
):
    """
    Raccoglie i dati dal form, li passa al motore PDF e restituisce il PDF come download.
    """

    # Costruisci il dizionario CONTENT con i dati del form
    content_data = {
        "titolo": titolo,
        "sottotitolo": f"{ente} · {regione} · {stato}",
        "metriche": [
            {"label": "DOTAZIONE TOTALE", "valore": dotazione, "bg": "blue"},
            {"label": "INTENSITÀ", "valore": intensita, "bg": "green"},
            {"label": "REGIONE", "valore": regione, "bg": "orange"},
            {"label": "STATO", "valore": stato, "bg": "blue"},
        ],
        "sinistra": [
            {
                "titolo": "ENTE / FINALITÀ",
                "voci": [
                    f"<b>Ente:</b> {ente}",
                    descrizione,
                ],
            },
            {
                "titolo": "CHI PUÒ PARTECIPARE",
                "voci": [destinatari],
            },
            {
                "titolo": "COSA È FINANZIABILE",
                "voci": [finanziabile],
            },
        ],
        "destra": [
            {
                "titolo": "DETTAGLI BANDO",
                "voci": [
                    f"<b>Intensità contributo:</b> {intensita}",
                    f"<b>Stato:</b> {stato}",
                    f"<b>Regione:</b> {regione}",
                ] + ([f"<b>Scadenza:</b> {scadenza}"] if scadenza else []),
            },
        ],
        "punti_forza": [
            "Finanziamento disponibile",
            "Procedura valutativa trasparente",
            "Contributo significativo",
        ],
        "criticita": [
            "Verificare i requisiti di ammissibilità",
            "Rispettare le tempistiche",
            "Consultare il bando ufficiale",
        ],
        "cta_testo": f"Sei interessato al {titolo}?",
        "cta_tel": "Tel. 010 8078800",
        "cta_email": "info@energelia.it",
        "fonte": "Fonte: Dati inseriti via ItalBandi Web App",
        "mese_anno": datetime.now().strftime("%B %Y"),
    }

    # Salva il CONTENT originale
    original_content = engine.CONTENT.copy()

    try:
        # Aggiorna CONTENT con i dati del form
        engine.CONTENT.update(content_data)

        # Genera il PDF in memoria
        pdf_buffer = io.BytesIO()
        engine.generate(output_path=pdf_buffer, verbose=False)
        pdf_buffer.seek(0)

        # Restituisce il PDF come download
        return FileResponse(
            io.BytesIO(pdf_buffer.getvalue()),
            media_type="application/pdf",
            filename=f"scheda_{titolo.lower().replace(' ', '_')[:30]}.pdf"
        )

    finally:
        # Ripristina il CONTENT originale (thread-safety)
        engine.CONTENT = original_content


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
