"""
schede_engine.py — Motore ReportLab per schede bandi Energelia
================================================================
Layout: testata navy con lockup logo, fascia metriche, card a due colonne
con barra titolo navy, pannelli "perche' interessante" / "criticita'",
CTA navy, footer. Impagina su 1 o 2 pagine A4 secondo la quantita' di
contenuto, senza comprimere il corpo del testo oltre il leggibile.

API invariata rispetto alla versione precedente:
    generate(content, output_path, logo_path, log_fn=None) -> str

Schema CONTENT accettato (tutte le chiavi opzionali tranne 'titolo'):
    titolo, sottotitolo, eyebrow, refline
    metriche  : [{label, valore, sub}]            (max 4)
    sinistra  : [{titolo, voci:[str]}]
    destra    : [{titolo, voci:[str]}]
    sezioni   : [{titolo, voci:[str]}]            alternativa a sinistra/destra
    tabella_contributi : {header:[...], righe:[[...]], note:[...]}
    punti_forza : [str]
    criticita   : [str]
    cta_testo, cta_tel, cta_email
    fonte, mese_anno
Nelle voci sono ammessi i tag <b>...</b>.

Requisiti: reportlab, pypdf (opzionale), pillow (opzionale, per il logo)
"""

import os
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph, Table, TableStyle, Flowable

# ── PALETTE ───────────────────────────────────────────────────────────────────
NAVY   = colors.HexColor("#0D2242")
GOLD   = colors.HexColor("#E0A33C")
AMBER  = colors.HexColor("#B4741B")
GREEN  = colors.HexColor("#2F6B4F")
INK    = colors.HexColor("#1B2432")
MUTED  = colors.HexColor("#5C6B80")
HAIR   = colors.HexColor("#D6DDE7")
WASH   = colors.HexColor("#F4F7FB")
WHITE  = colors.white
PANEL_G_BG, PANEL_G_BD = colors.HexColor("#F4F9F6"), colors.HexColor("#BFD6C7")
PANEL_A_BG, PANEL_A_BD = colors.HexColor("#FDF8F0"), colors.HexColor("#E4C79A")

W, H     = A4
MARGIN   = 11 * mm
CW       = W - 2 * MARGIN
COL_GAP  = 6 * mm
COL_W    = (CW - COL_GAP) / 2

HDR1_H   = 30 * mm          # testata pagina 1
HDR2_H   = 17 * mm          # testata pagine successive
RULE_H   = 0.7 * mm         # filetto oro
MET_H    = 17 * mm          # fascia metriche
TITLE_MAXLINES = 3          # righe max per il titolo in testata
FOOT_H   = 13 * mm
GAP_TOP  = 5.6 * mm         # aria fra fascia e primo blocco

# ── Dati societari: unico punto di verita' per testata, CTA e footer ─────────
TEL       = "010 7776530"
EMAIL     = "info@energelia.it"
INDIRIZZO = "Piazza Giacomo Matteotti 2, interno 3C · 16123 Genova"
FOOT_TXT_L = ("<b>Energelia S.r.l.</b> · Consulenza in Finanza Agevolata · "
              "Bandi &amp; Incentivi · Sostenibilita'<br/>"
              + INDIRIZZO + " · Tel. " + TEL + " · www.energelia.it")

# ── SCALA TIPOGRAFICA ─────────────────────────────────────────────────────────
NOM = {
    "bullet": 7.6, "card_title": 6.6, "rate": 6.3,
    "panel_title": 6.7, "cta": 7.8, "cta_tel": 9.6,
    "lead": 1.34, "bullet_gap": 1.5 * mm,
    "card_gap": 4.0 * mm, "card_pad": 3.2 * mm, "title_pad": 2.2 * mm,
}
FS_MIN, FS_MAX = 6.9, 9.0   # 6.9pt = minimo leggibile a stampa


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _p(scale):
    q = {}
    for k, v in NOM.items():
        if k == "lead":
            q[k] = _clamp(v, 1.20, 1.42)
        elif k.endswith("gap") or k.endswith("pad"):
            q[k] = max(1.1 * mm, v * (0.62 + 0.38 * scale))
        else:
            q[k] = _clamp(v * scale, FS_MIN, FS_MAX)
    return q


def _styles(q):
    lead = q["lead"]
    return {
        "bullet": ParagraphStyle(
            "bullet", fontName="Helvetica", fontSize=q["bullet"], textColor=INK,
            leading=q["bullet"] * lead, alignment=TA_LEFT,
            leftIndent=3.0 * mm, bulletIndent=0, spaceAfter=q["bullet_gap"],
            bulletFontName="Helvetica", bulletFontSize=q["bullet"] * 0.62,
            bulletColor=GOLD, bulletOffsetY=-q["bullet"] * 0.20,
        ),
        "panel_bullet": ParagraphStyle(
            "pbullet", fontName="Helvetica", fontSize=q["bullet"], textColor=INK,
            leading=q["bullet"] * lead, leftIndent=3.0 * mm, bulletIndent=0,
            spaceAfter=q["bullet_gap"],
            bulletFontName="Helvetica", bulletFontSize=q["bullet"] * 0.62,
            bulletOffsetY=-q["bullet"] * 0.20,
        ),
        "tab": ParagraphStyle("tab", fontName="Helvetica", fontSize=q["bullet"] * 0.95,
                              textColor=INK, leading=q["bullet"] * 1.25),
        "tabh": ParagraphStyle("tabh", fontName="Helvetica-Bold", fontSize=q["bullet"] * 0.9,
                               textColor=WHITE, leading=q["bullet"] * 1.25),
        "cta": ParagraphStyle("cta", fontName="Helvetica", fontSize=q["cta"],
                              textColor=WHITE, leading=q["cta"] * 1.42),
        "cta_c": ParagraphStyle("cta_c", fontName="Helvetica", fontSize=q["cta"] * 0.86,
                                textColor=colors.HexColor("#D6E1F0"),
                                leading=q["cta"] * 1.30, alignment=TA_RIGHT),
        "foot": ParagraphStyle("foot", fontName="Helvetica", fontSize=5.7,
                               textColor=MUTED, leading=5.7 * 1.45),
        "footr": ParagraphStyle("footr", fontName="Helvetica", fontSize=5.7,
                                textColor=MUTED, leading=5.7 * 1.45, alignment=TA_RIGHT),
    }


def _tracked(c, x, y, text, font, size, color, track, anchor="l"):
    """Testo con spaziatura fra lettere (reportlab non la offre nei Paragraph)."""
    c.saveState()
    c.setFillColor(color)
    if anchor == "r":
        x -= stringWidth(text, font, size) + track * max(0, len(text) - 1)
    to = c.beginText(x, y)
    to.setFont(font, size)
    to.setFillColor(color)
    try:
        to.setCharSpace(track)
    except Exception:
        pass
    to.textOut(text)
    c.drawText(to)
    c.restoreState()


def _fit(c, text, font, size, maxw, track=0.0):
    """Riduce il corpo finche' il testo sta nella larghezza data."""
    s = size
    while s > 5.0:
        wdt = stringWidth(text, font, s) + track * max(0, len(text) - 1)
        if wdt <= maxw:
            break
        s -= 0.25
    return s


def _wrap(text, font, size, maxw, maxlines):
    """Spezza il testo su piu' righe rispettando la larghezza disponibile."""
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if stringWidth(trial, font, size) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
            if len(lines) == maxlines:
                break
    if cur and len(lines) < maxlines:
        lines.append(cur)
    return lines or [str(text)]


def _wrap_all(text, font, size, maxw):
    """Come _wrap ma SENZA limite di righe: non perde mai parole."""
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if stringWidth(trial, font, size) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [str(text)]


def _wrap_fit(text, font, size_max, maxw, maxlines, size_min=8.4, step=0.2):
    """Trova il corpo piu' grande che fa stare il titolo INTERO in 'maxlines'
    righe. Restituisce (righe, corpo). Solo se nemmeno al corpo minimo il testo
    entra si tronca, e comunque all'ultima parola intera con ellissi."""
    text = " ".join(str(text).split())
    if not text:
        return [], size_max
    s = size_max
    while s >= size_min:
        lines = _wrap_all(text, font, s, maxw)
        if len(lines) <= maxlines:
            return lines, s
        s -= step
    lines = _wrap_all(text, font, size_min, maxw)[:maxlines]
    if lines:
        last = lines[-1]
        while last and stringWidth(last + " ...", font, size_min) > maxw:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = last + " ..."
    return lines, size_min


def _cut_words(text, font, size, maxw, suffix=" ..."):
    """Accorcia su una riga sola tagliando all'ultima parola intera."""
    t = " ".join(str(text).split())
    if stringWidth(t, font, size) <= maxw:
        return t
    while t and stringWidth(t + suffix, font, size) > maxw:
        t = t.rsplit(" ", 1)[0] if " " in t else t[:-1]
    return (t + suffix) if t else ""


_MET_MAXCH = 18
_RE_DATA = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b")


def _metric_value(label, valore):
    """Riduce il valore dei box metriche a un dato da colpo d'occhio.
    Il testo esteso resta nelle card: qui serve solo il numero chiave.
      "80% fondo perduto delle spese ammissibili"  -> "80%"
      "EUR 100.000 (EUR 110.000 con premialita')"  -> "EUR 100.000"
      "2 milioni di euro"                          -> "EUR 2 MLN"
    """
    v = " ".join(str(valore or "").split())
    if not v or v.strip(" .-\u2013\u2014") == "":
        return "\u2014"
    # ripulisce eventuali troncature gia' fatte a monte
    v = re.sub(r"\s*(?:\u2026|\.{3})\s*$", "", v).strip()
    v = re.sub(r"\s*\($", "", v).strip()
    lab = str(label or "")

    e_data = re.search(r"scaden|apertur|chiusur|termin|\bdata\b", lab, re.I)
    md = _RE_DATA.search(v)
    if md and e_data:
        return "%s/%s/%s" % md.groups()

    # percentuale (anche intervallo), purche' all'inizio del valore
    mr = re.match(r"^\D{0,14}?(\d{1,3})\s*%\D{0,18}?(\d{1,3})\s*%", v)
    if mr:
        return "%s%%-%s%%" % mr.groups()
    ms = re.match(r"^\D{0,14}?(\d{1,3})\s*%", v)
    if ms:
        return ms.group(1) + "%"

    # milioni / miliardi
    for rx, suf in ((r"([\d]+(?:[.,][\d]+)?)\s*(?:mln|milion\w*)\b", "MLN"),
                    (r"([\d]+(?:[.,][\d]+)?)\s*(?:mld|miliard\w*)\b", "MLD")):
        m = re.search(rx, v, re.I)
        if m:
            n = m.group(1).replace(",", ".")
            try:
                n = "%g" % float(n)
            except ValueError:
                pass
            return "EUR %s %s" % (n, suf)

    # primo importo in euro
    m = re.search(r"(?:EUR|\u20ac|euro)\s*([\d][\d.,]*)", v, re.I)
    if m:
        return "EUR " + m.group(1).rstrip(".,")
    m = re.search(r"\b(\d{1,3}(?:\.\d{3})+(?:,\d{2})?)\b", v)
    if m:
        return "EUR " + m.group(1)

    if md:
        return "%s/%s/%s" % md.groups()

    if len(v) <= _MET_MAXCH:
        return v
    out = v[:_MET_MAXCH]
    if " " in out and not v[_MET_MAXCH:_MET_MAXCH + 1].isspace():
        out = out.rsplit(" ", 1)[0]
    return out.rstrip(" ,;.:-") or v[:_MET_MAXCH]


# ── FLOWABLE: barra titolo card ───────────────────────────────────────────────
class TitleBar(Flowable):
    def __init__(self, text, width, fs, pad, bg=NAVY, fg=WHITE, track=1.05):
        Flowable.__init__(self)
        self.text, self.width0, self.fs = text.upper(), width, fs
        self.pad, self.bg, self.fg, self.track = pad, bg, fg, track
        self.height0 = fs * 1.05 + 2 * pad

    def wrap(self, aw, ah):
        return self.width0, self.height0

    def draw(self):
        c = self.canv
        if self.bg is not None:
            c.setFillColor(self.bg)
            c.rect(0, 0, self.width0, self.height0, stroke=0, fill=1)
        inner = self.width0 - 2 * (3.2 * mm)
        fs = _fit(c, self.text, "Helvetica-Bold", self.fs, inner, self.track)
        _tracked(c, 3.2 * mm, self.pad + self.fs * 0.20, self.text,
                 "Helvetica-Bold", fs, self.fg, self.track)


# ── FLOWABLE: riga "intensita'" dentro la card ────────────────────────────────
class RateRow(Flowable):
    def __init__(self, label, value, width, fs):
        Flowable.__init__(self)
        self.label, self.value, self.width0, self.fs = label.upper(), value, width, fs
        self.height0 = fs * 2.5

    def wrap(self, aw, ah):
        return self.width0, self.height0

    def draw(self):
        c = self.canv
        base = self.fs * 1.15
        _tracked(c, 0, base, self.label, "Helvetica-Bold", self.fs, AMBER, 0.75)
        if self.value:
            _tracked(c, self.width0, base, str(self.value), "Helvetica-Bold",
                     self.fs, NAVY, 0.25, anchor="r")
        c.setStrokeColor(HAIR)
        c.setLineWidth(0.4)
        c.line(0, base - self.fs * 0.55, self.width0, base - self.fs * 0.55)


# ── COSTRUZIONE BLOCCHI ───────────────────────────────────────────────────────
def _bullets(voci, S, style="bullet"):
    out = []
    for v in voci:
        t = str(v).strip()
        if not t:
            continue
        if t.startswith("::"):                      # "::Etichetta|Valore" -> RateRow
            body = t[2:]
            lab, _, val = body.partition("|")
            out.append(("rate", lab.strip(), val.strip()))
        else:
            out.append(("p", Paragraph(t, S[style], bulletText="\u25cf"), None))
    return out


def _card(sec, q, S, width):
    """Card = barra titolo navy + corpo bordato. Restituisce un Table."""
    items = _bullets(sec.get("voci", []), S)
    body = []
    inner_w = width - 2 * q["card_pad"]
    for kind, a, b in items:
        body.append(RateRow(a, b, inner_w, q["rate"]) if kind == "rate" else a)
    if not body:
        body = [Paragraph("Dato non disponibile nel testo del bando.", S["bullet"],
                          bulletText="\u25cf")]

    t = Table([[TitleBar(sec.get("titolo", ""), width, q["card_title"], q["title_pad"])],
               [body]], colWidths=[width])
    t.setStyle(TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, 0), 0), ("RIGHTPADDING", (0, 0), (-1, 0), 0),
        ("TOPPADDING",   (0, 0), (-1, 0), 0), ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
        ("LEFTPADDING",  (0, 1), (-1, 1), q["card_pad"]),
        ("RIGHTPADDING", (0, 1), (-1, 1), q["card_pad"]),
        ("TOPPADDING",   (0, 1), (-1, 1), q["card_pad"] * 0.9),
        ("BOTTOMPADDING", (0, 1), (-1, 1), q["card_pad"] * 0.6),
        ("BOX",       (0, 1), (-1, 1), 0.4, HAIR),
        ("LINEAFTER", (0, 1), (-1, 1), 0.4, HAIR),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _tabella(tc, q, S, width):
    """Tabella contributi opzionale, resa come card."""
    hdr = [Paragraph(str(h), S["tabh"]) for h in tc.get("header", [])]
    rows = [hdr]
    styles = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.4, HAIR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
    ]
    for i, r in enumerate(tc.get("righe", []), start=1):
        cells = list(r)
        evid = bool(cells[-1]) if len(cells) > len(hdr) else False
        cells = cells[:len(hdr)] if len(hdr) else cells
        rows.append([Paragraph(str(x), S["tab"]) for x in cells])
        if evid:
            styles.append(("BACKGROUND", (0, i), (-1, i), WASH))
    n = max(1, len(hdr))
    t = Table(rows, colWidths=[width / n] * n)
    t.setStyle(TableStyle(styles))
    return t


def _panel(titolo, voci, q, S, kind, width):
    bg, bd, fg = ((PANEL_G_BG, PANEL_G_BD, GREEN) if kind == "good"
                  else (PANEL_A_BG, PANEL_A_BD, AMBER))
    st = ParagraphStyle("pb_%s" % kind, parent=S["panel_bullet"], bulletColor=fg)
    half = (width - 2 * q["card_pad"] - COL_GAP) / 2
    paras = [Paragraph(str(v), st, bulletText="\u25cf") for v in voci if str(v).strip()]
    if not paras:
        return None
    mid = (len(paras) + 1) // 2
    two = Table([[paras[:mid], paras[mid:]]], colWidths=[half + COL_GAP / 2] * 2)
    two.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), COL_GAP / 2),
        ("LEFTPADDING", (1, 0), (1, 0), COL_GAP / 2), ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    t = Table([[TitleBar(titolo, width, q["panel_title"], q["title_pad"], bg=None, fg=fg)],
               [two]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.4, bd),
        ("LINEBEFORE", (0, 0), (0, -1), 1.1 * mm, fg),
        ("LEFTPADDING", (0, 0), (-1, -1), q["card_pad"]),
        ("RIGHTPADDING", (0, 0), (-1, -1), q["card_pad"]),
        ("TOPPADDING", (0, 0), (-1, 0), q["card_pad"] * 0.7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
        ("TOPPADDING", (0, 1), (-1, 1), q["card_pad"] * 0.4),
        ("BOTTOMPADDING", (0, 1), (-1, 1), q["card_pad"] * 0.7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _cta(content, q, S):
    left = Paragraph(str(content.get("cta_testo", "")), S["cta"])
    tel = TEL
    right = [
        Paragraph('<font size="%.1f" color="#FFFFFF"><b>%s</b></font>' % (q["cta_tel"], tel),
                  S["cta_c"]),
        Paragraph(EMAIL, S["cta_c"]),
    ]
    t = Table([[left, right]], colWidths=[CW * 0.68, CW * 0.32])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LINEBEFORE", (1, 0), (1, 0), 0.4, colors.HexColor("#43587A")),
        ("LEFTPADDING", (0, 0), (0, 0), 4.6 * mm), ("RIGHTPADDING", (0, 0), (0, 0), 6 * mm),
        ("LEFTPADDING", (1, 0), (1, 0), 6 * mm), ("RIGHTPADDING", (1, 0), (1, 0), 4.6 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


# ── LOGO: ricerca del file ────────────────────────────────────────────────────
LOGO_NOMI = (
    "nuovo_logo_Energelia.png", "nuovo logo Energelia.png",
    "Logo_Energelia_realistico.png", "Logo Energelia realistico.png",
    "logo_energelia.png", "logo_Energelia.png", "logo.png",
)
LOGO_DIRS = (
    r"C:\Users\alber\Desktop\Cartellona programmi Energelia\Mailing e Scraping\Creazione Schede",
    r"C:\Users\alber\Desktop\Cartellona programmi Energelia\Creazione Schede",
    r"C:\Users\alber\Desktop\Sito Italbandi Gestione",
)


def trova_logo(indizio=None):
    """Accetta un file, una cartella o None e restituisce il PNG del logo."""
    cand = []
    if indizio:
        ind = str(indizio)
        if os.path.isfile(ind):
            return ind
        if os.path.isdir(ind):
            cand += [os.path.join(ind, n) for n in LOGO_NOMI]
        else:
            cand += [os.path.join(os.path.dirname(ind), n) for n in LOGO_NOMI]
    for d in LOGO_DIRS:
        cand += [os.path.join(d, n) for n in LOGO_NOMI]
    here = os.path.dirname(os.path.abspath(__file__))
    cand += [os.path.join(here, n) for n in LOGO_NOMI]
    for c in cand:
        if os.path.isfile(c):
            return c
    # ultima spiaggia: scansione ricorsiva delle cartelle note
    radici = [here] + [d for d in LOGO_DIRS if os.path.isdir(d)]
    if indizio and os.path.isdir(str(indizio)):
        radici.insert(0, str(indizio))
    for radice in radici:
        for base, _dirs, files in os.walk(radice):
            for f in files:
                low = f.lower()
                if low.endswith(".png") and "energelia" in low and "logo" in low:
                    return os.path.join(base, f)
    return None


# ── LOGO: ritaglio emblema + wordmark con fondo trasparente ───────────────────
def _prepare_logo(logo_path):
    """Separa lanterna e lettering dal logo quadrato. Cache accanto al file."""
    if not logo_path or not os.path.exists(str(logo_path)):
        return None, None
    base = os.path.splitext(str(logo_path))[0]
    emb, wrd = base + "_emblema.png", base + "_wordmark.png"
    # su hosting con filesystem di sola lettura (Render, container) i ritagli
    # vanno in cartella temporanea, altrimenti il logo sparirebbe in silenzio
    cartella = os.path.dirname(os.path.abspath(str(logo_path)))
    if not os.access(cartella, os.W_OK):
        import tempfile
        tmpd = os.path.join(tempfile.gettempdir(), "energelia_logo")
        try:
            os.makedirs(tmpd, exist_ok=True)
            nome = os.path.basename(base)
            emb = os.path.join(tmpd, nome + "_emblema.png")
            wrd = os.path.join(tmpd, nome + "_wordmark.png")
        except Exception:
            pass
    if os.path.exists(emb) and os.path.exists(wrd):
        return emb, wrd
    try:
        from PIL import Image
    except Exception:
        return None, None
    try:
        im = Image.open(str(logo_path)).convert("RGB")
        px, wI, hI = im.load(), im.size[0], im.size[1]

        def luma(t):
            return 0.299 * t[0] + 0.587 * t[1] + 0.114 * t[2]

        rows = [max(luma(px[x, y]) for x in range(0, wI, 3)) for y in range(hI)]
        bands, inb, s0 = [], False, 0
        for y, m in enumerate(rows):
            if m > 70 and not inb:
                inb, s0 = True, y
            elif m <= 70 and inb:
                inb = False
                if y - s0 > hI * 0.02:
                    bands.append((s0, y))
        if inb and hI - s0 > hI * 0.02:
            bands.append((s0, hI))
        if not bands:
            return None, None

        def hspan(a, b):
            xs = [x for x in range(wI)
                  if max(luma(px[x, y]) for y in range(a, b, 2)) > 70]
            return (min(xs), max(xs)) if xs else (0, wI - 1)

        def cut(box, out):
            crop = im.crop(box).convert("RGBA")
            cp = crop.load()
            for yy in range(crop.size[1]):
                for xx in range(crop.size[0]):
                    r, g, b, _ = cp[xx, yy]
                    a = _clamp((luma((r, g, b)) - 44.0) / 18.0, 0.0, 1.0)
                    cp[xx, yy] = (r, g, b, int(a * 255))
            crop.save(out)

        pad = int(hI * 0.008)
        y0, y1 = bands[0]
        x0, x1 = hspan(y0, y1)
        cut((max(0, x0 - pad), max(0, y0 - pad), min(wI, x1 + pad), min(hI, y1 + pad)), emb)

        if len(bands) > 1:
            y0, y1 = bands[1][0], bands[-1][1]
            x0, x1 = hspan(bands[1][0], bands[1][1])
            xa, xb = hspan(bands[-1][0], bands[-1][1])
            x0, x1 = min(x0, xa), max(x1, xb)
            cut((max(0, x0 - pad), max(0, y0 - pad),
                 min(wI, x1 + pad), min(hI, y1 + pad)), wrd)
        else:
            wrd = None
        return emb, wrd
    except Exception:
        return None, None


# ── FURNITURE DI PAGINA ───────────────────────────────────────────────────────
def _draw_header(c, content, emb, wrd, first, page_no, n_pages):
    hh = HDR1_H if first else HDR2_H
    top = H
    c.setFillColor(NAVY)
    c.rect(0, top - hh - RULE_H, W, hh + RULE_H, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.rect(0, top - hh - RULE_H, W, RULE_H, stroke=0, fill=1)

    cy = top - hh / 2 - RULE_H / 2
    x = MARGIN
    eh = (19 if first else 12.4) * mm
    if emb:
        try:
            from reportlab.lib.utils import ImageReader
            ir = ImageReader(emb)
            iw, ih = ir.getSize()
            ew = eh * iw / ih
            c.drawImage(ir, x, cy - eh / 2, width=ew, height=eh, mask="auto")
            x += ew + 3.4 * mm
        except Exception:
            pass
    if wrd:
        try:
            from reportlab.lib.utils import ImageReader
            ir = ImageReader(wrd)
            iw, ih = ir.getSize()
            wh = (10 if first else 7.3) * mm
            ww = wh * iw / ih
            c.drawImage(ir, x, cy - wh / 2, width=ww, height=wh, mask="auto")
            x += ww
        except Exception:
            pass

    sep = x + 4.5 * mm
    c.setStrokeColor(colors.HexColor("#4B5F80"))
    c.setLineWidth(0.4)
    c.line(sep, cy - hh * 0.32, sep, cy + hh * 0.32)
    tx = sep + 8 * mm
    avail = W - MARGIN - tx

    if first:
        eyebrow = content.get("eyebrow") or ""
        title = " ".join(str(content.get("titolo", "")).split())
        sub = " ".join(str(content.get("sottotitolo", "")).split())
        refl = content.get("refline") or ""

        # Il titolo non viene mai tagliato: si cerca il corpo piu' grande che
        # lo faccia stare per intero in un massimo di TITLE_MAXLINES righe.
        lines, fs = _wrap_fit(title, "Helvetica-Bold", 15.0, avail, TITLE_MAXLINES)

        # Blocco testo centrato verticalmente nella testata
        blk = (5.6 * mm if eyebrow else 1.5 * mm)
        blk += fs * 1.16 * max(1, len(lines)) + 1.6 * mm
        if sub:
            blk += 4.4 * mm
        if refl:
            blk += 3.0 * mm
        y = cy + max(blk / 2 - 2.0 * mm, hh * 0.18)
        y = min(y, cy + hh * 0.34)

        if eyebrow:
            _tracked(c, tx, y, eyebrow.upper(), "Helvetica-Bold",
                     _fit(c, eyebrow.upper(), "Helvetica-Bold", 6.4, avail, 1.5),
                     GOLD, 1.5)
            y -= 5.6 * mm
        else:
            y -= 1.5 * mm
        c.setFont("Helvetica-Bold", fs)
        c.setFillColor(WHITE)
        for ln in lines:
            c.drawString(tx, y, ln)
            y -= fs * 1.16
        y -= 1.6 * mm
        if sub:
            sfs = _fit(c, sub, "Helvetica", 9.5, avail)
            if sfs < 7.4:
                sfs = 7.4
                sub = _cut_words(sub, "Helvetica", sfs, avail)
            c.setFont("Helvetica", sfs)
            c.setFillColor(colors.HexColor("#C9D6E8"))
            c.drawString(tx, y, sub)
            y -= 4.4 * mm
        if refl:
            rfs = _fit(c, refl, "Helvetica", 6.2, avail)
            _tracked(c, tx, y, refl, "Helvetica", rfs, colors.HexColor("#93A8C4"), 0.25)
    else:
        title = " ".join(str(content.get("titolo", "")).split())
        wmax = avail - 24 * mm
        fs = _fit(c, title, "Helvetica-Bold", 10.6, wmax)
        if fs <= 7.6:
            fs = 7.6
            title = _cut_words(title, "Helvetica-Bold", fs, wmax)
        c.setFont("Helvetica-Bold", fs)
        c.setFillColor(WHITE)
        c.drawString(tx, cy + 0.6 * mm, title)
        sub = " ".join(str(content.get("sottotitolo", "")).split())
        if sub:
            sfs = _fit(c, sub, "Helvetica", 7.4, wmax)
            if sfs <= 6.0:
                sfs = 6.0
                sub = _cut_words(sub, "Helvetica", sfs, wmax)
            c.setFont("Helvetica", sfs)
            c.setFillColor(colors.HexColor("#C9D6E8"))
            c.drawString(tx, cy - 3.4 * mm, sub)
        _tracked(c, W - MARGIN, cy, "PAG. %d DI %d" % (page_no, n_pages),
                 "Helvetica-Bold", 6.2, colors.HexColor("#93A8C4"), 1.4, anchor="r")


def _draw_metrics(c, metriche):
    top = H - HDR1_H - RULE_H
    c.setFillColor(WASH)
    c.rect(0, top - MET_H, W, MET_H, stroke=0, fill=1)
    c.setStrokeColor(HAIR)
    c.setLineWidth(0.4)
    c.line(0, top - MET_H, W, top - MET_H)

    ms = (metriche or [])[:4]
    if not ms:
        return
    n = len(ms)
    seg = W / n
    for i, m in enumerate(ms):
        x0 = i * seg
        if i:
            c.line(x0, top - MET_H + 2.5 * mm, x0, top - 2.5 * mm)
        tx = x0 + (MARGIN if i == 0 else 5 * mm)
        maxw = seg - (MARGIN if i in (0, n - 1) else 5 * mm) - 5 * mm
        lab = str(m.get("label", "")).upper()
        _tracked(c, tx, top - 5.4 * mm, lab, "Helvetica-Bold",
                 _fit(c, lab, "Helvetica-Bold", 5.6, maxw, 1.3), MUTED, 1.3)
        val = _metric_value(m.get("label", ""), m.get("valore", ""))
        vfs = _fit(c, val, "Helvetica-Bold", 12.0, maxw)
        if vfs <= 7.8:
            vfs = 7.8
            val = _cut_words(val, "Helvetica-Bold", vfs, maxw)
        c.setFont("Helvetica-Bold", vfs)
        c.setFillColor(NAVY)
        c.drawString(tx, top - 10.6 * mm, val)
        sub = str(m.get("sub", "") or "")
        if sub:
            c.setFont("Helvetica", _fit(c, sub, "Helvetica", 5.9, maxw))
            c.setFillColor(MUTED)
            c.drawString(tx, top - 14.2 * mm, sub)


def _draw_footer(c, content, S):
    y = MARGIN
    c.setStrokeColor(HAIR)
    c.setLineWidth(0.4)
    c.line(MARGIN, y + FOOT_H, W - MARGIN, y + FOOT_H)
    right = ("%s · %s<br/>Documento a valore informativo: per i contenuti vincolanti "
             "fare riferimento al testo ufficiale del bando."
             % (content.get("fonte", ""), content.get("mese_anno", "")))
    tbl = Table([[Paragraph(FOOT_TXT_L, S["foot"]), Paragraph(right, S["footr"])]],
                colWidths=[CW * 0.46, CW * 0.54])
    tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    _, th = tbl.wrap(CW, FOOT_H)
    tbl.drawOn(c, MARGIN, y + FOOT_H - 2.2 * mm - th)


# ── IMPAGINAZIONE ─────────────────────────────────────────────────────────────
def _content_top(first):
    return H - (HDR1_H if first else HDR2_H) - RULE_H - (MET_H if first else 0) - GAP_TOP


def _content_bottom():
    return MARGIN + FOOT_H + 3 * mm


def _sezioni(content):
    if content.get("sezioni"):
        secs = list(content["sezioni"])
    else:
        secs = list(content.get("sinistra") or []) + list(content.get("destra") or [])
    return [s for s in secs if s and (s.get("voci") or s.get("titolo"))]


def _layout(content, scale, log=None):
    """Costruisce le pagine. Ritorna (pages, ok) — ok=False se non ci sta."""
    q, S = _p(scale), _styles(_p(scale))
    secs = _sezioni(content)

    cards = [(_card(s, q, S, COL_W), s) for s in secs]
    tc = content.get("tabella_contributi")
    if tc and tc.get("righe"):
        cards.append((_tabella(tc, q, S, COL_W), {"titolo": "TABELLA"}))

    heights = []
    for t, _s in cards:
        _w, h = t.wrap(COL_W, H)
        heights.append(h)

    panels = []
    pf = _panel("Perche' e' interessante", content.get("punti_forza") or [], q, S, "good", CW)
    cr = _panel("Criticita' e attenzioni", content.get("criticita") or [], q, S, "warn", CW)
    for p in (pf, cr):
        if p is not None:
            _w, h = p.wrap(CW, H)
            panels.append((p, h))

    cta = _cta(content, q, S)
    _w, cta_h = cta.wrap(CW, H)

    tail = sum(h for _p_, h in panels) + (q["card_gap"] * len(panels)) + cta_h + q["card_gap"]

    # distribuzione: riempimento greedy dell'elenco ordinato di card,
    # colonna per colonna. Si passa alla colonna successiva solo quando
    # la prossima card non ci entra piu': cosi' nessuna colonna resta
    # sguarnita mentre c'e' ancora contenuto in coda (a differenza di una
    # spartizione che minimizzi solo il riempimento massimo, che a parita'
    # di risultato puo' scegliere un taglio squilibrato e lasciare vuota
    # meta' di una pagina). Ogni colonna tiene comunque almeno una card,
    # anche se la supera, per non perdere contenuto in silenzio.
    def capacities(npages):
        caps = []
        for i in range(2 * npages):
            pg = i // 2
            cap = _content_top(pg == 0) - _content_bottom()
            if pg == npages - 1:
                cap -= tail
            caps.append(max(1.0, cap))
        return caps

    def partition(caps):
        """Ritorna (riempimento_massimo, [indici di taglio])."""
        n = len(heights)
        tagli, idx = [0], 0
        fills = []
        for cap in caps:
            used, prese = 0.0, 0
            while idx < n:
                extra = (q["card_gap"] if prese else 0.0) + heights[idx]
                if prese == 0 or used + extra <= cap:
                    used += extra
                    idx += 1
                    prese += 1
                else:
                    break
            fills.append(used / cap if cap else 0.0)
            tagli.append(idx)
        fill_max = max(fills) if fills else 0.0
        if idx < n:                     # card avanzate: non ci sta a queste pagine
            fill_max = max(fill_max, 999.0)
        return fill_max, tagli

    def build(npages):
        caps = capacities(npages)
        _fill, tagli = partition(caps)
        cols = [[t for t, _s in cards[tagli[i]:tagli[i + 1]]] for i in range(len(caps))]
        return [{"cards": [cols[2 * i], cols[2 * i + 1]]} for i in range(npages)], _fill

    maxp = int(content.get("max_pagine", 2))
    pages, fill = None, None
    for npg in range(1, maxp + 1):
        cand, f = build(npg)
        if f <= 1.0:
            pages, fill = cand, f
            break
    if pages is None:
        pages, fill = build(maxp)

    pages[-1]["panels"] = panels
    pages[-1]["cta"] = cta
    ok = (fill is not None and fill <= 1.0) and len(pages) <= maxp

    return pages, ok, q, S


def _render(pages, content, output_path, emb, wrd, q, S):
    c = pdfcanvas.Canvas(output_path, pagesize=A4)
    c.setTitle(str(content.get("titolo", "Scheda bando")))
    c.setAuthor("Energelia S.r.l.")
    n = len(pages)
    for i, pg in enumerate(pages):
        first = (i == 0)
        _draw_header(c, content, emb, wrd, first, i + 1, n)
        if first:
            _draw_metrics(c, content.get("metriche"))
        y_top = _content_top(first)
        for ci, cl in enumerate(pg["cards"]):
            x = MARGIN + ci * (COL_W + COL_GAP)
            y = y_top
            for t in cl:
                _w, h = t.wrap(COL_W, H)
                t.drawOn(c, x, y - h)
                y -= h + q["card_gap"]
        y = y_top
        for cl in pg["cards"]:
            hh = sum(t.wrap(COL_W, H)[1] + q["card_gap"] for t in cl)
            y = min(y, y_top - hh)
        for p, h in pg.get("panels", []):
            p.drawOn(c, MARGIN, y - h)
            y -= h + q["card_gap"]
        cta = pg.get("cta")
        if cta is not None:
            _w, h = cta.wrap(CW, H)
            cta.drawOn(c, MARGIN, _content_bottom())
        _draw_footer(c, content, S)
        c.showPage()
    c.save()
    return output_path


# ── VALIDAZIONE ───────────────────────────────────────────────────────────────
OBBLIGATORI = ("titolo",)


def validate(content):
    """Ritorna la lista dei problemi bloccanti. Vuota = contenuto utilizzabile."""
    err = []
    for k in OBBLIGATORI:
        if not str(content.get(k, "")).strip():
            err.append("campo obbligatorio mancante: '%s'" % k)
    secs = _sezioni(content)
    piene = [s for s in secs if [v for v in s.get("voci", []) if str(v).strip()]]
    if len(piene) < 2:
        err.append("sezioni valorizzate: %d (minimo 2) — l'estrazione dal PDF "
                   "non ha prodotto contenuto utile" % len(piene))
    if not (content.get("metriche") or []):
        err.append("nessuna metrica valorizzata")
    return err


# ── API ───────────────────────────────────────────────────────────────────────
def generate(content, output_path, logo_path=None, log_fn=None, strict=False):
    def log(m):
        if log_fn:
            log_fn(m)

    problemi = validate(content)
    if problemi:
        for p in problemi:
            log("  [!] %s" % p)
        if strict:
            raise ValueError("Contenuto insufficiente per generare la scheda:\n - "
                             + "\n - ".join(problemi))

    file_logo = trova_logo(logo_path)
    emb, wrd = _prepare_logo(file_logo)
    if emb:
        log("Logo: %s" % file_logo)
    else:
        log("Logo: non trovato, testata senza marchio. "
            "Cercato in: %s" % ", ".join(LOGO_DIRS))

    log("Calibrazione scala...")

    def search(npag_max, lo=0.52, hi=1.25):
        best_l, l, h = None, lo, hi
        for _ in range(9):
            mid = (l + h) / 2
            pages, ok, q, S = _layout(dict(content, max_pagine=npag_max), mid)
            if ok and len(pages) <= npag_max:
                best_l = (mid, pages, q, S)
                l = mid
            else:
                h = mid
            if h - l < 0.01:
                break
        return best_l

    # preferenza: contenuto pieno, usando quante pagine servono (nel limite
    # del tetto) prima di rinunciare a qualunque voce
    tetto = max(2, int(content.get("max_pagine", 2)))
    def sfoltisci(cont, quante):
        """Toglie le ultime `quante` voci di ogni sezione."""
        d = dict(cont)
        d["sezioni"] = [dict(sez, voci=sez.get("voci", [])[:-quante] or
                             sez.get("voci", [])[:1])
                        for sez in _sezioni(cont)]
        d.pop("sinistra", None)
        d.pop("destra", None)
        return d

    originale, best = content, None
    # Prima il contenuto pieno su tutte le pagine disponibili (1, poi 2, ...
    # fino al tetto): meglio una pagina in piu' che una voce in meno. Si
    # comincia a sfoltire solo se anche al tetto massimo di pagine il
    # contenuto pieno non ci sta a un corpo leggibile.
    for taglio in (0, 1, 2):
        content = originale if taglio == 0 else sfoltisci(originale, taglio)
        for npg in range(1, tetto + 1):
            cand = search(npg)
            if cand:
                best = cand
                nota = "" if taglio == 0 else (
                    " (tolte le ultime %d voci per sezione)" % taglio)
                log("  %d pagina/e, scala %.3f%s" % (npg, cand[0], nota))
                break
        if best:
            break
    if best is None:
        content = originale

    if best is None:
        log("  [!] Contenuto molto esteso: impagino alla scala minima.")
        pages, _ok, q, S = _layout(dict(content, max_pagine=tetto + 2), 0.70)
        best = (0.70, pages, q, S)

    scale, pages, q, S = best
    log("Scala ottimale: %.3f — %d pagina/e" % (scale, len(pages)))

    d = os.path.dirname(os.path.abspath(output_path))
    if d:
        os.makedirs(d, exist_ok=True)
    _render(pages, content, output_path, emb, wrd, q, S)
    log("PDF salvato: %s" % output_path)
    return output_path
