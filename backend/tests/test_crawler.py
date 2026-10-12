import asyncio
import json
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from backend.crawler import PublicCrawler, page_links, public_url
from backend.crm import CRM
from backend.db import Database
from backend.domain import now
from backend.extract import person_data
from backend.main import create_app
from backend.providers import ProviderError, Settings, WebFetcher

HOME = '<meta property="og:site_name" content="Aurora Asset Management"><p>Aurora Asset Management is an independent asset management firm investing in public equities in Spain.</p><nav><a href="/team">Our team</a></nav>'
TEAM = '<meta property="og:site_name" content="Aurora Asset Management"><p>Public equity investment management.</p><script type="application/ld+json">'+json.dumps({'@type':'Person','name':'Ana Perez','jobTitle':'CIO','worksFor':{'name':'Aurora Asset Management'},'sameAs':'https://linkedin.com/in/ana-crawl'})+'</script>'


class Pages:
    def __init__(self, values=None, gate=None):
        self.values = values or {'https://aurora.example/':HOME,'https://aurora.example/team':TEAM}
        self.gate = gate
        self.calls = []
    async def page(self, url):
        self.calls.append(url)
        if self.gate:await self.gate.wait()
        if url not in self.values:raise ProviderError('Source unavailable')
        return {'url':url,'html':self.values[url],'observed_at':now()}


def setup(tmp_path, pages=None, model=None):
    db=Database(tmp_path/'crawl.sqlite');db.initialize()
    crm=CRM(db,tmp_path/'shared')
    pages=pages or Pages()
    crawler=PublicCrawler(crm,model,lambda:pages,interval=0)
    crawler.state['enabled']=True
    return crawler,pages


async def step(crawler):
    item=crawler.take()
    assert item
    await crawler.process(item)
    crawler.finish(item,True)
    crawler.persist()
    return item


def test_directory_new_company_team_and_contacts_work_during_paid_run_without_credits(tmp_path):
    async def run():
        directory='<main><a href="https://aurora.example/">Aurora Asset Management</a><a href="https://boreal.example/">Boreal Asset Management</a><a href="https://linkedin.com/in/private">LinkedIn</a><a href="http://127.0.0.1/admin">Trap</a></main>'
        pages=Pages({'https://directory.example/members':directory,'https://aurora.example/':HOME,'https://aurora.example/team':TEAM})
        crawler,_=setup(tmp_path,pages)
        rid=crawler.db.create_run('Paid search',[]);crawler.db.update_run(rid,status='running')
        crawler.enqueue([{'url':'https://directory.example/members','kind':'directory'}])
        await step(crawler);await step(crawler);await step(crawler)
        assert crawler.db.run(rid)['status']=='running'
        contacts=crawler.db.contacts()
        assert len(contacts)==1 and contacts[0]['name']=='Ana Perez'
        assert crawler.state['new_contacts']==1 and crawler.state['new_firms']==1
        assert 'https://boreal.example/' not in pages.calls  # Team pages take precedence over the next company homepage.
        assert crawler.snapshot()['credits_used']==0
        with crawler.db.connect() as con:assert con.execute('SELECT COUNT(*) FROM credits').fetchone()[0]==0
        assert len(list((tmp_path/'shared'/'contacts').glob('*.json')))==1
        assert 'http://127.0.0.1/admin' not in pages.calls
        assert all('linkedin.com' not in u for u in pages.calls)
    asyncio.run(run())


def test_navigation_and_multilingual_team_links_and_directory_scope():
    page={'url':'https://aurora.example/','html':'<nav><a href="/equipe/jean">Notre equipe</a><a href="/team/ana">Ana Perez</a></nav><footer><a href="/privacy">Privacy</a></footer><a href="https://other.example/team">Other</a>'}
    links=page_links(page)
    assert {r['url'] for r in links}=={'https://aurora.example/equipe/jean','https://aurora.example/team/ana'}
    assert [r['url'] for r in page_links(page,True)]==['https://other.example/team']


def test_cooldown_persistence_and_repeat_ingestion_are_idempotent(tmp_path):
    async def run():
        crawler,pages=setup(tmp_path)
        crawler.enqueue([{'url':'https://aurora.example/'}])
        await step(crawler);await step(crawler)
        again=PublicCrawler(crawler.crm,None,lambda:pages,interval=0)
        assert again.state['new_contacts']==1 and again.take() is None
        again.state['enabled']=True
        with again.db.connect() as con:con.execute("UPDATE crawl_queue SET next_at=? WHERE url LIKE '%/team'",(now(),))
        await step(again)
        assert len(again.db.contacts())==1 and again.state['new_contacts']==1 and again.state['duplicates']==1
    asyncio.run(run())


def test_model_only_adds_grounded_people_and_protects_contacted_records(tmp_path):
    class Model:
        async def health(self):return {'ready':True}
        async def extract(self,page):
            return [person_data('Marta Lopez','CIO',page['url'],'Marta Lopez CIO'),
                    person_data('Invented Person','CIO',page['url'],'Invented Person CIO')]
    async def run():
        pages=Pages({'https://aurora.example/team':'<meta property="og:site_name" content="Aurora Asset Management"><p>Public equity asset management. Marta Lopez CIO</p>'})
        crawler,_=setup(tmp_path,pages,Model())
        crawler.enqueue([{'url':'https://aurora.example/team'}])
        await step(crawler)
        assert [c['name'] for c in crawler.db.contacts()]==['Marta Lopez']
        assert crawler.state['model_calls']==1
        from backend.crm_models import InteractionInput
        c=crawler.db.contacts()[0]
        crawler.crm.interaction(c['id'],InteractionInput(author='QA',channel='email',comment='Already contacted'))
        crawler.db.contact(c['id'])
        with crawler.db.connect() as con:con.execute('UPDATE crawl_queue SET next_at=?',(now(),))
        await step(crawler)
        assert crawler.state['new_contacts']==1 and crawler.state['duplicates']==0
    asyncio.run(run())


def test_stop_cancels_slow_page_without_saving_late_contacts(tmp_path):
    async def run():
        gate=asyncio.Event();pages=Pages(gate=gate);crawler,_=setup(tmp_path,pages)
        crawler.enqueue([{'url':'https://aurora.example/'}])
        crawler.wake()
        for _ in range(50):
            if pages.calls:break
            await asyncio.sleep(.01)
        await crawler.stop();gate.set()
        assert not crawler.db.contacts() and not crawler.state['enabled']
        with crawler.db.connect() as con:assert con.execute('SELECT status FROM crawl_queue').fetchone()[0]=='pending'
    asyncio.run(run())


def test_sitemaps_discover_biographies_and_skip_external_hosts(tmp_path):
    class Maps(Pages):
        async def sitemap(self,url):
            return {'url':url,'html':'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://aurora.example/team/ana</loc></url><url><loc>https://foreign.example/team/trap</loc></url><url><loc>https://aurora.example/privacy</loc></url></urlset>','observed_at':now()}
    async def run():
        crawler,_=setup(tmp_path,Maps())
        crawler.enqueue([{'url':'https://aurora.example/sitemap.xml','kind':'sitemap'}])
        await step(crawler)
        next_page=crawler.take()
        assert next_page['url']=='https://aurora.example/team/ana'
        assert crawler.snapshot()['urls']==2
    asyncio.run(run())


def test_free_crawler_api_needs_no_key_or_quota_and_rejects_private_seeds(tmp_path):
    settings=Settings(api_key='',monthly_limit=0,database_path=str(tmp_path/'api.sqlite'),shared_path=str(tmp_path/'api-shared'))
    app=create_app(settings,fetcher_factory=lambda:Pages())
    app.state.local_model.start=lambda:None
    app.state.crawler.wake=lambda:None
    with TestClient(app) as client:
        assert client.post('/api/crawler/start',json={'seed_urls':['http://localhost:8001/']}).status_code==422
        response=client.post('/api/crawler/start',json={'seed_urls':['https://aurora.example/']})
        assert response.status_code==200 and response.json()['enabled']
        assert client.get('/api/crawler').json()['credits_used']==0
        assert client.post('/api/crawler/stop',json={}).json()['status']=='stopped'


def test_web_reader_checks_robots_before_reading_xml(tmp_path):
    db=Database(tmp_path/'reader.sqlite');db.initialize()
    class Reader(WebFetcher):
        async def validate(self,url):pass
        async def request(self,url,limit):
            if url.endswith('/robots.txt'):return 200,'User-agent: *\nDisallow: /sitemap.xml',url,'text/plain'
            raise AssertionError('Disallowed sitemap must never be requested')
    async def run():
        try:await Reader(db).sitemap('https://aurora.example/sitemap.xml')
        except ProviderError as e:assert 'robots.txt' in str(e)
        else:assert False
    asyncio.run(run())


def test_public_urls_reject_private_hosts_credentials_and_binary_files():
    for url in ('http://localhost/','http://192.168.1.1/','https://user:pass@firm.example/','https://firm.example/team.pdf','https://firm.example:1234/'):
        assert public_url(url) is None


def test_model_timeout_keeps_traversing_team_links(tmp_path):
    class Broken:
        async def health(self):return {'ready':True}
        async def extract(self,page):raise ProviderError('Model timed out')
    async def run():
        page='<meta property="og:site_name" content="Aurora Asset Management"><p>Public equity asset management.</p><a href="/team/ana">Team biography</a>'
        crawler,_=setup(tmp_path,Pages({'https://aurora.example/team':page}),Broken())
        crawler.enqueue([{'url':'https://aurora.example/team'}])
        await step(crawler)
        assert crawler.take()['url']=='https://aurora.example/team/ana'
        assert crawler.state['enabled'] and not crawler.db.contacts()
    asyncio.run(run())


def test_web_scan_revisits_previous_empty_and_old_searches(tmp_path):
    from backend.runner import Runner
    class Search:
        def __init__(self):self.calls=[]
        async def search(self,query,rid):
            self.calls.append(query)
            if query=='discover':return [{'title':'Aurora Asset Management','url':'https://aurora.example/','content':'Independent asset management public equities'}],False
            return [],False
    async def run():
        for previous_count,age in [(0,0),(1,8)]:
            crawler,_=setup(tmp_path/str(age))
            crawler.db.upsert_firm({'name':'Aurora Asset Management','domain':'aurora.example','equity':True})
            old=crawler.db.create_run('Earlier discovery',[])
            qid=crawler.db.add_query(old,'"Aurora Asset Management" team','people');crawler.db.update_query(qid,'completed')
            crawler.db.update_run(old,status='completed',contacts_found=previous_count)
            with crawler.db.connect() as con:con.execute('UPDATE runs SET started_at=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(days=age)).isoformat(),old))
            search=Search();runner=Runner(crawler.db,Settings(api_key='test'),search,lambda:Pages())
            rid=runner.start('equity',[{'text':'discover','phase':'firms'},{'text':'"{gestora}" team','phase':'people'}])
            await asyncio.gather(*runner.tasks)
            assert '"Aurora Asset Management" team' in search.calls
            assert crawler.db.run(rid)['status']=='completed'
    asyncio.run(run())


def test_new_firm_news_without_contacts_gets_stable_uuid_and_does_not_crash(tmp_path):
    from backend.signals import list_signals
    async def run():
        html=HOME+'<article>Aurora Asset Management launches a new equity fund.</article>'
        crawler,_=setup(tmp_path,Pages({'https://aurora.example/':html}))
        crawler.enqueue([{'url':'https://aurora.example/'}])
        item=await step(crawler)
        assert not crawler.db.contacts()
        records=list_signals(crawler.crm)
        assert len(records)==1 and records[0]['firm_uuid']
        assert crawler.state['new_signals']==1
        await crawler.process(item)
        assert len(list_signals(crawler.crm))==1 and crawler.state['new_signals']==1
        assert len(list((tmp_path/'shared'/'firms').glob('*.json')))==1
    asyncio.run(run())


def test_unexpected_page_error_is_logged_and_next_page_still_adds_contacts(tmp_path,caplog):
    async def run():
        crawler,_=setup(tmp_path)
        crawler.enqueue([{'url':'https://aurora.example/bad','priority':0},
                         {'url':'https://aurora.example/team','priority':1}])
        original=crawler.process
        async def process(item):
            if item['url'].endswith('/bad'):raise TypeError('Malformed page fixture')
            await original(item)
            crawler.state['enabled']=False
        crawler.process=process
        await asyncio.wait_for(crawler.loop(),10)
        assert crawler.state['failed_pages']==1 and crawler.state['new_contacts']==1
        assert 'Malformed page fixture' in caplog.text
        with crawler.db.connect() as con:
            rows=con.execute('SELECT status FROM crawl_queue ORDER BY id').fetchall()
        assert [r[0] for r in rows]==['failed','done']
    asyncio.run(run())
