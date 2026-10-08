import asyncio
from pathlib import Path
from fastapi.testclient import TestClient
from backend.continuous import ContinuousScanner
from backend.crm import CRM
from backend.crm_models import ApolloSearchInput, InteractionInput
from backend.db import Database, ACTIVE
from backend.enrichment import Apollo, ApolloRunner
from backend.main import create_app
from backend.models import SearchInput, ContactInput
from backend.providers import Settings, QuotaError
from backend.runner import Runner


class Web:
    def __init__(self, gate=None, quota=False):
        self.queries = []
        self.gate = gate
        self.quota = quota
    async def search(self, query, rid):
        self.queries.append(query)
        if self.gate: await self.gate.wait()
        if self.quota: raise QuotaError('Cuota gratuita agotada')
        return [], False


class People(Apollo):
    def __init__(self, settings, crm, pages=None):
        super().__init__(settings, crm)
        self.pages = pages or {}
        self.seen = []
    async def search(self, body):
        self.seen.append(body.page)
        return self.pages.get(body.page, [])
    async def enrich(self, **kwargs):
        raise AssertionError('El descubrimiento continuo no debe enriquecer ni gastar créditos')


def build(tmp_path, web=None, pages=None):
    settings = Settings(api_key='tvly-continuous-test', apollo_key='apollo-continuous-test', database_path=str(tmp_path/'scout.sqlite'))
    db = Database(settings.database_path); db.initialize()
    crm = CRM(db, tmp_path/'shared')
    runner = Runner(db, settings, provider=web or Web())
    people = People(settings, crm, pages)
    apollo = ApolloRunner(runner, people, crm)
    ctrl = ContinuousScanner(runner, apollo, crm, interval=0)
    ctrl.wake = lambda: None  # Drive server scheduling explicitly, without timing races.
    return ctrl, runner, people, crm


async def finish(runner):
    if runner.tasks: await asyncio.gather(*list(runner.tasks))


def body():
    return SearchInput(keywords='renta variable', queries=[{'text':'renta variable independent equity gestores España', 'phase':'firms'}], continuous=True)


def test_continuous_uses_fresh_batches_without_user_or_browser(tmp_path):
    async def run():
        ctrl, runner, _, crm = build(tmp_path)
        first = await ctrl.start_web(body()); await finish(runner)
        await ctrl.tick(); second = crm.db.latest_run(); await finish(runner)
        assert second['id'] > first['id']
        assert ctrl.snapshot()['web']['enabled']
        assert set(q['text'] for q in first['queries']).isdisjoint(q['text'] for q in crm.db.run(second['id'])['queries'])
        assert crm.db.run(second['id'])['completed_queries'] <= 20
        ctrl.stop('web'); before = len(runner.provider.queries)
        await ctrl.tick(); assert len(runner.provider.queries) == before
        assert not ctrl.snapshot()['web']['enabled']
        assert 'config' not in ctrl.snapshot()['web']
    asyncio.run(run())


def test_two_sources_queue_and_alternate_and_share_unique_contacts(tmp_path):
    async def run():
        gate = asyncio.Event()
        raw = {'id':'apollo-ana', 'name':'Ana Pérez', 'title':'CIO', 'linkedin_url':'https://linkedin.com/in/ana-test', 'organization':{'name':'Aurora Asset Management','primary_domain':'aurora.example','country':'Spain','estimated_num_employees':30}}
        partial = {'id':'apollo-partial','first_name':'Lucía','last_name_obfuscated':'Xxx','title':'CIO','organization':raw['organization']}
        ctrl, runner, people, crm = build(tmp_path, Web(gate), {1:[raw,partial], 2:[raw]})
        await ctrl.start_web(body())
        await ctrl.start_apollo(ApolloSearchInput(continuous=True))
        assert ctrl.snapshot()['apollo']['status']=='queued'
        with crm.db.connect() as con: assert con.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]==1
        gate.set(); await finish(runner)
        await ctrl.tick(); assert crm.db.latest_run()['provider']=='apollo'
        await finish(runner)
        assert len(crm.db.contacts())==1
        c=crm.db.contacts()[0]
        assert c['apollo_id']=='apollo-ana'
        assert len(crm.db.run(crm.db.latest_run()['id'])['candidates'])==2
        await ctrl.tick(); assert crm.db.latest_run()['provider']=='web'
        await finish(runner); await ctrl.tick(); await finish(runner)
        assert people.seen==[1,2] and len(crm.db.contacts())==1
        assert crm.dashboard()['totals']['identified']==1
        ctrl.stop()
    asyncio.run(run())


def test_continuous_skips_already_contacted_before_automatic_import(tmp_path):
    async def run():
        raw={'id':'apollo-known','name':'Ana Pérez','title':'Head of Equities','linkedin_url':'https://linkedin.com/in/ana-known','organization':{'name':'Aurora Asset Management','primary_domain':'aurora.example'}}
        ctrl, runner, _, crm=build(tmp_path,pages={1:[raw]})
        c=crm.db.save_manual(ContactInput(name='Ana Pérez',company='Aurora Asset Management',role='CIO',linkedin_url=raw['linkedin_url']))
        crm.interaction(c['id'],InteractionInput(author='Marco',channel='call',comment='No volver a llamar'))
        await ctrl.start_apollo(ApolloSearchInput(continuous=True)); await finish(runner)
        result=crm.db.latest_run()
        assert result['omitted']==1 and result['candidates']==[]
        assert crm.db.contact(c['id'])['role']=='CIO'
        assert crm.history(c['id'])[0]['comment']=='No volver a llamar'
        ctrl.stop()
    asyncio.run(run())


def test_quota_stops_future_batches_and_preserves_history(tmp_path):
    async def run():
        ctrl,runner,_,crm=build(tmp_path,Web(quota=True))
        await ctrl.start_web(body());await finish(runner);await ctrl.tick()
        assert ctrl.snapshot()['web']['status']=='quota_exhausted'
        assert not ctrl.snapshot()['web']['enabled']
        assert len(runner.provider.queries)==1
        await ctrl.tick();assert len(runner.provider.queries)==1
        assert crm.db.latest_run()['errors']==['Cuota gratuita agotada']
    asyncio.run(run())


def test_empty_apollo_waits_without_repeating_or_enriching(tmp_path):
    async def run():
        ctrl,runner,people,_=build(tmp_path)
        await ctrl.start_apollo(ApolloSearchInput(continuous=True));await finish(runner);await ctrl.tick()
        assert ctrl.snapshot()['apollo']['enabled'] and ctrl.snapshot()['apollo']['status']=='waiting'
        assert 'siete días' in ctrl.snapshot()['apollo']['reason']
        await ctrl.tick();assert people.seen==[1]
        ctrl.stop()
    asyncio.run(run())


def test_restart_requires_explicit_resume_and_keeps_cursor(tmp_path):
    async def run():
        ctrl,runner,_,crm=build(tmp_path)
        first=await ctrl.start_web(body());await finish(runner)
        fresh=ContinuousScanner(runner,ctrl.apollo,crm,interval=0);fresh.wake=lambda:None
        fresh.interrupt()
        assert fresh.snapshot()['web']['status']=='interrupted'
        assert not fresh.snapshot()['web']['enabled']
        await fresh.resume('web');await finish(runner)
        assert crm.db.latest_run()['id']>first['id']
        fresh.stop()
    asyncio.run(run())


def test_server_api_stop_and_resume_without_page(tmp_path):
    settings=Settings(api_key='tvly-api-test',database_path=str(tmp_path/'api.sqlite'),shared_path=str(tmp_path/'shared-api'))
    app=create_app(settings,provider=Web())
    with TestClient(app) as client:
        response=client.post('/api/searches',json=body().model_dump())
        assert response.status_code==202
        assert client.get('/api/scanning').json()['web']['enabled']
        rid=response.json()['id']
        client.post('/api/searches/'+str(rid)+'/cancel')
        assert not client.get('/api/scanning').json()['web']['enabled']
        assert client.post('/api/scanning/unknown/stop').status_code==422
        assert client.post('/api/scanning/apollo/resume').status_code==400
        assert client.post('/api/scanning/all/stop').status_code==200
    with TestClient(app) as client:
        assert not client.get('/api/scanning').json()['web']['enabled']


def test_exhausted_local_budget_prevents_start_before_any_request(tmp_path):
    async def run():
        ctrl,runner,_,crm=build(tmp_path)
        runner.settings.monthly_limit=0
        try:
            await ctrl.start_web(body())
            assert False, 'No debe iniciarse un escaneo sin cuota'
        except ValueError as error:
            assert 'Cuota gratuita' in str(error)
        assert not runner.provider.queries
        assert not ctrl.snapshot()['web']['enabled']
        assert crm.db.latest_run() is None
    asyncio.run(run())


def test_resume_repairs_legacy_person_search_chain(tmp_path):
    async def run():
        ctrl,runner,_,crm=build(tmp_path)
        db=crm.db
        general=db.create_run('renta variable',[{'text':'gestoras equity España','phase':'firms'}]);db.update_run(general,status='completed')
        person=db.create_run('Antonio Gutiérrez',[{'text':'Antonio','phase':'people'}]);db.update_run(person,status='completed');crm.set_run_metadata(person,force_contact_id=7)
        child=db.create_run('Antonio Gutiérrez',[{'text':'Antonio Europa','phase':'firms'}]);db.update_run(child,status='completed');crm.set_run_metadata(child,parent_run_id=person,continuous=True)
        ctrl.streams['web'].update(config={'keywords':'Antonio Gutiérrez','queries':db.run(person)['plan']},last_run_id=child,processed_run_id=child)
        await ctrl.resume('web');await finish(runner)
        assert ctrl.streams['web']['config']['keywords']=='renta variable'
        assert db.latest_run()['keywords']=='renta variable'
        assert all('Antonio' not in text for text in runner.provider.queries)
        ctrl.stop()
    asyncio.run(run())
