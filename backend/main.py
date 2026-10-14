import csv
import io
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from .db import ACTIVE, Database
from .domain import EUROPE, expand_queries
from .models import ContactInput, ExpandInput, SearchInput, TavilyKeyInput
from .providers import ROOT, Settings
from .runner import Runner

def csv_cell(value):
    text = "" if value is None else str(value)
    # Protect spreadsheet users from formulas in imported search snippets.
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")): text = "'" + text
    return text

def compact_evidence(items, quote_limit=300, limit=25):
    """Listing payloads keep the latest observation per field and source, with short quotes."""
    seen = {}
    for item in items or []:
        if not isinstance(item, dict): continue
        key = (item.get("field"), item.get("url"))
        seen.pop(key, None)
        value = item.get("value")
        seen[key] = {**item, "quote": str(item.get("quote") or "")[:quote_limit], "value": value[:quote_limit] if isinstance(value, str) else value}
    return list(seen.values())[-limit:]

def compact_contact(contact):
    # Full evidence stays available from /api/contacts/{id}; lists only need a readable summary.
    return {**contact, "evidence": compact_evidence(contact.get("evidence")),
        "reasons": [{**r, "evidence": compact_evidence(r.get("evidence"))} if isinstance(r, dict) and "evidence" in r else r for r in contact.get("reasons") or []]}

def select_contacts(contacts, country="", role="", min_score=0, size_min=None, size_max=None, status="qualified", q=""):
    from .domain import normalized
    filtered = []
    for contact in contacts:
        if status != "all" and contact["status"] != status: continue
        if country and contact["country"] != country: continue
        if role and role != contact.get("role", ""): continue
        if contact["score"] < min_score: continue
        if size_min is not None and (contact["employees_min"] is None or contact["employees_min"] < size_min): continue
        if size_max is not None and (contact["employees_max"] is None or contact["employees_max"] > size_max): continue
        if q and normalized(q) not in normalized(contact["name"] + " " + contact["company"] + " " + contact.get("role", "")): continue
        filtered.append(contact)
    return filtered

def create_app(settings=None, provider=None, fetcher_factory=None):
    settings = settings or Settings.from_env()
    db = Database(settings.database_path)
    db.initialize()
    runner = Runner(db, settings, provider, fetcher_factory)

    from .extensions import install_extensions

    @asynccontextmanager
    async def lifespan(app):
        db.interrupt_runs()
        app.state.scanning.interrupt()
        crm.import_shared()
        from .playbook import seed_scripts
        seed_scripts(crm)
        from .dedup import merge_obvious
        merge_obvious(crm)
        for contact in db.contacts():
            if contact["status"] == "qualified" and not contact.get("qualified_at"): crm.set_meta(contact["id"], qualified_at=contact["created_at"])
        crm.export_shared()
        app.state.local_model.start()
        await app.state.autopilot.startup()
        await app.state.crawler.startup()
        yield
        await app.state.crawler.shutdown()
        await app.state.autopilot.shutdown()
        await app.state.scanning.shutdown()
        await runner.shutdown()
        await app.state.local_model.shutdown()

    app = FastAPI(title="Kerna Client Research", lifespan=lifespan)
    app.state.db, app.state.runner = db, runner
    crm = install_extensions(app, db, settings, runner)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        allowed = {"http://127.0.0.1:8001", "http://localhost:8001", "http://127.0.0.1:5173", "http://localhost:5173"}
        if origin and origin not in allowed and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Solo se permite acceso desde la aplicación local."}, status_code=403)
        response = await call_next(request)
        if request.method in ("POST", "PATCH") and response.status_code < 400:
            crm.export_shared()
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/api/health")
    def health():
        return {"ok": True, "api_configured": bool(settings.api_key), "credits_used": db.credits_used(settings.account),
            "monthly_limit": settings.monthly_limit, "countries": list(EUROPE), "version": "2.0.0"}

    @app.post("/api/settings/tavily")
    async def configure_tavily(body: TavilyKeyInput):
        key = body.api_key.get_secret_value().strip()
        if not key.startswith("tvly-") or not 10 <= len(key) <= 512 or any(c.isspace() for c in key):
            raise HTTPException(400, "Pega la API key completa de Tavily, que empieza por tvly-.")
        latest = db.latest_run()
        if latest and latest["status"] in ACTIVE:
            raise HTTPException(409, "Espera a que termine la búsqueda antes de cambiar la clave.")
        try:
            settings.save_api_key(key)
        except OSError:
            raise HTTPException(500, "No se pudo guardar la clave en este equipo. Comprueba los permisos de la carpeta.") from None
        return health()

    @app.post("/api/queries/expand")
    def expand(body: ExpandInput):
        return expand_queries(body.keywords, body.country)

    @app.get("/api/searches/latest")
    def latest():
        return db.latest_run()

    @app.post("/api/searches", status_code=202)
    async def start(body: SearchInput):
        if not settings.api_key:
            raise HTTPException(400, "Conecta tu clave gratuita de Tavily en Nueva búsqueda o Configuración para buscar.")
        queries = [q.model_dump() for q in body.queries]
        if not body.parent_run_id and not any(q["phase"] == "firms" for q in queries):
            raise HTTPException(422, "Incluye al menos una consulta de descubrimiento de gestoras.")
        if body.continuous:
            try: return await app.state.scanning.start_web(body)
            except ValueError as e: raise HTTPException(400,str(e)) from None
            except RuntimeError as e: raise HTTPException(409,str(e)) from None
        try:
            run_id = runner.start(body.keywords, queries, {"use_ollama": body.use_ollama, "parent_run_id": body.parent_run_id})
        except RuntimeError:
            raise HTTPException(409, "Ya hay una búsqueda en curso. Deténla o espera a que termine.") from None
        return db.run(run_id)

    @app.get("/api/searches/{run_id}")
    def get_run(run_id: int):
        run = db.run(run_id)
        if not run: raise HTTPException(404, "Búsqueda no encontrada.")
        return run

    @app.post("/api/searches/{run_id}/cancel")
    def cancel(run_id: int):
        run = db.run(run_id)
        if not run: raise HTTPException(404, "Búsqueda no encontrada.")
        for source, stream in app.state.scanning.streams.items():
            if stream.get('last_run_id') == run_id and stream.get('enabled'):
                app.state.scanning.stop(source)
        if run["status"] in ACTIVE:
            db.update_run(run_id, cancel_requested=1, status="stopping")
        return db.run(run_id)

    def filtered(country="", role="", min_score=0, size_min=None, size_max=None, status="qualified", q=""):
        if status not in ("qualified", "review", "excluded", "all"):
            raise HTTPException(422, "Estado de contacto no válido.")
        return select_contacts(db.contacts(), country, role, min_score, size_min, size_max, status, q)

    @app.get("/api/contacts")
    def contacts(country: str = "", role: str = "", min_score: int = 0, size_min: int | None = None,
                 size_max: int | None = None, status: str = "qualified", q: str = ""):
        return [compact_contact(c) for c in filtered(country, role, min_score, size_min, size_max, status, q)]

    @app.get("/api/stats")
    def stats():
        contacts = db.contacts()
        return {"total": len(contacts), "qualified": sum(c["status"] == "qualified" for c in contacts),
            "review": sum(c["status"] == "review" for c in contacts), "excluded": sum(c["status"] == "excluded" for c in contacts),
            "high": sum(c["status"] == "qualified" and c["score"] >= 80 for c in contacts)}

    @app.get("/api/contacts/export")
    def export(country: str = "", role: str = "", min_score: int = 0, size_min: int | None = None,
               size_max: int | None = None, status: str = "qualified", q: str = ""):
        contacts = filtered(country, role, min_score, size_min, size_max, status, q)
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Nombre", "Cargo", "Gestora", "País", "Empleados mínimo", "Empleados máximo", "Puntuación",
                         "Prioridad", "Estado", "LinkedIn", "Foto", "Fuentes", "Pendiente"])
        for c in contacts:
            row = [c["name"], c["role"], c["company"], c["country"], c["employees_min"], c["employees_max"], c["score"],
                   c["priority"], c["status"], c.get("linkedin_url"), c.get("photo_url"),
                   " | ".join(dict.fromkeys(e["url"] for e in c["evidence"] if e["url"])), " | ".join(c["missing"] + c["issues"])]
            writer.writerow([csv_cell(v) for v in row])
        return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="equity-scout-contactos.csv"'})

    @app.get("/api/contacts/{contact_id}")
    def contact(contact_id: int):
        item = db.contact(contact_id)
        if not item: raise HTTPException(404, "Contacto no encontrado.")
        return item

    @app.post("/api/contacts", status_code=201)
    def add_contact(body: ContactInput):
        try: return db.save_manual(body)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Ya existe un contacto con ese LinkedIn.") from None

    @app.patch("/api/contacts/{contact_id}")
    def edit_contact(contact_id: int, body: ContactInput):
        try: return db.save_manual(body, contact_id)
        except LookupError as error:
            raise HTTPException(404, str(error)) from None
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Ya existe un contacto con ese LinkedIn.") from None

    dist = ROOT / "frontend" / "dist"
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def home():
        if (dist / "index.html").exists(): return FileResponse(dist / "index.html")
        return JSONResponse({"message": "Ejecuta npm run build o usa npm run dev para abrir la interfaz."})

    return app

app = create_app()
