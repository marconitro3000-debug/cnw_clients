import asyncio
import json
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.db import Database
from backend.crm import CRM
from backend.models import ContactInput, SearchInput
from backend.crm_models import SignalSearchInput, PublicSearchInput, InteractionInput
from backend.providers import Settings, Tavily, ProviderError, QuotaError
from backend.local_model import LocalModel
from backend.signals import (source_document, extract_signals, recency, save_signal, list_signals,
    review_signal, eligible_firms, canonical_source)

TODAY=datetime.now(timezone.utc).date().isoformat()
FIRM={'name':'Aurora Asset Management','domain':'aurora.example'}
QUOTE='Aurora Asset Management launches a new equity fund.'

def doc(text=QUOTE,date=TODAY,basis='document',url='https://aurora.example/news/fund'):
    return {'text':text,'title':'Nuevo fondo','url':url,'published_at':date,'date_basis':basis,'observed_at':datetime.now(timezone.utc).isoformat()}

def setup(tmp_path,provider=None,pages=None):
    settings=Settings(api_key='tvly-news-test',database_path=str(tmp_path/'test.sqlite'),shared_path=str(tmp_path/'shared'))
    app=create_app(settings,provider=provider,fetcher_factory=lambda:pages or Pages())
    c=app.state.db.save_manual(ContactInput(name='Ana Pérez',company=FIRM['name'],role='CIO',equity=True,employees_min=30,employees_max=30,linkedin_url='https://linkedin.com/in/ana-news',note='Equipo verificado'))
    app.state.db.upsert_firm(FIRM)
    return app,c

@pytest.mark.parametrize('text,kind',[
    (QUOTE,'fund_launch'),
    ('Aurora Asset Management is hiring a Python analyst.','hiring'),
    ('Aurora Asset Management opens a new office in Madrid.','expansion'),
    ('Aurora Asset Management appoints a new CIO.','leadership'),
    ('Aurora Asset Management adopts a new data platform.','technology'),
    ('Aurora Asset Management follows an event-driven strategy.','event_driven'),
    ('We are hiring a new equity analyst.','hiring'),
    ('Lanzamos un nuevo fondo de renta variable.','fund_launch')])
def test_explicit_attributed_events(text,kind):
    assert kind in {s['kind'] for s in extract_signals(doc(text),FIRM)}

@pytest.mark.parametrize('text',[
    'Tesla launches a new fund, according to Aurora Asset Management.',
    'Aurora Asset Management analyses the expansion of Tesla.',
    'Aurora Asset Management invests in a company hiring engineers.',
    'We are hiring a new analyst.',
    'Aurora Asset Management will not launch a new fund.',
    'Aurora Asset Management is not event-driven.',
    'Aurora Asset Management launches its annual report.',
    'Tesla launches a fund. Aurora Asset Management comments on markets.'
])
def test_issuer_events_reports_negations_and_unattributed_posts_are_rejected(text):
    assert extract_signals(doc(text,url='https://press.example/news'),FIRM)==[]


def test_dates_distinguish_publication_update_estimates_and_conflicts():
    r={'url':'https://aurora.example/news','title':'News','content':QUOTE,'published_date':TODAY}
    page={'url':r['url'],'html':'<script type="application/ld+json">'+json.dumps({'@type':'NewsArticle','datePublished':'2020-02-03','dateModified':TODAY})+'</script><article>'+QUOTE+'</article>'}
    document=source_document(r,page)
    assert document['published_at']=='2020-02-03' and document['date_basis']=='document'
    assert recency(extract_signals(document,FIRM)[0])=='old'
    assert source_document(r)['date_basis']=='provider_estimate'
    assert source_document({**r,'published_date':None})['published_at'] is None
    page['html']='<meta property="article:published_time" content="2020-02-03"><time datetime="'+TODAY+'">Today</time><article>'+QUOTE+'</article>'
    assert source_document(r,page)['date_basis']=='conflicting'
    assert source_document(r,page)['published_at'] is None

@pytest.mark.parametrize('date,basis,state',[(None,'unknown','undated'),(TODAY,'provider_estimate','estimated'),(TODAY,'document','recent'),('2020-01-01','document','old'),('2099-01-01','document','future')])
def test_recency(date,basis,state):
    assert recency(extract_signals(doc(date=date,basis=basis),FIRM)[0])==state


def test_historical_event_in_new_publication_is_not_a_fresh_opportunity():
    signal=extract_signals(doc('Aurora Asset Management launched a new fund in 2019.'),FIRM)[0]
    assert recency(signal)=='historical'
    signal=extract_signals(doc('Aurora Asset Management launched a new fund on 2020-01-02.'),FIRM)[0]
    assert signal['event_at']=='2020-01-02' and recency(signal)!='recent'


def test_model_proposals_require_verbatim_evidence_and_correct_firm():
    document=doc('Aurora Asset Management today proudly announces: we are launching a new equity fund.')
    proposals=[{'kind':'fund_launch','quote':'We invent a new fund.'},{'kind':'hiring','quote':document['text']},None]
    assert extract_signals(doc('Aurora Asset Management publishes a research note.'),FIRM,proposals)==[]
    records=extract_signals(document,FIRM,[{'kind':'fund_launch','quote':'we are launching a new equity fund.'}])
    assert any(s['method']=='local_model' and s['review']=='pending' for s in records)


def test_local_model_is_loopback_structured_and_optional(tmp_path):
    model=LocalModel(tmp_path)
    assert asyncio.run(model.extract_signals({'html':QUOTE,'url':doc()['url']},FIRM))==[]
    captured=[]
    def serve(request):
        assert request.url.host=='127.0.0.1'
        if request.url.path=='/health':return httpx.Response(200,json={'status':'ok'})
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'signals':[{'kind':'fund_launch','quote':QUOTE}]})}}]})
    model=LocalModel(tmp_path,transport=httpx.MockTransport(serve));model.port=45678
    assert asyncio.run(model.extract_signals({'html':QUOTE,'url':doc()['url']},FIRM))[0]['quote']==QUOTE
    assert captured[0]['response_format']['type']=='json_schema'
    assert captured[0]['chat_template_kwargs']['enable_thinking'] is False


def test_signals_do_not_change_fit_and_shared_history_is_idempotent(tmp_path):
    app,c=setup(tmp_path);crm=app.state.crm;before=app.state.db.contact(c['id'])
    s=extract_signals(doc(),FIRM)[0]
    key,created=save_signal(crm,c['firm_id'],s);assert created
    review_signal(crm,key,'confirmed')
    assert not save_signal(crm,c['firm_id'],{**s,'title':'Changed title'})[1]
    reviewed=list_signals(crm)[0]
    assert reviewed['review']=='confirmed' and len(reviewed['reviews'])==1 and reviewed['title']=='Nuevo fondo'
    after=app.state.db.contact(c['id']);assert after['score']==before['score'] and after['status']==before['status'] and after['recent_signal_count']==1
    crm.interaction(c['id'],InteractionInput(author='Marco',channel='call',comment='Usa Excel'))
    crm.export_shared()
    other=Database(tmp_path/'other.sqlite');other.initialize();copy=CRM(other,tmp_path/'shared')
    copy.import_shared();copy.import_shared()
    assert len(other.contacts())==1 and len(list_signals(copy))==1
    assert copy.history(other.contacts()[0]['id'])[0]['comment']=='Usa Excel'
    assert list_signals(copy)[0]['review']=='confirmed'
    assert (tmp_path/'shared'/'senales.csv').exists()
    assert 'launches' in (tmp_path/'shared'/'senales.csv').read_text('utf-8-sig')
    assert not copy.conflicts()


def test_api_reviews_filters_csv_and_event_driven_is_descriptive(tmp_path):
    app,c=setup(tmp_path)
    with TestClient(app) as client:
        crm=app.state.crm
        key,_=save_signal(crm,c['firm_id'],extract_signals(doc(date=None,basis='unknown'),FIRM)[0])
        assert client.get('/api/signals').json()['total']==0
        assert client.get('/api/signals?recent_only=false').json()['total']==1
        assert client.get('/api/crm/contacts?signals=recent').json()['total']==0
        assert 'Ana Pérez' not in client.get('/api/crm/contacts/export?signals=recent').text
        assert client.post('/api/signals/'+key+'/review',json={'decision':'confirmed'}).status_code==200
        assert client.get('/api/signals').json()['total']==0  # Confirmation cannot invent a missing date.
        event=extract_signals(doc('Aurora Asset Management follows an event-driven strategy.'),FIRM)[0]
        save_signal(crm,c['firm_id'],event)
        assert client.get('/api/crm/contacts?signals=event_driven').json()['total']==1
        assert client.get('/api/crm/contacts?signals=recent').json()['total']==0
        fresh,_=save_signal(crm,c['firm_id'],extract_signals(doc(url='https://aurora.example/news/new-fund'),FIRM)[0])
        assert client.get('/api/crm/contacts?signals=recent').json()['total']==1
        assert 'Ana Pérez' in client.get('/api/crm/contacts/export?signals=recent').text
        assert client.post('/api/signals/'+fresh+'/review',json={'decision':'rejected'}).status_code==200
        assert client.get('/api/crm/contacts?signals=recent').json()['total']==0
        assert client.get('/api/signals?kind=bad').status_code==422
        assert client.get('/api/signals?days=1').status_code==422
        assert client.get('/api/signals?page=0').status_code==422
        assert client.get('/api/crm/contacts?signals=bad').status_code==422
        assert client.post('/api/signals/no-such/review',json={'decision':'confirmed'}).status_code==404

class Search:
    def __init__(self,quota_after=None,gate=None):self.calls=[];self.quota_after=quota_after;self.gate=gate
    async def search_signals(self,q,rid,days):
        self.calls.append((q,days))
        if self.gate:await self.gate.wait()
        if self.quota_after is not None and len(self.calls)>self.quota_after:raise QuotaError('Cuota agotada')
        return [{'url':'https://aurora.example/news/fund?utm_source=news','title':'New fund','content':QUOTE,'published_date':TODAY}],False
    async def search(self,q,rid):return [],False
class Pages:
    def __init__(self):self.calls=[]
    async def page(self,url):
        self.calls.append(url)
        return {'url':url,'html':'<meta property="article:published_time" content="'+TODAY+'"><article><p>'+QUOTE+'</p></article>'}


def test_scan_reuses_pages_deduplicates_does_not_create_contacts_or_spend_on_enrichment(tmp_path):
    async def run():
        search=Search();pages=Pages();app,c=setup(tmp_path,search,pages)
        runner=app.state.runner
        for _ in range(2):
            rid=runner.start_signals([c['firm_id']],90)
            await asyncio.gather(*list(runner.tasks))
            assert app.state.db.run(rid)['status']=='completed',app.state.db.run(rid)
        assert len(search.calls)==6 and len(pages.calls)==2
        assert len(app.state.db.contacts())==1 and len(list_signals(app.state.crm))==1
        assert app.state.db.run(rid)['signals_found']==1 and app.state.db.run(rid)['new_signals']==0 and app.state.db.run(rid)['contacts_found']==0
        assert list_signals(app.state.crm)[0]['source_url']=='https://aurora.example/news/fund'
    asyncio.run(run())


def test_quota_preserves_partial_results_and_blocks_following_queries(tmp_path):
    async def run():
        search=Search(quota_after=1);app,c=setup(tmp_path,search)
        rid=app.state.runner.start_signals([c['firm_id']])
        await asyncio.gather(*list(app.state.runner.tasks))
        result=app.state.db.run(rid)
        assert result['status']=='quota_exhausted' and len(search.calls)==2
        assert result['new_signals']==1 and len(list_signals(app.state.crm))==1
    asyncio.run(run())


def test_stop_during_search_prevents_saving_late_results(tmp_path):
    async def run():
        gate=asyncio.Event();search=Search(gate=gate);app,c=setup(tmp_path,search)
        rid=app.state.runner.start_signals([c['firm_id']]);await asyncio.sleep(0)
        app.state.db.update_run(rid,cancel_requested=1);gate.set()
        await asyncio.gather(*list(app.state.runner.tasks))
        assert app.state.db.run(rid)['status']=='stopped' and not list_signals(app.state.crm)
    asyncio.run(run())


def test_signals_skip_all_contacted_firms_and_missing_domains(tmp_path):
    app,c=setup(tmp_path)
    assert len(eligible_firms(app.state.crm))==1
    app.state.crm.interaction(c['id'],InteractionInput(author='Marco',channel='email',comment='Ya contactado'))
    assert eligible_firms(app.state.crm)==[]
    app.state.db.save_manual(ContactInput(name='Luis Pérez',company=FIRM['name'],role='CIO'))
    assert len(eligible_firms(app.state.crm))==1  # Another untouched person at the same firm remains eligible.


def test_three_streams_take_turns_and_news_continuation_stops_after_one_pass(tmp_path):
    async def run():
        gate=asyncio.Event()
        class Web(Search):
            async def search(self,q,rid):await gate.wait();return [],False
        app,c=setup(tmp_path,Web(gate=None));ctrl=app.state.scanning;ctrl.interval=0;ctrl.wake=lambda:None
        await ctrl.start_web(SearchInput(keywords='equity',queries=[{'text':'equity independent gestoras','phase':'firms'}],continuous=True))
        await ctrl.start_public(PublicSearchInput(contact_ids=[c['id']],continuous=False))
        state=await ctrl.start_signals(SignalSearchInput(continuous=False,firm_ids=[c['firm_id']]))
        assert state['signals']['status']=='queued'
        gate.set();await asyncio.gather(*list(app.state.runner.tasks))
        await ctrl.tick();assert app.state.db.latest_run()['provider']=='public'
        await asyncio.gather(*list(app.state.runner.tasks))
        await ctrl.tick();assert app.state.db.latest_run()['provider']=='signals'
        await asyncio.gather(*list(app.state.runner.tasks))
        await ctrl.tick();await asyncio.gather(*list(app.state.runner.tasks))
        ctrl.stop('web');await ctrl.tick()
        assert ctrl.snapshot()['signals']['status']=='completed' and not ctrl.snapshot()['signals']['enabled']
        ctrl.stop()
    asyncio.run(run())


def test_signal_search_date_options_have_separate_cache_and_share_free_budget(tmp_path):
    db=Database(tmp_path/'test.sqlite');db.initialize()
    settings=Settings(api_key='tvly-news-test',database_path=str(tmp_path/'test.sqlite'),monthly_limit=2)
    requests=[]
    def serve(request):
        requests.append(json.loads(request.content));return httpx.Response(200,json={'results':[{'url':doc()['url'],'title':'News','content':QUOTE,'published_date':TODAY}]})
    provider=Tavily(settings,db,transport=httpx.MockTransport(serve))
    async def run():
        rid=db.create_run('News',[])
        assert (await provider.search_signals('Aurora launch',rid,90))[1] is False
        assert (await provider.search_signals('Aurora launch',rid,90))[1] is True
        assert (await provider.search('Aurora launch',rid))[1] is False
        with pytest.raises(QuotaError):await provider.search_signals('Other news',rid,90)
        assert len(requests)==2 and db.credits_used(settings.account)==2
    asyncio.run(run())
    assert requests[0]['search_depth']=='basic' and requests[0]['include_published_date'] is True
    assert requests[0]['end_date']==TODAY and requests[0]['start_date']<TODAY
    assert 'include_published_date' not in requests[1]


def test_public_linkedin_post_is_parsed_from_snippet_without_fetching_linkedin(tmp_path):
    class Posts(Search):
        async def search_signals(self,q,rid,days):
            self.calls.append(q)
            return [{'url':'https://www.linkedin.com/posts/aurora-new-fund','title':'Post público','content':QUOTE,'published_date':TODAY}],False
    async def run():
        posts=Posts();pages=Pages();app,c=setup(tmp_path,posts,pages)
        rid=app.state.runner.start_signals([c['firm_id']]);await asyncio.gather(*list(app.state.runner.tasks))
        signals=list_signals(app.state.crm)
        assert len(signals)==1 and signals[0]['recency']=='estimated'
        assert pages.calls==[] and app.state.db.run(rid)['status']=='completed'
    asyncio.run(run())


def test_four_firms_have_at_most_twelve_queries_and_sixteen_source_reads(tmp_path):
    class Many(Search):
        async def search_signals(self,q,rid,days):
            self.calls.append(q)
            return [{'url':f'https://press.example/news/{len(self.calls)}-{i}','title':'News','content':q.split(chr(34))[1]+' launches a new equity fund.'} for i in range(5)],False
    async def run():
        provider=Many();pages=Pages();app,c=setup(tmp_path,provider,pages)
        ids=[c['firm_id']]
        for name in ('Boreal Asset Management','Solana Investment Management','Ocean Asset Management','Nova Asset Management'):
            # Only firms with someone in the agenda are prospected, so each one gets a contact.
            fid=app.state.db.upsert_firm({'name':name,'domain':name.split()[0].lower()+'.example','equity':True})
            app.state.db.save_manual(ContactInput(name='Eva '+name.split()[0],company=name,role='CIO',equity=True,employees_min=30,employees_max=30,linkedin_url='https://linkedin.com/in/eva-'+name.split()[0].lower(),note='Equipo verificado'))
            ids.append(fid)
        rid=app.state.runner.start_signals(ids);await asyncio.gather(*list(app.state.runner.tasks))
        assert len(provider.calls)==12 and len(pages.calls)==16
        assert app.state.db.run(rid)['status']=='completed' and app.state.db.run(rid)['total_queries']==12
    asyncio.run(run())


def test_optional_model_failure_and_cancellation_keep_conventional_scan(tmp_path):
    quote='Our team is hiring a new equity analyst.'
    class Difficult(Pages):
        async def page(self,url):return {'url':url,'html':'<article>Aurora Asset Management '+('extra context '*100)+quote+'</article>'}
    class Broken:
        async def extract_signals(self,page,firm):raise ProviderError('Modelo local no disponible')
    async def failure():
        app,c=setup(tmp_path/'failure',Search(),Difficult());app.state.runner.local_model=Broken()
        rid=app.state.runner.start_signals([c['firm_id']]);await asyncio.gather(*list(app.state.runner.tasks))
        assert app.state.db.run(rid)['status']=='completed' and 'Modelo local no disponible' in app.state.db.run(rid)['errors']
    async def cancel():
        started=asyncio.Event();stopped=asyncio.Event()
        class Slow:
            async def extract_signals(self,page,firm):
                started.set()
                try:await asyncio.sleep(60)
                finally:stopped.set()
        app,c=setup(tmp_path/'cancel',Search(),Difficult());app.state.runner.local_model=Slow()
        rid=app.state.runner.start_signals([c['firm_id']]);await asyncio.wait_for(started.wait(),3)
        app.state.db.update_run(rid,cancel_requested=1,status='stopping')
        await asyncio.wait_for(asyncio.gather(*list(app.state.runner.tasks)),3)
        assert stopped.is_set() and app.state.db.run(rid)['status']=='stopped' and not list_signals(app.state.crm)
    asyncio.run(failure());asyncio.run(cancel())


def test_news_restart_preserves_cursor_and_quota_blocks_before_search(tmp_path):
    from backend.continuous import ContinuousScanner
    async def run():
        app,c=setup(tmp_path,Search());ctrl=app.state.scanning;ctrl.wake=lambda:None;ctrl.interval=30
        await ctrl.start_signals(SignalSearchInput(firm_ids=[c['firm_id']],continuous=True))
        await asyncio.gather(*list(app.state.runner.tasks));await ctrl.tick()
        fresh=ContinuousScanner(app.state.runner,ctrl.apollo,app.state.crm,interval=0);fresh.wake=lambda:None;fresh.interrupt()
        assert not fresh.snapshot()['signals']['enabled'] and fresh.streams['signals']['config']['after_id']==c['firm_id']
        app.state.runner.settings.monthly_limit=0
        with pytest.raises(ValueError):await fresh.resume('signals')
        assert len(app.state.runner.provider.calls)==3 and len(list_signals(app.state.crm))==1
        fresh.stop();ctrl.stop()
    asyncio.run(run())


def test_invalid_shared_source_is_quarantined_and_review_conflicts_are_visible(tmp_path):
    app,c=setup(tmp_path);crm=app.state.crm
    key,_=save_signal(crm,c['firm_id'],extract_signals(doc(),FIRM)[0]);crm.export_shared()
    other=Database(tmp_path/'other.sqlite');other.initialize();copy=CRM(other,tmp_path/'shared');copy.import_shared()
    review_signal(copy,key,'rejected')
    path=tmp_path/'shared'/'signals'/(key+'.json')
    incoming=json.loads(path.read_text('utf-8'));incoming['record']['review']='confirmed'
    path.write_text(json.dumps(incoming),'utf-8');copy.import_shared()
    assert any(c['kind']=='signals' for c in copy.conflicts())
    incoming['record']['source_url']='javascript:alert(1)';path.write_text(json.dumps(incoming),'utf-8');copy.import_shared()
    assert any(c['kind']=='invalid' for c in copy.conflicts())
    assert list_signals(copy)[0]['review']=='rejected'


def test_news_company_scope_excludes_namesakes_before_reading_sources(tmp_path):
    class Namesake(Search):
        async def search_signals(self,q,rid,days):
            self.calls.append(q)
            return [{'url':'https://press.example/other','title':'Aurora Payments','content':'Aurora Payments launches a new platform.'}],False
    async def run():
        provider=Namesake();pages=Pages();app,c=setup(tmp_path,provider,pages)
        rid=app.state.runner.start_signals([c['firm_id']]);await asyncio.gather(*list(app.state.runner.tasks))
        assert pages.calls==[] and list_signals(app.state.crm)==[]
        assert all('"Aurora Asset Management"' in q for q in provider.calls)
    asyncio.run(run())


def test_corporate_news_query_applies_domain_filter_at_provider(tmp_path):
    db=Database(tmp_path/'test.sqlite');db.initialize();seen=[]
    def serve(request):seen.append(json.loads(request.content));return httpx.Response(200,json={'results':[]})
    provider=Tavily(Settings(api_key='test',database_path=str(tmp_path/'test.sqlite')),db,transport=httpx.MockTransport(serve))
    async def run():
        rid=db.create_run('News',[])
        await provider.search_signals('site:aurora.example "Aurora Asset Management" news',rid)
    asyncio.run(run())
    assert seen[0]['include_domains']==['aurora.example']


@pytest.mark.parametrize('phrase,expected',[
    ('on 12 June 2020','old'),('on June 12th, 2020','old'),
    ('el 12 de junio de 2020','old'),('in 2099','future'),
    ('on 2020-01-02 and 2021-02-03','historical')])
def test_explicit_event_dates_override_recent_publication(phrase,expected):
    signal=extract_signals(doc('Aurora Asset Management launches a new fund '+phrase+'.'),FIRM)[0]
    assert recency(signal) in (expected,'historical') if expected=='old' else recency(signal)==expected
    if phrase.startswith(('on 12 June','on June','el 12')):assert signal['event_at']=='2020-06-12'


def test_newsroom_paragraphs_and_inline_company_names_keep_extractable_evidence():
    result={'url':doc()['url'],'title':'News','content':'','published_date':TODAY}
    page={'url':result['url'],'html':'<main><div>'+('Background context '*80)+'</div><p>Aurora <strong>Asset Management</strong> launches a new equity fund</p><p>'+('More background '*80)+'</p></main>'}
    document=source_document(result,page)
    records=extract_signals(document,FIRM)
    assert any(s['kind']=='fund_launch' and s['quote']==QUOTE.rstrip('.') for s in records)
    assert document['date_basis']=='provider_estimate'
