"""
bandi_engine.py — ItalBandi
Logica estratta da schede_gui.py (invariata).
Rimosso solo: tkinter, percorsi Windows, auto-install pip.
"""
import requests, os, re, sys, json, time
from datetime import datetime
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

# ── Credenziali ───────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("CLAUDE_API_KEY", "")

ALGOLIA_APP_ID  = "LHI8XKBFMN"
ALGOLIA_API_KEY = "f55131344ae840ea7f27c6dcb0782654"
ALGOLIA_INDEX   = "ceu_searchable_posts"
ALGOLIA_URL     = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"
ALGOLIA_HEADERS = {
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "X-Algolia-API-Key":        ALGOLIA_API_KEY,
    "Content-Type":             "application/json",
}

REGIONI = [
    "Abruzzo","Basilicata","Calabria","Campania","Emilia-Romagna",
    "Friuli-Venezia-Giulia","Lazio","Liguria","Lombardia","Marche",
    "Molise","Piemonte","Puglia","Sardegna","Sicilia","Toscana",
    "Trentino-Alto-Adige","Umbria","Valle d'Aosta","Veneto",
]
PROVINCE = {
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
}

UFFICIALI_KEYWORDS = [
    ".gov.it", ".regione.", ".provincia.", ".comune.", ".mise.gov",
    ".mef.gov", ".mimit.gov", ".mur.gov", ".invitalia.", ".finlombarda.",
    ".simest.", ".camcom.", "gazzettaufficiale", "normattiva",
    ".inail.", ".anci.", ".agriligurianet.",
]

_session = requests.Session()
_session.headers.update({
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
})

def _is_ufficiale(url):
    url_l = url.lower()
    return any(k in url_l for k in UFFICIALI_KEYWORDS)


def fmt_date(val):
    if not val:
        return "", None
    if isinstance(val, (int, float)):
        try:
            dt = datetime.fromtimestamp(val)
            return dt.strftime("%d/%m/%Y"), dt
        except Exception:
            return str(val), None
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
        try:
            dt = datetime.strptime(str(val).strip(), fmt)
            return dt.strftime("%d/%m/%Y"), dt
        except Exception:
            pass
    # Stringa già leggibile (es. "Fino ad esaurimento fondi")
    s = str(val).strip()
    if len(s) > 3:
        return s, None
    return "", None


def build_filters(scadenza_vals, livello, regione, provincia):
    parts = []
    if scadenza_vals:
        sc = " OR ".join(f'scadenza_testo:"{v}"' for v in scadenza_vals)
        parts.append(f"({sc})")
    if livello == "Bandi europei":
        parts.append('taxonomies_hierarchical.area_geografica.lvl0:"Bandi Europei"')
    elif livello == "Bandi nazionali":
        parts.append('taxonomies_hierarchical.area_geografica.lvl0:"Bandi Nazionali"')
    elif livello == "Bandi regionali":
        if provincia and provincia != "(tutte)":
            parts.append(f'taxonomies_hierarchical.area_geografica.lvl1:"{provincia}"')
        elif regione:
            parts.append(f'taxonomies_hierarchical.area_geografica.lvl0:"{regione}"')
    return " AND ".join(parts)


def query_algolia(filters, keyword, log_fn, stop_fn, max_hits=500, restrict_attrs=None):
    all_hits, page, total = [], 0, 0
    while True:
        if stop_fn():
            break
        payload = {"query": keyword, "hitsPerPage": 100, "page": page,
                   "filters": filters, "attributesToRetrieve": ["*"]}
        if restrict_attrs:
            payload["restrictSearchableAttributes"] = restrict_attrs
        r = requests.post(ALGOLIA_URL, headers=ALGOLIA_HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        data     = r.json()
        hits     = data.get("hits", [])
        all_hits.extend(hits)
        total    = data.get("nbHits", 0)
        nb_pages = data.get("nbPages", 1)
        log_fn(f"  Pagina {page+1}/{nb_pages} — {len(all_hits)}/{total} bandi")
        if page + 1 >= nb_pages or len(all_hits) >= max_hits:
            break
        page += 1
    return all_hits, total


# =============================================================================
#  ESTRAZIONE DATI DALL'HIT ALGOLIA
# =============================================================================

def _scadenza_da_hit(hit):
    for campo in ("scadenza", "data_scadenza", "deadline", "data_chiusura",
                  "fine", "data_fine", "end_date", "scadenza_data"):
        val = hit.get(campo)
        if val:
            s, dt = fmt_date(val)
            if s:
                return s, dt
    return "", None


def _dotazione_da_hit(hit):
    for campo in ("dotazione", "dotazione_finanziaria", "budget", "importo",
                  "importo_totale", "risorse", "finanziamento", "stanziamento",
                  "fondo", "contributo_massimo"):
        val = hit.get(campo)
        if val and str(val).strip() not in ("0", "0.0", "", "[]", "{}"):
            v = str(val).strip()
            try:
                n = float(v.replace(",", ".").replace(".", "").replace(" ", ""))
                if n > 0:
                    if n >= 1_000_000:
                        return f"EUR {n/1_000_000:,.1f} MLN".replace(",", ".")
                    return f"EUR {int(n):,}".replace(",", ".")
            except ValueError:
                if any(c.isdigit() for c in v):
                    return v[:50]
    return None


def beneficiari_da_hit(hit):
    for chiave in ("beneficiari", "destinatari", "soggetti_ammissibili",
                   "soggetti", "tipo_beneficiario"):
        val = hit.get(chiave)
        if val:
            if isinstance(val, list):
                puliti = [str(v).split("/")[0].strip() for v in val[:3]]
                return ", ".join(p for p in puliti if p)
            if isinstance(val, str) and val.strip():
                return val.strip()[:120]
    return ""


def livello_da_hit(hit):
    taxh = hit.get("taxonomies_hierarchical", {})
    ag   = taxh.get("area_geografica", {}) or {}
    lvl0 = ag.get("lvl0") or []
    lvl1 = ag.get("lvl1") or []
    if not lvl0:
        return "—"
    area = lvl0[0]
    if "Europei" in area:
        return "Europeo"
    if "Nazionali" in area:
        return "Nazionale"
    geo = lvl1[0].replace("Provincia di ", "") if lvl1 else area
    return f"Regionale  {geo}"


# =============================================================================
#  MOTORE DI RICERCA — Claude API con web_search
# =============================================================================

def _fetch_text(url, log_fn=None):
    """Scarica una pagina e restituisce il testo pulito."""
    try:
        r     = _session.get(url, timeout=15, allow_redirects=True)
        r.raise_for_status()
        html  = r.text
        html  = re.sub(r'<script[^>]*>.*?</script>', ' ', html,  flags=re.DOTALL | re.IGNORECASE)
        html  = re.sub(r'<style[^>]*>.*?</style>',   ' ', html,  flags=re.DOTALL | re.IGNORECASE)
        testo = re.sub(r'<[^>]+>', ' ', html)
        testo = re.sub(r'\s+',     ' ', testo).strip()
        return testo
    except Exception as e:
        if log_fn:
            log_fn(f"  Fetch error {url[:60]}: {e}")
        return ""


def _fetch_text_pdf(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        return " ".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        return ""


def _estrai_links_da_html(html):
    return re.findall(r'href=[\'"]?(https?://[^\'">\s]+)[\'"]?', html)


def _cerca_bando_con_claude(titolo, log_fn=None):
    """Usa Claude API + web_search. Retry automatico su rate limit 429."""
    def log(m):
        if log_fn: log_fn(m)

    if not ANTHROPIC_API_KEY:
        log("  [!] ANTHROPIC_API_KEY non configurata")
        return "", ""

    log(f"  [Claude] Ricerca: {titolo[:65]}...")
    prompt = (
        f'Cerca informazioni sul bando italiano: "{titolo}"\n\n'
        "Trova e riporta con valori NUMERICI ESATTI:\n"
        "1. Dotazione finanziaria totale (importo del fondo)\n"
        "2. Intensita del contributo (% o importo max per beneficiario)\n"
        "3. Scadenza presentazione domande\n"
        "4. Apertura sportello\n"
        "5. Chi puo partecipare (beneficiari)\n"
        "6. Spese ammissibili\n"
        "7. Come presentare la domanda (portale/piattaforma)\n"
        "8. URL sito ufficiale\n\n"
        "Riporta i dati trovati in modo diretto e preciso."
    )

    for tentativo in range(3):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001",
                      "max_tokens": 1500,
                      "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=90,
            )
            if resp.status_code == 429:
                wait = (tentativo + 1) * 8
                log(f"  Rate limit — attendo {wait}s (tentativo {tentativo+1}/3)...")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                log(f"  API error {resp.status_code}: {resp.text[:120]}")
                return "", ""

            content = resp.json().get("content", [])
            testo   = "\n".join(b.get("text","") for b in content if b.get("type")=="text").strip()
            url_uff = ""
            for u in re.findall(r'https?://[^\s<>]+', testo):
                if _is_ufficiale(u):
                    url_uff = u.rstrip(".,)")
                    break
            log(f"  [Claude] OK — {len(testo)} caratteri")
            if url_uff:
                log(f"  [Claude] Fonte: {url_uff[:70]}")
            return testo, url_uff

        except Exception as e:
            log(f"  [Claude] Errore: {e}")
            return "", ""

    log("  [Claude] Tutti i tentativi falliti")
    return "", ""


def _cerca_fonte_pagina_ce(link_ce, log_fn=None):
    """Fallback: scarica la pagina CE e cerca link ufficiali."""
    def log(m):
        if log_fn: log_fn(m)

    if not link_ce:
        return "", ""
    try:
        r    = _session.get(link_ce, timeout=12)
        html = r.text
        links_uff = list(dict.fromkeys(
            l for l in _estrai_links_da_html(html)
            if _is_ufficiale(l) and "contributieuropa" not in l
        ))
        log(f"  Pagina CE: {len(links_uff)} link ufficiali")
        for link in links_uff[:3]:
            testo = _fetch_text(link, log_fn)
            if testo and len(testo) > 300:
                return link, testo
        # Testo della pagina CE come ultimo fallback
        testo_ce = re.sub(r'<[^>]+>', ' ', html)
        testo_ce = re.sub(r'\s+', ' ', testo_ce).strip()
        return link_ce, testo_ce
    except Exception as e:
        log(f"  Errore CE: {e}")
        return "", ""


# =============================================================================
#  ESTRAZIONE DATI STRUTTURATI DAL TESTO
# =============================================================================

JUNK_VALUES = {
    "null", "none", "", "n/a", "nd", "n.d.", "non specificato",
    "non disponibile", "vedi bando", "da definire", "da verificare",
    "non indicato", "non presente", "vedere bando", "—", "-",
}


def _sintetizza_metrica(campo, valore):
    """
    Riduce il valore per i box metriche (colpo d'occhio).
    intensita  → "50%"  o  "EUR 50.000"
    dotazione  → "EUR 10 MLN"  o  "EUR 500.000"
    scadenza   → "15/07/2026"
    stato      → "Aperto" / "Pross. apertura" / "Chiuso"
    """
    if not valore or str(valore).strip() in ("—", "-", ""):
        return "—"
    v = str(valore).strip()
    c = campo.lower()

    if "intensit" in c or "contributo" in c:
        m2 = re.search(r'(\d{1,3})\s*%[^0-9]{0,15}(\d{1,3})\s*%', v)
        if m2:
            return f"{m2.group(1)}%-{m2.group(2)}%"
        m = re.search(r'(\d{1,3})\s*%', v)
        if m:
            return f"{m.group(1)}%"
        m = re.search(r'(?:eur(?:o)?\s*|€\s*)([\d][\d\.,]+)', v, re.IGNORECASE)
        if m:
            return f"EUR {m.group(1)}"[:16]
        return v[:15]

    if "dotaz" in c or "fondo" in c or "risorse" in c:
        m = re.search(r'([\d]+(?:[,\.][\d]+)?)\s*(?:milion[ei]|mln)\b', v, re.IGNORECASE)
        if m:
            try:
                n = float(m.group(1).replace(",", "."))
                return f"EUR {n:g} MLN"
            except ValueError:
                return f"EUR {m.group(1)} MLN"
        for raw in re.findall(r'[\d][\d\.,]+', v):
            try:
                n = float(raw.replace(".", "").replace(",", "."))
                if n >= 1_000_000:
                    return f"EUR {n/1_000_000:g} MLN"
                if n >= 1_000:
                    return f"EUR {int(n):,}".replace(",", ".")
            except ValueError:
                continue
        return v[:18]

    if "scad" in c or "apertura" in c or "data" in c:
        m = re.search(r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}', v)
        if m:
            return m.group(0).replace("-", "/").replace(".", "/")
        return v[:18]

    if "stato" in c:
        vl = v.lower()
        if "prossima" in vl:                   return "Pross. apertura"
        if "aperto" in vl or "aperti" in vl:   return "Aperto"
        if "chiuso" in vl:                      return "Chiuso"
        return v[:15]

    return v[:18]


def _pulisci(val):
    """Restituisce val se significativo, None se è un placeholder."""
    if not val:
        return None
    if str(val).strip().lower() in JUNK_VALUES:
        return None
    return str(val).strip()


def _estrai_dati_con_ia(testo, titolo, log_fn=None):
    """
    Estrae dati strutturati dal testo.
    Se API key configurata: usa Claude per parsing JSON.
    Altrimenti: regex calibrati.
    """
    def log(m):
        if log_fn: log_fn(m)

    if not testo or len(testo) < 80:
        return {}

    # ── Claude API per parsing strutturato ───────────────────────────────
    if ANTHROPIC_API_KEY:
        prompt = (
            "Dal testo seguente estrai i dati del bando in JSON.\n"
            "Campi: dotazione (importo totale fondo), intensita (% o EUR max per beneficiario), "
            "scadenza (DD/MM/YYYY), apertura (DD/MM/YYYY), beneficiari (chi partecipa, max 100 car.), "
            "spese (cosa si finanzia, max 150 car.), procedura (come presentare domanda, max 100 car.), "
            "note_critiche (vincoli principali, max 150 car.).\n"
            "USA null SE il dato NON E' NEL TESTO. NON scrivere mai 'vedi bando' o 'non specificato'.\n\n"
            f"Titolo: {titolo}\nTesto:\n{testo[:4000]}\n\n"
            'Rispondi SOLO con JSON valido.'
        )
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 600,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=25,
            )
            raw  = resp.json()["content"][0]["text"].strip()
            raw  = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
            data = json.loads(raw)
            puliti = {k: _pulisci(v) for k, v in data.items()}
            puliti = {k: v for k, v in puliti.items() if v}
            log(f"  AI parsing: {list(puliti.keys())}")
            if puliti:
                return puliti
        except Exception as e:
            log(f"  AI parsing error: {e}")

    # ── Regex fallback ────────────────────────────────────────────────────
    log("  Regex extraction...")
    result = {}

    for pat in [
        r'dotazione\s+(?:finanziaria\s+)?(?:di|pari\s+a)\s*(?:euro\s+|eur\s+|€\s*)?([\d][\d\.\s]*(?:milion[ei]|mln)?(?:\s*(?:di\s*)?(?:euro|€))?)',
        r'(?:risorse|stanziamento|budget|fondo)\s+(?:di|pari\s+a)\s*(?:€\s*)?([\d][\d\.\s]*(?:milion[ei]|mln)?)',
        r'([\d][\d\.]*)\s*(?:milion[ei]|mln)\s*(?:di\s*)?(?:euro|€)',
    ]:
        m = re.search(pat, testo, re.IGNORECASE)
        if m:
            result["dotazione"] = m.group(1).strip().rstrip(".,")[:50]
            break

    for pat in [
        r'(?:contributo|agevolazione|fondo\s+perduto)[^%\.]{0,80}?(\d{1,3})\s*%',
        r'(?:fino\s+(?:al|a)|pari\s+al)\s+(\d{1,3})\s*%',
        r'(\d{1,3})\s*%\s+(?:delle?\s+)?(?:spese|costi|investiment)',
    ]:
        m = re.search(pat, testo, re.IGNORECASE)
        if m:
            result["intensita"] = f"{m.group(1)}%"
            break

    for pat in [
        r'(?:scadenza|termine|chiusura|entro\s+il)[^\d]{0,20}(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
        r'(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})',
    ]:
        m = re.search(pat, testo, re.IGNORECASE)
        if m:
            result["scadenza"] = m.group(1).replace("-", "/").replace(".", "/")
            break

    log(f"  Regex: {list(result.keys())}")
    return result


# =============================================================================
#  BUILD CONTENT — assembla il dict per l'engine PDF
# =============================================================================

def _nome_file_sicuro(titolo):
    s  = re.sub(r'[^\w\s\-]', '', titolo)
    s  = re.sub(r'\s+', '_', s.strip())
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"Scheda_{s[:50]}_{ts}.pdf"


def _ente_da_area(area):
    if not area:
        return "Ente erogatore"
    a = area.lower()
    if "europ" in a:
        return "Commissione Europea / Fondi UE"
    if "naz" in a:
        return "Ministero / Ente nazionale"
    return f"Regione / Ente locale · {area}"


def _cta_da_stato(stato):
    if not stato:
        return "Contattaci per valutare la tua candidatura!"
    s = stato.lower()
    if "prossima" in s:
        return "Bando in arrivo: preparati ora con Energelia!"
    if "aperto" in s or "aperti" in s:
        return "Bando aperto: agisci ora, siamo a disposizione!"
    return "Contattaci per valutare la tua candidatura!"


def _sintetizza(val, max_len=20):
    """
    Riduce un valore al dato essenziale per il box metrica.
    Es: "50% delle spese ammissibili per..." -> "50%"
        "EUR 2.000.000 complessivi" -> "EUR 2.000.000"
        "Fino a EUR 50.000 per impresa" -> "Fino a EUR 50.000"
    """
    import re as _re
    if not val or val == "—":
        return "—"
    v = str(val).strip()

    # Estrai solo percentuale se presente all'inizio
    m = _re.match(r'^(\d{1,3}\s*%)', v)
    if m:
        return m.group(1).strip()

    # "X% delle/del/di..." → "X%"
    m = _re.match(r'^((?:fino\s+(?:al|a)\s+)?\d{1,3}\s*%)', v, _re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # "EUR X" o "€ X" o "X milioni/mln" → tieni solo la parte numerica+unità
    m = _re.match(r'^((?:EUR|€|euro)\s*[\d\.\,]+(?:\s*(?:MLN|MLD|milion\w+))?)', v, _re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = _re.match(r'^([\d\.\,]+\s*(?:MLN|MLD|milion\w+|miliard\w+)?\s*(?:EUR|€|euro)?)', v, _re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        if len(candidate) <= max_len:
            return candidate

    # Tronca con "..." se troppo lungo
    if len(v) > max_len:
        return v[:max_len].rstrip() + "…"
    return v


def _build_metriche(dotazione, intensita, stato_metrica, stato_bg, data_label, data_val):
    return [
        {"label": "DOTAZIONE",
         "valore": _sintetizza_metrica("dotazione", dotazione),
         "bg": "blue"},
        {"label": "INTENSITA'",
         "valore": _sintetizza_metrica("intensita", intensita),
         "bg": "green"},
        {"label": "STATO",
         "valore": _sintetizza_metrica("stato", stato_metrica),
         "bg": stato_bg},
        {"label": data_label or "SCADENZA",
         "valore": _sintetizza_metrica("scadenza", data_val),
         "bg": "blue"},
    ]


def _genera_scheda_con_claude(titolo, testo_bando, log_fn=None):
    """
    Cuore del sistema: Claude legge il testo del bando e genera TUTTE
    le sezioni della scheda come JSON strutturato.
    """
    def log(m):
        if log_fn: log_fn(m)

    if not ANTHROPIC_API_KEY:
        log("  [!] ANTHROPIC_API_KEY non configurata")
        return {}

    log("  [Claude] Generazione contenuti scheda...")

    prompt = (
        f'Sei un esperto di finanza agevolata italiana che lavora per Energelia S.r.l.\n\n'
        f'Analizza il seguente testo di un bando di finanziamento. '
        f'Se mancano dati numerici chiave (importi, percentuali, date), cercali online.\n\n'
        f'TITOLO BANDO: "{titolo}"\n\n'
        f'TESTO DISPONIBILE:\n{testo_bando[:6000]}\n\n'
        f'Genera i contenuti per la scheda Energelia in formato JSON con questa struttura ESATTA.\n'
        f'Ogni bullet deve contenere dati REALI e SPECIFICI estratti dal bando — mai placeholder.\n\n'
        f'{{\n'
        f'  "dotazione": "importo totale fondo (es. EUR 10 MLN) o null se non trovato",\n'
        f'  "intensita": "percentuale e tipo (es. 40% fondo perduto) o null",\n'
        f'  "contributo_max": "importo massimo per beneficiario in euro o null",\n'
        f'  "investimento_min": "investimento minimo ammissibile in euro o null",\n'
        f'  "scadenza": "DD/MM/YYYY o null",\n'
        f'  "apertura": "DD/MM/YYYY o null",\n'
        f'  "ente_finalita": ["Nome ente erogatore", "Obiettivo specifico del bando", "Contesto programmatico"],\n'
        f'  "chi_partecipa": ["Tipologia soggetti ammessi", "Requisiti soggettivi chiave", "Eventuali esclusioni"],\n'
        f'  "cosa_finanziabile": ["Tipologie di investimento ammissibili", "Voci di spesa con eventuali % max", "Spese speciali o premiali"],\n'
        f'  "spese_non_ammissibili": ["Spese escluse esplicitamente", "IVA (salvo casi specifici)", "Spese ante-ammissione"],\n'
        f'  "contributo_voci": ["Intensita con valori numerici esatti", "Contributo massimo per beneficiario", "Scaglioni o fasce per dimensione"],\n'
        f'  "criteri_valutazione": ["Tipo procedura: valutativa/sportello", "Criteri principali con punteggi", "Documentazione richiesta"],\n'
        f'  "fasi_tempi": ["Apertura: data o stato", "Scadenza: data", "Istruttoria e rendicontazione"],\n'
        f'  "come_presentare": ["Portale o piattaforma specifica", "Credenziali richieste (SPID, CNS)", "Allegati principali obbligatori"],\n'
        f'  "perche_interessante": ["Punto di forza 1 concreto", "Punto di forza 2 concreto", "Punto di forza 3 concreto"],\n'
        f'  "criticita": ["Vincolo operativo reale", "Attenzione su requisiti o esclusioni", "Scadenze da rispettare"]\n'
        f'}}\n\n'
        f'Rispondi SOLO con il JSON valido. Nessun testo prima o dopo. Solo JSON puro.'
    )

    for tentativo in range(3):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001",
                      "max_tokens": 2000,
                      "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=120,
            )
            if resp.status_code == 429:
                wait = (tentativo + 1) * 8
                log(f"  Rate limit — attendo {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                log(f"  API error {resp.status_code}: {resp.text[:120]}")
                return {}

            blocks = resp.json().get("content", [])
            testo  = "\n".join(b.get("text","") for b in blocks if b.get("type")=="text").strip()
            if not testo:
                log("  Risposta vuota da Claude")
                return {}

            # Rimuovi fence ```json e tag spurii, poi estrai {…}
            raw = re.sub(r'```(?:json)?\s*', '', testo)
            raw = re.sub(r'```', '', raw)
            raw = re.sub(r'</?[a-zA-Z:][^>]*>', '', raw).strip()
            start = raw.find('{')
            end   = raw.rfind('}')
            if start == -1 or end == -1:
                log(f"  Nessun JSON (len={len(testo)})")
                log(f"  Anteprima: {testo[:200]}")
                return {}
            data = json.loads(raw[start:end+1])
            log(f"  [Claude] Scheda generata — {len(data)} sezioni")
            return data

        except json.JSONDecodeError as e:
            log(f"  JSON decode error: {e}")
            return {}
        except Exception as e:
            log(f"  [Claude] Errore: {e}")
            return {}

    return {}


def build_content(titolo, hit, testo_ufficiale, fonte_url, mese_anno=None, log_fn=None):
    hit       = hit or {}
    mese_anno = mese_anno or datetime.now().strftime("%B %Y")
    stato     = hit.get("scadenza_testo", "")

    sc_alg, _ = _scadenza_da_hit(hit)
    taxh  = hit.get("taxonomies_hierarchical", {})
    areas = (taxh.get("area_geografica") or {}).get("lvl0") or []
    area  = areas[0] if areas else ""
    ente_alg = _ente_da_area(area)

    # ── Claude genera tutte le sezioni dal testo del bando ────────────────
    cl = {}
    if testo_ufficiale:
        cl = _genera_scheda_con_claude(titolo, testo_ufficiale, log_fn)

    def cv(key, fallback=None):
        v = cl.get(key)
        if isinstance(v, list):
            return [x for x in v if x and str(x).strip()] or (fallback if isinstance(fallback, list) else [])
        if v and str(v).strip() not in ("null", "None", "", "—", "-"):
            return str(v).strip()
        return fallback

    dotazione   = cv("dotazione",   _dotazione_da_hit(hit))
    intensita   = cv("intensita")
    contrib_max = cv("contributo_max")
    scadenza    = cv("scadenza",    sc_alg)
    apertura    = cv("apertura")

    # ── Verifica se la scadenza è già passata (correzione stato errato da CE) ──
    _, sc_dt = fmt_date(scadenza) if scadenza else (None, None)
    if sc_dt and sc_dt < datetime.now() and "prossima" in stato.lower():
        stato = "Bandi chiusi"  # CE non ha aggiornato il tag — correggiamo

    if apertura and scadenza:
        data_label, data_val = "SCADENZA", scadenza
    elif scadenza:
        data_label, data_val = "SCADENZA", scadenza
    elif apertura:
        data_label, data_val = "APERTURA", apertura
    else:
        data_label, data_val = "SCADENZA", None

    stato_bg = "blue" if "prossima" in stato.lower() else "orange"

    def sezione(key, fallback_voci):
        voci = cv(key, [])
        return voci if voci else fallback_voci

    ente_voci   = sezione("ente_finalita",        [ente_alg, f"Area: {area}"] if area else [ente_alg])
    ben_voci    = sezione("chi_partecipa",         [beneficiari_da_hit(hit) or "Verificare requisiti sul bando"])
    fin_voci    = sezione("cosa_finanziabile",     ["Verificare spese ammissibili sul bando"])
    nonamm_voci = sezione("spese_non_ammissibili", ["IVA (salvo casi specifici)", "Spese ante-ammissione", "Oneri finanziari"])
    contrib_voci= sezione("contributo_voci",       [f"Intensita\': {intensita}" if intensita else "Verificare sul bando"])
    crit_val    = sezione("criteri_valutazione",   ["Verificare procedura e criteri sul bando"])
    tempi_voci  = sezione("fasi_tempi", [f"<b>Apertura:</b> {apertura}" if apertura else None,
                                          f"<b>Scadenza:</b> {scadenza}" if scadenza else None])
    come_voci   = sezione("come_presentare",       ["Verificare allegati obbligatori", "Contatta Energelia per supporto"])
    punti_forza = sezione("perche_interessante",   [f"Contributo: {intensita}" if intensita else None,
                                                    f"Scadenza: {scadenza}" if scadenza else None])
    criticita   = sezione("criticita", ["Verificare requisiti soggettivi prima di candidarsi",
                                         "Controllare cumulabilita\' con altri contributi ricevuti",
                                         "Rispettare le scadenze di presentazione e rendicontazione"])

    def pulisci_lista(lst):
        return [str(x).strip() for x in lst if x and str(x).strip() not in ("None","null","—","-","")]

    return {
        "titolo":      titolo.upper(),
        "sottotitolo": " · ".join(v for v in [ente_alg, area, stato] if v),
        "metriche":    _build_metriche(dotazione or contrib_max, intensita,
                                        stato or "Aperto", stato_bg, data_label, data_val),
        "sinistra": [
            {"titolo": "ENTE / FINALITA'",      "voci": pulisci_lista(ente_voci)},
            {"titolo": "CHI PUO' PARTECIPARE",  "voci": pulisci_lista(ben_voci)},
            {"titolo": "COSA E' FINANZIABILE",  "voci": pulisci_lista(fin_voci)},
            {"titolo": "SPESE NON AMMISSIBILI", "voci": pulisci_lista(nonamm_voci)},
        ],
        "tabella_contributi": None,
        "destra": [
            {"titolo": "CONTRIBUTO / INTENSITA'", "voci": pulisci_lista(contrib_voci)},
            {"titolo": "CRITERI / VALUTAZIONE",    "voci": pulisci_lista(crit_val)},
            {"titolo": "FASI E TEMPI",             "voci": pulisci_lista(tempi_voci)},
            {"titolo": "COME PRESENTARE",          "voci": pulisci_lista(come_voci)},
        ],
        "punti_forza": pulisci_lista(punti_forza),
        "criticita":   pulisci_lista(criticita),
        "cta_testo":   _cta_da_stato(stato),
        "cta_tel":     "Tel. 010 8078800",
        "cta_email":   "a.augusti@energelia.it",
        "fonte":       f"Fonte: {fonte_url[:80]}" if fonte_url else "Fonte: bando ufficiale",
        "mese_anno":   mese_anno,
    }


def _cerca_fonte_pagina_ce(link_ce, log_fn=None):
    """Scarica la pagina CE, segue i link ufficiali e restituisce (url, testo)."""
    def log(m):
        if log_fn: log_fn(m)
    if not link_ce:
        return "", ""
    try:
        r    = _session.get(link_ce, timeout=12)
        html = r.text
        links_uff = list(dict.fromkeys(
            l for l in _estrai_links_da_html(html)
            if _is_ufficiale(l) and "contributieuropa" not in l
        ))
        log(f"  Pagina CE: {len(links_uff)} link ufficiali trovati")
        for link in links_uff[:3]:
            testo = _fetch_text(link, log_fn)
            if testo and len(testo) > 300:
                return link, testo
        testo_ce = re.sub(r'<[^>]+>', ' ', html)
        testo_ce = re.sub(r'\s+', ' ', testo_ce).strip()
        return link_ce, testo_ce
    except Exception as e:
        log(f"  Errore CE: {e}")
        return "", ""


# =============================================================================
#  FLUSSO GENERAZIONE SCHEDA
# =============================================================================

def genera_scheda_da_hit(hit, log_fn, done_fn, error_fn):
    """
    1. Leggi pagina CE + link ufficiali
    2. Claude legge il testo e genera tutte le sezioni
    3. Genera PDF
    """
    titolo  = hit.get("post_title", "Bando senza titolo")
    link_ce = hit.get("permalink", "")

    log_fn(f">> {titolo[:80]}")
    log_fn("-" * 55)

    testo_ce_pag = ""
    if link_ce:
        log_fn("  [1] Lettura pagina contributieuropa.com...")
        testo_ce_pag = _fetch_text(link_ce, log_fn)
        if testo_ce_pag:
            log_fn(f"      {len(testo_ce_pag)} caratteri")

    url_uff, testo_uff = "", ""
    if link_ce:
        log_fn("  [2] Link ufficiali dalla pagina CE...")
        url_uff, testo_uff = _cerca_fonte_pagina_ce(link_ce, log_fn)

    parti = []
    if testo_ce_pag:
        parti.append(f"=== CONTRIBUTIEUROPA ===\n{testo_ce_pag}")
    if testo_uff and testo_uff != testo_ce_pag:
        parti.append(f"=== FONTE UFFICIALE ===\n{testo_uff}")
    testo_bando = "\n\n".join(parti)
    url_finale  = url_uff or link_ce or "contributieuropa.com"

    log_fn("-" * 55)
    log_fn("  Elaborazione e generazione PDF...")

    content = build_content(
        titolo=titolo, hit=hit,
        testo_ufficiale=testo_bando, fonte_url=url_finale,
        mese_anno=datetime.now().strftime("%B %Y"), log_fn=log_fn,
    )
    nome_file   = _nome_file_sicuro(titolo)
    output_path = str(OUTPUT_DIR / nome_file)
    try:
        ENGINE.generate(content, output_path, LOGO_PATH)
        done_fn(output_path)
    except Exception as e:
        error_fn(f"Errore generazione PDF:\n{e}")


def genera_scheda_da_pdf(pdf_path, log_fn, done_fn, error_fn):
    """Genera scheda da PDF caricato dall'utente."""
    log_fn(f">> Lettura PDF: {Path(pdf_path).name}")
    testo = _fetch_text_pdf(pdf_path)
    if not testo or len(testo) < 50:
        error_fn("Impossibile estrarre testo.\nVerifica che non sia un PDF scansionato.")
        return

    righe  = [r.strip() for r in testo.split('\n') if len(r.strip()) > 15]
    titolo = righe[0][:120] if righe else Path(pdf_path).stem
    log_fn(f"  Titolo: {titolo[:70]}")

    testo_claude, url_claude = _cerca_bando_con_claude(titolo, "", testo[:3000], log_fn)
    testo_finale = testo_claude or testo
    url_finale   = url_claude or f"PDF: {Path(pdf_path).name}"

    content = build_content(
        titolo=titolo, hit={},
        testo_ufficiale=testo_finale, fonte_url=url_finale,
        mese_anno=datetime.now().strftime("%B %Y"), log_fn=log_fn,
    )
    nome_file   = _nome_file_sicuro(Path(pdf_path).stem)
    output_path = str(OUTPUT_DIR / nome_file)
    try:
        ENGINE.generate(content, output_path, LOGO_PATH)
        done_fn(output_path)
    except Exception as e:
        error_fn(f"Errore generazione PDF:\n{e}")



def _suggerisci_con_claude(bandi, log_fn=None):
    def log(m):
        if log_fn: log_fn(m)
    if not ANTHROPIC_API_KEY:
        log("API key mancante"); return {}
    righe = []
    for i, h in enumerate(bandi[:80]):
        titolo = h.get("post_title","")[:100]
        ben    = beneficiari_da_hit(h) or ""
        taxh   = h.get("taxonomies_hierarchical",{})
        areas  = (taxh.get("area_geografica") or {}).get("lvl0") or []
        area   = areas[0] if areas else "Nazionale"
        righe.append(f"{i+1}. [{area}] {titolo} | Beneficiari: {ben}")
    prompt = (
        "Sei un esperto di finanza agevolata italiana. "
        "Classifica i seguenti bandi in base alla PLATEA DI POTENZIALI FRUITORI.\n"
        "Considera solo imprese private, cooperative, professionisti — escludi Comuni e PA.\n\n"
        "PLATEA AMPIA = categorie molto diffuse (PMI, ristoratori, commercianti, ecc.)\n"
        "NICCHIA = categorie specifiche (imprese ittiche, tartufo, tessile storico, ecc.)\n\n"
        f"BANDI:\n{chr(10).join(righe)}\n\n"
        'Rispondi SOLO con JSON: {"ampia":[{"titolo":"titolo esatto","platea":"stima","motivo":"1 riga"}],'
        '"nicchia":[{"titolo":"titolo esatto","platea":"stima","motivo":"1 riga"}]}\n'
        "5 elementi per lista. Solo JSON."
    )
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 1500,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        if resp.status_code != 200:
            log(f"API error {resp.status_code}"); return {}
        blocks = resp.json().get("content", [])
        testo  = "\n".join(b.get("text","") for b in blocks if b.get("type")=="text").strip()
        if not testo: return {}
        raw = re.sub(r'```(?:json)?\s*', '', testo)
        raw = re.sub(r'```', '', raw).strip()
        start = raw.find('{'); end = raw.rfind('}')
        if start == -1 or end == -1: return {}
        data = json.loads(raw[start:end+1])
        log(f"✓ {len(data.get('ampia',[]))} ampia + {len(data.get('nicchia',[]))} nicchia")
        return data
    except Exception as e:
        log(f"Errore: {e}"); return {}




# =============================================================================
#  WRAPPER PER IL WEB — chiamate senza callback Tkinter
# =============================================================================

def cerca_bandi_web(keyword="", stato="aperto", livello="", regione="", provincia="", max_hits=50):
    """Wrapper di query_algolia per uso web (senza stop_fn e log_fn Tkinter)."""
    stato_map = {
        "aperto":   ["Bandi aperti"],
        "prossimo": ["Bandi prossima apertura"],
        "tutti":    ["Bandi aperti", "Bandi prossima apertura"],
    }
    stato_vals = stato_map.get(stato, ["Bandi aperti"])
    livello_map = {
        "europeo":   "Bandi europei",
        "nazionale": "Bandi nazionali",
        "regionale": "Bandi regionali",
    }
    livello_mapped = livello_map.get(livello, livello)
    filters    = build_filters(stato_vals, livello_mapped, regione, provincia)
    log        = lambda m: None
    stop       = lambda: False
    hits, totale = query_algolia(filters, keyword, log, stop, max_hits=max_hits)
    return hits, totale

def hit_to_card(hit):
    """Converte un hit Algolia in dict per il frontend."""
    sc_str, _ = _scadenza_da_hit(hit)
    taxh  = hit.get("taxonomies_hierarchical", {})
    ag    = (taxh.get("area_geografica") or {})
    lvl0  = (ag.get("lvl0") or [""])[0]
    lvl1  = (ag.get("lvl1") or [""])[0]
    dotaz = _dotazione_da_hit(hit) or "—"
    stato = hit.get("scadenza_testo", "—")
    ben   = beneficiari_da_hit(hit) or "—"
    link  = hit.get("link") or hit.get("url") or hit.get("permalink") or ""
    return {
        "id":          hit.get("objectID", ""),
        "titolo":      hit.get("post_title") or hit.get("title") or "—",
        "stato":       stato,
        "livello":     livello_da_hit(hit),
        "dotazione":   dotaz,
        "scadenza":    sc_str or "—",
        "beneficiari": ben,
        "link_ce":     link,
        "_hit":        hit,
    }

def get_testo_bando(hit):
    """Recupera il testo del bando dalla pagina ContributiEuropa."""
    link_ce = hit.get("link") or hit.get("url") or hit.get("permalink") or ""
    if not link_ce:
        return "", ""
    url, testo = _cerca_fonte_pagina_ce(link_ce, log_fn=None)
    return url, testo

def build_content_web(titolo, hit, testo_ufficiale, fonte_url):
    """Chiama build_content senza log_fn."""
    return build_content(titolo, hit, testo_ufficiale, fonte_url, log_fn=None)
