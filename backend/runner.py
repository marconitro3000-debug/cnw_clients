import asyncio
import re
from datetime import datetime, timedelta, timezone
from .db import ACTIVE
from .domain import now, normalized
from .extract import corporate_domain, domain_of, extract_page, result_firm, result_person, team_links
from .providers import ProviderError, QuotaError, Tavily, WebFetcher

class Runner:
    def __init__(self, db, settings, provider=None, fetcher_factory=None):
        self.db, self.settings = db, settings
        self.provider = provider or Tavily(settings, db)
        self.fetcher_factory = fetcher_factory or (lambda: WebFetcher(db))
        self.tasks = set()

    def start(self, keywords, queries, metadata=None):
        run_id = self.db.create_run(keywords, queries)
        if hasattr(self.db, "crm"):
            self.db.crm.identifiers()
            self.db.crm.set_run_metadata(run_id, **{"provider":"web", "omitted":0, **(metadata or {})})
        task = asyncio.create_task(self.execute(run_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return run_id

    def start_public(self,contact_ids):
        return self.start('Correos, LinkedIn y teléfonos públicos',[],{'provider':'public','mode':'public_contacts','contact_ids':contact_ids})

    def start_signals(self,firm_ids,days=90):
        return self.start('Noticias y señales recientes',[],{'provider':'signals','firm_ids':firm_ids,'days':days})

    def canceled(self, run_id):
        run = self.db.run(run_id, decorate=False)
        return not run or bool(run["cancel_requested"])

    async def shutdown(self):
        for task in list(self.tasks): task.cancel()
        if self.tasks: await asyncio.gather(*list(self.tasks), return_exceptions=True)

    async def execute(self, run_id):
        run = self.db.run(run_id)
        if hasattr(self.db,"crm") and self.db.crm.run_metadata(run_id).get("provider")=="public":
            from .public_contacts import execute_public
            return await execute_public(self,run_id)
        if hasattr(self.db,'crm') and self.db.crm.run_metadata(run_id).get('provider')=='signals':
            from .signals import execute_signal_scan
            return await execute_signal_scan(self,run_id)
        plan = run["plan"]
        fetcher = self.fetcher_factory()
        firms = {}
        crm = getattr(self.db, "crm", None)
        metadata = crm.run_metadata(run_id) if crm else {}
        if crm:
            with self.db.connect() as con: seeds = [self.db.firm(r[0]) for r in con.execute("SELECT id FROM firms").fetchall()]
            for seed in seeds:
                if len(firms) < 4 and any(seed["name"] in q["text"] or seed.get("domain") and seed["domain"] in q["text"] for q in plan):
                    firms[seed["domain"]] = seed
        completed = 0
        found_ids = set()

        def explored(candidate):
            # Skip recent successful searches, but revisit empty or old searches.
            with self.db.connect() as con:
                row = con.execute("SELECT name FROM firms WHERE domain=? LIMIT 1", (candidate.get("domain", "").lower().removeprefix("www."),)).fetchone()
                if row is None: return False
                return con.execute("SELECT 1 FROM run_queries q JOIN runs r ON r.id=q.run_id WHERE q.phase='people' AND q.run_id<>? AND instr(q.text, ?)>0 AND r.contacts_found>0 AND r.started_at>=? LIMIT 1", (run_id, '"' + row[0] + '"', (datetime.now(timezone.utc)-timedelta(days=7)).isoformat())).fetchone() is not None

        # Templates are expanded for at most four discovered companies.
        firms_plan = [q for q in plan if q["phase"] == "firms"]
        people_plan = [q for q in plan if q["phase"] == "people"]
        estimate = min(20, len(firms_plan) + sum(4 if "{gestora}" in q["text"] or "{dominio}" in q["text"] else 1 for q in people_plan))
        self.db.update_run(run_id, status="running", total_queries=estimate)

        def save_person(person, firm_id):
            if crm:
                known = crm.find_person(person, firm_id)
                if known and known['blocked'] and known['id'] != metadata.get('force_contact_id'):
                    current = crm.run_metadata(run_id)
                    crm.set_run_metadata(run_id, omitted=current.get('omitted',0)+1)
                    return
            contact_id, fresh = self.db.upsert_contact(person, firm_id)
            found_ids.add(contact_id)
            if crm:
                crm.save_public_channels(contact_id, person)
                crm.observe(contact_id, run_id, fresh, export=False)
            self.db.update_run(run_id, contacts_found=len(found_ids))

        async def ingest_page(url, firm=None, follow=True):
            if self.canceled(run_id): return None
            try:
                page = await fetcher.page(url)
                if self.canceled(run_id): return None
                extracted = extract_page(page["html"], page["url"], firm, page["observed_at"])
                parsed_firm = extracted["firm"]
                if not parsed_firm: return None
                if parsed_firm.get("equity") is False: return None
                firm_id = self.db.upsert_firm(parsed_firm)
                current = self.db.firm(firm_id)
                extractor = self.ollama if metadata.get('use_ollama') and hasattr(self, 'ollama') else getattr(self, 'local_model', None)
                if extractor and (metadata.get('use_ollama') or not extracted['people']):
                    try:
                        extraction_task = asyncio.create_task(extractor.extract(page))
                        try:
                            while not extraction_task.done():
                                if self.canceled(run_id):
                                    extraction_task.cancel()
                                    await asyncio.gather(extraction_task, return_exceptions=True)
                                    break
                                await asyncio.wait({extraction_task}, timeout=0.25)
                            extra = [] if extraction_task.cancelled() else extraction_task.result()
                        finally:
                            if not extraction_task.done():
                                extraction_task.cancel()
                                await asyncio.gather(extraction_task, return_exceptions=True)
                        if not self.canceled(run_id):
                            names = {normalized(p['name']) for p in extracted['people']}
                            extracted['people'].extend(p for p in extra if normalized(p['name']) not in names)
                    except ProviderError as error: self.db.run_error(run_id, str(error))
                for person in extracted["people"]:
                    if self.canceled(run_id): break
                    save_person(person, firm_id)
                self.db.update_run(run_id, contacts_found=len(found_ids))
                if follow:
                    for link in team_links(page["html"], page["url"]):
                        if self.canceled(run_id): break
                        await ingest_page(link, current, False)
                return self.db.firm(firm_id)
            except (ProviderError, OSError) as error:
                # Corporate page failures don't abort a valid search.
                self.db.run_error(run_id, f"{domain_of(url)}: {str(error)}")
                return None

        async def perform(query, phase, firm=None):
            nonlocal completed
            if self.canceled(run_id) or completed >= 20: return False
            query_id = self.db.add_query(run_id, query, phase)
            self.db.update_query(query_id, "running")
            try:
                results, cached = await self.provider.search(query, run_id)
                self.db.update_query(query_id, "completed", cached)
            except ProviderError as error:
                self.db.update_query(query_id, "failed", error=str(error))
                raise
            crawler = getattr(self, 'crawler', None)
            if crawler and crawler.state['enabled']:
                links = []
                for result in results:
                    candidate = result_firm(result)
                    if candidate:links.append({'url':result['url'],'name':candidate['name'],'priority':10})
                if links:await asyncio.to_thread(crawler.enqueue, links, 'Búsqueda web')
            completed += 1
            self.db.update_run(run_id, completed_queries=completed)
            if self.canceled(run_id): return False
            for result in results:
                if self.canceled(run_id): return False
                url = result.get("url", "")
                if firm is not None:
                    person = result_person(result, firm)
                    if person:
                        save_person(person, firm["id"])
                        self.db.update_run(run_id, contacts_found=len(found_ids))
                    if corporate_domain(url) and domain_of(url) == firm["domain"]:
                        # Snippet observations must concern the searched company.
                        parsed = result_firm(result)
                        if parsed and (parsed["domain"] == firm["domain"]):
                            parsed["name"] = firm["name"]
                            self.db.upsert_firm(parsed)
                        await ingest_page(url, self.db.firm(firm["id"]))
                    # LinkedIn company snippets can enrich size/location, never fetched.
                    elif "linkedin.com/company/" in url and normalized(firm["name"]) in normalized(result.get("title", "")):
                        from .extract import firm_from_text
                        snippet = firm_from_text(firm["name"], url, result.get("title", "") + " " + result.get("content", ""), observed_at=result.get("observed_at"))
                        snippet["domain"] = firm["domain"]
                        self.db.upsert_firm(snippet)
                else:
                    if phase == "people":
                        for known in list(firms.values()):
                            person = result_person(result, self.db.firm(known["id"]))
                            if person:
                                save_person(person, known["id"])
                        self.db.update_run(run_id, contacts_found=len(found_ids))
                    candidate = result_firm(result)
                    if candidate is None: continue
                    if candidate["domain"] not in firms and (len(firms) >= 4 or explored(candidate)):
                        self.db.upsert_firm(candidate)
                        continue
                    if candidate.get("equity") is False: continue
                    firm_id = self.db.upsert_firm(candidate)
                    current = self.db.firm(firm_id)
                    firms[current["domain"]] = current
                    improved = await ingest_page(url, current)
                    if improved: firms[current["domain"]] = improved
            if crm: await asyncio.to_thread(crm.export_shared)
            return True

        try:
            for item in firms_plan:
                if not await perform(item["text"], "firms"): break
            # All data on the discovered firm are refreshed after discovery.
            actual = []
            for item in people_plan:
                template = item["text"]
                if "{gestora}" in template or "{dominio}" in template:
                    for firm in firms.values():
                        actual.append((template.replace("{gestora}", firm["name"]).replace("{dominio}", firm["domain"]), self.db.firm(firm["id"])))
                else:
                    # Unscoped person queries can only be attributed to discovered companies.
                    actual.append((template, None))
            actual = actual[:max(0, 20-completed)]
            self.db.update_run(run_id, total_queries=completed+len(actual))
            for text, firm in actual:
                if firm is None:
                    # Discovery-only queries retain the same conservative attribution.
                    if not await perform(text, "people"): break
                elif not await perform(text, "people", self.db.firm(firm["id"])): break
            status = "stopped" if self.canceled(run_id) else "completed"
            self.db.update_run(run_id, status=status, finished_at=now(), contacts_found=len(found_ids))
        except QuotaError as error:
            self.db.run_error(run_id, str(error))
            self.db.update_run(run_id, status="quota_exhausted", finished_at=now())
        except ProviderError as error:
            self.db.run_error(run_id, str(error))
            self.db.update_run(run_id, status="failed", finished_at=now())
        except asyncio.CancelledError:
            self.db.update_run(run_id, status="interrupted", finished_at=now())
            raise
        except Exception:
            self.db.run_error(run_id, "Error interno de procesamiento. Los contactos guardados se conservan.")
            self.db.update_run(run_id, status="failed", finished_at=now())

        finally:
            if crm: await asyncio.to_thread(crm.export_shared)
