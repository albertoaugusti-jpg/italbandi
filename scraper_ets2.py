"""
scraper_ets2.py — Scraper bandi Terzo Settore / ETS
Fonti: Ministero Lavoro, CSVnet, Cantiere Terzo Settore, Fondazione Con il Sud
AI: Gemini Flash per estrazione strutturata
DB: /data/ets2.db via db_ets2.py
"""
import os, re, json, time, requests
import db_ets2 as DB

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
    "Accept-Language": "it-IT,it;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

FONTI = [
    {
        "nome": "Ministero del Lavoro — Avvisi Terzo Settore",
        "url":  "https://www.lavoro.gov.it/temi-e-priorita/Terzo-settore-e-responsabilita-sociale-delle-imprese/focus-on/Terzo-settore/Pagine/Avvisi-e-bandi.aspx",
    },
    {
        "nome": "CSVnet — Bandi per il volontariato",
        "url":  "https://www.csvnet.it/bandi",
    },
    {
        "nome": "Cantiere Terzo Settore — Bandi",
        "url":  "https://www.cantiereterzosettore.it/bandi/",
    },
    {
        "nome": "Fondazione Con il Sud — Bandi",
        "url":  "https://www.fondazioneconilsud.it/bandi/",
    },
    {
        "nome": "Impresa Sociale — Bandi e finanziamenti",
        "url":  "https://www.impresasociale.net/bandi-e-finanziamenti/",
    },
]

BANDI_FISSI = [
    {
        "titolo":      "Fondo per le Associazioni Sportive e di Promozione Sociale — CSV",
        "fonte":       "Centri Servizi Volontariato",
        "url":         "https://www.csvnet.it/bandi",
        "scadenza":    "Verificare sul portale CSV regionale",
        "beneficiari": "ODV, APS, ETS iscritte al RUNTS",
        "descrizione":  "I CSV regionali erogano contributi per progetti di volontariato e promozione sociale.",
        "dotazione":   "Variabile per CSV regionale",
        "livello":     "regionale",
        "stato":       "aperto",
    },
    {
        "titolo":      "Servizio Civile Universale — Bando ordinario 2025",
        "fonte":       "Dipartimento Politiche Giovanili",
        "url":         "https://www.scelgoilserviziocivile.gov.it",
        "scadenza":    "Verificare apertura bando",
        "beneficiari": "ETS, ODV, APS accreditate al Servizio Civile",
        "descrizione":  "Contributo per progetti di Servizio Civile Universale. Gli enti accreditati possono presentare programmi.",
        "dotazione":   "Rimborso operatori circa EUR 507/mese",
        "livello":     "nazionale",
        "stato":       "aperto",
    },
    {
        "titolo":      "5x1000 — Destinazione a ETS e APS",
        "fonte":       "Agenzia delle Entrate",
        "url":         "https://www.agenziaentrate.gov.it/portale/web/guest/schede/agevolazioni/5-per-mille",
        "scadenza":    "Iscrizione entro aprile — rendiconto entro dicembre",
        "beneficiari": "ETS iscritte al RUNTS, ODV, APS, fondazioni",
        "descrizione":  "Le organizzazioni iscritte possono ricevere la quota del 5x1000 IRPEF dai contribuenti.",
        "dotazione":   "Variabile — media nazionale EUR 8.000 per ente",
        "livello":     "nazionale",
        "stato":       "aperto",
    },
    {
        "titolo":      "Fondazione Con il Sud — Bando Communities",
        "fonte":       "Fondazione Con il Sud",
        "url":         "https://www.fondazioneconilsud.it/bandi/",
        "scadenza":    "Verificare sul sito",
        "beneficiari": "Reti di ETS nel Sud Italia",
        "descrizione":  "Sostegno a progetti di sviluppo comunitario nel Mezzogiorno tramite partnership tra ETS e soggetti privati.",
        "dotazione":   "Fino a EUR 400.000 per progetto",
        "livello":     "nazionale",
        "stato":       "aperto",
    },
    {
        "titolo":      "Avviso per il sostegno alle organizzazioni di volontariato — Ministero Lavoro",
        "fonte":       "Ministero del Lavoro e delle Politiche Sociali",
        "url":         "https://www.lavoro.gov.it/temi-e-priorita/Terzo-settore-e-responsabilita-sociale-delle-imprese",
        "scadenza":    "Verificare apertura avviso",
        "beneficiari": "ODV iscritte al RUNTS",
        "descrizione":  "Contributi per progetti di utilità sociale promossi da organizzazioni di volontariato.",
        "dotazione":   "Non specificato — verificare avviso",
        "livello":     "nazionale",
        "stato":       "aperto",
    },
]


def _fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        if r.status_code == 200:
            return r.text
        print(f"[ETS2] {r.status_code} {url}", flush=True)
    except Exception as e:
        print(f"[ETS2] fetch error {url}: {e}", flush=True)
    return ""


def _pulisci_html(html):
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>",  " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def _gemini_estrai(testo, fonte_nome):
    if not GEMINI_API_KEY or len(testo) < 100:
        return []

    prompt = f"""Sei un esperto di bandi pubblici italiani per il Terzo Settore.

Analizza questo testo dalla pagina "{fonte_nome}" e identifica TUTTI i bandi, avvisi e finanziamenti per ETS, ODV, APS, cooperative sociali, fondazioni e organizzazioni non profit.

TESTO:
{testo[:6000]}

Rispondi SOLO con un array JSON. Nessun testo prima o dopo. Nessun blocco ```json```.
Inizia direttamente con [ e termina con ].

[
  {{
    "titolo": "titolo completo del bando",
    "scadenza": "data scadenza GG/MM/AAAA oppure descrizione breve",
    "beneficiari": "chi può partecipare es. ODV APS ETS cooperative sociali",
    "descrizione": "cosa finanzia in 2 righe max",
    "dotazione": "importo o percentuale se indicato altrimenti stringa vuota",
    "livello": "europeo oppure nazionale oppure regionale",
    "stato": "aperto oppure chiuso oppure prossima_apertura"
  }}
]

Se non trovi bandi restituisci: []"""

    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=40,
        )
        if resp.status_code != 200:
            print(f"[ETS2] Gemini error {resp.status_code}", flush=True)
            return []

        raw = resp.json()
        testo_r = raw["candidates"][0]["content"]["parts"][0]["text"].strip()
        testo_r = testo_r.replace("```json", "").replace("```", "").strip()
        s = testo_r.find("[")
        e = testo_r.rfind("]") + 1
        if s == -1 or e == 0:
            return []
        return json.loads(testo_r[s:e])

    except Exception as ex:
        print(f"[ETS2] Gemini parse error: {ex}", flush=True)
        return []


def scrapa():
    DB.init()
    nuovi = 0

    # 1. Bandi fissi
    print("[ETS2] Carico bandi fissi...", flush=True)
    for b in BANDI_FISSI:
        if DB.inserisci(b):
            nuovi += 1
            print(f"  + {b['titolo'][:60]}", flush=True)

    # 2. Scraping web
    for fonte in FONTI:
        print(f"\n[ETS2] Scraping: {fonte['nome']}", flush=True)
        html = _fetch(fonte["url"])
        if not html:
            continue
        testo = _pulisci_html(html)
        bandi = _gemini_estrai(testo, fonte["nome"])
        for b in bandi:
            if not b.get("titolo") or len(b["titolo"]) < 10:
                continue
            b["fonte"] = fonte["nome"]
            b["url"]   = fonte["url"]
            if DB.inserisci(b):
                nuovi += 1
                print(f"  + {b['titolo'][:60]}", flush=True)
        time.sleep(2)

    print(f"\n[ETS2] Completato — {nuovi} nuovi bandi, totale {DB.conta()}", flush=True)
    return nuovi


if __name__ == "__main__":
    scrapa()
