"""
bandi_engine.py — ItalBandi
Flusso pulito:
  1. Titolo bando da Algolia (già nel browser)
  2. Claude cerca il bando su Google con web_search
  3. Se trova link ufficiale (decreto/PDF/.gov) lo legge
  4. Genera JSON con il prompt Energelia
  5. Restituisce content dict per schede_engine.generate()
"""
import requests, os, re, json, time
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

# ── Algolia helpers ───────────────────────────────────────────────────────────

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


def cerca_bandi_web(keyword="", stato="aperto", livello="", regione="", provincia="", max_hits=50):
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
    stato_vals     = stato_map.get(stato, ["Bandi aperti"])
    livello_mapped = livello_map.get(livello, livello)
    filters        = build_filters(stato_vals, livello_mapped, regione, provincia)

    payload = {"query": keyword, "hitsPerPage": max_hits, "page": 0,
               "filters": filters, "attributesToRetrieve": ["*"]}
    r = requests.post(ALGOLIA_URL, headers=ALGOLIA_HEADERS, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("hits", []), data.get("nbHits", 0)


# ── Hit → card per il frontend ────────────────────────────────────────────────

def _fmt_date(val):
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
    s = str(val).strip()
    return (s, None) if len(s) > 3 else ("", None)


def _scadenza_da_hit(hit):
    for campo in ("scadenza", "data_scadenza", "deadline", "data_chiusura", "fine", "end_date"):
        val = hit.get(campo)
        if val:
            s, dt = _fmt_date(val)
            if s:
                return s, dt
    return "", None


def _dotazione_da_hit(hit):
    for campo in ("dotazione", "dotazione_finanziaria", "budget", "importo",
                  "importo_totale", "risorse", "finanziamento", "stanziamento"):
        val = hit.get(campo)
        if val and str(val).strip() not in ("0", "0.0", "", "[]", "{}"):
            v = str(val).strip()
            try:
                n = float(v.replace(",", ".").replace(".", "").replace(" ", ""))
                if n > 0:
                    return f"EUR {n/1_000_000:,.1f} MLN".replace(",", ".") if n >= 1_000_000 \
                           else f"EUR {int(n):,}".replace(",", ".")
            except ValueError:
                if any(c.isdigit() for c in v):
                    return v[:50]
    return None


def _beneficiari_da_hit(hit):
    for k in ("beneficiari", "destinatari", "soggetti_ammissibili"):
        val = hit.get(k)
        if val:
            if isinstance(val, list):
                return ", ".join(str(x).split("/")[0].strip() for x in val[:3])
            if isinstance(val, str) and val.strip():
                return val.strip()[:120]
    return ""


def _livello_da_hit(hit):
    taxh = hit.get("taxonomies_hierarchical", {})
    ag   = taxh.get("area_geografica", {}) or {}
    lvl0 = (ag.get("lvl0") or [])
    lvl1 = (ag.get("lvl1") or [])
    if not lvl0:
        return "—"
    area = lvl0[0]
    if "Europei" in area:   return "Europeo"
    if "Nazionali" in area: return "Nazionale"
    geo = lvl1[0].replace("Provincia di ", "") if lvl1 else area
    return f"Regionale · {geo}"


def hit_to_card(hit):
    sc_str, _ = _scadenza_da_hit(hit)
    return {
        "id":          hit.get("objectID", ""),
        "titolo":      hit.get("post_title") or hit.get("title") or "—",
        "stato":       hit.get("scadenza_testo", "—"),
        "livello":     _livello_da_hit(hit),
        "dotazione":   _dotazione_da_hit(hit) or "—",
        "scadenza":    sc_str or "—",
        "beneficiari": _beneficiari_da_hit(hit) or "—",
        "_hit":        hit,
    }


# ── CUORE: Claude cerca il bando e genera la scheda ──────────────────────────

def _genera_con_claude(titolo, stato_bando):
    """
    Claude cerca il bando su Google, legge le fonti ufficiali se disponibili,
    e genera tutte le sezioni della scheda in JSON.
    """
    if not ANTHROPIC_API_KEY:
        return {}

    stato_cta = "prossima apertura" if "prossima" in stato_bando.lower() else "aperto"

    prompt = f"""Sei un esperto di finanza agevolata italiana che lavora per Energelia S.r.l.

Devi creare la scheda informativa del seguente bando:

TITOLO BANDO: "{titolo}"
STATO: {stato_bando}

ISTRUZIONI:
1. Cerca informazioni complete su questo bando usando web_search
2. Se trovi un link a decreto ufficiale, PDF ministeriale o sito .gov.it/.regione.it, leggilo
3. Usa SOLO dati reali trovati — mai placeholder come "verificare sul bando"
4. Genera la scheda in formato JSON con questa struttura ESATTA:

{{
  "sottotitolo": "Ente erogatore · riferimento normativo · tipo contributo · stato",
  "dotazione": "importo totale fondo es. EUR 5 MLN oppure null",
  "intensita": "es. 60% fondo perduto oppure null",
  "contributo_max": "es. EUR 150.000 oppure null",
  "investimento_range": "es. 60k - 500k oppure null",
  "data_metrica": "es. scadenza 15/12/2026 oppure prossima apertura",
  "label_data": "SCADENZA oppure APERTURA",
  "ente_finalita": ["Ente erogatore preciso", "Obiettivo del bando", "Contesto normativo"],
  "chi_partecipa": ["Tipologia beneficiari", "Requisiti chiave", "Eventuali esclusioni"],
  "cosa_finanziabile": ["Intervento 1", "Intervento 2", "Intervento 3"],
  "spese_ammissibili": ["Spesa 1", "Spesa 2", "Spesa 3", "Spesa 4"],
  "struttura_agevolazione": [["Voce", "Valore"], ["Intensita fondo perduto", "X%"], ["Contributo massimo", "EUR X"]],
  "criteri_valutazione": ["Tipo procedura", "Criterio 1", "Criterio 2"],
  "fasi_tempi": ["Apertura: data", "Scadenza: data", "Rendicontazione: tempi"],
  "come_presentare": ["Portale specifico", "Credenziali richieste", "Allegati obbligatori"],
  "perche_interessante": ["Punto forza 1 concreto", "Punto forza 2 concreto", "Punto forza 3 concreto"],
  "criticita": ["Vincolo 1 reale", "Vincolo 2 reale", "Vincolo 3 reale"],
  "cta_testo": "Frase CTA personalizzata per questo bando",
  "fonte": "Fonte: ente/decreto/riferimento ufficiale trovato"
}}

Rispondi SOLO con JSON valido. Nessun testo prima o dopo."""

    for tentativo in range(3):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      "claude-haiku-4-5-20251001",
                    "max_tokens": 2500,
                    "tools":      [{"type": "web_search_20250305", "name": "web_search"}],
                    "messages":   [{"role": "user", "content": prompt}],
                },
                timeout=120,
            )

            if resp.status_code == 429:
                time.sleep((tentativo + 1) * 10)
                continue
            if resp.status_code != 200:
                return {}

            blocks = resp.json().get("content", [])
            testo  = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
            if not testo:
                return {}

            raw   = re.sub(r'```(?:json)?\s*', '', testo)
            raw   = re.sub(r'```', '', raw).strip()
            start = raw.find('{')
            end   = raw.rfind('}')
            if start == -1 or end == -1:
                return {}

            return json.loads(raw[start:end+1])

        except (json.JSONDecodeError, Exception):
            return {}

    return {}


# ── Costruisce il CONTENT dict per schede_engine ─────────────────────────────

def _pulisci(lst):
    return [str(x).strip() for x in (lst or [])
            if x and str(x).strip() not in ("", "None", "null", "—", "-")]


def _sintetizza(val, max_len=16):
    if not val or str(val).strip() in ("—", "-", "", "null", "None"):
        return "—"
    v = str(val).strip()
    if len(v) <= max_len:
        return v
    return v[:max_len].rstrip() + "…"


def genera_scheda_web(hit):
    """
    Punto di ingresso principale per la generazione scheda dal web.
    Restituisce (content_dict, titolo).
    """
    titolo      = hit.get("post_title", "") or hit.get("title", "") or "Bando"
    stato_bando = hit.get("scadenza_testo", "Bandi aperti")
    sc_str, _   = _scadenza_da_hit(hit)
    dotaz_hit   = _dotazione_da_hit(hit)

    # Estrai area geografica
    taxh  = hit.get("taxonomies_hierarchical", {})
    ag    = taxh.get("area_geografica", {}) or {}
    lvl0  = (ag.get("lvl0") or [""])[0]
    lvl1  = (ag.get("lvl1") or [""])[0]
    area  = lvl1 or lvl0 or ""

    # Claude cerca e popola
    cl = _genera_con_claude(titolo, stato_bando)

    def cv(key, fallback=None):
        v = cl.get(key)
        if isinstance(v, list):
            return v if v else (fallback or [])
        if v and str(v).strip() not in ("", "None", "null", "—", "-"):
            return str(v).strip()
        return fallback

    # Metriche
    dotazione  = cv("dotazione",       dotaz_hit or "—")
    intensita  = cv("intensita",       "—")
    contr_max  = cv("contributo_max",  "—")
    inv_range  = cv("investimento_range", "—")
    data_val   = cv("data_metrica",    sc_str or "—")
    label_data = cv("label_data",      "SCADENZA")

    # Usa contributo_max come seconda metrica se intensita non disponibile
    met2_label = "CONTRIBUTO MAX" if contr_max != "—" else "INTENSITA'"
    met2_val   = contr_max if contr_max != "—" else intensita
    met3_label = "INVESTIMENTO"
    met3_val   = inv_range if inv_range != "—" else intensita

    metriche = [
        {"label": "DOTAZIONE",  "valore": _sintetizza(dotazione),  "bg": "blue"},
        {"label": met2_label,   "valore": _sintetizza(met2_val),   "bg": "orange"},
        {"label": met3_label,   "valore": _sintetizza(met3_val),   "bg": "green"},
        {"label": label_data,   "valore": _sintetizza(data_val),   "bg": "blue"},
    ]

    # Sezioni
    sottotitolo = cv("sottotitolo", f"{area} · {stato_bando}" if area else stato_bando)
    
    # Tabella contributi se disponibile
    tab_contrib = cv("struttura_agevolazione")
    tabella = None
    if isinstance(tab_contrib, list) and len(tab_contrib) > 1:
        tabella = tab_contrib

    # Sinistra
    sinistra = [
        {"titolo": "ENTE / FINALITA'",      "voci": _pulisci(cv("ente_finalita", []))},
        {"titolo": "CHI PUO' PARTECIPARE",  "voci": _pulisci(cv("chi_partecipa", []))},
        {"titolo": "COSA E' FINANZIABILE",  "voci": _pulisci(cv("cosa_finanziabile", []))},
        {"titolo": "SPESE AMMISSIBILI",     "voci": _pulisci(cv("spese_ammissibili", []))},
    ]

    # Destra
    destra = [
        {"titolo": "CRITERI / VALUTAZIONE", "voci": _pulisci(cv("criteri_valutazione", []))},
        {"titolo": "FASI E TEMPI",          "voci": _pulisci(cv("fasi_tempi", []))},
        {"titolo": "COME PRESENTARE",       "voci": _pulisci(cv("come_presentare", []))},
    ]

    # CTA personalizzata
    cta_testo = cv("cta_testo",
        "Bando aperto: agisci ora, siamo a disposizione!" if "aperto" in stato_bando.lower()
        else "Bando in arrivo: preparati ora con Energelia!")

    fonte = cv("fonte", f"Elaborato da Energelia S.r.l. · {datetime.now().strftime('%B %Y')}")

    content = {
        "titolo":             titolo.upper(),
        "sottotitolo":        sottotitolo,
        "metriche":           metriche,
        "sinistra":           sinistra,
        "tabella_contributi": tabella,
        "destra":             destra,
        "punti_forza":        _pulisci(cv("perche_interessante", [])),
        "criticita":          _pulisci(cv("criticita", [])),
        "cta_testo":          cta_testo,
        "cta_tel":            "Tel. 010 8078800",
        "cta_email":          "a.augusti@energelia.it",
        "fonte":              fonte,
        "mese_anno":          datetime.now().strftime("%B %Y"),
    }

    return content, titolo
