"""
schede_engine.py — Motore ReportLab per schede bandi Energelia
Importare e chiamare: generate(content, output_path, logo_path)
"""
import io, os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image as RLImage,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER

# ── PALETTE ───────────────────────────────────────────────────────────────────
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
BG_MAP  = {"blue": LBLUE, "green": LGREEN, "orange": LORANGE, "gold": GOLD}

W, H        = A4
PAGE_MARGIN = 18 * mm
TOP_MARGIN  = 12 * mm
BOT_MARGIN  = 11 * mm

# ── PARAMETRI NOMINALI (scale=1.0) ────────────────────────────────────────────
NOM = {
    "company_fs": 13.0, "tagline_fs": 7.5, "addr_fs": 6.5,
    "title_fs": 14.0,   "subtitle_fs": 8.5, "sec_fs": 8.5,
    "bullet_fs": 7.8,   "metric_val_fs": 11.0, "metric_lbl_fs": 6.5,
    "box_title_fs": 7.8, "cta_fs": 8.0, "cta_tel_fs": 9.5,
    "foot_fs": 6.2,     "tab_fs": 7.5,
    "sp_after_hr": 4.0, "sp_after_title": 5.0, "sp_after_met": 6.0,
    "sp_sec": 4.0,      "sp_body_boxes": 6.0,  "sp_boxes_cta": 5.0,
    "sp_cta_foot": 4.0, "lead_factor": 1.35,
    "metric_pad": 5.0,  "box_pad_tb": 5.0, "box_pad_lr": 6.0,
    "title_pad": 6.0,   "tab_pad": 3.0,
}
SCALE_MIN, SCALE_MAX = 0.48, 1.30
BFS_MIN,   BFS_MAX   = 5.0,  9.0


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _scale_params(scale):
    p = {}
    for k, v in NOM.items():
        if k.endswith("_fs"):
            p[k] = _clamp(v * scale, 5.0, v * 1.5)
        elif k.startswith("sp_") or k in ("metric_pad","box_pad_tb","box_pad_lr","title_pad","tab_pad"):
            p[k] = max(0.5, v * scale)
        elif k == "lead_factor":
            p[k] = _clamp(v * (0.5 + scale * 0.5), 1.15, 1.5)
        else:
            p[k] = v * scale
    return p


def _make_styles(p):
    def sty(name, fn="Helvetica", fs=8, tc=DGRAY, lead=None, align=TA_LEFT, **kw):
        ld = lead if lead is not None else fs * p["lead_factor"]
        return ParagraphStyle(name, fontName=fn, fontSize=fs, textColor=tc,
                              leading=ld, alignment=align, **kw)
    bfs = _clamp(p["bullet_fs"], BFS_MIN, BFS_MAX)
    return {
        "company":  sty("company",  "Helvetica-Bold", p["company_fs"],    NAVY),
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
        "ok":       sty("ok",       "Helvetica-Bold", p["box_title_fs"], GREEN2),
        "warn":     sty("warn",     "Helvetica-Bold", p["box_title_fs"], RED2),
        "cta":      sty("cta",      fs=p["cta_fs"],     tc=NAVY,  align=TA_CENTER),
        "cta_tel":  sty("cta_tel",  "Helvetica-Bold", p["cta_tel_fs"], TEAL, align=TA_CENTER),
        "cta_em":   sty("cta_em",   fs=p["cta_fs"]-0.2, tc=TEAL, align=TA_CENTER),
        "foot":     sty("foot",     fs=p["foot_fs"], tc=MGRAY, align=TA_CENTER),
    }


def _sp(p, key):
    return Spacer(1, max(0.5, p[key]))


def _build_story(p, content, logo_path):
    S  = _make_styles(p)
    CW = W - 2 * PAGE_MARGIN

    story = []

    # ── HEADER ────────────────────────────────────────────────────────────────
    txt_rows = [
        [Paragraph("Energelia S.r.l.", S["company"])],
        [Paragraph("Consulenza in Finanza Agevolata · Bandi &amp; Incentivi · Sostenibilita'", S["tagline"])],
        [Paragraph("Largo XII Ottobre 1/3, Torre WTC · 16121 Genova", S["addr"])],
        [Paragraph("a.augusti@energelia.it · b.legger@energelia.it · a.castagnaro@energelia.it", S["mail"])],
        [Paragraph("Tel. 010 8078800 · www.energelia.it", S["pec"])],
    ]
    txt_tbl = Table(txt_rows, colWidths=[CW])
    txt_tbl.setStyle(TableStyle([
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),0),  ("BOTTOMPADDING",(0,0),(-1,-1),0.8),
    ]))
    story.append(txt_tbl)
    story.append(HRFlowable(width=CW, thickness=1.5, color=TEAL, spaceAfter=p["sp_after_hr"]))

    # ── TITOLO ────────────────────────────────────────────────────────────────
    title_tbl = Table([
        [Paragraph(content["titolo"],      S["title"])],
        [Paragraph(content["sottotitolo"], S["subtitle"])],
    ], colWidths=[CW])
    title_tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),NAVY),
        ("TOPPADDING",(0,0),(-1,-1),p["title_pad"]),
        ("BOTTOMPADDING",(0,0),(-1,-1),p["title_pad"]),
        ("LEFTPADDING",(0,0),(-1,-1),10), ("RIGHTPADDING",(0,0),(-1,-1),10),
    ]))
    story.append(title_tbl)
    story.append(_sp(p, "sp_after_title"))

    # ── METRICHE (4 box) ──────────────────────────────────────────────────────
    # Altezza fissa box metriche — MAI dipende dal contenuto
    BOX_H_PT = 52   # punti tipografici, costante

    def metric_cell(m):
        bg   = BG_MAP.get(m.get("bg", "blue"), LBLUE)
        cw   = (CW/4) - 3*mm
        LBL_H = 11   # altezza fissa riga etichetta
        VAL_H = BOX_H_PT - LBL_H - 8  # altezza residua per il valore

        # Etichetta: sempre su una riga, uppercase, piccola
        label = str(m["label"]).upper()[:22]
        lbl   = Paragraph(label, S["met_lbl"])

        # Valore: tronca hard a max 15 car per riga, max 2 righe
        val_raw = str(m["valore"]).strip()
        if "\n" in val_raw:
            val_lines = [l[:15] for l in val_raw.split("\n")[:2]]
            vfs = p["metric_val_fs"] * 0.80
        else:
            val_lines = [val_raw[:16]]
            if   len(val_raw) <= 6:  vfs = p["metric_val_fs"] * 1.10
            elif len(val_raw) <= 10: vfs = p["metric_val_fs"]
            elif len(val_raw) <= 14: vfs = p["metric_val_fs"] * 0.88
            else:                    vfs = p["metric_val_fs"] * 0.76

        val_paras = [
            Paragraph(vl, ParagraphStyle(
                "_mv", fontName="Helvetica-Bold",
                fontSize=vfs, textColor=NAVY,
                leading=vfs * 1.15, alignment=TA_CENTER,
                wordWrap=None,       # MAI andare a capo automaticamente
                allowWidows=0, allowOrphans=0,
            )) for vl in val_lines
        ]

        # Table interna: riga etichetta + riga/e valore, altezze fisse
        n_val = len(val_paras)
        rh_val = VAL_H / n_val
        inner = Table(
            [[lbl]] + [[vp] for vp in val_paras],
            colWidths  = [cw],
            rowHeights = [LBL_H] + [rh_val] * n_val,
        )
        inner.setStyle(TableStyle([
            ("BACKGROUND",   (0,0),(-1,-1), bg),
            ("TOPPADDING",   (0,0),(-1,-1), 2),
            ("BOTTOMPADDING",(0,0),(-1,-1), 2),
            ("LEFTPADDING",  (0,0),(-1,-1), 3),
            ("RIGHTPADDING", (0,0),(-1,-1), 3),
            ("VALIGN",       (0,0),(-1,-1), "MIDDLE"),
        ]))
        return inner

    # Tabella esterna: 4 colonne, altezza fissa uguale per tutti
    met_cells = [metric_cell(m) for m in content["metriche"]]
    met_tbl = Table(
        [met_cells],
        colWidths  = [(CW/4) - 1*mm] * 4,
        rowHeights = [BOX_H_PT],
        hAlign     = "LEFT",
    )
    met_tbl.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0),(-1,-1), 1.5),
        ("RIGHTPADDING", (0,0),(-1,-1), 1.5),
        ("TOPPADDING",   (0,0),(-1,-1), 0),
        ("BOTTOMPADDING",(0,0),(-1,-1), 0),
        ("VALIGN",       (0,0),(-1,-1), "MIDDLE"),
    ]))
    story.append(met_tbl)
    story.append(_sp(p, "sp_after_met"))

    # ── CORPO 2 COLONNE ───────────────────────────────────────────────────────
    COL1 = CW * 0.52
    COL2 = CW * 0.44
    GAP  = CW - COL1 - COL2

    def render_section(sec_data, col_w):
        out = []
        hd  = Table([[Paragraph("| " + sec_data["titolo"], S["sec"])]], colWidths=[col_w])
        hd.setStyle(TableStyle([
            ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
            ("TOPPADDING",(0,0),(-1,-1),1),  ("BOTTOMPADDING",(0,0),(-1,-1),2),
        ]))
        out.append(hd)
        for voce in sec_data["voci"]:
            out.append(Paragraph("\u2022 " + voce, S["bullet"]))
        out.append(_sp(p, "sp_sec"))
        return out

    left = []
    for sd in content["sinistra"]:
        left += render_section(sd, COL1)

    right = []
    tc_def = content.get("tabella_contributi")
    if tc_def:
        right.append(Paragraph("| CONTRIBUTO / INTENSITA'", S["sec"]))
        right.append(Spacer(1, 2))
        n_cols    = len(tc_def["header"])
        tab_data  = [[Paragraph(h, S["tabh"]) for h in tc_def["header"]]]
        for row in tc_def["righe"]:
            is_best = row[-1] if isinstance(row[-1], bool) else False
            cells   = row[:-1] if isinstance(row[-1], bool) else row
            stl     = [S["tabcb"] if (j == n_cols-1 and is_best) else S["tabc"]
                       for j in range(n_cols)]
            tab_data.append([Paragraph(cells[j], stl[j]) for j in range(n_cols)])
        ct = Table(tab_data, colWidths=[COL2/n_cols]*n_cols)
        ts = [
            ("BACKGROUND",(0,0),(-1,0),NAVY),
            ("GRID",(0,0),(-1,-1),0.4,LGRAY),
            ("TOPPADDING",(0,0),(-1,-1),p["tab_pad"]),
            ("BOTTOMPADDING",(0,0),(-1,-1),p["tab_pad"]),
            ("LEFTPADDING",(0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4),
        ]
        for i, row in enumerate(tc_def["righe"]):
            is_best = row[-1] if isinstance(row[-1], bool) else False
            bg = LGREEN if is_best else (WHITE if i % 2 == 0 else F5F9)
            ts.append(("BACKGROUND",(0,i+1),(-1,i+1),bg))
        ct.setStyle(TableStyle(ts))
        right.append(ct)
        for nota in (tc_def.get("note") or []):
            right.append(Paragraph("\u2022 " + nota, S["bullet"]))
        right.append(_sp(p, "sp_sec"))

    for sd in content["destra"]:
        right += render_section(sd, COL2)

    def build_col(items, col_w):
        t = Table([[item] for item in items], colWidths=[col_w])
        t.setStyle(TableStyle([
            ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
            ("TOPPADDING",(0,0),(-1,-1),0),  ("BOTTOMPADDING",(0,0),(-1,-1),0),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
        ]))
        return t

    body = Table(
        [[build_col(left, COL1), Spacer(GAP, 1), build_col(right, COL2)]],
        colWidths=[COL1, GAP, COL2])
    body.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),0),  ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))
    story.append(body)
    story.append(_sp(p, "sp_body_boxes"))

    # ── BOX VERDE / ROSSO ─────────────────────────────────────────────────────
    HW = (CW/2) - 4*mm

    def render_box(title_para, voci, col_w):
        rows = [[title_para]]
        for v in voci:
            rows.append([Paragraph("\u2022 " + v, S["bullet"])])
        t = Table(rows, colWidths=[col_w])
        t.setStyle(TableStyle([
            ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
            ("TOPPADDING",(0,0),(-1,-1),0),  ("BOTTOMPADDING",(0,0),(-1,-1),1.5),
        ]))
        return t

    box = Table([[
        render_box(Paragraph("(+)  PERCHE' E' INTERESSANTE", S["ok"]),
                   content["punti_forza"], HW),
        render_box(Paragraph("(!)  CRITICITA' E ATTENZIONI",  S["warn"]),
                   content["criticita"],   HW),
    ]], colWidths=[CW/2, CW/2])
    box.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(0,0),LGREEN), ("BACKGROUND",(1,0),(1,0),LRED),
        ("BOX",(0,0),(0,0),0.6,GREEN2),    ("BOX",(1,0),(1,0),0.6,RED2),
        ("TOPPADDING",(0,0),(-1,-1),p["box_pad_tb"]),
        ("BOTTOMPADDING",(0,0),(-1,-1),p["box_pad_tb"]),
        ("LEFTPADDING",(0,0),(-1,-1),p["box_pad_lr"]),
        ("RIGHTPADDING",(0,0),(-1,-1),p["box_pad_lr"]),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
    ]))
    story.append(box)
    story.append(_sp(p, "sp_boxes_cta"))

    # ── CTA ───────────────────────────────────────────────────────────────────
    cta = Table([[
        Paragraph(content["cta_testo"], S["cta"]),
        Paragraph(f"<b>{content['cta_tel']}</b>", S["cta_tel"]),
        Paragraph(content["cta_email"], S["cta_em"]),
    ]], colWidths=[CW*0.45, CW*0.27, CW*0.28])
    cta.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),LBLUE),
        ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING",(0,0),(-1,-1),8), ("RIGHTPADDING",(0,0),(-1,-1),8),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("LINEAFTER",(0,0),(1,0),0.5,TEAL),
    ]))
    story.append(cta)
    story.append(_sp(p, "sp_cta_foot"))

    # ── FOOTER ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width=CW, thickness=0.5, color=LGRAY, spaceAfter=2))
    story.append(Paragraph(
        "Energelia S.r.l. · Largo XII Ottobre 1/3, Torre WTC · 16121 Genova "
        "· Tel. 010 8078800 · www.energelia.it<br/>"
        f"{content.get('fonte','')} · {content.get('mese_anno','')}<br/>"
        "Il presente documento ha valore informativo. "
        "Fare riferimento al testo ufficiale del bando per tutti i contenuti vincolanti.",
        S["foot"]
    ))
    return story


def _count_pages(story):
    """Conta le pagine costruendo il PDF in memoria."""
    from pypdf import PdfReader
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
                            topMargin=TOP_MARGIN,   bottomMargin=BOT_MARGIN)
    doc.build(story)
    buf.seek(0)
    return len(PdfReader(buf).pages)


def generate(content, output_path, logo_path, log_fn=None):
    """
    Genera il PDF della scheda bando.
    - content:     dict con i dati del bando (struttura CONTENT)
    - output_path: percorso del file PDF di output
    - logo_path:   percorso del logo PNG Energelia
    - log_fn:      callable opzionale per messaggi di progresso
    Restituisce il percorso del file generato.
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    log("Calibrazione scala...")
    lo, hi, best = SCALE_MIN, SCALE_MAX, SCALE_MIN
    for i in range(10):
        mid   = (lo + hi) / 2
        story = _build_story(_scale_params(mid), content, logo_path)
        n     = _count_pages(story)
        log(f"  iter {i+1}: scale={mid:.3f}  pagine={n}")
        if n <= 1:
            best = mid
            lo   = mid
        else:
            hi   = mid
        if hi - lo < 0.005:
            break

    log(f"Scala ottimale: {best:.3f}")
    story = _build_story(_scale_params(best), content, logo_path)

    import os
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                            leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
                            topMargin=TOP_MARGIN,   bottomMargin=BOT_MARGIN)
    doc.build(story)
    log(f"PDF salvato: {output_path}")
    return output_path
