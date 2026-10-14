import copy
import hashlib
import threading
import time
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .domain import evidence, identity, linkedin_url, now, score_contact

ACTIVE = ("queued", "running", "stopping")
TERMINAL = ("completed", "stopped", "failed", "quota_exhausted", "interrupted")
SCHEMA = """
CREATE TABLE IF NOT EXISTS firms (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL,
 domain TEXT NOT NULL DEFAULT '', data TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS firm_name ON firms(name_key);
CREATE INDEX IF NOT EXISTS firm_domain ON firms(domain);
CREATE TABLE IF NOT EXISTS contacts (
 id INTEGER PRIMARY KEY, firm_id INTEGER NOT NULL REFERENCES firms(id),
 name_key TEXT NOT NULL, linkedin_url TEXT UNIQUE, data TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS contact_identity ON contacts(name_key, firm_id);
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY, keywords TEXT NOT NULL, plan TEXT NOT NULL,
 status TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
 completed_queries INTEGER NOT NULL DEFAULT 0, total_queries INTEGER NOT NULL DEFAULT 0,
 credits INTEGER NOT NULL DEFAULT 0, contacts_found INTEGER NOT NULL DEFAULT 0,
 errors TEXT NOT NULL DEFAULT '[]', started_at TEXT NOT NULL, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS run_queries (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id),
 text TEXT NOT NULL, phase TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 cached INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cache (
 key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credits (
 id INTEGER PRIMARY KEY, account TEXT NOT NULL, month TEXT NOT NULL,
 run_id INTEGER REFERENCES runs(id), amount INTEGER NOT NULL, created_at TEXT NOT NULL
);
"""

def unique(items):
    seen, result = set(), []
    for item in items:
        token = item if isinstance(item, (str, int, float, bool, type(None))) else json.dumps(item, sort_keys=True, ensure_ascii=False)
        if token not in seen:
            result.append(item); seen.add(token)
    return result

def merge_data(old, new, fields, override=False):
    merged = dict(old)
    issues = set(old.get("issues", [])) | set(new.get("issues", []))
    for field in fields:
        a, b = old.get(field), new.get(field)
        if override:
            merged[field] = b
            issues.discard("conflict:" + field)
        elif b is not None and b != "":
            if "conflict:" + field in issues:
                continue
            if field == "name" and a and identity(a) == identity(b):
                continue
            if a is not None and a != "" and a != b:
                issues.add("conflict:" + field)
                merged[field] = a if field == "name" else None if not isinstance(a, str) else ""
            else:
                merged[field] = b
    merged["issues"] = sorted(issues)
    merged["evidence"] = unique(old.get("evidence", []) + new.get("evidence", []))
    return merged

class Database:
    def __init__(self, filename):
        self.filename = str(filename)
        # Invalidate contact views only when their source tables change.
        self.version = 0
        self._contacts_cache = None
        self._cache_lock = threading.Lock()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.filename, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        changed=set()
        def track_write(action,table,column,database,trigger):
            if action in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE):
                changed.add(table)
            return sqlite3.SQLITE_OK
        con.set_authorizer(track_write)
        try:
            yield con
            con.commit()
            if con.total_changes and changed.intersection({'contacts','firms','contact_crm','interactions','business_signals','shared_aliases'}):
                self.version += 1
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def initialize(self):
        Path(self.filename).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)

    def interrupt_runs(self):
        with self.connect() as con:
            con.execute("UPDATE runs SET status='interrupted', finished_at=? WHERE status IN ('queued','running','stopping')", (now(),))
            con.execute("UPDATE run_queries SET status='interrupted' WHERE status='running'")

    def upsert_firm(self, data, override=False):
        data = {**data, "issues": data.get("issues", []), "evidence": data.get("evidence", [])}
        name, domain = data["name"].strip(), data.get("domain", "").lower().removeprefix("www.")
        with self.connect() as con:
            row = con.execute("SELECT * FROM firms WHERE domain=? LIMIT 1", (domain,)).fetchone() if domain else None
            if row is None:
                row = con.execute("SELECT * FROM firms WHERE name_key=? AND (domain='' OR ?='') LIMIT 1", (identity(name), domain)).fetchone()
            if row is None and domain:
                # A directory or news copy of a firm that already has its own site (or the reverse) is the same firm.
                from .dedup import firm_key, own_domain
                for candidate in con.execute("SELECT * FROM firms").fetchall():
                    if firm_key(candidate["name"]) == firm_key(name) and own_domain(name, domain) != own_domain(candidate["name"], candidate["domain"]):
                        row = candidate
                        if not own_domain(name, domain): domain = candidate["domain"]
                        break
            if row:
                old = json.loads(row["data"])
                merged = merge_data(old, data, ["country", "employees_min", "employees_max", "equity", "analysis"], override)
                # Overlapping employee ranges can safely be narrowed. Disjoint ranges stay unresolved.
                if not override and all(old.get(k) is not None and data.get(k) is not None for k in ("employees_min", "employees_max")):
                    lo = max(old["employees_min"], data["employees_min"])
                    hi = min(old["employees_max"], data["employees_max"])
                    if lo <= hi:
                        merged["employees_min"], merged["employees_max"] = lo, hi
                        merged["issues"] = [x for x in merged["issues"] if x not in ("conflict:employees_min", "conflict:employees_max")]
                    else:
                        merged["employees_min"] = merged["employees_max"] = None
                        merged["issues"] = unique(merged["issues"] + ["conflict:employees"])
                if override:
                    merged["issues"] = []
                elif any(i.startswith("conflict:employees") for i in merged["issues"]):
                    merged["employees_min"] = merged["employees_max"] = None
                merged["name"] = name if override else old["name"]
                merged["domain"] = domain or row["domain"]
                con.execute("UPDATE firms SET name=?,name_key=?,domain=?,data=?,updated_at=? WHERE id=?",
                    (merged["name"], identity(merged["name"]), merged["domain"], json.dumps(merged), now(), row["id"]))
                return row["id"]
            cursor = con.execute("INSERT INTO firms(name,name_key,domain,data,updated_at) VALUES(?,?,?,?,?)",
                (name, identity(name), domain, json.dumps({**data, "name": name, "domain": domain}), now()))
            return cursor.lastrowid

    def firm(self, firm_id):
        with self.connect() as con:
            row = con.execute("SELECT * FROM firms WHERE id=?", (firm_id,)).fetchone()
            return {**json.loads(row["data"]), "id": row["id"], **({"uuid": row["uuid"]} if "uuid" in row.keys() else {})} if row else None

    def upsert_contact(self, data, firm_id):
        data = {**data, "issues": data.get("issues", []), "evidence": data.get("evidence", [])}
        url = linkedin_url(data.get("linkedin_url")) if data.get("linkedin_url") else None
        key = identity(data["name"])
        with self.connect() as con:
            row = con.execute("SELECT * FROM contacts WHERE linkedin_url=?", (url,)).fetchone() if url else None
            if row is None:
                row = con.execute("SELECT * FROM contacts WHERE name_key=? AND firm_id=? AND (linkedin_url IS NULL OR ? IS NULL) LIMIT 1", (key, firm_id, url)).fetchone()
            data["linkedin_url"] = url
            if row:
                old = json.loads(row["data"])
                merged = merge_data(old, data, ["name", "role", "photo_url"], False)
                merged["linkedin_url"] = row["linkedin_url"] or url
                if row["firm_id"] != firm_id:
                    merged["issues"] = unique(merged["issues"] + ["association_unverified", "conflict:company"])
                if not row["linkedin_url"] and not set(e["url"] for e in data["evidence"]).intersection(e["url"] for e in old.get("evidence", [])):
                    merged["issues"] = unique(merged["issues"] + ["possible_duplicate"])
                con.execute("UPDATE contacts SET linkedin_url=?,data=?,updated_at=? WHERE id=?", (merged["linkedin_url"], json.dumps(merged), now(), row["id"]))
                return row["id"], False
            cursor = con.execute("INSERT INTO contacts(firm_id,name_key,linkedin_url,data,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (firm_id, key, url, json.dumps(data), now(), now()))
            return cursor.lastrowid, True

    def contacts(self, contact_id=None, contact_uuids=None, summary=False):
        if contact_id is None and contact_uuids is None:
            # The full list is rebuilt only after a write (or 30 s, for edits made outside this process).
            with self._cache_lock:
                cached = self._contacts_cache
                if cached and cached[0] == self.version and time.monotonic() - cached[1] < 30:
                    return copy.deepcopy(self._contact_index(cached[2]) if summary else cached[2])
                version = self.version
                result = self._build_contacts(None, None)
                self._contacts_cache = (version, time.monotonic(), result)
                return copy.deepcopy(self._contact_index(result) if summary else result)
        result=self._build_contacts(contact_id, contact_uuids)
        return self._contact_index(result) if summary else result

    @staticmethod
    def _contact_index(contacts):
        # Navigation needs names, filters and counts. Evidence stays on paged lists
        # and individual files instead of being copied and sent on every poll.
        excluded={'evidence','reasons','business_signals','contact_sources','data_sources','email_candidates'}
        return [{**{k:v for k,v in c.items() if k not in excluded},'evidence':[],'reasons':[],'business_signals':[]} for c in contacts]

    def _build_contacts(self, contact_id, contact_uuids):
        if contact_uuids is not None and not contact_uuids: return []
        where = " WHERE c.id=?" if contact_id is not None else " WHERE c.uuid IN (" + ",".join("?" for _ in contact_uuids) + ")" if contact_uuids is not None else ""
        args = (contact_id,) if contact_id is not None else tuple(contact_uuids) if contact_uuids is not None else ()
        with self.connect() as con:
            rows = con.execute("""SELECT c.*, f.name company, f.domain, f.data firm_data FROM contacts c
                JOIN firms f ON f.id=c.firm_id""" + where, args).fetchall()
        result = []
        for row in rows:
            person, firm = json.loads(row["data"]), json.loads(row["firm_data"])
            record = {**person, "id": row["id"], "firm_id": row["firm_id"], "company": row["company"], "domain": row["domain"],
                **{k: firm.get(k) for k in ("country", "employees_min", "employees_max", "equity", "analysis")},
                "evidence": unique(person.get("evidence", []) + firm.get("evidence", [])),
                "issues": unique(person.get("issues", []) + firm.get("issues", [])),
                "created_at": row["created_at"], "updated_at": max(row["updated_at"], row["created_at"]),
            }
            result.append(score_contact(record))
        if hasattr(self, "crm"): result = self.crm.decorate(result)
        return sorted(result, key=lambda c: (-c["score"], c["name"]))

    def contact(self, contact_id):
        return next((c for c in self.contacts(contact_id) if c["id"] == contact_id), None)

    def save_manual(self, data, contact_id=None):
        raw = data.model_dump()
        quote = raw.pop("note", "").strip() or "Revisión manual confirmada por el usuario."
        timestamp = now()
        firm_fields = {"country": raw["country"], "employees_min": raw["employees_min"],
            "employees_max": raw["employees_max"], "equity": raw["equity"], "analysis": raw["analysis"]}
        firm_evidence = [evidence(k, v, "", quote, timestamp) for k, v in firm_fields.items() if v is not None and v != "" and not k.startswith("employees_")]
        if raw["employees_min"] is not None and raw["employees_max"] is not None:
            firm_evidence.append(evidence("employees", [raw["employees_min"], raw["employees_max"]], "", quote, timestamp))
        existing = self.contact(contact_id) if contact_id else None
        if contact_id and not existing:
            raise LookupError("Contacto no encontrado.")
        if raw["linkedin_url"]:
            with self.connect() as con:
                duplicate = con.execute("SELECT id FROM contacts WHERE linkedin_url=?", (raw["linkedin_url"],)).fetchone()
                if duplicate and duplicate["id"] != contact_id:
                    raise sqlite3.IntegrityError("Duplicate LinkedIn profile.")
        firm_id = self.upsert_firm({"name": raw["company"], "domain": existing.get("domain", "") if existing and existing["company"] == raw["company"] else "",
            **firm_fields, "evidence": firm_evidence}, override=True)
        person = {k: raw[k] for k in ("name", "role", "linkedin_url", "photo_url")}
        person["issues"] = []
        person["evidence"] = [evidence(k, v, "", quote, timestamp) for k, v in person.items() if k not in ("issues", "evidence") and v]
        with self.connect() as con:
            if contact_id:
                con.execute("UPDATE contacts SET firm_id=?, name_key=?,linkedin_url=?,data=?,updated_at=? WHERE id=?",
                    (firm_id, identity(raw["name"]), raw["linkedin_url"], json.dumps(person), timestamp, contact_id))
            else:
                row = con.execute("INSERT INTO contacts(firm_id,name_key,linkedin_url,data,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (firm_id, identity(raw["name"]), raw["linkedin_url"], json.dumps(person), timestamp, timestamp))
                contact_id = row.lastrowid
        return self.contact(contact_id)

    def cache_get(self, key, seconds=604800):
        with self.connect() as con:
            row = con.execute("SELECT * FROM cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["created_at"]) < datetime.now(timezone.utc) - timedelta(seconds=seconds):
            return None
        return json.loads(row["payload"])

    def cache_put(self, key, payload):
        with self.connect() as con:
            con.execute("INSERT OR REPLACE INTO cache(key,payload,created_at) VALUES(?,?,?)", (key, json.dumps(payload), now()))

    def reserve_credit(self, account, run_id, limit):
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            used = con.execute("SELECT COALESCE(SUM(amount),0) FROM credits WHERE account=? AND month=?", (account, month)).fetchone()[0]
            if used >= limit:
                return False
            con.execute("INSERT INTO credits(account,month,run_id,amount,created_at) VALUES(?,?,?,?,?)", (account, month, run_id, 1, now()))
            con.execute("UPDATE runs SET credits=credits+1 WHERE id=?", (run_id,))
        return True

    def credits_used(self, account):
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with self.connect() as con:
            return con.execute("SELECT COALESCE(SUM(amount),0) FROM credits WHERE account=? AND month=?", (account, month)).fetchone()[0]

    def create_run(self, keywords, plan):
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT id FROM runs WHERE status IN ('queued','running','stopping')").fetchone():
                raise RuntimeError("Ya hay una búsqueda en curso.")
            cursor = con.execute("INSERT INTO runs(keywords,plan,status,started_at) VALUES(?,?,'queued',?)", (keywords, json.dumps(plan), now()))
            return cursor.lastrowid

    def run(self, run_id, decorate=True):
        with self.connect() as con:
            row = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row: return None
            queries = [dict(r) for r in con.execute("SELECT * FROM run_queries WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        record = dict(row)
        record["plan"] = json.loads(record["plan"])
        record["errors"] = json.loads(record["errors"])
        record["queries"] = queries
        if decorate and hasattr(self, "crm"):
            self.crm.identifiers()
            with self.connect() as con: record["uuid"] = con.execute("SELECT uuid FROM runs WHERE id=?", (run_id,)).fetchone()[0]
            record.update(self.crm.run_summary(record))
        return record

    def latest_run(self, decorate=True):
        with self.connect() as con:
            row = con.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return self.run(row["id"], decorate) if row else None

    def update_run(self, run_id, **values):
        allowed = {"status", "completed_queries", "total_queries", "contacts_found", "finished_at", "cancel_requested"}
        if not set(values) <= allowed: raise ValueError("Invalid run update")
        with self.connect() as con:
            con.execute("UPDATE runs SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?", (*values.values(), run_id))

    def run_error(self, run_id, message):
        with self.connect() as con:
            row = con.execute("SELECT errors FROM runs WHERE id=?", (run_id,)).fetchone()
            errors = json.loads(row[0])
            con.execute("UPDATE runs SET errors=? WHERE id=?", (json.dumps(errors + [message[:1000]]), run_id))

    def add_query(self, run_id, text, phase):
        with self.connect() as con:
            cursor = con.execute("INSERT INTO run_queries(run_id,text,phase) VALUES(?,?,?)", (run_id, text, phase))
            return cursor.lastrowid

    def update_query(self, query_id, status, cached=False, error=""):
        with self.connect() as con:
            con.execute("UPDATE run_queries SET status=?,cached=?,error=? WHERE id=?", (status, int(cached), error[:1000], query_id))
