"""
scraper_sport.py — Raccoglie bandi sportivi da Sport e Salute + CONI
Salva in /data/bandi_sport.db (SQLite persistente)
Chiamare direttamente: python scraper_sport.py
Oppure via endpoint admin: POST /admin/scraper/sport
"""
import sqlite3, hashlib, re, json, os, time, requests
from datetime import datetime

DB_SPORT = "/data/bandi_sport.db"
ANTHROPIC_API_KEY = os.environ.get("CLAUDE_API_KEY", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

FONTI_SPORT = [
    {
        "nome": "Sport e Salute — Bandi e Avvisi",
        "url": "https://www.sportesalute.eu/bandi-e-avvisi.html",
        "tipo": "html",
    },
    {
        "nome": "Sport e Salute — Bandi Europei",
        "url": "https://www.sportesalute.eu/bandi-e-avvisi/bandi-europei.html",
        "tipo": "html",
    },
    {
        "nome": "Sport e Salute — Sport nei Territori",
        "url": "https://www.sportesalute.eu/sportneiterritori/bandi-e-finanziamenti.html",
        "tipo": "html",
    },
    {
        "nome": "CONI — Finanziamenti",
        "url": "https://www.coni.it/it/finanziamenti.html",
        "tipo": "html",
    },
]

BANDI_FISSI_SPORT = [
    {
        "titolo": "Contribuzione Ordinaria Sport e Salute alle ASD/SSD 2025",
        "scadenza": "Domanda entro 31/03/2025",
        "beneficiari": "Associazioni e Società Sportive Dilettantistiche affiliate FSN/DSA/EPS",
        "descrizione": "Contributi annuali di Sport e Salute S.p.A. per il sostegno all'attività sportiva di base delle ASD e SSD affiliate agli enti riconosciuti.",
        "dotazione": "Variabile per associazione — budget totale €796.340",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "Sport e Salute",
        "url": "https://www.sportesalute.eu/bandi-e-avvisi.html",
    },
    {
        "titolo": "Sport Illumina — Playground in aree pubbliche",
        "scadenza": "Domanda aperta — verificare sul portale",
        "beneficiari": "Comuni, Enti locali, ASD/SSD",
        "descrizione": "Avviso pubblico per la realizzazione di playground sportivi in aree pubbliche di libero accesso. Progetto promosso da Sport e Salute.",
        "dotazione": "Non specificato — contributo a fondo perduto",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "Sport e Salute",
        "url": "https://www.sportesalute.eu/bandi-e-avvisi.html",
    },
    {
        "titolo": "Erasmus+ Sport — Partenariati di Cooperazione 2026",
        "scadenza": "05/03/2026",
        "beneficiari": "Organizzazioni sportive, enti pubblici, associazioni attive nel settore sportivo UE",
        "descrizione": "Programma europeo Erasmus+ per progetti transnazionali di cooperazione nel settore sportivo. Azione chiave 2 — Cooperazione tra organizzazioni.",
        "dotazione": "Budget complessivo €2.000.000",
        "livello": "europeo",
        "stato": "aperto",
        "fonte": "Commissione Europea / Sport e Salute",
        "url": "https://www.sportesalute.eu/bandi-e-avvisi/bandi-europei.html",
    },
    {
        "titolo": "Voucher per lo Sport — Regione Lazio",
        "scadenza": "Verificare sul portale regionale",
        "beneficiari": "ASD, SSD, ETS di ambito sportivo operanti nel Lazio",
        "descrizione": "Voucher per l'accesso allo sport destinati a cittadini in condizioni di disagio economico. Le associazioni ricevono i voucher dai beneficiari.",
        "dotazione": "Non specificato",
        "livello": "regionale",
        "stato": "aperto",
        "fonte": "Sport e Salute / Regione Lazio",
        "url": "https://www.sportesalute.eu/bandi-e-avvisi.html",
    },
    {
        "titolo": "CONI — Contributi per l'impiantistica sportiva",
        "scadenza": "Verificare sul sito CONI",
        "beneficiari": "Enti locali, ASD, SSD per costruzione e ristrutturazione impianti",
        "descrizione": "Il CONI eroga contributi per la realizzazione, ristrutturazione e messa a norma di impianti sportivi su tutto il territorio nazionale.",
        "dotazione": "Variabile — fino al 50% del costo ammissibile",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "CONI",
        "url": "https://www.coni.it/it/finanziamenti.html",
    },
    {
        "titolo": "Sport di Tutti — Attività sportiva per fasce deboli",
        "scadenza": "Programma permanente",
        "beneficiari": "ASD e SSD che promuovono sport per persone in difficoltà economica",
        "descrizione": "Programma di Sport e Salute per garantire l'accesso allo sport a bambini e ragazzi in condizioni svantaggiate tramite voucher e contributi diretti.",
        "dotazione": "Voucher da €100 a €300 per beneficiario",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "Sport e Salute",
        "url": "https://www.sportesalute.eu",
    },
]


def init_db():
    con = sqlite3.connect(DB_SPORT)
    con.execute("""CREATE TABLE IF NOT EXISTS bandi_sport (
        id           TEXT PRIMARY KEY,
        titolo       TEXT NOT NULL,
        fonte        TEXT,
        url          TEXT,
        scadenza     TEXT,
        beneficiari  TEXT,
        descrizione  TEXT,
        dotazione    TEXT,
        settore      TEXT DEFAULT 'Sport',
        livello      TEXT DEFAULT 'nazionale',
        stato        TEXT DEFAULT 'aperto',
        testo_grezzo TEXT,
        scheda_json  TEXT,
        aggiornato   TEXT
    )""")
    con.commit()
    con.close()
    print("[SPORT DB] inizializzato", flush=True)


def _hash(titolo, url):
    return hashlib.md5(f"{titolo}{url}".encode()).hexdigest()[:16]


def _pulisci_html(html):
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', html).strip()


def _fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        if r.status_code == 200:
            return r.text
        print(f"[FETCH] {r.status_code} {url}", flush=True)
    except Exception as e:
        print(f"[FETCH ERR] {url}: {e}", flush=True)
    return ""


def _estrai_bandi_da_testo(testo, fonte_nome, fonte_url):
    """Usa Claude Haiku per estrarre i bandi strutturati dal testo della pagina."""
    if not ANTHROPIC_API_KEY or len(testo) < 100:
        return []

    prompt = f"""Sei un esperto di bandi pubblici italiani per lo sport.

Analizza questo testo estratto dalla pagina "{fonte_nome}" e identifica TUTTI i bandi/avvisi presenti.

TESTO:
{testo[:6000]}

Per ogni bando trovato restituisci un oggetto JSON. Rispondi SOLO con un array JSON, nient'altro:
[
  {{
    "titolo": "titolo completo del bando",
    "scadenza": "data scadenza in formato GG/MM/AAAA o 'non specificata'",
    "beneficiari": "chi può partecipare (es: ASD, SSD, ETS, Comuni)",
    "descrizione": "breve descrizione in 2 righe massimo",
    "dotazione": "importo totale o contributo massimo se indicato, altrimenti 'non specificato'",
    "livello": "europeo|nazionale|regionale",
    "stato": "aperto|chiuso|prossima_apertura"
  }}
]

Se non trovi bandi restituisci: []"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=40
        )
        blocks = resp.json().get("content", [])
        testo_out = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        raw = re.sub(r'```(?:json)?\s*', '', testo_out)
        raw = re.sub(r'```', '', raw).strip()
        s = raw.find('[')
        e = raw.rfind(']')
        if s != -1 and e != -1:
            return json.loads(raw[s:e+1])
    except Exception as ex:
        print(f"[AI ERR] {ex}", flush=True)
    return []


def salva_bando(bando, fonte_nome, fonte_url):
    bid = _hash(bando.get("titolo", ""), fonte_url)
    con = sqlite3.connect(DB_SPORT)
    esiste = con.execute("SELECT id FROM bandi_sport WHERE id=?", (bid,)).fetchone()
    if esiste:
        con.close()
        return False  # già presente
    con.execute("""INSERT INTO bandi_sport
        (id, titolo, fonte, url, scadenza, beneficiari, descrizione,
         dotazione, livello, stato, aggiornato)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
        bid,
        bando.get("titolo", "")[:500],
        fonte_nome,
        fonte_url,
        bando.get("scadenza", "non specificata"),
        bando.get("beneficiari", ""),
        bando.get("descrizione", ""),
        bando.get("dotazione", "non specificato"),
        bando.get("livello", "nazionale"),
        bando.get("stato", "aperto"),
        datetime.now().isoformat()
    ))
    con.commit()
    con.close()
    return True


def scrapa_tutto():
    init_db()
    totale_nuovi = 0
    status = []

    # 1. Prima carica i bandi fissi noti
    print("[SPORT] Caricamento bandi fissi...", flush=True)
    for b in BANDI_FISSI_SPORT:
        if salva_bando(b, b.get("fonte", ""), b.get("url", "")):
            totale_nuovi += 1
            print(f"  + {b['titolo'][:60]}", flush=True)

    # 2. Poi scrapa le fonti web
    for fonte in FONTI_SPORT:
        print(f"\n[SPORT] Scraping: {fonte['nome']}", flush=True)
        html = _fetch(fonte["url"])
        if not html:
            status.append({"fonte": fonte["nome"], "ok": False, "nuovi": 0})
            continue

        testo = _pulisci_html(html)
        bandi = _estrai_bandi_da_testo(testo, fonte["nome"], fonte["url"])
        nuovi = 0
        for b in bandi:
            if b.get("titolo") and len(b["titolo"]) > 10:
                if salva_bando(b, fonte["nome"], fonte["url"]):
                    nuovi += 1
                    print(f"  + {b['titolo'][:60]}", flush=True)
        totale_nuovi += nuovi
        status.append({"fonte": fonte["nome"], "ok": True, "nuovi": nuovi})
        time.sleep(2)  # rispetta i server

    print(f"\n[SPORT] Completato — {totale_nuovi} bandi nuovi inseriti", flush=True)
    return totale_nuovi, status


def cerca_bandi_sport(keyword="", stato="aperto", livello="", max_results=50):
    """Query sul DB sport — usata dall'endpoint /api/cerca-sport."""
    con = sqlite3.connect(DB_SPORT)

    where = []
    params = []

    if stato and stato != "tutti":
        where.append("stato = ?")
        params.append(stato)
    if livello:
        where.append("livello = ?")
        params.append(livello)
    if keyword:
        where.append("(titolo LIKE ? OR descrizione LIKE ? OR beneficiari LIKE ?)")
        kw = f"%{keyword}%"
        params += [kw, kw, kw]

    sql = "SELECT id, titolo, scadenza, beneficiari, livello, stato, fonte, url FROM bandi_sport"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY aggiornato DESC LIMIT {max_results}"

    rows = con.execute(sql, params).fetchall()
    con.close()

    bandi = []
    for r in rows:
        bandi.append({
            "id": r[0],
            "titolo": r[1],
            "scadenza": r[2] or "—",
            "beneficiari": r[3] or "—",
            "livello": r[4] or "Nazionale",
            "stato": r[5] or "aperto",
            "fonte": r[6],
            "url": r[7],
            "_hit": {"objectID": r[0], "post_title": r[1], "permalink": r[7]},
        })
    return bandi, len(bandi)


def conta_bandi():
    try:
        con = sqlite3.connect(DB_SPORT)
        n = con.execute("SELECT COUNT(*) FROM bandi_sport").fetchone()[0]
        con.close()
        return n
    except:
        return 0


if __name__ == "__main__":
    scrapa_tutto()
