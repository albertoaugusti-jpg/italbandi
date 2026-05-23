#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         ENERGELIA S.r.l. — GENERATORE SCHEDE BANDI  v2.0                   ║
║         Engine con autoscaling: riempie sempre la pagina A4                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

COME USARE:
  1. Compila il blocco CONTENT qui sotto con i dati del bando
  2. Imposta OUTPUT e LOGO
  3. Esegui: python3 energelia_scheda_engine.py
  4. Il motore trova automaticamente la scala ottimale (binary search)
     e produce un PDF di esattamente 1 pagina A4 ben riempita.

LOGICA DI SCALA:
  - scale=1.0  → parametri nominali
  - scale<1.0  → contenuto ampio, si comprime per stare in 1 pagina
  - scale>1.0  → contenuto scarso, si espande per riempire la pagina
  - Limiti: SCALE_MIN=0.62  SCALE_MAX=1.30
  - Font bullet: clamp [6.0, 9.0]
  - Spacer: clamp [0, ∞]
"""

import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image as RLImage, KeepTogether
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
import os

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAZIONE FILE
# ─────────────────────────────────────────────────────────────────────────────
OUTPUT = "/mnt/user-data/outputs/scheda_distretti_commercio_2026.pdf"
LOGO   = "/home/claude/logo.png"   # PNG quadrato 1:1

# ─────────────────────────────────────────────────────────────────────────────
# ██████████████  CONTENT  ████████████████████████████████████████████████████
# Compila questa sezione con i dati del bando. Tutto il resto è automatico.
# ─────────────────────────────────────────────────────────────────────────────
CONTENT = {

    # ── Testata bando ─────────────────────────────────────────────────────────
    "titolo":    "BANDO DISTRETTI DEL COMMERCIO 2026",
    "sottotitolo": (
        "Regione Lombardia · DGR XII/5702 del 02/02/2026 "
        "· Contributo a fondo perduto · Lombardia · Prossima apertura"
    ),

    # ── 4 box metriche ────────────────────────────────────────────────────────
    # bg: "blue"=LBLUE  "green"=LGREEN  "orange"=LORANGE  "gold"=GOLD
    "metriche": [
        {"label": "DOTAZIONE TOTALE",      "valore": "EUR 63.000.000", "bg": "blue"},
        {"label": "CONTRIBUTO MAX",        "valore": "EUR 520.000",    "bg": "green"},
        {"label": "INTENSITÀ CONTRIBUTO",  "valore": "50% del costo",  "bg": "orange"},
        {"label": "STATO",                 "valore": "Prossima\napertura", "bg": "blue"},
    ],

    # ── Colonna sinistra ──────────────────────────────────────────────────────
    # Ogni sezione: {"titolo": str, "voci": [str, ...]}
    # Nei bullet usare tag HTML: <b>testo</b>
    "sinistra": [
        {
            "titolo": "ENTE / FINALITÀ",
            "voci": [
                "Regione Lombardia – Dir. Gen. Sviluppo Economico (Ass. Guido Guidesi)",
                "Rigenerazione urbana e rilancio del commercio locale nei Distretti lombardi",
                "Contrasto alla desertificazione commerciale e premio alle eccellenze progettuali",
            ],
        },
        {
            "titolo": "CHI PUÒ PARTECIPARE",
            "voci": [
                "<b>Diretti:</b> Comuni, Comunità Montane, Unioni di Comuni aderenti a Distretto del Commercio (DUC o DiD) iscritto all'Elenco Regionale (d.d.u.o. 18701/2019) o con istanza in iter",
                "<b>Indiretti:</b> MPMI nel Distretto, tramite bandi finanziati dall'Ente Locale con risorse proprie",
                "Partenariato obbligatorio con Associazioni di categoria provinciali del commercio",
            ],
        },
        {
            "titolo": "COSA È FINANZIABILE",
            "voci": [
                "<b>Conto capitale:</b> immobili, opere, impianti, macchinari, beni immateriali, aree ed espropri (incremento patrimonio pubblico)",
                "<b>Parte corrente:</b> governance, Manager di Distretto, animazione, promozione, servizi comuni, sicurezza, consulenze",
                "Investimento minimo di progetto: EUR 300.000 (quota bando imprese esclusa)",
            ],
        },
        {
            "titolo": "VINCOLI / NON AMMISSIBILE",
            "voci": [
                "Bando <b>esclusivamente per Enti Pubblici</b> — nessun accesso diretto per le imprese private",
                "Obbligo risorse proprie EL per bando imprese: min EUR 100.000 (Eccellenza) / EUR 50.000 (Ordinari)",
                "Spese eleggibili solo dalla data DGR 02/02/2026; regime de minimis se attività economica (Reg. UE 2023/2831)",
            ],
        },
    ],

    # ── Colonna destra ────────────────────────────────────────────────────────
    # Tabella contributi: opzionale. Se None, non viene renderizzata.
    "tabella_contributi": {
        "header": ["Tipologia", "Punteggio", "Contributo max"],
        # row: [col1, col2, col3, evidenzia_riga (bool)]
        "righe": [
            ["Eccellenza", "161–200 pt", "EUR 520.000", True],
            ["Ordinario",  "120–160 pt", "EUR 189.900", False],
        ],
        # note testuali sotto la tabella (opzionale, lista di str)
        "note": [
            "Eccellenza: EUR 500.000 cap. + EUR 20.000 corrente",
            "Ordinari: EUR 178.500 cap. + EUR 11.400 corrente",
        ],
    },

    "destra": [
        {
            "titolo": "CRITERI DI VALUTAZIONE",
            "voci": [
                "Procedura valutativa con graduatoria; punteggio 0–200 (soglia min. 120/200)",
                "Analisi di contesto, strategia, coerenza budget, modalità di governance",
                "Premialità: +10 pt progetti interdistrettuali; +10 pt interventi per la sicurezza",
            ],
        },
        {
            "titolo": "FASI E TEMPI",
            "voci": [
                "<b>Apertura:</b> bando attuativo atteso entro apr.–mag. 2026 (60 gg dalla DGR)",
                "<b>Graduatoria:</b> entro 31/12/2026 · <b>Acconto:</b> 25% cap. + 50% corrente nel 2026",
                "<b>Rendicontazione:</b> ordinari 30/06/2029 · eccellenza 30/06/2030",
            ],
        },
        {
            "titolo": "COME PRESENTARE",
            "voci": [
                "Piattaforma <b>Bandi e Servizi</b> di Regione Lombardia (bandi.regione.lombardia.it)",
                "Domanda dal Comune capofila con progetto, analisi di contesto e budget dettagliato",
                "Monitorare BURL per pubblicazione del bando attuativo",
            ],
        },
    ],

    # ── Box verde (punti di forza) ────────────────────────────────────────────
    "punti_forza": [
        "EUR 63M su più annualità (2026–2030): flussi certi e programmabili",
        "Intensità 50%; anticipo 25% cap. + 50% corrente già nel 2026",
        "Contributo max EUR 520.000 per i Progetti di Eccellenza",
        "Premialità fino a +20 pt; ediz. precedente: 149 progetti, EUR 60M erogati",
    ],

    # ── Box rosso (criticità) ─────────────────────────────────────────────────
    "criticita": [
        "SOLO Enti Pubblici — nessun accesso diretto per le imprese private",
        "Iscrizione Elenco Regionale Distretti obbligatoria (o istanza in corso)",
        "Partenariato con Assoc. di categoria provinciali: requisito formale vincolante",
        "Bando attuativo non ancora pubblicato (DGR criteri: 02/02/2026)",
    ],

    # ── CTA ───────────────────────────────────────────────────────────────────
    # Testo adattato al contesto:
    # bando imminente → "Agisci ora"
    # prossima apertura → "Preparati ora"
    # solo PA → "Il tuo Comune è interessato?"
    "cta_testo": "Il tuo Comune è in un Distretto del Commercio? Preparati ora per il bando attuativo!",
    "cta_tel":   "Tel. 010 8078800",
    "cta_email": "a.augusti@energelia.it",

    # ── Footer ────────────────────────────────────────────────────────────────
    "fonte": "Fonte: DGR Regione Lombardia n. XII/5702 del 02/02/2026 e Allegato A",
    "mese_anno": "Maggio 2026",
}

# ─────────────────────────────────────────────────────────────────────────────
# PALETTE
# ─────────────────────────────────────────────────────────────────────────────
NAVY    = colors.HexColor("#1F4E79")
TEAL    = colors.HexColor("#2E75B6")
LGRAY   = colors.HexColor("#CCCCCC")
DGRAY   = colors.HexColor("#444444")
MGRAY   = colors.HexColor("#888888")
WHITE   = colors.white
LBLUE   = colors.HexColor("#EBF3FB")
LGREEN  = colors.HexColor("#E8F5E9")
LORANGE = colors.HexColor("#FFF3E0")
LRED    = colors.HexColor("#FFF8F8")
GOLD    = colors.HexColor("#FFF8E1")
GREEN2  = colors.HexColor("#2E7D32")
RED2    = colors.HexColor("#B71C1C")
F5F9    = colors.HexColor("#F5F9FD")

BG_MAP = {"blue": LBLUE, "green": LGREEN, "orange": LORANGE, "gold": GOLD}

W, H = A4
MARGIN     = 18 * mm
TOP_MARGIN = 12 * mm
BOT_MARGIN = 11 * mm

# ─────────────────────────────────────────────────────────────────────────────
# PARAMETRI NOMINALI (a scale=1.0)
# ─────────────────────────────────────────────────────────────────────────────
NOM = {
    # font sizes
    "company_fs":   13.0,
    "tagline_fs":    7.5,
    "addr_fs":       6.5,
    "title_fs":     14.0,
    "subtitle_fs":   8.5,
    "sec_fs":        8.5,
    "bullet_fs":     7.8,
    "metric_val_fs": 11.0,
    "metric_lbl_fs": 6.5,
    "box_title_fs":  7.8,
    "cta_fs":        8.0,
    "cta_tel_fs":    9.5,
    "foot_fs":       6.2,
    "tab_fs":        7.5,
    # spacer heights
    "sp_after_hr":   4.0,
    "sp_after_title":5.0,
    "sp_after_met":  6.0,
    "sp_sec":        4.0,     # spacer dopo ogni sezione
    "sp_body_boxes": 6.0,     # fra corpo e box verde/rosso
    "sp_boxes_cta":  5.0,
    "sp_cta_foot":   4.0,
    # leading factors
    "lead_factor":   1.35,    # leading = fs * lead_factor
    # padding interni
    "metric_pad":    5.0,
    "box_pad_tb":    5.0,
    "box_pad_lr":    6.0,
    "title_pad":     6.0,
    "tab_pad":       3.0,
}

SCALE_MIN = 0.48
SCALE_MAX = 1.30
BULLET_FS_MIN = 5.2
BULLET_FS_MAX = 9.0


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def make_styles(p):
    """Genera il dizionario degli stili dato il set di parametri p."""
    def sty(name, fn="Helvetica", fs=8, tc=DGRAY, lead=None, align=TA_LEFT, **kw):
        ld = lead if lead is not None else fs * p["lead_factor"]
        return ParagraphStyle(name, fontName=fn, fontSize=fs, textColor=tc,
                              leading=ld, alignment=align, **kw)

    bfs = clamp(p["bullet_fs"], BULLET_FS_MIN, BULLET_FS_MAX)
    return {
        "company":  sty("company",  "Helvetica-Bold", p["company_fs"], NAVY),
        "tagline":  sty("tagline",  fs=p["tagline_fs"], tc=colors.HexColor("#555555")),
        "addr":     sty("addr",     fs=p["addr_fs"],    tc=DGRAY),
        "mail":     sty("mail",     fs=p["addr_fs"],    tc=TEAL),
        "pec":      sty("pec",      fs=p["addr_fs"]-0.3, tc=MGRAY),
        "title":    sty("title",    "Helvetica-Bold", p["title_fs"],    WHITE, align=TA_CENTER),
        "subtitle": sty("subtitle", fs=p["subtitle_fs"], tc=WHITE, align=TA_CENTER),
        "sec":      sty("sec",      "Helvetica-Bold", p["sec_fs"], NAVY),
        "bullet":   sty("bullet",   fs=bfs, tc=DGRAY, leftIndent=7),
        "met_val":  sty("met_val",  "Helvetica-Bold", p["metric_val_fs"], NAVY, align=TA_CENTER),
        "met_lbl":  sty("met_lbl",  fs=p["metric_lbl_fs"], tc=MGRAY, align=TA_CENTER),
        "tabh":     sty("tabh",     "Helvetica-Bold", p["tab_fs"], WHITE, align=TA_CENTER),
        "tabc":     sty("tabc",     fs=p["tab_fs"], tc=DGRAY, align=TA_LEFT),
        "tabcb":    sty("tabcb",    "Helvetica-Bold", p["tab_fs"], NAVY, align=TA_CENTER),
        "tab_note": sty("tab_note", fs=clamp(p["tab_fs"]-0.3, 5.5, 8.0), tc=DGRAY, leftIndent=7),
        "ok":       sty("ok",       "Helvetica-Bold", p["box_title_fs"], GREEN2),
        "warn":     sty("warn",     "Helvetica-Bold", p["box_title_fs"], RED2),
        "cta":      sty("cta",      fs=p["cta_fs"],     tc=NAVY,  align=TA_CENTER),
        "cta_tel":  sty("cta_tel",  "Helvetica-Bold", p["cta_tel_fs"], TEAL, align=TA_CENTER),
        "cta_em":   sty("cta_em",   fs=p["cta_fs"]-0.2, tc=TEAL, align=TA_CENTER),
        "foot":     sty("foot",     fs=p["foot_fs"], tc=MGRAY, align=TA_CENTER),
    }


def sp(p, key):
    """Spacer verticale scalato."""
    return Spacer(1, max(0.5, p[key]))


def build_story(p, content):
    """
    Costruisce la story ReportLab usando i parametri p e i dati content.
    Restituisce una lista di Flowable.
    """
    S   = make_styles(p)
    CW  = W - 2 * MARGIN
    story = []

    # ── HEADER ────────────────────────────────────────────────────────────────
    logo_sz = 13 * mm
    if os.path.exists(LOGO):
        logo_cell = RLImage(LOGO, width=logo_sz, height=logo_sz)
    else:
        logo_cell = Paragraph("<b>ENERGELIA</b>", S["company"])

    txt_rows = [
        [Paragraph("Energelia S.r.l.", S["company"])],
        [Paragraph("Consulenza in Finanza Agevolata · Bandi &amp; Incentivi · Sostenibilità", S["tagline"])],
        [Paragraph("Largo XII Ottobre 1/3, Torre WTC · 16121 Genova", S["addr"])],
        [Paragraph("a.augusti@energelia.it · b.legger@energelia.it · a.castagnaro@energelia.it", S["mail"])],
        [Paragraph("Tel. 010 8078800 · www.energelia.it", S["pec"])],
    ]
    txt_tbl = Table(txt_rows, colWidths=[CW - logo_sz - 6*mm])
    txt_tbl.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0),(-1,-1), 0), ("RIGHTPADDING", (0,0),(-1,-1), 0),
        ("TOPPADDING",   (0,0),(-1,-1), 0), ("BOTTOMPADDING",(0,0),(-1,-1), 0.8),
    ]))
    hdr = Table([[logo_cell, txt_tbl]], colWidths=[logo_sz + 5*mm, CW - logo_sz - 5*mm])
    hdr.setStyle(TableStyle([
        ("VALIGN",       (0,0),(-1,-1), "MIDDLE"),
        ("LEFTPADDING",  (0,0),(-1,-1), 0), ("RIGHTPADDING", (0,0),(-1,-1), 0),
        ("TOPPADDING",   (0,0),(-1,-1), 0), ("BOTTOMPADDING",(0,0),(-1,-1), 0),
    ]))
    story.append(hdr)
    story.append(HRFlowable(width=CW, thickness=1.5, color=TEAL, spaceAfter=p["sp_after_hr"]))

    # ── TITOLO ────────────────────────────────────────────────────────────────
    title_tbl = Table([
        [Paragraph(content["titolo"],     S["title"])],
        [Paragraph(content["sottotitolo"], S["subtitle"])],
    ], colWidths=[CW])
    title_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), NAVY),
        ("TOPPADDING",   (0,0),(-1,-1), p["title_pad"]),
        ("BOTTOMPADDING",(0,0),(-1,-1), p["title_pad"]),
        ("LEFTPADDING",  (0,0),(-1,-1), 10),
        ("RIGHTPADDING", (0,0),(-1,-1), 10),
    ]))
    story.append(title_tbl)
    story.append(sp(p, "sp_after_title"))

    # ── METRICHE ──────────────────────────────────────────────────────────────
    def metric_cell(m):
        bg = BG_MAP.get(m.get("bg", "blue"), LBLUE)
        val_lines = m["valore"].split("\n")
        # Se valore multiriga, usa font leggermente più piccolo
        vfs = p["metric_val_fs"] if len(val_lines) == 1 else p["metric_val_fs"] * 0.88
        rows = [[Paragraph(m["label"], S["met_lbl"])]]
        for vl in val_lines:
            vs = ParagraphStyle("_mv", fontName="Helvetica-Bold",
                                fontSize=vfs, textColor=NAVY,
                                leading=vfs * 1.2, alignment=TA_CENTER)
            rows.append([Paragraph(vl, vs)])
        t = Table(rows, colWidths=[(CW/4) - 3*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND",   (0,0),(-1,-1), bg),
            ("TOPPADDING",   (0,0),(-1,-1), p["metric_pad"]),
            ("BOTTOMPADDING",(0,0),(-1,-1), p["metric_pad"]),
            ("LEFTPADDING",  (0,0),(-1,-1), 3),
            ("RIGHTPADDING", (0,0),(-1,-1), 3),
        ]))
        return t

    met_row  = [metric_cell(m) for m in content["metriche"]]
    met_tbl  = Table([met_row], colWidths=[(CW/4) - 1*mm]*4, hAlign="LEFT")
    met_tbl.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0),(-1,-1), 1.5), ("RIGHTPADDING", (0,0),(-1,-1), 1.5),
        ("TOPPADDING",   (0,0),(-1,-1), 0),   ("BOTTOMPADDING",(0,0),(-1,-1), 0),
    ]))
    story.append(met_tbl)
    story.append(sp(p, "sp_after_met"))

    # ── CORPO 2 COLONNE ───────────────────────────────────────────────────────
    COL1 = CW * 0.52
    COL2 = CW * 0.44
    GAP  = CW - COL1 - COL2

    def render_section(sec_data, col_w):
        """Renderizza una sezione (titolo + bullet) per una colonna."""
        out = []
        hd = Table([[Paragraph("| " + sec_data["titolo"], S["sec"])]],
                   colWidths=[col_w])
        hd.setStyle(TableStyle([
            ("LEFTPADDING",  (0,0),(-1,-1), 0), ("RIGHTPADDING", (0,0),(-1,-1), 0),
            ("TOPPADDING",   (0,0),(-1,-1), 1), ("BOTTOMPADDING",(0,0),(-1,-1), 2),
        ]))
        out.append(hd)
        for voce in sec_data["voci"]:
            out.append(Paragraph("• " + voce, S["bullet"]))
        out.append(sp(p, "sp_sec"))
        return out

    # Colonna sinistra
    left = []
    for sec_data in content["sinistra"]:
        left += render_section(sec_data, COL1)

    # Colonna destra
    right = []

    # Tabella contributi (opzionale)
    if content.get("tabella_contributi"):
        tc = content["tabella_contributi"]
        right.append(Paragraph("| CONTRIBUTO / INTENSITÀ", S["sec"]))
        right.append(Spacer(1, 2))

        n_cols = len(tc["header"])
        col_w  = COL2 / n_cols
        tab_data = [[Paragraph(h, S["tabh"]) for h in tc["header"]]]
        for i, row in enumerate(tc["righe"]):
            is_best = row[-1] if isinstance(row[-1], bool) else False
            cells   = row[:-1] if isinstance(row[-1], bool) else row
            styles  = [S["tabcb"] if (j == n_cols-1 and is_best) else S["tabc"]
                       for j in range(n_cols)]
            tab_data.append([Paragraph(cells[j], styles[j]) for j in range(n_cols)])

        ct_widths = [COL2 / n_cols] * n_cols
        ct = Table(tab_data, colWidths=ct_widths)

        ts = [
            ("BACKGROUND",   (0,0), (-1, 0), NAVY),
            ("GRID",         (0,0), (-1,-1), 0.4, LGRAY),
            ("TOPPADDING",   (0,0), (-1,-1), p["tab_pad"]),
            ("BOTTOMPADDING",(0,0), (-1,-1), p["tab_pad"]),
            ("LEFTPADDING",  (0,0), (-1,-1), 4),
            ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ]
        for i, row in enumerate(tc["righe"]):
            is_best = row[-1] if isinstance(row[-1], bool) else False
            bg = LGREEN if is_best else (WHITE if i % 2 == 0 else F5F9)
            ts.append(("BACKGROUND", (0, i+1), (-1, i+1), bg))
        ct.setStyle(TableStyle(ts))
        right.append(ct)

        if tc.get("note"):
            right.append(Spacer(1, 2))
            for nota in tc["note"]:
                right.append(Paragraph("• " + nota, S["bullet"]))
        right.append(sp(p, "sp_sec"))

    for sec_data in content["destra"]:
        right += render_section(sec_data, COL2)

    def build_col(items, col_w):
        t = Table([[item] for item in items], colWidths=[col_w])
        t.setStyle(TableStyle([
            ("LEFTPADDING",  (0,0),(-1,-1), 0), ("RIGHTPADDING", (0,0),(-1,-1), 0),
            ("TOPPADDING",   (0,0),(-1,-1), 0), ("BOTTOMPADDING",(0,0),(-1,-1), 0),
            ("VALIGN",       (0,0),(-1,-1), "TOP"),
        ]))
        return t

    body = Table(
        [[build_col(left, COL1), Spacer(GAP, 1), build_col(right, COL2)]],
        colWidths=[COL1, GAP, COL2]
    )
    body.setStyle(TableStyle([
        ("VALIGN",       (0,0),(-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0),(-1,-1), 0), ("RIGHTPADDING", (0,0),(-1,-1), 0),
        ("TOPPADDING",   (0,0),(-1,-1), 0), ("BOTTOMPADDING",(0,0),(-1,-1), 0),
    ]))
    story.append(body)
    story.append(sp(p, "sp_body_boxes"))

    # ── BOX VERDE / ROSSO ─────────────────────────────────────────────────────
    HW = (CW / 2) - 4*mm

    def render_box(title_para, voci, col_w):
        rows = [[title_para]]
        for v in voci:
            rows.append([Paragraph("• " + v, S["bullet"])])
        t = Table(rows, colWidths=[col_w])
        t.setStyle(TableStyle([
            ("LEFTPADDING",  (0,0),(-1,-1), 0), ("RIGHTPADDING", (0,0),(-1,-1), 0),
            ("TOPPADDING",   (0,0),(-1,-1), 0), ("BOTTOMPADDING",(0,0),(-1,-1), 1.5),
        ]))
        return t

    box_data = [[
        render_box(Paragraph("(+)  PERCHÉ È INTERESSANTE", S["ok"]),
                   content["punti_forza"], HW),
        render_box(Paragraph("(!)  CRITICITÀ E ATTENZIONI", S["warn"]),
                   content["criticita"], HW),
    ]]
    box = Table(box_data, colWidths=[CW/2, CW/2])
    box.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(0,0), LGREEN), ("BACKGROUND", (1,0),(1,0), LRED),
        ("BOX",          (0,0),(0,0), 0.6, GREEN2), ("BOX", (1,0),(1,0), 0.6, RED2),
        ("TOPPADDING",   (0,0),(-1,-1), p["box_pad_tb"]),
        ("BOTTOMPADDING",(0,0),(-1,-1), p["box_pad_tb"]),
        ("LEFTPADDING",  (0,0),(-1,-1), p["box_pad_lr"]),
        ("RIGHTPADDING", (0,0),(-1,-1), p["box_pad_lr"]),
        ("VALIGN",       (0,0),(-1,-1), "TOP"),
    ]))
    story.append(box)
    story.append(sp(p, "sp_boxes_cta"))

    # ── CTA ───────────────────────────────────────────────────────────────────
    cta = Table([[
        Paragraph(content["cta_testo"], S["cta"]),
        Paragraph(f"<b>{content['cta_tel']}</b>", S["cta_tel"]),
        Paragraph(content["cta_email"], S["cta_em"]),
    ]], colWidths=[CW*0.45, CW*0.27, CW*0.28])
    cta.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), LBLUE),
        ("TOPPADDING",   (0,0),(-1,-1), 5), ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("LEFTPADDING",  (0,0),(-1,-1), 8), ("RIGHTPADDING", (0,0),(-1,-1), 8),
        ("VALIGN",       (0,0),(-1,-1), "MIDDLE"),
        ("LINEAFTER",    (0,0),(1,0),  0.5, TEAL),
    ]))
    story.append(cta)
    story.append(sp(p, "sp_cta_foot"))

    # ── FOOTER ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width=CW, thickness=0.5, color=LGRAY, spaceAfter=2))
    story.append(Paragraph(
        "Energelia S.r.l. · Largo XII Ottobre 1/3, Torre WTC · 16121 Genova "
        "· Tel. 010 8078800 · www.energelia.it<br/>"
        f"{content['fonte']} · {content['mese_anno']}<br/>"
        "Il presente documento ha valore informativo. "
        "Fare riferimento al testo ufficiale del bando per tutti i contenuti vincolanti.",
        S["foot"]
    ))

    return story


# ─────────────────────────────────────────────────────────────────────────────
# AUTOSCALING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def scale_params(scale):
    """
    Applica il fattore scale ai parametri nominali.
    - Font: scalati ma con floor/ceiling per leggibilità
    - Spacer: scalati linearmente (floor a 0.5)
    """
    p = {}
    for k, v in NOM.items():
        if k.endswith("_fs"):
            # font sizes: scala ma clamp
            p[k] = clamp(v * scale, 5.0, v * 1.5)
        elif k.startswith("sp_") or k.endswith("_pad") or k.endswith("_tb") or k.endswith("_lr"):
            # spazi e padding: scala linearmente
            p[k] = max(0.5, v * scale)
        elif k == "lead_factor":
            p[k] = clamp(v * (0.5 + scale * 0.5), 1.15, 1.5)
        else:
            p[k] = v * scale
    return p


def count_pages(story, buf=None):
    """Costruisce il PDF in memoria e restituisce il numero di pagine."""
    from pypdf import PdfReader
    buf = buf or io.BytesIO()
    buf.seek(0)
    buf.truncate()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=TOP_MARGIN, bottomMargin=BOT_MARGIN,
    )
    doc.build(story)
    buf.seek(0)
    return len(PdfReader(buf).pages)


def find_optimal_scale(content, verbose=True):
    """
    Binary search per trovare il massimo scale tale che il PDF stia in 1 pagina.
    Poi fa un secondo passaggio per massimizzare il riempimento.
    """
    lo, hi = SCALE_MIN, SCALE_MAX
    best_scale = lo

    if verbose:
        print("Calibrazione scala...")

    # Fase 1: trova il massimo scale che stia in 1 pagina
    for i in range(10):
        mid = (lo + hi) / 2
        p   = scale_params(mid)
        story = build_story(p, content)
        n = count_pages(story)
        if verbose:
            print(f"  iter {i+1}: scale={mid:.4f}  pagine={n}")
        if n <= 1:
            best_scale = mid
            lo = mid
        else:
            hi = mid
        if hi - lo < 0.005:
            break

    if verbose:
        print(f"  → Scala ottimale: {best_scale:.4f}")
    return best_scale


def generate(output_path=None, verbose=True):
    out = output_path or OUTPUT
    scale = find_optimal_scale(CONTENT, verbose=verbose)
    p     = scale_params(scale)
    story = build_story(p, CONTENT)

    doc = SimpleDocTemplate(
        out, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=TOP_MARGIN, bottomMargin=BOT_MARGIN,
    )
    doc.build(story)

    if verbose:
        from pypdf import PdfReader
        with open(out, "rb") as f:
            n = len(PdfReader(f).pages)
        print(f"\nPDF generato: {out}")
        print(f"Scala finale: {scale:.4f}")
        print(f"Pagine PDF:   {n}")

    return out


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    generate()
