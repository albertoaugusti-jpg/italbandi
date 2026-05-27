"""
scraper_privati.py — Raccoglie bonus, detrazioni e contributi per privati e famiglie
Fonti: incentivi.gov.it, INPS, Agenzia delle Entrate, portali regionali
Salva in /data/bandi_privati.db (SQLite persistente)
"""
import sqlite3, hashlib, re, json, os, time, requests
from datetime import datetime

DB_PRIVATI = "/data/bandi_privati.db"
ANTHROPIC_API_KEY = os.environ.get("CLAUDE_API_KEY", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

FONTI_PRIVATI = [
    {
        "nome": "incentivi.gov.it — Persone fisiche",
        "url": "https://www.incentivi.gov.it/it/misure?field_beneficiari_target_id=3",
        "tipo": "html",
    },
    {
        "nome": "INPS — Bonus e Contributi Famiglie",
        "url": "https://www.inps.it/it/it/dati-e-bilanci/tutti-i-servizi.html",
        "tipo": "html",
    },
    {
        "nome": "Agenzia Entrate — Agevolazioni",
        "url": "https://www.agenziaentrate.gov.it/portale/web/guest/schede/agevolazioni",
        "tipo": "html",
    },
    {
        "nome": "Governo.it — Bonus Famiglie 2025",
        "url": "https://www.governo.it/it/articolo/bonus-e-agevolazioni-famiglie/25761",
        "tipo": "html",
    },
    {
        "nome": "INPS — Assegno Unico e Universale",
        "url": "https://www.inps.it/it/it/dettaglio-scheda.schede-servizio-e-prestazioni.50089.assegno-unico-e-universale-per-i-figli-a-carico.html",
        "tipo": "html",
    },
]

# Bandi "fissi" noti — sempre presenti, aggiornati manualmente
BANDI_FISSI = [
    {
        "titolo": "Assegno Unico Universale per i figli a carico",
        "scadenza": "Domanda continua — nessuna scadenza",
        "beneficiari": "Famiglie con figli a carico fino a 21 anni",
        "descrizione": "Contributo mensile per ogni figlio a carico. Importo variabile in base all'ISEE, da €57 a €199 al mese per figlio.",
        "dotazione": "Da €57 a €199/mese per figlio",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "INPS",
        "url": "https://www.inps.it/it/it/dettaglio-scheda.schede-servizio-e-prestazioni.50089.html",
    },
    {
        "titolo": "Bonus Asilo Nido 2025",
        "scadenza": "Domanda entro il 31/12/2025",
        "beneficiari": "Genitori di bambini fino a 3 anni",
        "descrizione": "Rimborso delle rette di asilo nido pubblico o privato. Importo fino a €3.600 annui in base all'ISEE.",
        "dotazione": "Fino a €3.600 annui",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "INPS",
        "url": "https://www.inps.it/it/it/dettaglio-scheda.schede-servizio-e-prestazioni.50005.html",
    },
    {
        "titolo": "Ecobonus — Detrazione per efficienza energetica",
        "scadenza": "Spese sostenute entro 31/12/2025",
        "beneficiari": "Persone fisiche proprietarie di immobili",
        "descrizione": "Detrazioni IRPEF dal 50% al 65% per interventi di efficienza energetica su edifici esistenti (caldaie, cappotto, infissi).",
        "dotazione": "Detrazione 50-65% della spesa",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "Agenzia delle Entrate",
        "url": "https://www.agenziaentrate.gov.it/portale/web/guest/schede/agevolazioni/ecobonus",
    },
    {
        "titolo": "Bonus Ristrutturazione Casa 50%",
        "scadenza": "Spese sostenute entro 31/12/2025",
        "beneficiari": "Proprietari e inquilini di immobili residenziali",
        "descrizione": "Detrazione IRPEF del 50% per lavori di ristrutturazione edilizia, su un massimo di €96.000 per unità immobiliare.",
        "dotazione": "Detrazione 50% — max €48.000",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "Agenzia delle Entrate",
        "url": "https://www.agenziaentrate.gov.it/portale/web/guest/schede/agevolazioni/bonus-ristrutturazioni",
    },
    {
        "titolo": "Bonus Mobili e Grandi Elettrodomestici",
        "scadenza": "Acquisti entro 31/12/2025",
        "beneficiari": "Chi ha effettuato ristrutturazioni dal 2024",
        "descrizione": "Detrazione IRPEF del 50% per acquisto di mobili e grandi elettrodomestici, su un massimo di €5.000.",
        "dotazione": "Detrazione 50% — max €2.500",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "Agenzia delle Entrate",
        "url": "https://www.agenziaentrate.gov.it/portale/web/guest/schede/agevolazioni/bonus-mobili",
    },
    {
        "titolo": "Bonus Sociale Energia Elettrica e Gas",
        "scadenza": "Domanda continua — attivazione automatica con ISEE",
        "beneficiari": "Famiglie con ISEE fino a €9.530 (o €20.000 con 4+ figli)",
        "descrizione": "Sconto automatico in bolletta per luce e gas. Attivazione automatica presentando l'ISEE aggiornato al CAF.",
        "dotazione": "Sconto variabile — media €200/anno luce + €150/anno gas",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "ARERA / INPS",
        "url": "https://www.arera.it/it/bonus_sociale.htm",
    },
    {
        "titolo": "Carta Acquisti — Bonus spesa famiglie disagiate",
        "scadenza": "Domanda continua",
        "beneficiari": "Famiglie con ISEE fino a €15.000 con figli under 3 o anziani over 65",
        "descrizione": "Carta prepagata da €80 ogni 2 mesi per acquisto di beni alimentari e medicinali.",
        "dotazione": "€80 ogni 2 mesi (€480 annui)",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "INPS",
        "url": "https://www.inps.it/it/it/dettaglio-scheda.schede-servizio-e-prestazioni.50017.html",
    },
    {
        "titolo": "Sismabonus — Detrazione per riduzione rischio sismico",
        "scadenza": "Spese entro 31/12/2025",
        "beneficiari": "Proprietari di immobili in zone sismiche 1, 2, 3",
        "descrizione": "Detrazione IRPEF dal 50% all'85% per interventi di messa in sicurezza antisismica degli edifici.",
        "dotazione": "Detrazione 50-85% della spesa",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "Agenzia delle Entrate",
        "url": "https://www.agenziaentrate.gov.it/portale/web/guest/schede/agevolazioni/sismabonus",
    },
    {
        "titolo": "Bonus Barriere Architettoniche 75%",
        "scadenza": "Spese entro 31/12/2025",
        "beneficiari": "Proprietari di immobili — priorità per disabili",
        "descrizione": "Detrazione IRPEF del 75% per interventi di eliminazione di barriere architettoniche (ascensori, rampe, bagni).",
        "dotazione": "Detrazione 75% della spesa",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "Agenzia delle Entrate",
        "url": "https://www.agenziaentrate.gov.it/portale/web/guest/schede/agevolazioni/bonus-barriere-architettoniche",
    },
    {
        "titolo": "Fondo di Garanzia Prima Casa — Mutui under 36",
        "scadenza": "Domanda continua",
        "beneficiari": "Under 36 con ISEE fino a €40.000 per acquisto prima casa",
        "descrizione": "Garanzia statale fino all'80% del mutuo per l'acquisto della prima casa. Esenzione da imposte ipotecaria e catastale.",
        "dotazione": "Garanzia fino all'80% del mutuo",
        "livello": "nazionale",
        "stato": "aperto",
        "fonte": "Consap / MEF",
        "url": "https://www.consap.it/abitazione/fondo-garanzia-prima-casa/",
    },
]


def init_db():
    os.makedirs("/data", exist_ok=True)
    con = sqlite3.connect(DB_PRIVATI)
    con.execute("""CREATE TABLE IF NOT EXISTS bandi_privati (
        id           TEXT PRIMARY KEY,
        titolo       TEXT NOT NULL,
        fonte        TEXT,
        url          TEXT,
        scadenza     TEXT,
        beneficiari  TEXT,
        descrizione  TEXT,
        dotazione    TEXT,
        settore      TEXT DEFAULT 'Privati',
        livello      TEXT DEFAULT 'nazionale',
        stato        TEXT DEFAULT 'aperto',
        aggiornato   TEXT
    )""")
    con.commit()
    con.close()
    print("[PRIVATI DB] inizializzato", flush=True)


def _hash(titolo, url=""):
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


def _estrai_da_testo(testo, fonte_nome, fonte_url):
    if not ANTHROPIC_API_KEY or len(testo) < 100:
        return []

    prompt = f"""Sei un esperto di agevolazioni fiscali e bonus per privati cittadini italiani.

Analizza questo testo dalla pagina "{fonte_nome}" e identifica TUTTI i bonus, detrazioni, contributi e agevolazioni per PRIVATI CITTADINI o FAMIGLIE.

TESTO:
{testo[:6000]}

Per ogni agevolazione trovata restituisci un oggetto JSON. Rispondi SOLO con array JSON:
[
  {{
    "titolo": "nome completo del bonus o agevolazione",
    "scadenza": "data scadenza o 'Domanda continua' se permanente",
    "beneficiari": "chi ne ha diritto (es: famiglie con ISEE sotto X, under 36, disabili)",
    "descrizione": "breve descrizione in 2 righe — cosa si ottiene e come",
    "dotazione": "importo, percentuale detrazione o valore del beneficio",
    "livello": "nazionale|regionale|europeo",
    "stato": "aperto|chiuso|prossima_apertura"
  }}
]

Se non trovi agevolazioni per privati restituisci: []"""

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
        s = raw.find('['); e = raw.rfind(']')
        if s != -1 and e != -1:
            return json.loads(raw[s:e+1])
    except Exception as ex:
        print(f"[AI ERR] {ex}", flush=True)
    return []


def salva_bando(bando, fonte_nome="", fonte_url=""):
    bid = _hash(bando.get("titolo", ""), bando.get("url", fonte_url))
    con = sqlite3.connect(DB_PRIVATI)
    esiste = con.execute("SELECT id FROM bandi_privati WHERE id=?", (bid,)).fetchone()
    if esiste:
        con.close()
        return False
    con.execute("""INSERT INTO bandi_privati
        (id, titolo, fonte, url, scadenza, beneficiari, descrizione,
         dotazione, livello, stato, aggiornato)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
        bid,
        bando.get("titolo", "")[:500],
        bando.get("fonte", fonte_nome),
        bando.get("url", fonte_url),
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

    # 1. Prima carica i bandi fissi noti
    print("[PRIVATI] Caricamento bandi fissi...", flush=True)
    for b in BANDI_FISSI:
        if salva_bando(b):
            totale_nuovi += 1
            print(f"  + {b['titolo'][:60]}", flush=True)

    # 2. Poi scrapa le fonti web
    for fonte in FONTI_PRIVATI:
        print(f"\n[PRIVATI] Scraping: {fonte['nome']}", flush=True)
        html = _fetch(fonte["url"])
        if not html:
            continue
        testo = _pulisci_html(html)
        bandi = _estrai_da_testo(testo, fonte["nome"], fonte["url"])
        for b in bandi:
            if b.get("titolo") and len(b["titolo"]) > 10:
                if salva_bando(b, fonte["nome"], fonte["url"]):
                    totale_nuovi += 1
                    print(f"  + {b['titolo'][:60]}", flush=True)
        time.sleep(2)

    print(f"\n[PRIVATI] Completato — {totale_nuovi} agevolazioni inserite", flush=True)
    return totale_nuovi


def cerca_bandi_privati(keyword="", stato="aperto", livello="", max_results=50):
    try:
        con = sqlite3.connect(DB_PRIVATI)
    except Exception:
        return [], 0

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

    sql = "SELECT id, titolo, scadenza, beneficiari, livello, stato, fonte, url FROM bandi_privati"
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
        con = sqlite3.connect(DB_PRIVATI)
        n = con.execute("SELECT COUNT(*) FROM bandi_privati").fetchone()[0]
        con.close()
        return n
    except:
        return 0


if __name__ == "__main__":
    scrapa_tutto()
