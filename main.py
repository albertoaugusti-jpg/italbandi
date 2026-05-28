"""
bandi_engine.py — ItalBandi
Ricerca bandi su ContributiEuropa (Algolia) e generazione schede PDF via Claude.
"""
import os, re, json, time, requests
from datetime import datetime

# ── Credenziali ───────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")

ALGOLIA_APP_ID  = "LHI8XKBFMN"
ALGOLIA_API_KEY = "f55131344ae840ea7f27c6dcb0782654"
ALGOLIA_INDEX   = "ceu_searchable_posts"
ALGOLIA_URL     = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"
ALGOLIA_HEADERS = {
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "X-Algolia-API-Key":        ALGOLIA_API_KEY,
    "Content-Type":             "application/json",
}


# ── 1. RICERCA ALGOLIA ────────────────────────────────────────────────────────

def cerca_bandi_web(keyword="", stato="aperto", livello="", regione="",
                    provincia="", max_hits=50, solo_titolo=False):
    stato_map = {
        "aperto":   ["Bandi aperti"],
        "prossimo": ["Bandi prossima apertura"],
        "tutti":    ["Bandi aperti", "Bandi prossima apertura"],
    }
    livello_map = {
        "europeo":   "Bandi europei",
        "nazionale": "Bandi nazionali",
        "regionale": "Bandi regionali",
    }

    parts = []
    sc = stato_map.get(stato, ["Bandi aperti"])
    parts.append("(" + " OR ".join(f'scadenza_testo:"{v}"' for v in sc) + ")")

    lv = livello_map.get(livello, "")
    if lv == "Bandi europei":
        parts.append('taxonomies_hierarchical.area_geografica.lvl0:"Bandi Europei"')
    elif lv == "Bandi nazionali":
        parts.append('taxonomies_hierarchical.area_geografica.lvl0:"Bandi Nazionali"')
    elif lv == "Bandi regionali":
        if provincia and provincia != "(tutte)":
            parts.append(f'taxonomies_hierarchical.area_geografica.lvl1:"{provincia}"')
        elif regione:
            parts.append(f'taxonomies_hierarchical.area_geografica.lvl0:"{regione}"')

    payload = {
        "query": keyword,
        "hitsPerPage": max_hits,
        "page": 0,
        "filters": " AND ".join(parts),
        "attributesToRetrieve": ["*"],
    }
    if solo_titolo and keyword:
        payload["restrictSearchableAttributes"] = ["post_title"]

    r = requests.post(ALGOLIA_URL, headers=ALGOLIA_HEADERS, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("hits", []), data.get("nbHits", 0)


# ── 2. HIT → CARD ─────────────────────────────────────────────────────────────

def _fmt_date(val):
    if not val:
        return ""
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val).strftime("%d/%m/%Y")
        except:
            return str(val)
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
        try:
            return datetime.strptime(str(val).strip(), fmt).strftime("%d/%m/%Y")
        except:
            pass
    s = str(val).strip()
    return s if len(s) > 3 else ""


def _scadenza(hit):
    for k in ("scadenza", "data_scadenza", "deadline", "data_chiusura", "fine", "end_date"):
        v = hit.get(k)
        if v:
            s = _fmt_date(v)
            if s:
                return s
    return ""


def _dotazione(hit):
    for k in ("dotazione", "dotazione_finanziaria", "budget", "importo",
               "importo_totale", "risorse", "finanziamento"):
        v = hit.get(k)
        if v and str(v).strip() not in ("0", "0.0", "", "[]", "{}"):
            s = str(v).strip()
            try:
                n = float(s.replace(",", ".").replace(".", "").replace(" ", ""))
                if n > 0:
                    if n >= 1_000_000:
                        return f"EUR {n/1_000_000:.1f} MLN"
                    return f"EUR {int(n):,}".replace(",", ".")
            except:
                if any(c.isdigit() for c in s):
                    return s[:50]
    return None


def _beneficiari(hit):
    for k in ("beneficiari", "destinatari", "soggetti_ammissibili"):
        v = hit.get(k)
        if v:
            if isinstance(v, list):
                return ", ".join(str(x).split("/")[0].strip() for x in v[:3])
            if isinstance(v, str) and v.strip():
                return v.strip()[:120]
    return ""


def _livello(hit):
    ag   = (hit.get("taxonomies_hierarchical") or {}).get("area_geografica") or {}
    lvl0 = ag.get("lvl0") or []
    lvl1 = ag.get("lvl1") or []
    if not lvl0:
        return "—"
    area = lvl0[0]
    if "Europei"   in area: return "Europeo"
    if "Nazionali" in area: return "Nazionale"
    geo = lvl1[0].replace("Provincia di ", "") if lvl1 else area
    return f"Regionale · {geo}"


def hit_to_card(hit):
    return {
        "id":          hit.get("objectID", ""),
        "titolo":      hit.get("post_title") or hit.get("title") or "—",
        "stato":       hit.get("scadenza_testo", "—"),
        "livello":     _livello(hit),
        "dotazione":   _dotazione(hit) or "—",
        "scadenza":    _scadenza(hit) or "—",
        "beneficiari": _beneficiari(hit) or "—",
        "_hit":        hit,
    }


# ── 3. CHIAMATA CLAUDE ────────────────────────────────────────────────────────

def _chiedi_claude(titolo, testo, stato_bando, usa_web_search=False):
    """
    Chiede a Claude di generare il JSON della scheda.
    - Se usa_web_search=True: Claude cerca il bando online (più costoso)
    - Se usa_web_search=False: Claude usa il testo passato (economico)
    Restituisce un dict (può contenere _api_error).
    """
    if not ANTHROPIC_API_KEY:
        return {"_api_error": "API key mancante"}

    if usa_web_search:
        istruzioni = f"""Usa web_search per cercare questo bando e trovare informazioni complete.
URL bando: {testo}
Cerca dati reali: importi, percentuali, date, beneficiari."""
    else:
        istruzioni = f"""Analizza il testo del bando qui sotto ed estrai tutte le informazioni.

TESTO DEL BANDO:
{testo[:8000]}"""

    prompt = f"""Sei un esperto di finanza agevolata italiana di Energelia S.r.l.

BANDO: {titolo}
STATO: {stato_bando}

{istruzioni}

Genera un JSON con questa struttura. Rispondi SOLO con il JSON, senza testo prima o dopo, senza blocchi di codice:

{{
  "sottotitolo": "Ente erogatore - riferimento normativo - tipo agevolazione - {stato_bando}",
  "dotazione": "importo totale es. EUR 5 MLN oppure null",
  "intensita": "es. 60% fondo perduto oppure null",
  "contributo_max": "es. EUR 150.000 oppure null",
  "data_scadenza": "DD/MM/YYYY oppure null",
  "ente_finalita": ["voce 1", "voce 2", "voce 3"],
  "chi_partecipa": ["voce 1", "voce 2", "voce 3"],
  "cosa_finanziabile": ["voce 1", "voce 2", "voce 3"],
  "spese_non_ammissibili": ["voce 1", "voce 2", "voce 3"],
  "contributo_voci": ["voce 1", "voce 2", "voce 3"],
  "criteri_valutazione": ["voce 1", "voce 2", "voce 3"],
  "fasi_tempi": ["voce 1", "voce 2", "voce 3"],
  "come_presentare": ["voce 1", "voce 2", "voce 3"],
  "perche_interessante": ["voce 1", "voce 2", "voce 3"],
  "criticita": ["voce 1", "voce 2", "voce 3"],
  "cta_testo": "frase call to action per questo bando",
  "fonte_ufficiale": "ente o riferimento normativo"
}}"""

    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }
    if usa_web_search:
        payload["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

    for tentativo in range(3):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=120 if usa_web_search else 60,
            )

            if resp.status_code == 429:
                time.sleep((tentativo + 1) * 10)
                continue

            if resp.status_code != 200:
                return {"_api_error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

            # Estrai testo dalla risposta
            blocks = resp.json().get("content", [])
            testo_r = "\n".join(
                b.get("text", "") for b in blocks if b.get("type") == "text"
            ).strip()

            if not testo_r:
                return {"_api_error": "risposta vuota"}

            # Pulisci e parsa il JSON
            # Rimuovi eventuale code block markdown
            testo_r = testo_r.replace("```json", "").replace("```", "").strip()

            # Trova il JSON nel testo
            s = testo_r.find("{")
            e = testo_r.rfind("}") + 1
            if s == -1 or e == 0:
                return {"_api_error": f"no JSON trovato: {testo_r[:100]}"}

            chunk = testo_r[s:e]

            # Tentativo 1: parse diretto
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                pass

            # Tentativo 2: rimuovi newline non escaped e virgole finali
            try:
                c = chunk.replace("\n", " ").replace("\r", " ")
                c = re.sub(r",\s*([}\]])", r"\1", c)
                return json.loads(c)
            except json.JSONDecodeError:
                pass

            # Tentativo 3: escape backslash spuri
            try:
                c = re.sub(r"\\(?![\"\\\/bfnrtu])", r"\\\\", chunk)
                c = c.replace("\n", " ").replace("\r", " ")
                c = re.sub(r",\s*([}\]])", r"\1", c)
                return json.loads(c)
            except json.JSONDecodeError as ex:
                return {"_api_error": f"JSON non parsabile: {ex}"}

        except Exception as ex:
            return {"_api_error": str(ex)}

    return {"_api_error": "max tentativi raggiunto"}


# ── 4. ASSEMBLA CONTENT PER schede_engine ─────────────────────────────────────

def _val(d, key, fallback=None):
    """Estrae un valore dal dict Claude, con fallback."""
    v = d.get(key)
    if v is None:
        return fallback
    if isinstance(v, list):
        return v if v else (fallback or [])
    s = str(v).strip()
    if s in ("", "null", "None", "—", "-"):
        return fallback
    return s


def _voci(d, key):
    """Estrae una lista di voci pulite."""
    v = d.get(key)
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v
            if x and str(x).strip() not in ("", "null", "None", "—", "-")]


def _sintetizza(val, max_len=16):
    """Tronca un valore per le metriche."""
    if not val or str(val).strip() in ("—", "-", "", "null", "None"):
        return "—"
    v = str(val).strip()
    return v if len(v) <= max_len else v[:max_len].rstrip() + "…"


def _assembla_content(hit, cl):
    """Costruisce il dict content che schede_engine.generate() si aspetta."""
    titolo      = hit.get("post_title", "") or hit.get("title", "") or "Bando"
    stato_bando = hit.get("scadenza_testo", "Bandi aperti")

    # Dati dall'hit Algolia come fallback
    scad_hit  = _scadenza(hit)
    dotaz_hit = _dotazione(hit)

    # Dati da Claude
    dotazione   = _val(cl, "dotazione",     dotaz_hit or "—")
    intensita   = _val(cl, "intensita",     "—")
    contr_max   = _val(cl, "contributo_max","—")
    data_val    = _val(cl, "data_scadenza", scad_hit or "—")
    sottotitolo = _val(cl, "sottotitolo",   stato_bando)
    cta_testo   = _val(cl, "cta_testo",
                       "Bando aperto: agisci ora!" if "aperto" in stato_bando.lower()
                       else "Preparati ora con Energelia!")
    fonte       = _val(cl, "fonte_ufficiale",
                       f"Elaborato da Energelia S.r.l. · {datetime.now().strftime('%B %Y')}")

    stato_bg = "blue" if "prossima" in stato_bando.lower() else "orange"

    return {
        "titolo":      titolo.upper(),
        "sottotitolo": sottotitolo,
        "metriche": [
            {"label": "DOTAZIONE",     "valore": _sintetizza(dotazione),  "bg": "blue"},
            {"label": "INTENSITA'",    "valore": _sintetizza(intensita),  "bg": "orange"},
            {"label": "CONTRIBUTO MAX","valore": _sintetizza(contr_max),  "bg": "green"},
            {"label": "SCADENZA",      "valore": _sintetizza(data_val),   "bg": stato_bg},
        ],
        "sinistra": [
            {"titolo": "ENTE / FINALITA'",      "voci": _voci(cl, "ente_finalita")},
            {"titolo": "CHI PUO' PARTECIPARE",  "voci": _voci(cl, "chi_partecipa")},
            {"titolo": "COSA E' FINANZIABILE",  "voci": _voci(cl, "cosa_finanziabile")},
            {"titolo": "SPESE NON AMMISSIBILI", "voci": _voci(cl, "spese_non_ammissibili")},
        ],
        "tabella_contributi": cl.get("tabella_contributi")
            if isinstance(cl.get("tabella_contributi"), dict) else None,
        "destra": [
            {"titolo": "CONTRIBUTO / INTENSITA'", "voci": _voci(cl, "contributo_voci")},
            {"titolo": "CRITERI / VALUTAZIONE",   "voci": _voci(cl, "criteri_valutazione")},
            {"titolo": "FASI E TEMPI",            "voci": _voci(cl, "fasi_tempi")},
            {"titolo": "COME PRESENTARE",         "voci": _voci(cl, "come_presentare")},
        ],
        "punti_forza": _voci(cl, "perche_interessante"),
        "criticita":   _voci(cl, "criticita"),
        "cta_testo":   cta_testo,
        "cta_tel":     "Tel. 010 8078800",
        "cta_email":   "a.augusti@energelia.it",
        "fonte":       f"Elaborato da Energelia S.r.l. · {datetime.now().strftime('%B %Y')}",
        "mese_anno":   datetime.now().strftime("%B %Y"),
        "_api_error":  cl.get("_api_error", ""),
    }


# ── 5. ENTRY POINT ────────────────────────────────────────────────────────────

def genera_scheda_da_testo(hit, testo_cache):
    """Genera scheda usando testo già disponibile. Economico (~1-2 cent)."""
    titolo      = hit.get("post_title", "") or hit.get("title", "") or "Bando"
    stato_bando = hit.get("scadenza_testo", "Bandi aperti")
    cl = _chiedi_claude(titolo, testo_cache, stato_bando, usa_web_search=False)
    return _assembla_content(hit, cl), titolo


def genera_scheda_web(hit):
    """Genera scheda con web search. Più completo ma costoso (~12 cent)."""
    titolo      = hit.get("post_title", "") or hit.get("title", "") or "Bando"
    stato_bando = hit.get("scadenza_testo", "Bandi aperti")
    url_bando   = hit.get("permalink", "") or hit.get("link", "") or hit.get("url", "")
    cl = _chiedi_claude(titolo, url_bando, stato_bando, usa_web_search=True)
    return _assembla_content(hit, cl), titolo
