"""
bandi_engine.py — ItalBandi
Estrae da schede_gui.py tutto ciò che serve per il web:
- query Algolia
- scraping pagina ContributiEuropa
- generazione scheda con Claude API
- build_content per il motore PDF
"""
import os, re, json, time, requests
from datetime import datetime

# ── Credenziali ───────────────────────────────────────────────────────────────
ALGOLIA_APP_ID  = "LHI8XKBFMN"
ALGOLIA_API_KEY = "f55131344ae840ea7f27c6dcb0782654"
ALGOLIA_INDEX   = "ceu_searchable_posts"
ALGOLIA_URL     = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"
ALGOLIA_HEADERS = {
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "X-Algolia-API-Key":        ALGOLIA_API_KEY,
    "Content-Type":             "application/json",
}
ANTHROPIC_API_KEY = os.environ.get("CLAUDE_API_KEY", "")

UFFICIALI_KEYWORDS = [
    ".gov.it", ".regione.", ".provincia.", ".comune.", ".mise.gov",
    ".mef.gov", ".mimit.gov", ".mur.gov", ".invitalia.", ".finlombarda.",
    ".simest.", ".camcom.", "gazzettaufficiale", "normattiva",
    ".inail.", ".anci.", ".agriligurianet.",
]

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
})

JUNK_VALUES = {"null","none","","n/a","nd","n.d.","non specificato",
               "non disponibile","vedi bando","da definire","—","-"}

# ── Utilities ─────────────────────────────────────────────────────────────────

def _is_ufficiale(url):
    return any(k in url.lower() for k in UFFICIALI_KEYWORDS)

def fmt_date(val):
    if not val: return "", None
    if isinstance(val, (int, float)):
        try:
            dt = datetime.fromtimestamp(val)
            return dt.strftime("%d/%m/%Y"), dt
        except: return str(val), None
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
        try:
            dt = datetime.strptime(str(val).strip(), fmt)
            return dt.strftime("%d/%m/%Y"), dt
        except: pass
    s = str(val).strip()
    return (s, None) if len(s) > 3 else ("", None)

def _pulisci(val):
    if not val: return None
    if str(val).strip().lower() in JUNK_VALUES: return None
    return str(val).strip()

def _fetch_text(url):
    try:
        r    = _session.get(url, timeout=15, allow_redirects=True)
        html = r.text
        html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL|re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>',   ' ', html, flags=re.DOTALL|re.IGNORECASE)
        t    = re.sub(r'<[^>]+>', ' ', html)
        return re.sub(r'\s+', ' ', t).strip()
    except: return ""

def _estrai_links_da_html(html):
    return re.findall(r'href=[\'"]?(https?://[^\'">\s]+)[\'"]?', html)

# ── Algolia ───────────────────────────────────────────────────────────────────

def build_filters(stato_vals, livello, regione, provincia):
    parts = []
    if stato_vals:
        sc = " OR ".join(f'scadenza_testo:"{v}"' for v in stato_vals)
        parts.append(f"({sc})")
    if livello == "europeo":
        parts.append('taxonomies_hierarchical.area_geografica.lvl0:"Bandi Europei"')
    elif livello == "nazionale":
        parts.append('taxonomies_hierarchical.area_geografica.lvl0:"Bandi Nazionali"')
    elif livello == "regionale":
        if provincia and provincia != "tutte":
            parts.append(f'taxonomies_hierarchical.area_geografica.lvl1:"{provincia}"')
        elif regione:
            parts.append(f'taxonomies_hierarchical.area_geografica.lvl0:"{regione}"')
    return " AND ".join(parts)

def cerca_bandi(keyword="", stato="aperto", livello="", regione="", provincia="", max_hits=50):
    stato_map = {
        "aperto":   ["Bandi aperti"],
        "prossimo": ["Bandi prossima apertura"],
        "tutti":    ["Bandi aperti", "Bandi prossima apertura"],
    }
    stato_vals = stato_map.get(stato, ["Bandi aperti"])
    filters    = build_filters(stato_vals, livello, regione, provincia)
    payload    = {"query": keyword, "hitsPerPage": max_hits, "page": 0,
                  "filters": filters, "attributesToRetrieve": ["*"]}
    r = requests.post(ALGOLIA_URL, headers=ALGOLIA_HEADERS, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("hits", []), data.get("nbHits", 0)

def hit_to_card(hit):
    """Converte un hit Algolia in dizionario per il frontend."""
    taxh  = hit.get("taxonomies_hierarchical", {})
    ag    = (taxh.get("area_geografica") or {})
    lvl0  = (ag.get("lvl0") or [""])[0]
    lvl1  = (ag.get("lvl1") or [""])[0]
    sc_str, sc_dt = _scadenza_da_hit(hit)

    ben = ""
    for k in ("beneficiari","destinatari","soggetti_ammissibili"):
        v = hit.get(k)
        if v:
            ben = (", ".join(str(x).split("/")[0].strip() for x in v[:3])
                   if isinstance(v, list) else str(v)[:120])
            break

    dotaz = _dotazione_da_hit(hit) or "—"
    stato = hit.get("scadenza_testo", "—")
    link  = hit.get("link") or hit.get("url") or hit.get("permalink") or ""

    return {
        "id":        hit.get("objectID", ""),
        "titolo":    hit.get("post_title") or hit.get("title") or "—",
        "stato":     stato,
        "livello":   lvl1 or lvl0 or "—",
        "dotazione": dotaz,
        "scadenza":  sc_str or "—",
        "beneficiari": ben or "—",
        "link_ce":   link,
        "_hit":      hit,   # hit completo per generazione scheda
    }

# ── Estrazione dati dall'hit ──────────────────────────────────────────────────

def _scadenza_da_hit(hit):
    for campo in ("scadenza","data_scadenza","deadline","data_chiusura","fine","end_date"):
        val = hit.get(campo)
        if val:
            s, dt = fmt_date(val)
            if s: return s, dt
    return "", None

def _dotazione_da_hit(hit):
    for campo in ("dotazione","dotazione_finanziaria","budget","importo",
                  "importo_totale","risorse","finanziamento","stanziamento"):
        val = hit.get(campo)
        if val and str(val).strip() not in ("0","0.0","","[]","{}"):
            v = str(val).strip()
            try:
                n = float(v.replace(",",".").replace(".","").replace(" ",""))
                if n > 0:
                    return f"EUR {n/1_000_000:,.1f} MLN".replace(",",".") if n >= 1_000_000 \
                           else f"EUR {int(n):,}".replace(",",".")
            except: 
                if any(c.isdigit() for c in v): return v[:50]
    return None

def _ente_da_area(area):
    if not area: return "Ente erogatore"
    a = area.lower()
    if "europ" in a: return "Commissione Europea / Fondi UE"
    if "naz"   in a: return "Ministero / Ente nazionale"
    return f"Regione / Ente locale · {area}"

def _cta_da_stato(stato):
    s = (stato or "").lower()
    if "prossima" in s: return "Bando in arrivo: preparati ora con Energelia!"
    if "aperto"   in s or "aperti" in s: return "Bando aperto: agisci ora, siamo a disposizione!"
    return "Contattaci per valutare la tua candidatura!"

def _sintetizza_metrica(campo, valore):
    if not valore or str(valore).strip() in ("—","-",""): return "—"
    v = str(valore).strip()
    c = campo.lower()
    if "intensit" in c or "contributo" in c:
        m = re.search(r'(\d{1,3})\s*%', v)
        if m: return f"{m.group(1)}%"
    if "dotaz" in c or "fondo" in c:
        m = re.search(r'([\d]+(?:[,\.][\d]+)?)\s*(?:milion[ei]|mln)\b', v, re.IGNORECASE)
        if m:
            try: return f"EUR {float(m.group(1).replace(',','.')):.4g} MLN"
            except: pass
    if "scad" in c or "data" in c:
        m = re.search(r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}', v)
        if m: return m.group(0).replace("-","/").replace(".","/")
    if "stato" in c:
        vl = v.lower()
        if "prossima" in vl: return "Pross. apertura"
        if "aperto"   in vl or "aperti" in vl: return "Aperto"
    return v[:18]

def _build_metriche(dotazione, intensita, stato_m, stato_bg, data_label, data_val):
    return [
        {"label": "DOTAZIONE",    "valore": _sintetizza_metrica("dotazione", dotazione), "bg": "blue"},
        {"label": "INTENSITA'",   "valore": _sintetizza_metrica("intensita",  intensita), "bg": "green"},
        {"label": "STATO",        "valore": _sintetizza_metrica("stato",      stato_m),   "bg": stato_bg},
        {"label": data_label or "SCADENZA",
                                  "valore": _sintetizza_metrica("scadenza",   data_val),  "bg": "blue"},
    ]

# ── Scraping pagina ContributiEuropa ─────────────────────────────────────────

def _cerca_fonte_pagina_ce(link_ce):
    if not link_ce: return "", ""
    try:
        r    = _session.get(link_ce, timeout=12)
        html = r.text
        links_uff = list(dict.fromkeys(
            l for l in _estrai_links_da_html(html)
            if _is_ufficiale(l) and "contributieuropa" not in l
        ))
        for link in links_uff[:3]:
            testo = _fetch_text(link)
            if testo and len(testo) > 300:
                return link, testo
        testo_ce = re.sub(r'<[^>]+>', ' ', html)
        testo_ce = re.sub(r'\s+', ' ', testo_ce).strip()
        return link_ce, testo_ce
    except: return "", ""

# ── Claude genera le sezioni della scheda ─────────────────────────────────────

def _genera_scheda_con_claude(titolo, testo_bando):
    if not ANTHROPIC_API_KEY: return {}

    prompt = (
        f'Sei un esperto di finanza agevolata italiana che lavora per Energelia S.r.l.\n\n'
        f'Analizza il seguente testo di un bando. Se mancano dati, cercali online.\n\n'
        f'TITOLO BANDO: "{titolo}"\n\nTESTO:\n{testo_bando[:6000]}\n\n'
        f'Genera i contenuti per la scheda in formato JSON con questa struttura ESATTA.\n'
        f'Ogni bullet deve contenere dati REALI estratti dal bando. Mai placeholder.\n\n'
        '{{\n'
        '  "dotazione": "importo totale fondo o null",\n'
        '  "intensita": "percentuale e tipo o null",\n'
        '  "contributo_max": "importo massimo per beneficiario o null",\n'
        '  "scadenza": "DD/MM/YYYY o null",\n'
        '  "apertura": "DD/MM/YYYY o null",\n'
        '  "ente_finalita": ["Nome ente", "Obiettivo", "Contesto"],\n'
        '  "chi_partecipa": ["Beneficiari", "Requisiti chiave", "Esclusioni"],\n'
        '  "cosa_finanziabile": ["Investimenti ammissibili", "Voci di spesa", "Spese premiali"],\n'
        '  "spese_non_ammissibili": ["Spese escluse", "IVA", "Spese ante-ammissione"],\n'
        '  "contributo_voci": ["Intensita con valori", "Contributo max", "Scaglioni"],\n'
        '  "criteri_valutazione": ["Tipo procedura", "Criteri con punteggi", "Documentazione"],\n'
        '  "fasi_tempi": ["Apertura: data", "Scadenza: data", "Rendicontazione"],\n'
        '  "come_presentare": ["Portale specifico", "Credenziali richieste", "Allegati obbligatori"],\n'
        '  "perche_interessante": ["Punto forza 1", "Punto forza 2", "Punto forza 3"],\n'
        '  "criticita": ["Vincolo 1", "Vincolo 2", "Scadenze da rispettare"]\n'
        '}}\n\nRispondi SOLO con JSON valido. Nessun testo prima o dopo.'
    )

    for tentativo in range(3):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 2000,
                      "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=120,
            )
            if resp.status_code == 429:
                time.sleep((tentativo+1)*8); continue
            if resp.status_code != 200: return {}

            blocks = resp.json().get("content", [])
            testo  = "\n".join(b.get("text","") for b in blocks if b.get("type")=="text").strip()
            if not testo: return {}

            raw   = re.sub(r'```(?:json)?\s*', '', testo)
            raw   = re.sub(r'```', '', raw)
            raw   = re.sub(r'</?[a-zA-Z:][^>]*>', '', raw).strip()
            start = raw.find('{'); end = raw.rfind('}')
            if start == -1 or end == -1: return {}
            return json.loads(raw[start:end+1])

        except json.JSONDecodeError: return {}
        except: return {}
    return {}

# ── build_content: assembla il dict per il motore PDF ─────────────────────────

def build_content(titolo, hit, testo_ufficiale, fonte_url, mese_anno=None):
    hit       = hit or {}
    mese_anno = mese_anno or datetime.now().strftime("%B %Y")
    stato     = hit.get("scadenza_testo", "")

    sc_alg, _ = _scadenza_da_hit(hit)
    taxh  = hit.get("taxonomies_hierarchical", {})
    areas = (taxh.get("area_geografica") or {}).get("lvl0") or []
    area  = areas[0] if areas else ""
    ente_alg = _ente_da_area(area)

    cl = _genera_scheda_con_claude(titolo, testo_ufficiale) if testo_ufficiale else {}

    def cv(key, fallback=None):
        v = cl.get(key)
        if isinstance(v, list):
            return [x for x in v if x and str(x).strip()] or (fallback if isinstance(fallback, list) else [])
        if v and str(v).strip() not in ("null","None","","—","-"):
            return str(v).strip()
        return fallback

    dotazione = cv("dotazione", _dotazione_da_hit(hit))
    intensita = cv("intensita")
    scadenza  = cv("scadenza", sc_alg)
    apertura  = cv("apertura")

    _, sc_dt = fmt_date(scadenza) if scadenza else (None, None)
    if sc_dt and sc_dt < datetime.now() and "prossima" in stato.lower():
        stato = "Bandi chiusi"

    if scadenza:
        data_label, data_val = "SCADENZA", scadenza
    elif apertura:
        data_label, data_val = "APERTURA", apertura
    else:
        data_label, data_val = "SCADENZA", None

    stato_bg = "blue" if "prossima" in stato.lower() else "orange"

    def sez(key, fallback):
        voci = cv(key, [])
        return voci if voci else fallback

    def pulisci(lst):
        return [str(x).strip() for x in lst if x and str(x).strip() not in ("None","null","—","-","")]

    return {
        "titolo":      titolo.upper(),
        "sottotitolo": " · ".join(v for v in [ente_alg, area, stato] if v),
        "metriche":    _build_metriche(dotazione, intensita, stato or "Aperto", stato_bg, data_label, data_val),
        "sinistra": [
            {"titolo": "ENTE / FINALITA'",      "voci": pulisci(sez("ente_finalita",       [ente_alg]))},
            {"titolo": "CHI PUO' PARTECIPARE",  "voci": pulisci(sez("chi_partecipa",       ["Verificare requisiti sul bando"]))},
            {"titolo": "COSA E' FINANZIABILE",  "voci": pulisci(sez("cosa_finanziabile",   ["Verificare spese ammissibili"]))},
            {"titolo": "SPESE NON AMMISSIBILI", "voci": pulisci(sez("spese_non_ammissibili",["IVA (salvo casi specifici)","Spese ante-ammissione"]))},
        ],
        "tabella_contributi": None,
        "destra": [
            {"titolo": "CONTRIBUTO / INTENSITA'", "voci": pulisci(sez("contributo_voci",    [f"Intensita': {intensita}" if intensita else "Verificare sul bando"]))},
            {"titolo": "CRITERI / VALUTAZIONE",   "voci": pulisci(sez("criteri_valutazione",["Verificare procedura e criteri"]))},
            {"titolo": "FASI E TEMPI",            "voci": pulisci(sez("fasi_tempi",          [f"Scadenza: {scadenza}" if scadenza else "Verificare"]))},
            {"titolo": "COME PRESENTARE",         "voci": pulisci(sez("come_presentare",    ["Contatta Energelia per supporto"]))},
        ],
        "punti_forza": pulisci(sez("perche_interessante", [f"Contributo: {intensita}" if intensita else "Verificare"])),
        "criticita":   pulisci(sez("criticita", ["Verificare requisiti soggettivi","Controllare cumulabilita'"])),
        "cta_testo":   _cta_da_stato(stato),
        "cta_tel":     "Tel. 010 8078800",
        "cta_email":   "a.augusti@energelia.it",
        "fonte":       f"Fonte: {fonte_url[:80]}" if fonte_url else "Fonte: bando ufficiale",
        "mese_anno":   mese_anno,
    }

def get_testo_bando(hit):
    """Recupera il testo del bando dalla pagina ContributiEuropa."""
    link_ce = hit.get("link") or hit.get("url") or hit.get("permalink") or ""
    if not link_ce: return "", ""
    url, testo = _cerca_fonte_pagina_ce(link_ce)
    return url, testo
