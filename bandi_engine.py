"""
bandi_engine.py — ItalBandi
Flusso: titolo + URL bando → Claude legge e genera scheda
"""
import requests, os, re, json, time
from datetime import datetime

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

# ── Algolia: ricerca bandi ────────────────────────────────────────────────────

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


def cerca_bandi_web(keyword="", stato="aperto", livello="", regione="", provincia="", max_hits=50, solo_titolo=False):
    stato_map   = {"aperto": ["Bandi aperti"], "prossimo": ["Bandi prossima apertura"], "tutti": ["Bandi aperti","Bandi prossima apertura"]}
    livello_map = {"europeo": "Bandi europei", "nazionale": "Bandi nazionali", "regionale": "Bandi regionali"}
    filters = build_filters(stato_map.get(stato, ["Bandi aperti"]), livello_map.get(livello, livello), regione, provincia)
    payload = {"query": keyword, "hitsPerPage": max_hits, "page": 0,
               "filters": filters, "attributesToRetrieve": ["*"]}
    if solo_titolo and keyword:
        payload["restrictSearchableAttributes"] = ["post_title"]
    r = requests.post(ALGOLIA_URL, headers=ALGOLIA_HEADERS, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("hits", []), data.get("nbHits", 0)


# ── Dati dall'hit ─────────────────────────────────────────────────────────────

def _fmt_date(val):
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


def _scadenza_da_hit(hit):
    for c in ("scadenza","data_scadenza","deadline","data_chiusura","fine","end_date"):
        val = hit.get(c)
        if val:
            s, dt = _fmt_date(val)
            if s: return s, dt
    return "", None


def _dotazione_da_hit(hit):
    for c in ("dotazione","dotazione_finanziaria","budget","importo","importo_totale","risorse","finanziamento"):
        val = hit.get(c)
        if val and str(val).strip() not in ("0","0.0","","[]","{}"):
            v = str(val).strip()
            try:
                n = float(v.replace(",",".").replace(".","").replace(" ",""))
                if n > 0:
                    return f"EUR {n/1_000_000:,.1f} MLN".replace(",",".") if n>=1_000_000 else f"EUR {int(n):,}".replace(",",".")
            except: 
                if any(c.isdigit() for c in v): return v[:50]
    return None


def _beneficiari_da_hit(hit):
    for k in ("beneficiari","destinatari","soggetti_ammissibili"):
        val = hit.get(k)
        if val:
            if isinstance(val, list): return ", ".join(str(x).split("/")[0].strip() for x in val[:3])
            if isinstance(val, str) and val.strip(): return val.strip()[:120]
    return ""


def _livello_da_hit(hit):
    taxh = hit.get("taxonomies_hierarchical", {})
    ag   = taxh.get("area_geografica", {}) or {}
    lvl0 = (ag.get("lvl0") or [])
    lvl1 = (ag.get("lvl1") or [])
    if not lvl0: return "—"
    area = lvl0[0]
    if "Europei"   in area: return "Europeo"
    if "Nazionali" in area: return "Nazionale"
    geo = lvl1[0].replace("Provincia di ","") if lvl1 else area
    return f"Regionale · {geo}"


def hit_to_card(hit):
    sc_str, _ = _scadenza_da_hit(hit)
    return {
        "id":          hit.get("objectID",""),
        "titolo":      hit.get("post_title") or hit.get("title") or "—",
        "stato":       hit.get("scadenza_testo","—"),
        "livello":     _livello_da_hit(hit),
        "dotazione":   _dotazione_da_hit(hit) or "—",
        "scadenza":    sc_str or "—",
        "beneficiari": _beneficiari_da_hit(hit) or "—",
        "_hit":        hit,
    }


# ── Claude legge il bando e genera la scheda ─────────────────────────────────

def _chiedi_a_claude(titolo, url_bando, stato_bando):
    """
    Passa titolo + URL a Claude.
    Claude usa web_search per leggere la pagina e la documentazione ufficiale.
    Genera JSON con tutte le sezioni della scheda Energelia.
    """
    if not ANTHROPIC_API_KEY:
        return {}

    url_info = f"\nURL della pagina del bando: {url_bando}" if url_bando else ""

    prompt = f"""Sei un esperto di finanza agevolata italiana di Energelia S.r.l.

BANDO DA ANALIZZARE:
Titolo: {titolo}
Stato: {stato_bando}{url_info}

ISTRUZIONI:
1. Usa web_search per cercare questo bando e trovare informazioni complete
2. Se trovi un link a documentazione ufficiale (decreto, PDF su .gov.it o .regione.it), leggilo
3. Raccogli TUTTI i dati numerici reali: importi, percentuali, date, limiti
4. Non usare mai "verificare sul bando" o placeholder — solo dati reali trovati

Genera la scheda in JSON con questa struttura ESATTA:
{{
  "sottotitolo": "Ente erogatore · riferimento normativo · tipo agevolazione · {stato_bando}",
  "dotazione": "importo totale fondo es. EUR 5 MLN (null se non trovato)",
  "intensita": "es. 60% fondo perduto (null se non trovato)",
  "contributo_max": "es. EUR 150.000 (null se non trovato)",
  "data_scadenza": "DD/MM/YYYY o descrizione (null se non trovato)",
  "ente_finalita": ["Ente erogatore preciso", "Obiettivo del bando", "Riferimento normativo"],
  "chi_partecipa": ["Beneficiari principali", "Requisiti chiave", "Eventuali esclusioni"],
  "cosa_finanziabile": ["Tipologia 1", "Tipologia 2", "Tipologia 3"],
  "spese_ammissibili": ["Voce 1", "Voce 2", "Voce 3"],
  "spese_non_ammissibili": ["Voce esclusa 1", "IVA se non recuperabile", "Spese ante-ammissione"],
  "contributo_voci": ["Intensita: X%", "Contributo max: EUR X", "Investimento min: EUR X"],
  "criteri_valutazione": ["Tipo procedura: sportello/valutativa", "Criterio 1", "Documentazione richiesta"],
  "fasi_tempi": ["Apertura: data", "Scadenza: data", "Rendicontazione: termini"],
  "come_presentare": ["Portale specifico con URL", "Credenziali: SPID/CNS/altro", "Allegati obbligatori principali"],
  "perche_interessante": ["Punto forza concreto 1", "Punto forza concreto 2", "Punto forza concreto 3"],
  "criticita": ["Vincolo operativo 1", "Vincolo operativo 2", "Attenzione specifica"],
  "cta_testo": "Frase CTA specifica per questo bando e target",
  "fonte_ufficiale": "Ente/decreto/riferimento trovato"
}}

Rispondi SOLO con JSON valido. Nessun testo prima o dopo."""

    for tentativo in range(3):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model":    "claude-haiku-4-5-20251001",
                      "max_tokens": 2500,
                      "tools":    [{"type": "web_search_20250305", "name": "web_search"}],
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=120,
            )
            if resp.status_code == 429:
                time.sleep((tentativo+1)*10)
                continue
            if resp.status_code != 200:
                return {"_api_error": f"{resp.status_code}: {resp.text[:200]}"}

            blocks = resp.json().get("content", [])
            testo  = "\n".join(b.get("text","") for b in blocks if b.get("type")=="text").strip()
            if not testo:
                return {"_api_error": "risposta vuota"}

            raw   = re.sub(r'```(?:json)?\s*','',testo)
            raw   = re.sub(r'```','',raw).strip()
            start = raw.find('{'); end = raw.rfind('}')
            if start==-1 or end==-1:
                return {"_api_error": f"no JSON: {testo[:100]}"}

            return json.loads(raw[start:end+1])

        except json.JSONDecodeError as e:
            return {"_api_error": f"JSON error: {e}"}
        except Exception as e:
            return {"_api_error": str(e)}
    return {}


# ── Assembla CONTENT per energelia_scheda_engine ──────────────────────────────

def _pulisci(lst):
    return [str(x).strip() for x in (lst or [])
            if x and str(x).strip() not in ("","None","null","—","-")]


def _sintetizza(val, max_len=16):
    if not val or str(val).strip() in ("—","-","","null","None"): return "—"
    v = str(val).strip()
    return v if len(v)<=max_len else v[:max_len].rstrip()+"…"


def genera_scheda_web(hit):
    """
    Genera la scheda dal bando.
    Restituisce (content_dict, titolo) compatibile con energelia_scheda_engine.
    """
    titolo      = hit.get("post_title","") or hit.get("title","") or "Bando"
    stato_bando = hit.get("scadenza_testo","Bandi aperti")
    url_bando   = hit.get("permalink","") or hit.get("link","") or hit.get("url","")
    sc_str, _   = _scadenza_da_hit(hit)
    dotaz_hit   = _dotazione_da_hit(hit)

    taxh = hit.get("taxonomies_hierarchical",{})
    ag   = taxh.get("area_geografica",{}) or {}
    lvl0 = (ag.get("lvl0") or [""])[0]
    lvl1 = (ag.get("lvl1") or [""])[0]
    area = lvl1 or lvl0 or ""

    # Claude cerca e genera
    cl = _chiedi_a_claude(titolo, url_bando, stato_bando)

    # Log dell'eventuale errore API nel content stesso (visibile nel traceback del server)
    api_error = cl.get("_api_error","")

    def cv(key, fallback=None):
        v = cl.get(key)
        if isinstance(v, list):
            return v if v else (fallback or [])
        if v and str(v).strip() not in ("","None","null","—","-"):
            return str(v).strip()
        return fallback

    dotazione  = cv("dotazione",    dotaz_hit or "—")
    intensita  = cv("intensita",    "—")
    contr_max  = cv("contributo_max","—")
    data_val   = cv("data_scadenza", sc_str or "—")
    sottotitolo= cv("sottotitolo",   f"{area} · {stato_bando}" if area else stato_bando)
    fonte      = cv("fonte_ufficiale", f"Elaborato da Energelia S.r.l. · {datetime.now().strftime('%B %Y')}")

    stato_bg = "blue" if "prossima" in stato_bando.lower() else "orange"

    content = {
        "titolo":      titolo.upper(),
        "sottotitolo": sottotitolo,
        "metriche": [
            {"label":"DOTAZIONE",    "valore":_sintetizza(dotazione),  "bg":"blue"},
            {"label":"INTENSITA'",   "valore":_sintetizza(intensita),  "bg":"orange"},
            {"label":"CONTRIBUTO MAX","valore":_sintetizza(contr_max), "bg":"green"},
            {"label":"SCADENZA",     "valore":_sintetizza(data_val),   "bg":stato_bg},
        ],
        "sinistra": [
            {"titolo":"ENTE / FINALITA'",     "voci":_pulisci(cv("ente_finalita",[]))},
            {"titolo":"CHI PUO' PARTECIPARE", "voci":_pulisci(cv("chi_partecipa",[]))},
            {"titolo":"COSA E' FINANZIABILE", "voci":_pulisci(cv("cosa_finanziabile",[]))},
            {"titolo":"SPESE NON AMMISSIBILI","voci":_pulisci(cv("spese_non_ammissibili",[]))},
        ],
        "tabella_contributi": cl.get("tabella_contributi") if isinstance(cl.get("tabella_contributi"), dict) else None,
        "destra": [
            {"titolo":"CONTRIBUTO / INTENSITA'","voci":_pulisci(cv("contributo_voci",[]))},
            {"titolo":"CRITERI / VALUTAZIONE",  "voci":_pulisci(cv("criteri_valutazione",[]))},
            {"titolo":"FASI E TEMPI",           "voci":_pulisci(cv("fasi_tempi",[]))},
            {"titolo":"COME PRESENTARE",        "voci":_pulisci(cv("come_presentare",[]))},
        ],
        "punti_forza": _pulisci(cv("perche_interessante",[])),
        "criticita":   _pulisci(cv("criticita",[])),
        "cta_testo":   cv("cta_testo",
                          "Bando aperto: agisci ora!" if "aperto" in stato_bando.lower()
                          else "Preparati ora con Energelia!"),
        "cta_tel":    "Tel. 010 8078800",
        "cta_email":  "a.augusti@energelia.it",
        "fonte":      f"Elaborato da Energelia S.r.l. · {datetime.now().strftime('%B %Y')}",
        "mese_anno":  datetime.now().strftime("%B %Y"),
        "_api_error": api_error,  # visibile nel traceback se qualcosa va storto
    }

    return content, titolo


# ── Genera scheda da testo già disponibile (cache) — SENZA web_search ────────

def _chiedi_a_claude_da_testo(titolo, testo, stato_bando):
    """Come _chiedi_a_claude ma usa il testo già disponibile — zero web_search."""
    if not ANTHROPIC_API_KEY:
        return {}

    # CTA adattata allo stato
    if "prossima" in stato_bando.lower():
        cta_default = "Preparati ora: il bando apre presto. Contattaci per la pre-istruttoria!"
    else:
        cta_default = "Vuoi capire se la tua azienda può accedere a questo bando?"

    prompt = f"""Sei un esperto senior di finanza agevolata italiana che lavora per Energelia S.r.l.

BANDO DA ANALIZZARE:
Titolo: {titolo}
Stato: {stato_bando}

TESTO DEL BANDO:
{testo[:8000]}

REGOLE OBBLIGATORIE:
- Ogni bullet deve essere una frase COMPLETA e SPECIFICA (80-160 caratteri) con dati reali
- MAI scrivere "verificare sul bando", "non specificato", "vedi bando"
- Usa <b>etichetta:</b> per evidenziare etichette dentro i bullet (non per l'intero bullet)
- Minimo 3 bullet per sezione, ideale 4
- Le metriche devono essere sintetiche (max 20 caratteri per riga), usa \\n per multiriga
- tabella_contributi: usa null se non ci sono tipologie/scaglioni distinti

Genera la scheda in JSON con questa struttura ESATTA:
{{
  "sottotitolo": "Ente erogatore · riferimento normativo · tipo agevolazione · {stato_bando}",
  "dotazione": "es. EUR 45 MLN (null se non presente nel testo)",
  "intensita": "es. 35%\\nfondo perduto (null se non presente)",
  "contributo_max": "es. EUR 250.000 (null se non presente)",
  "data_scadenza": "DD/MM/YYYY (null se non presente)",
  "ente_finalita": [
    "Nome ente erogatore con riferimento normativo preciso",
    "Obiettivo specifico del bando con dati concreti",
    "Programma di riferimento e contesto (es. PR FESR 2021-27, PNRR M1C2)",
    "Eventuale info su lotti, sportelli o dotazione per area geografica"
  ],
  "chi_partecipa": [
    "Forma giuridica e dimensione con settori specifici se indicati",
    "Requisiti territoriali e registrazione (es. sede operativa, iscrizione CCIAA)",
    "<b>Escluse:</b> categorie escluse esplicitamente dal bando",
    "Requisiti settoriali o codici ATECO rilevanti se specificati"
  ],
  "cosa_finanziabile": [
    "<b>Linea A:</b> descrizione concreta con esempi e % max se previsti",
    "<b>Linea B:</b> altra categoria di spesa con dettagli",
    "Investimento minimo/massimo ammissibile in EUR se indicato",
    "Eventuale quarta tipologia o vincolo sulle spese"
  ],
  "spese_non_ammissibili": [
    "IVA e oneri fiscali recuperabili dal beneficiario",
    "Spese sostenute prima della data di ammissibilità (ante-domanda)",
    "Eventuali categorie specifiche escluse citate nel testo",
    "Ulteriore esclusione specifica del bando se presente"
  ],
  "tabella_contributi": null,
  "contributo_voci": [
    "Intensità: XX% delle spese ammissibili (IVA esclusa)",
    "<b>Contributo massimo:</b> EUR X.XXX per beneficiario",
    "Regime di aiuto: De minimis o esenzione con riferimento regolamento",
    "Eventuale maggiorazione per categorie prioritarie (+X%)"
  ],
  "criteri_valutazione": [
    "Procedura: valutativa con graduatoria / sportello / automatica",
    "Criteri principali di selezione con punteggi se indicati",
    "Soglia minima di accesso se prevista",
    "Premialità per categorie specifiche se previste"
  ],
  "fasi_tempi": [
    "<b>Apertura:</b> data effettiva o stato attuale",
    "<b>Scadenza domande:</b> data e ora esatte",
    "<b>Istruttoria:</b> tempistica prevista",
    "<b>Rendicontazione:</b> scadenza finale per spese"
  ],
  "come_presentare": [
    "Piattaforma specifica con nome portale",
    "Credenziali richieste: SPID/CNS/CIE e firma digitale",
    "Allegati principali obbligatori",
    "Eventuale supporto CAA o sportello dedicato"
  ],
  "perche_interessante": [
    "Vantaggio concreto 1 con dati numerici (es. fondo perduto fino al X%)",
    "Vantaggio concreto 2 (target, semplicità, dotazione, deadline comoda)",
    "Vantaggio concreto 3 (cumulabilità, anticipo erogazione, ecc.)",
    "Eventuale quarto punto di forza specifico"
  ],
  "criticita": [
    "Prima criticità reale con dettaglio operativo",
    "Seconda criticità: requisito stringente o esclusione importante",
    "Terza criticità: tempi, complessità istruttoria, spese ante-domanda",
    "Eventuale quarta attenzione specifica del bando"
  ],
  "cta_testo": "{cta_default}",
  "fonte_ufficiale": "Riferimento normativo o ente trovato nel testo"
}}

Rispondi SOLO con JSON valido. Nessun testo prima o dopo."""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model":    "claude-haiku-4-5-20251001",
                  "max_tokens": 2000,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        if resp.status_code != 200:
            return {"_api_error": f"{resp.status_code}"}

        blocks = resp.json().get("content", [])
        testo_r = "\n".join(b.get("text","") for b in blocks if b.get("type")=="text").strip()
        raw   = re.sub(r'```(?:json)?\s*','',testo_r)
        raw   = re.sub(r'```','',raw).strip()
        start = raw.find('{'); end = raw.rfind('}')
        if start==-1 or end==-1:
            return {}
        return json.loads(raw[start:end+1])
    except Exception as e:
        return {"_api_error": str(e)}


def genera_scheda_da_testo(hit, testo_cache):
    """
    Genera scheda usando il testo dalla cache — SENZA web_search.
    Costo ~1-2 centesimi invece di 12-13.
    """
    titolo      = hit.get("post_title","") or hit.get("title","") or "Bando"
    stato_bando = hit.get("scadenza_testo","Bandi aperti")
    sc_str, _   = _scadenza_da_hit(hit)
    dotaz_hit   = _dotazione_da_hit(hit)

    taxh = hit.get("taxonomies_hierarchical",{})
    ag   = taxh.get("area_geografica",{}) or {}
    lvl0 = (ag.get("lvl0") or [""])[0]
    lvl1 = (ag.get("lvl1") or [""])[0]
    area = lvl1 or lvl0 or ""

    cl = _chiedi_a_claude_da_testo(titolo, testo_cache, stato_bando)
    api_error = cl.get("_api_error","")

    def cv(key, fallback=None):
        v = cl.get(key)
        if isinstance(v, list): return v if v else (fallback or [])
        if v and str(v).strip() not in ("","None","null","—","-"): return str(v).strip()
        return fallback

    dotazione  = cv("dotazione",     dotaz_hit or "—")
    intensita  = cv("intensita",     "—")
    contr_max  = cv("contributo_max","—")
    data_val   = cv("data_scadenza", sc_str or "—")
    sottotitolo= cv("sottotitolo",   f"{area} · {stato_bando}" if area else stato_bando)
    fonte      = cv("fonte_ufficiale", f"Elaborato da Energelia S.r.l. · {datetime.now().strftime('%B %Y')}")
    stato_bg   = "blue" if "prossima" in stato_bando.lower() else "orange"

    content = {
        "titolo":      titolo.upper(),
        "sottotitolo": sottotitolo,
        "metriche": [
            {"label":"DOTAZIONE",     "valore":_sintetizza(dotazione),  "bg":"blue"},
            {"label":"INTENSITA'",    "valore":_sintetizza(intensita),  "bg":"orange"},
            {"label":"CONTRIBUTO MAX","valore":_sintetizza(contr_max),  "bg":"green"},
            {"label":"SCADENZA",      "valore":_sintetizza(data_val),   "bg":stato_bg},
        ],
        "sinistra": [
            {"titolo":"ENTE / FINALITA'",     "voci":_pulisci(cv("ente_finalita",[]))},
            {"titolo":"CHI PUO' PARTECIPARE", "voci":_pulisci(cv("chi_partecipa",[]))},
            {"titolo":"COSA E' FINANZIABILE", "voci":_pulisci(cv("cosa_finanziabile",[]))},
            {"titolo":"SPESE NON AMMISSIBILI","voci":_pulisci(cv("spese_non_ammissibili",[]))},
        ],
        "tabella_contributi": cl.get("tabella_contributi") if isinstance(cl.get("tabella_contributi"), dict) else None,
        "destra": [
            {"titolo":"CONTRIBUTO / INTENSITA'","voci":_pulisci(cv("contributo_voci",[]))},
            {"titolo":"CRITERI / VALUTAZIONE",  "voci":_pulisci(cv("criteri_valutazione",[]))},
            {"titolo":"FASI E TEMPI",           "voci":_pulisci(cv("fasi_tempi",[]))},
            {"titolo":"COME PRESENTARE",        "voci":_pulisci(cv("come_presentare",[]))},
        ],
        "punti_forza": _pulisci(cv("perche_interessante",[])),
        "criticita":   _pulisci(cv("criticita",[])),
        "cta_testo":   cv("cta_testo", "Bando aperto: agisci ora!" if "aperto" in stato_bando.lower() else "Preparati ora con Energelia!"),
        "cta_tel":    "Tel. 010 8078800",
        "cta_email":  "a.augusti@energelia.it",
        "fonte":      f"Elaborato da Energelia S.r.l. · {datetime.now().strftime('%B %Y')}",
        "mese_anno":  datetime.now().strftime("%B %Y"),
        "_api_error": api_error,
    }
    return content, titolo
