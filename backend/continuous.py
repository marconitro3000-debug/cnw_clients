"""Continuous discovery owned by the local server, with one provider request stream at a time."""
import asyncio
from datetime import datetime, timedelta, timezone
from .batches import prepare_next_batch, general_web_seed, person_search_root
from .crm_models import ApolloSearchInput
from .db import ACTIVE
from .domain import now

SOURCES = ('web', 'public', 'apollo')


class ContinuousScanner:
    def __init__(self, runner, apollo, crm, interval=30):
        self.runner, self.apollo, self.crm = runner, apollo, crm
        self.db = crm.db
        self.interval = interval
        self.streams = crm.setting('continuous_scanning', {})
        self.task = None
        self.previous = None
        for source in SOURCES:
            self.streams.setdefault(source, {'enabled': False, 'status': 'idle', 'reason': '', 'lots': 0})

    def persist(self):
        self.crm.set_setting('continuous_scanning', self.streams)

    def snapshot(self):
        return {source: {k: v for k, v in self.streams[source].items() if k != 'config'} for source in SOURCES}

    def interrupt(self):
        for stream in self.streams.values():
            if stream.get('enabled'):
                stream.update(enabled=False, status='interrupted', reason='El servidor se reinició. Pulsa Continuar para reanudar el avance guardado.')
        self.persist()

    def wake(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.pump())

    def activate(self, source, config):
        if self.streams[source].get('enabled'):
            raise RuntimeError('Este escaneo continuo ya está activado.')
        self.streams[source] = {'enabled': True, 'status': 'queued', 'reason': '', 'lots': 0,
                                'config': config, 'next_at': now(), 'last_run_id': None, 'processed_run_id': None}
        self.persist()

    async def start_web(self, body):
        if not self.runner.settings.api_key:
            raise ValueError('Configura Tavily antes de iniciar el escaneo web.')
        if self.db.credits_used(self.runner.settings.account) >= self.runner.settings.monthly_limit:
            raise ValueError('Cuota gratuita de Tavily agotada. Los resultados se conservan.')
        self.activate('web', body.model_dump())
        await self.tick()
        self.wake()
        return self.db.latest_run()

    async def start_apollo(self, body):
        if not self.apollo.provider.settings.apollo_key:
            raise ValueError('Configura la clave de Apollo antes de iniciar su escaneo.')
        access=self.apollo.provider.access_status(body.source)
        if access.get('status') in ('denied','invalid'): raise ValueError(access['message'])
        self.activate('apollo', body.model_dump())
        await self.tick()
        self.wake()
        return self.db.latest_run()

    async def start_public(self,body):
        self.activate('public',{'contact_ids':body.contact_ids,'continuous':body.continuous,'after_id':0})
        await self.tick();self.wake()
        return self.snapshot()

    async def resume(self, source):
        stream = self.streams[source]
        if stream.get('enabled'):
            return self.snapshot()
        if source == 'web' and not self.runner.settings.api_key:
            raise ValueError('Configura Tavily antes de continuar.')
        if source == 'apollo' and not self.apollo.provider.settings.apollo_key:
            raise ValueError('Configura la clave de Apollo antes de continuar.')
        if source=='web' and stream.get('last_run_id') and person_search_root(self.db,stream['last_run_id']):
            seed=general_web_seed(self.db,stream['last_run_id'])
            stream.update(config={'keywords':seed['keywords'],'queries':seed['plan'],'use_ollama':False},last_run_id=seed['id'],processed_run_id=None)
        if source=='public' and not stream.get('config'): stream['config']={'contact_ids':[],'continuous':True,'after_id':0}
        if not stream.get('config'):
            with self.db.connect() as con:
                rows = con.execute('SELECT id FROM runs ORDER BY id DESC').fetchall()
            for row in rows:
                run = self.db.run(row[0])
                meta = self.crm.run_metadata(run['id'])
                if source == 'web' and meta.get('provider', 'web') == 'web' and not person_search_root(self.db,run['id']):
                    stream['config'] = {'keywords': run['keywords'], 'queries': run['plan'], 'use_ollama': meta.get('use_ollama', False)}
                    stream['last_run_id'] = run['id']
                    break
                if source == 'apollo' and meta.get('mode') == 'discover':
                    stream['config'] = meta['request']
                    stream['last_run_id'] = run['id']
                    break
        if not stream.get('config'):
            raise ValueError('Prepara primero los filtros de este escaneo.')
        previous_run = self.db.run(stream.get('last_run_id')) if stream.get('last_run_id') else None
        if previous_run and previous_run['status'] not in (*ACTIVE, 'completed'):
            stream['processed_run_id'] = previous_run['id']
        stream.update(enabled=True, status='queued', reason='', next_at=now())
        # The previous run is handled before preparing fresh queries or the next Apollo page.
        self.persist()
        await self.tick()
        self.wake()
        return self.snapshot()

    def stop(self, source=None):
        sources = [source] if source else SOURCES
        for key in sources:
            stream = self.streams[key]
            stream.update(enabled=False, status='stopped', reason='Detenido. Los contactos y el avance se conservan.')
            rid = stream.get('last_run_id')
            if rid:
                run = self.db.run(rid, decorate=False)
                if run and run['status'] in ACTIVE:
                    self.db.update_run(rid, cancel_requested=1, status='stopping')
        self.persist()
        return self.snapshot()

    def defer_cycle(self, source, reason):
        stream = self.streams[source]
        stream.update(status='waiting', reason=reason, next_at=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat())
        if source == 'apollo':
            stream['config']['page'] = stream['config'].get('first_page', 1)
        self.persist()

    async def tick(self):
        for source in SOURCES:
            stream = self.streams[source]
            if not stream.get('enabled'):
                continue
            rid = stream.get('last_run_id')
            if not rid or stream.get('processed_run_id') == rid:
                continue
            run = self.db.run(rid, decorate=False)
            if not run:
                stream.update(enabled=False, status='failed', reason='No se encuentra la ejecución anterior.')
            elif run['status'] not in ACTIVE:
                stream['processed_run_id'] = rid
                stream['lots'] += 1
                if run['status'] != 'completed':
                    stream.update(enabled=False, status=run['status'], reason=run['errors'][-1] if run['errors'] else 'Escaneo interrumpido; puedes continuarlo expresamente.')
                elif source == 'public':
                    ids=self.crm.run_metadata(rid).get('contact_ids',[])
                    if ids: stream['config']['after_id']=max(ids)
                    stream.update(status='waiting',reason='Preparando las siguientes fichas públicas.',next_at=(datetime.now(timezone.utc)+timedelta(seconds=self.interval)).isoformat())
                elif source == 'apollo':
                    meta = self.crm.run_metadata(rid)
                    page = stream['config'].get('page', 1)
                    if meta.get('result_count', len(meta.get('candidates', []))) == 0 and stream['config'].get('source')=='saved_contacts':
                        stream['config']['page']=stream['config'].get('first_page',1)
                        stream.update(status='waiting',reason='Contactos guardados recorridos. Se comprobarán nuevas incorporaciones dentro de cinco minutos.',next_at=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat())
                    elif meta.get('result_count', len(meta.get('candidates', []))) == 0 or page >= 500:
                        self.defer_cycle(source, 'Filtros recorridos. Se volverán a comprobar dentro de siete días; puedes cambiar los filtros ahora.')
                    else:
                        stream['config']['page'] = page + 1
                        stream.update(status='waiting', reason='Preparando la siguiente página.', next_at=(datetime.now(timezone.utc) + timedelta(seconds=self.interval)).isoformat())
                else:
                    stream.update(status='waiting', reason='Preparando consultas nuevas.', next_at=(datetime.now(timezone.utc) + timedelta(seconds=self.interval)).isoformat())
            self.persist()
        latest = self.db.latest_run(decorate=False)
        if latest and latest['status'] in ACTIVE:
            return
        order = list(SOURCES)
        if self.previous in order:
            order.remove(self.previous)
            order.append(self.previous)
        for source in order:
            stream = self.streams[source]
            if not stream.get('enabled') or datetime.fromisoformat(stream['next_at']) > datetime.now(timezone.utc):
                continue
            config = stream['config']
            try:
                if source == 'web':
                    if self.db.credits_used(self.runner.settings.account) >= self.runner.settings.monthly_limit:
                        stream.update(enabled=False, status='quota_exhausted', reason='Cuota gratuita de Tavily agotada. Los resultados se conservan.')
                        self.persist()
                        continue
                    previous_id = stream.get('last_run_id') or config.get('parent_run_id')
                    if previous_id:
                        batch = prepare_next_batch(self.db, previous_id)
                        if batch['exhausted']:
                            self.defer_cycle(source, 'Consultas recorridas. Se volverán a comprobar dentro de siete días; puedes cambiar las palabras clave ahora.')
                            continue
                        keywords, queries = batch['keywords'], batch['queries']
                    else:
                        keywords, queries = config['keywords'], config['queries']
                    rid = self.runner.start(keywords, queries, {'continuous': True, 'use_ollama': config.get('use_ollama', False), 'parent_run_id': previous_id})
                elif source=='public':
                    wanted=config.get('contact_ids',[])
                    candidates=[c for c in self.db.contacts() if not c['blocked'] and c['id']>config.get('after_id',0) and (not wanted or c['id'] in wanted)]
                    ids=sorted(c['id'] for c in candidates)[:4]
                    if not ids:
                        if not config.get('continuous',True): stream.update(enabled=False,status='completed',reason='Datos públicos revisados. Los resultados se conservan.')
                        else:
                            config['after_id']=0
                            stream.update(status='waiting',reason='Agenda recorrida. Se revisarán nuevas fichas dentro de cinco minutos.',next_at=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat())
                        self.persist();continue
                    rid=self.runner.start_public(ids)
                else:
                    config.setdefault('first_page', config.get('page', 1))
                    body = ApolloSearchInput.model_validate(config)
                    rid = self.apollo.start('discover', body, {'continuous': True, 'auto_import': True})
            except RuntimeError:
                return  # Another local action won the database's single-run lock.
            except (ValueError, LookupError) as error:
                stream.update(enabled=False, status='failed', reason=str(error))
                self.persist()
                continue
            stream.update(last_run_id=rid, status='running', reason='', next_at=now())
            self.previous = source
            self.persist()
            break

    async def pump(self):
        try:
            while any(s.get('enabled') for s in self.streams.values()):
                await self.tick()
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception:
            for stream in self.streams.values():
                if stream.get('enabled'):
                    stream.update(enabled=False, status='failed', reason='Se ha detenido el escaneo por un error interno. El avance se conserva.')
            self.persist()

    async def shutdown(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.interrupt()
