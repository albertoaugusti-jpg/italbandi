"""
scraper_sport2.py — Scraper bandi sportivi
Fonti: Sport e Salute, CONI, CSEN
AI: Gemini Flash per estrazione strutturata
DB: /data/sport2.db via db_sport2.py
"""
import os, re, json, time, requests
import db_sport2 as DB

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
    "Accept-Language": "it-IT,it;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

FONTI = [
    {
        "nome": "Sport e Salute — Bandi",
        "url":  "https://www.sportesalute.eu/bandi-e-avvisi.html",
    },
    {
        "nome": "Sport e Salute — Bandi Europei",
        "url":  "https://www.sportesalute.eu/bandi-e-avvisi/bandi-europei.html",
    },
    {
        "nome": "Sport e Salute — Sport nei Territori",
        "url":  "https://www.sportesalute.eu/sportneiterritori/bandi-e-finanziamenti.html",
    },
    {
        "nome": "CONI — Finanziamenti",
        "url":  "https://www.coni.it/it/finanziamenti.html",
    },
    {
        "nome": "CSEN — Bandi",
        "url":  "https://www.csen.it/bandi",
    },
]

# Bandi noti sempre presenti
BANDI_FISSI = [
    {
        "titolo":      "Erasmus+ Sport — Partenariati di Cooperazione 2026",
        "fonte":       "Commissione Europea / Sport e Salute",
        "url":         "https://www.sportesalute.eu/bandi-e-avvisi/bandi-europei.html",
        "scadenza":    "05/03/2026",
        "beneficiari": "Organizzazioni sportive, enti pubblici, ASD/SSD UE",
        "descrizione": "Programma Erasmus+ per progetti transnazionali di cooperazione sportiva. Azione chiave 2.",
        "dotazione":   "EUR 2.000.000",
        "livello":     "europeo",
        "stato":       "aperto",
    },
    {
        "titolo":      "Sport di Tutti — Attività per fasce deboli",
        "fonte":       "Sport e Salute",
        "url":         "https://www.sportesalute.eu",
        "scadenza":    "Programma permanente",
        "beneficiari": "ASD e SSD che promuovono sport per persone in difficoltà economica",
        "descrizione": "Voucher per garantire accesso allo sport a bambini e ragazzi in condizioni svantaggiate.",
        "dotazione":   "Voucher da EUR 100 a EUR 300 per beneficiario",
        "livello":     "nazionale",
        "stato":       "aperto",
    },
    {
        "titolo":      "CONI — Contributi per impianti sportivi",
        "fonte":       "CONI",
        "url":         "https://www.coni.it/it/finanziamenti.html",
        "scadenza":    "Verificare sul sito CONI",
        "beneficiari": "Enti locali, ASD, SSD per costruzione e ristrutturazione impianti",
        "descrizione": "Contributi per realizzazione, ristrutturazione e messa a norma di impianti sportivi.",
        "dotazione":   "Fino al 50% del costo ammissibile",
        "livello":     "nazionale",
        "stato":       "aperto",
    },
    {
        "titolo":      "Contribuzione ordinaria Sport e Salute alle ASD/SSD",
        "fonte":       "Sport e Salute",
        "url":         "https://www.sportesalute.eu/bandi-e-avvisi.html",
        "scadenza":    "Annuale — verificare apertura",
        "beneficiari": "ASD e SSD affiliate FSN/DSA/EPS",
        "descrizione": "Contributi annuali per il sostegno all'attività sportiva di base delle associazioni affiliate.",
        "dotazione":   "Variabile per associazione",
        "livello":     "nazionale",
        "stato":       "aperto",
    },
]


def _fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        if r.status_code == 200:
            return r.text
        print(f"[SPORT2] {r.status_code} {url}", flush=True)
    except Exception as e:
        print(f"[SPORT2] fetch error {url}: {e}", flush=True)
    return ""


def _pulisci_html(html):
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>",  " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def _gemini_estrai(testo, fonte_nome):
    if not GEMINI_API_KEY or len(testo) < 100:
        return []

    prompt = f"""Sei un esperto di bandi pubblici italiani per lo sport.

Analizza questo testo dalla pagina "{fonte_nome}" e identifica TUTTI i bandi, avvisi e finanziamenti presenti.

TESTO:
{testo[:6000]}

Rispondi SOLO con un array JSON. Nessun testo prima o dopo. Nessun blocco ```json```.
Inizia direttamente con [ e termina con ].

[
  {{
    "titolo": "titolo completo del bando",
    "scadenza": "data scadenza GG/MM/AAAA oppure descrizione breve",
    "beneficiari": "chi può partecipare es. ASD SSD Comuni",
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
            print(f"[SPORT2] Gemini error {resp.status_code}", flush=True)
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
        print(f"[SPORT2] Gemini parse error: {ex}", flush=True)
        return []


def scrapa():
    DB.init()
    nuovi = 0

    # 1. Bandi fissi
    print("[SPORT2] Carico bandi fissi...", flush=True)
    for b in BANDI_FISSI:
        if DB.inserisci(b):
            nuovi += 1
            print(f"  + {b['titolo'][:60]}", flush=True)

    # 2. Scraping web
    for fonte in FONTI:
        print(f"\n[SPORT2] Scraping: {fonte['nome']}", flush=True)
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

    print(f"\n[SPORT2] Completato — {nuovi} nuovi bandi, totale {DB.conta()}", flush=True)
    return nuovi


if __name__ == "__main__":
    scrapa()
