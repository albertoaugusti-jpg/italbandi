"""
db_sport2.py — Database layer per bandi sportivi
DB: /data/sport2.db
"""
import sqlite3, hashlib, os
from datetime import datetime

DB_PATH = "/data/sport2.db"


def init():
    os.makedirs("/data", exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS bandi (
        id          TEXT PRIMARY KEY,
        titolo      TEXT NOT NULL,
        fonte       TEXT,
        url         TEXT,
        scadenza    TEXT,
        beneficiari TEXT,
        descrizione TEXT,
        dotazione   TEXT,
        livello     TEXT DEFAULT 'nazionale',
        stato       TEXT DEFAULT 'aperto',
        aggiornato  TEXT
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_stato ON bandi(stato)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_livello ON bandi(livello)")
    con.commit()
    con.close()


def make_id(titolo, url=""):
    return hashlib.md5(f"{titolo}{url}".encode()).hexdigest()[:16]


def inserisci(bando):
    """Inserisce un bando se non esiste già. Restituisce True se nuovo."""
    bid = make_id(bando.get("titolo", ""), bando.get("url", ""))
    con = sqlite3.connect(DB_PATH)
    esiste = con.execute("SELECT 1 FROM bandi WHERE id=?", (bid,)).fetchone()
    if esiste:
        con.close()
        return False
    con.execute("""INSERT INTO bandi
        (id, titolo, fonte, url, scadenza, beneficiari, descrizione, dotazione, livello, stato, aggiornato)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
        bid,
        str(bando.get("titolo", ""))[:500],
        bando.get("fonte", ""),
        bando.get("url", ""),
        bando.get("scadenza", ""),
        bando.get("beneficiari", ""),
        bando.get("descrizione", ""),
        bando.get("dotazione", ""),
        bando.get("livello", "nazionale"),
        bando.get("stato", "aperto"),
        datetime.now().isoformat(),
    ))
    con.commit()
    con.close()
    return True


def cerca(keyword="", stato="aperto", livello="", limit=50):
    try:
        con = sqlite3.connect(DB_PATH)
    except Exception:
        return [], 0

    where, params = [], []

    if stato and stato != "tutti":
        where.append("stato = ?")
        params.append(stato)
    if livello:
        where.append("livello = ?")
        params.append(livello)
    if keyword:
        where.append("(titolo LIKE ? OR descrizione LIKE ? OR beneficiari LIKE ?)")
        k = f"%{keyword}%"
        params += [k, k, k]

    sql = "SELECT id, titolo, scadenza, beneficiari, livello, stato, fonte, url, descrizione FROM bandi"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY aggiornato DESC LIMIT {limit}"

    rows = con.execute(sql, params).fetchall()
    con.close()

    bandi = []
    for r in rows:
        bandi.append({
            "id":          r[0],
            "titolo":      r[1],
            "scadenza":    r[2] or "—",
            "beneficiari": r[3] or "—",
            "livello":     r[4] or "Nazionale",
            "stato":       r[5] or "aperto",
            "fonte":       r[6] or "",
            "url":         r[7] or "",
            "descrizione": r[8] or "",
            "_hit": {"objectID": r[0], "post_title": r[1], "permalink": r[7]},
        })
    return bandi, len(bandi)


def conta():
    try:
        con = sqlite3.connect(DB_PATH)
        n = con.execute("SELECT COUNT(*) FROM bandi").fetchone()[0]
        con.close()
        return n
    except:
        return 0
