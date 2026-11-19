"""Tiny SQLite layer. Rows store most customer data as JSON blobs to keep the schema flexible."""
import json
import re
import sqlite3
import time
from contextlib import contextmanager

from .settings import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    domain TEXT,
    interview TEXT NOT NULL DEFAULT '{}',
    brand TEXT NOT NULL DEFAULT '{}',
    suggestions TEXT NOT NULL DEFAULT '{}',
    site TEXT,
    published INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    colors TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS site_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    site TEXT NOT NULL,
    note TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name TEXT, email TEXT, phone TEXT, message TEXT,
    created_at REAL NOT NULL
);
"""

JSON_FIELDS = ("interview", "brand", "suggestions", "site", "colors")


def _row(r):
    if r is None:
        return None
    d = dict(r)
    for k in JSON_FIELDS:
        if k in d and isinstance(d[k], str):
            d[k] = json.loads(d[k])
    return d


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or "site"


def unique_slug(name: str) -> str:
    base = slugify(name)
    slug, n = base, 2
    with conn() as c:
        while c.execute("SELECT 1 FROM customers WHERE slug=?", (slug,)).fetchone():
            slug, n = f"{base}-{n}", n + 1
    return slug


def create_customer(name: str, interview: dict) -> dict:
    now = time.time()
    slug = unique_slug(name)
    with conn() as c:
        cur = c.execute(
            "INSERT INTO customers (slug,name,interview,created_at,updated_at) VALUES (?,?,?,?,?)",
            (slug, name, json.dumps(interview), now, now),
        )
        cid = cur.lastrowid
    return get_customer(cid)


def list_customers():
    with conn() as c:
        rows = c.execute("SELECT * FROM customers ORDER BY updated_at DESC").fetchall()
    return [_row(r) for r in rows]


def get_customer(cid: int):
    with conn() as c:
        return _row(c.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone())


def get_customer_by_slug(slug: str):
    with conn() as c:
        return _row(c.execute("SELECT * FROM customers WHERE slug=?", (slug,)).fetchone())


def normalize_domain(d: str | None) -> str | None:
    if not d:
        return None
    d = d.strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    d = d.removeprefix("www.")
    return d or None


def get_customer_by_domain(host: str):
    host = normalize_domain(host.split(":")[0])
    if not host:
        return None
    with conn() as c:
        return _row(c.execute("SELECT * FROM customers WHERE domain=?", (host,)).fetchone())


def update_customer(cid: int, **fields):
    if not fields:
        return
    for k in JSON_FIELDS:
        if k in fields and fields[k] is not None and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k])
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE customers SET {cols} WHERE id=?", (*fields.values(), cid))


def delete_customer(cid: int):
    with conn() as c:
        c.execute("DELETE FROM customers WHERE id=?", (cid,))


def add_asset(cid, filename, original_name, kind, colors):
    with conn() as c:
        c.execute(
            "INSERT INTO assets (customer_id,filename,original_name,kind,colors,created_at) VALUES (?,?,?,?,?,?)",
            (cid, filename, original_name, kind, json.dumps(colors), time.time()),
        )


def list_assets(cid):
    with conn() as c:
        rows = c.execute("SELECT * FROM assets WHERE customer_id=? ORDER BY id", (cid,)).fetchall()
    return [_row(r) for r in rows]


def get_asset(aid):
    with conn() as c:
        return _row(c.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone())


def delete_asset(aid):
    with conn() as c:
        c.execute("DELETE FROM assets WHERE id=?", (aid,))


def save_version(cid, site, note):
    with conn() as c:
        c.execute(
            "INSERT INTO site_versions (customer_id,site,note,created_at) VALUES (?,?,?,?)",
            (cid, json.dumps(site), note, time.time()),
        )


def list_versions(cid):
    with conn() as c:
        rows = c.execute(
            "SELECT id,note,created_at FROM site_versions WHERE customer_id=? ORDER BY id DESC LIMIT 20", (cid,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_version(vid):
    with conn() as c:
        return _row(c.execute("SELECT * FROM site_versions WHERE id=?", (vid,)).fetchone())


def add_lead(cid, name, email, phone, message):
    with conn() as c:
        c.execute(
            "INSERT INTO leads (customer_id,name,email,phone,message,created_at) VALUES (?,?,?,?,?,?)",
            (cid, name, email, phone, message, time.time()),
        )


def list_leads(cid):
    with conn() as c:
        rows = c.execute("SELECT * FROM leads WHERE customer_id=? ORDER BY id DESC", (cid,)).fetchall()
    return [dict(r) for r in rows]
