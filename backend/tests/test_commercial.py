import asyncio
import json
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.crm import CRM
from backend.crm_models import InteractionInput, ScriptInput, ApolloSearchInput, ApolloEnrichInput
from backend.db import Database
from backend.domain import evidence, now
from backend.enrichment import Apollo, ApolloRunner, Ollama, apollo_into_contact
from backend.extract import result_firm
from backend.main import create_app
from backend.models import ContactInput
from backend.providers import Settings, QuotaError, ProviderError
from backend.runner import Runner

@pytest.fixture
def commercial(tmp_path):
    settings=Settings(database_path=str(tmp_path/'scout.sqlite'),env_path=str(tmp_path/'.env'),shared_path=str(tmp_path/'shared'))
    app=create_app(settings)
    with TestClient(app) as client: yield client,app,settings

def add(client,name='Ana Pérez',link='ana-perez'):
    response=client.post('/api/contacts',json={'name':name,'company':'Aurora Asset Management','role':'CIO','country':'España','employees_min':30,'employees_max':30,'equity':True,'analysis':True,'linkedin_url':'https://linkedin.com/in/'+link,'note':'Revisión comprobada'})
    assert response.status_code==201,response.text
    return response.json()

def event(client,cid,**changes):
    body={'author':'Marco','channel':'call','result':'contacted','comment':'Primera llamada',**changes}
    response=client.post('/api/crm/contacts/'+str(cid)+'/interactions',json=body)
    assert response.status_code==201,response.text
    return response.json()

def test_migration_preserves_and_assigns_stable_ids(tmp_path):
    db=Database(tmp_path/'legacy.sqlite');db.initialize()
    contact=db.save_manual(ContactInput(name='Ana Pérez',company='Aurora Asset Management',role='CIO'))
    crm=CRM(db,tmp_path/'shared');uuid=db.contact(contact['id'])['uuid']
    CRM(db,tmp_path/'shared')
    assert db.contact(contact['id'])['uuid']==uuid
    assert db.contact(contact['id'])['name']=='Ana Pérez'

def test_contacting_blocks_without_changing_score(commercial):
    client,app,_=commercial;c=add(client);before=c['score']
    event(client,c['id'],result='no_response')
    after=client.get('/api/contacts/'+str(c['id'])).json()
    assert after['blocked'] and after['stage']=='no_response' and after['score']==before
    assert client.get('/api/crm/contacts?view=burned').json()['total']==1
    assert client.get('/api/crm/contacts?view=pending').json()['total']==0
    assert app.state.crm.directory.joinpath('interacciones.csv').exists()

def test_comment_followup_and_append_only_correction(commercial):
    client,app,_=commercial;c=add(client)
    original=event(client,c['id'],follow_up='2026-10-09T09:00:00Z')
    event(client,c['id'],channel='note',result=None,comment='Usa otra herramienta')
    assert app.state.db.contact(c['id'])['follow_up']
    correction=client.patch('/api/crm/contacts/'+str(c['id'])+'/interactions/'+original['uuid'],json={'author':'Marco','channel':'call','result':'interested','comment':'Corrección','occurred_at':original['occurred_at']})
    assert correction.status_code==200
    assert correction.json()['supersedes']==original['uuid']
    assert len(client.get('/api/crm/contacts/'+str(c['id'])+'/interactions').json())==3
    assert app.state.db.contact(c['id'])['stage']=='interested'
    event(client,c['id'],channel='note',result=None,clear_follow_up=True)
    assert app.state.db.contact(c['id'])['follow_up'] is None
    assert client.patch('/api/crm/contacts/'+str(c['id'])+'/interactions/'+original['uuid'],json={'author':'Marco','channel':'call'}).status_code==404

@pytest.mark.parametrize('channel',['call','linkedin','email'])
def test_each_outreach_channel_blocks(commercial,channel):
    client,app,_=commercial;c=add(client);event(client,c['id'],channel=channel)
    assert app.state.db.contact(c['id'])['blocked']

def test_notes_alone_do_not_block_and_date_validation(commercial):
    client,app,_=commercial;c=add(client);event(client,c['id'],channel='note',result=None)
    assert not app.state.db.contact(c['id'])['blocked']
    assert client.post('/api/crm/contacts/'+str(c['id'])+'/interactions',json={'author':'Marco','occurred_at':'yesterday'}).status_code==422


def test_versions_and_unique_attribution(commercial):
    client,app,_=commercial;c=add(client)
    s=client.post('/api/scripts',json={'title':'Apertura','channel':'call','text':'Hola {nombre}'}).json()
    event(client,c['id'],script_uuid=s['uuid']);event(client,c['id'],script_uuid=s['uuid'])
    client.patch('/api/scripts/'+s['uuid'],json={'title':'Apertura','channel':'call','text':'Nueva apertura'})
    event(client,c['id'],script_uuid=s['uuid'])
    event(client,c['id'],channel='note',result='demo')
    event(client,c['id'],channel='note',result='demo')
    stats=client.get('/api/scripts-statistics').json()
    assert stats[0]['approached']==1 and stats[0]['demos']==0
    assert stats[1]['approached']==1 and stats[1]['demos']==1 and stats[1]['conversion']==100
    assert app.state.crm.dashboard()['totals']=={'identified':1,'qualified':1,'contacted':1,'demos':1}
    with app.state.db.connect() as con:
        script=json.loads(con.execute('SELECT data FROM scripts').fetchone()[0]);assert len(script['versions'])==2


def test_pagination_filters_letters_export_and_metadata(commercial):
    client,app,_=commercial
    for name,slug in [('Álvaro López','alvaro'),('Ñora Pérez','nora'),('Nerea López','nerea')]: add(client,name,slug)
    c=app.state.db.contacts()[0]
    assert client.patch('/api/crm/contacts/'+str(c['id']),json={'owner':'Lucía','email':'a@example.com','phone':'+34 123'}).status_code==200
    assert client.get('/api/crm/contacts?letter=A').json()['total']==1
    assert client.get('/api/crm/contacts?letter=Ñ').json()['total']==1
    assert client.get('/api/crm/contacts?letter=N').json()['total']==1
    assert client.get('/api/crm/contacts?channel=email&owner=Lucía').json()['total']==1
    assert client.get('/api/crm/contacts?page_size=2&page=2').json()['items'].__len__()==1
    assert client.get('/api/crm/contacts?page_size=51').status_code==422
    export=client.get('/api/crm/contacts/export?letter=Ñ')
    assert 'Ñora Pérez' in export.text and 'Nerea López' not in export.text
    assert client.patch('/api/crm/contacts/'+str(c['id']),json={'email':'bad'}).status_code==422


def test_share_roundtrip_idempotent_including_run_and_events(commercial,tmp_path):
    client,app,settings=commercial;c=add(client)
    s=client.post('/api/scripts',json={'title':'Mensaje','channel':'linkedin','text':'Hola {nombre}, {gestora}'}).json()
    event(client,c['id'],channel='linkedin',script_uuid=s['uuid'],result='interested',comment='Le interesa equity')
    rid=app.state.db.create_run('equity',[{'text':'equity boutique España','phase':'firms'}]);app.state.crm.identifiers()
    qid=app.state.db.add_query(rid,'equity boutique España','firms');app.state.db.update_query(qid,'completed')
    app.state.crm.observe(c['id'],rid,False);app.state.db.update_run(rid,status='completed',finished_at=now())
    app.state.crm.export_shared()
    clone=create_app(Settings(database_path=str(tmp_path/'clone.sqlite'),env_path=str(tmp_path/'clone.env'),shared_path=settings.shared_path))
    with TestClient(clone) as second:
        assert second.get('/api/shared/status').json()['conflicts']==[]
        imported=second.get('/api/contacts?status=all').json()
        assert len(imported)==1 and imported[0]['uuid']==c['uuid'] and imported[0]['blocked']
        assert 'Le interesa' in imported[0]['notes']
        assert len(second.get('/api/search-history').json())==1
        second.post('/api/shared/import',json={});second.post('/api/shared/import',json={})
        assert len(second.get('/api/contacts?status=all').json())==1
        assert len(second.get('/api/crm/contacts/'+str(imported[0]['id'])+'/interactions').json())==1
        assert second.get('/api/shared/status').json()['conflicts']==[]


def test_shared_conflicts_and_write_failure_are_visible(commercial,monkeypatch):
    client,app,_=commercial;c=add(client);crm=app.state.crm
    path=crm.directory/'contacts'/(c['uuid']+'.json');record=json.loads(path.read_text())
    record['record']['data']['role']='Analyst';path.write_text(json.dumps(record))
    result=client.post('/api/shared/import',json={}).json();assert result['conflicts']==1
    assert app.state.db.contact(c['id'])['role']=='CIO'
    conflict=crm.conflicts()[0]
    client.post('/api/shared/conflicts/'+conflict['uuid']+'/resolve',json={'choice':'local'})
    assert crm.conflicts()==[]
    def fail(*args): raise OSError('Sin permisos de escritura')
    monkeypatch.setattr(crm,'atomic',fail)
    assert client.post('/api/shared/export',json={}).json()['ok'] is False
    assert client.get('/api/shared/status').json()['error']


def test_csv_preview_mapping_duplicates_burned_and_formula(commercial):
    client,app,_=commercial;text='Nombre;Gestora;Cargo;Correo;LinkedIn\nAna Pérez;Aurora Asset Management;CIO;a@example.com;https://linkedin.com/in/ana-perez\n'
    assert client.post('/api/imports/csv/preview',json={'text':text}).json()['count']==1
    body={'text':text,'mapping':{'name':'Nombre','company':'Gestora','role':'Cargo','email':'Correo','linkedin_url':'LinkedIn'}}
    result=client.post('/api/imports/csv',json=body).json();assert result['new']==1
    assert client.post('/api/imports/csv',json=body).json()['duplicates']==1
    c=app.state.db.contacts()[0];event(client,c['id'])
    assert client.post('/api/imports/csv',json=body).json()['omitted']==1
    client.patch('/api/crm/contacts/'+str(c['id']),json={'owner':'=formula()'})
    assert "'=formula()" in client.get('/api/crm/contacts/export').text

@pytest.mark.parametrize('title,url',[('ASSET MANAGEMENT IN EUROPE','https://efama.org/report'),('Your Trusted Partner in Asset Management','https://amundi.com'),('European Fund and Asset Management Association','https://industry.example')])
def test_report_and_slogan_not_firms(title,url):
    assert result_firm({'title':title,'url':url,'content':'equity investment management'}) is None


def test_next_batch_skips_completed_queries(commercial):
    client,app,_=commercial
    rid=app.state.db.create_run('renta variable',[]);app.state.crm.identifiers();app.state.db.update_run(rid,status='completed')
    first=client.get('/api/searches/'+str(rid)+'/next-batch').json()
    assert first['queries']
    for q in first['queries']:
        if q['phase']=='firms': qid=app.state.db.add_query(rid,q['text'],'firms');app.state.db.update_query(qid,'completed')
    second=client.get('/api/searches/'+str(rid)+'/next-batch').json()
    assert {q['text'] for q in first['queries'] if q['phase']=='firms'}.isdisjoint(q['text'] for q in second['queries'] if q['phase']=='firms')


def provider_fixture(commercial,handler):
    client,app,settings=commercial;settings.apollo_key='test-apollo-key';crm=app.state.crm
    crm.set_setting('apollo',{'free_account':True,'free_budget':10})
    return Apollo(settings,crm,httpx.MockTransport(handler))

def balance_response(left=10): return {'credit_usage_stats':{'lead_credit':{'limit':10,'consumed':10-left,'left_over':left}},'current_credit_cycle':{'start':'2026-10-01','end':'2026-11-01'}}

def test_apollo_no_budget_no_http_calls(commercial):
    calls=[];p=provider_fixture(commercial,lambda r:(calls.append(r),httpx.Response(200,json={}))[1]);p.crm.set_setting('apollo',{'free_account':True,'free_budget':0})
    with pytest.raises(QuotaError): asyncio.run(p.enrich(person_id='p1'))
    assert not calls

@pytest.mark.parametrize('response',[httpx.Response(403,json={}),httpx.Response(200,json={}),httpx.Response(200,json=balance_response(0))])
def test_apollo_fails_closed_when_balance_unavailable(commercial,response):
    paths=[]
    def handler(r): paths.append(r.url.path); return response
    p=provider_fixture(commercial,handler)
    with pytest.raises(ProviderError): asyncio.run(p.enrich(person_id='p1',phone=True))
    assert all('people/match' not in path for path in paths)


def test_apollo_budget_reserved_and_phone_poll_payload(commercial):
    requests=[]
    def handler(r):
        requests.append(r)
        if 'credit_usage_stats' in r.url.path: return httpx.Response(200,json=balance_response())
        return httpx.Response(200,json={'person':None,'request_id':-1039995589705121900})
    p=provider_fixture(commercial,handler)
    asyncio.run(p.enrich(person_id='p1',phone=True))
    payload=json.loads(requests[-1].content)
    assert payload['poll_only'] and payload['reveal_phone_number'] and not payload['run_waterfall_phone'] and 'webhook_url' not in payload
    asyncio.run(p.enrich(person_id='p2'))
    before=len(requests)
    with pytest.raises(QuotaError): asyncio.run(p.enrich(person_id='p3'))
    assert len(requests)==before+1


def test_apollo_search_free_and_country_validation(commercial):
    calls=[]
    def handler(r): calls.append(r);return httpx.Response(200,json={'people':[]})
    p=provider_fixture(commercial,handler)
    assert asyncio.run(p.search(ApolloSearchInput(countries=['España'])))==[]
    assert len(calls)==1 and 'mixed_people/api_search' in calls[0].url.path
    with pytest.raises(ProviderError): asyncio.run(p.search(ApolloSearchInput(countries=['United States'])))


def test_apollo_ambiguous_match_preserves_existing(commercial):
    client,app,_=commercial;c=add(client)
    with pytest.raises(ProviderError): apollo_into_contact(app.state.crm,{'id':'p','name':'Ana Pérez','title':'CIO','match_confidence':'low','organization':{'name':'Aurora Asset Management'}},app.state.db.contact(c['id']))
    assert len(app.state.db.contacts())==1 and app.state.crm.conflicts()


def test_pending_phone_recovery_no_new_enrichment(commercial):
    client,app,_=commercial;c=add(client);app.state.crm.set_meta(c['id'],apollo_id='p1')
    calls=[]
    def handler(r):
        calls.append(r.url.path)
        return httpx.Response(200,json={'people':[{'id':'p1','phone_numbers':[{'raw_number':'+34 123','type':'mobile'}]}]})
    p=provider_fixture(commercial,handler);ar=ApolloRunner(app.state.runner,p,app.state.crm);ar.pending('-123',c['id'])
    rid=app.state.db.create_run('Apollo poll',[]);app.state.crm.identifiers();asyncio.run(ar.poll_pending(rid))
    assert app.state.db.contact(c['id'])['phones'][0]['number']=='+34 123'
    assert app.state.crm.setting('apollo_pending')==[]
    assert calls==['/api/v1/webhook_result/-123']


def test_ollama_absent_and_cloud_model_disabled(commercial):
    client,app,_=commercial;crm=app.state.crm
    o=Ollama(crm,httpx.MockTransport(lambda r:httpx.Response(200,json={'models':[{'name':'model:cloud','remote_host':'https://ollama.com'}]})))
    assert asyncio.run(o.health())['models']==[]
    assert client.post('/api/settings/ollama',json={'enabled':True,'model':'model:cloud'}).status_code==422
    absent=Ollama(crm,httpx.MockTransport(lambda r:(_ for _ in ()).throw(httpx.ConnectError('offline'))))
    assert asyncio.run(absent.health())['reachable'] is False


def test_ollama_requires_exact_evidence(commercial):
    client,app,_=commercial;crm=app.state.crm;crm.set_setting('ollama',{'enabled':True,'model':Ollama.MODEL})
    def handler(r):
        if r.url.path=='/api/tags': return httpx.Response(200,json={'models':[{'name':Ollama.MODEL}]})
        return httpx.Response(200,json={'message':{'content':json.dumps({'people':[
            {'name':'Ana Pérez','role':'CIO','quote':'Ana Pérez es CIO','linkedin_url':'https://linkedin.com/in/inventado'},
            {'name':'Luis López','role':'CIO','quote':'Luis López es CIO','linkedin_url':''}]})}})
    people=asyncio.run(Ollama(crm,httpx.MockTransport(handler)).extract({'html':'<p>Ana Pérez es CIO</p>','url':'https://aurora.example/team','observed_at':now()}))
    assert len(people)==1 and people[0]['linkedin_url'] is None and people[0]['issues']==['ai_review']


def test_web_scan_skips_blocked_and_explicit_once(commercial):
    client,app,settings=commercial;c=add(client);event(client,c['id']);db=app.state.db
    with db.connect() as con:
        row=con.execute('SELECT data FROM firms').fetchone();data=json.loads(row[0]);data['domain']='aurora.example';con.execute('UPDATE firms SET domain=?,data=?',('aurora.example',json.dumps(data)))
    class Provider:
        async def search(self,q,rid): return [{'url':'https://linkedin.com/in/ana-perez','title':'Ana Pérez - CIO - Aurora Asset Management | LinkedIn','content':'Ana Pérez CIO at Aurora Asset Management','observed_at':now()}],False
    class Fetcher:
        async def page(self,url): raise ProviderError('offline fixture')
    runner=Runner(db,settings,Provider(),lambda:Fetcher())
    query=[{'text':'site:linkedin.com/in/ "Aurora Asset Management" "Ana Pérez" CIO','phase':'people'}]
    async def go(force=False):
        rid=runner.start('Ana Pérez',query,{'force_contact_id':c['id']} if force else {})
        await asyncio.gather(*list(runner.tasks));return db.run(rid)
    skipped=asyncio.run(go());assert skipped['omitted']==1 and skipped['contacts_found']==0
    explicit=asyncio.run(go(True));assert explicit['contacts_found']==1 and explicit['omitted']==0
    assert db.contact(c['id'])['blocked'] and db.contact(c['id'])['notes']=='Primera llamada'


def test_restart_interrupts_active_run_preserving_contact(commercial,tmp_path):
    client,app,settings=commercial;c=add(client);rid=app.state.db.create_run('interrupted',[])
    clone=create_app(settings)
    with TestClient(clone):
        assert clone.state.db.run(rid)['status']=='interrupted'
        assert clone.state.db.contact(c['id'])['uuid']==c['uuid']


def test_company_word_gestora_is_not_person_role():
    from backend.extract import result_person
    p=result_person({'url':'https://linkedin.com/in/ana-perez','title':'Ana Pérez - Renta 4 Gestora | LinkedIn','content':'Renta 4 Gestora'}, {'name':'Renta 4 Gestora'})
    assert p['role']=='' and 'role_unverified' in p['issues']

def test_apollo_wrong_name_even_high_confidence_not_merged(commercial):
    client,app,_=commercial;c=add(client)
    with pytest.raises(ProviderError): apollo_into_contact(app.state.crm,{'id':'p','name':'Luis López','title':'CIO','email':'wrong@example.com','match_confidence':'high','organization':{'name':'Aurora Asset Management'}},app.state.db.contact(c['id']))
    assert app.state.db.contact(c['id'])['email'] is None
    assert app.state.db.contact(c['id'])['name']=='Ana Pérez'

def test_ollama_cancellation_does_not_wait_for_model(commercial):
    client,app,settings=commercial;c=add(client);crm=app.state.crm;db=app.state.db
    from backend.domain import identity
    firm={'name':'Aurora Asset Management','domain':'aurora.example','country':'España','equity':True,'analysis':True,'employees_min':30,'employees_max':30,'evidence':[]}
    db.upsert_firm(firm)
    class Provider:
        async def search(self,q,rid): return [{'url':'https://aurora.example','title':'Aurora Asset Management','content':'equity asset management'}],False
    class Fetcher:
        async def page(self,url): return {'url':url,'html':'<title>Aurora Asset Management</title><p>equity asset management</p>','observed_at':now()}
    started=asyncio.Event()
    class Model:
        async def extract(self,page): started.set(); await asyncio.sleep(30); return []
    async def go():
        runner=Runner(db,settings,Provider(),lambda:Fetcher());runner.ollama=Model()
        rid=runner.start('equity',[{'text':'equity boutique gestora','phase':'firms'}],{'use_ollama':True})
        await asyncio.wait_for(started.wait(),3)
        db.update_run(rid,cancel_requested=1,status='stopping')
        await asyncio.wait_for(asyncio.gather(*list(runner.tasks)),3)
        assert db.run(rid)['status']=='stopped'
    asyncio.run(go())


def test_phone_pending_then_ready_and_contacted_skip_no_credits(commercial):
    client,app,settings=commercial;c=add(client);event(client,c['id'])
    calls=[]
    class Provider:
        account='test'
        async def enrich(self,**kwargs): calls.append('enrich'); raise AssertionError('Contactado: no llamar al proveedor')
        async def poll(self,rid):
            calls.append('poll')
            if calls.count('poll')==1: return {'error_code':'result_pending','retry_after_seconds':1}
            return {'people':[{'id':'p1','phone_numbers':[{'raw_number':'+34 999'}]}]}
    ar=ApolloRunner(app.state.runner,Provider(),app.state.crm)
    async def go():
        rid=ar.start('enrich',ApolloEnrichInput(contact_ids=[c['id']]))
        await asyncio.gather(*list(app.state.runner.tasks))
        assert app.state.db.run(rid)['omitted']==1
        ar.pending('123',c['id'])
        poll_rid=ar.start('poll',{})
        await asyncio.gather(*list(app.state.runner.tasks))
        assert app.state.db.run(poll_rid)['status']=='completed'
    asyncio.run(go())
    assert calls==['poll','poll']
    assert app.state.db.contact(c['id'])['phones'][0]['number']=='+34 999'

def test_one_active_job_for_both_scanners_and_duplicate_candidate_no_credit(commercial):
    client,app,settings=commercial;c=add(client);crm=app.state.crm;crm.set_meta(c['id'],apollo_id='p1')
    class Provider:
        async def enrich(self,**kwargs): raise AssertionError('No completar otra vez un candidato ya incorporado')
    from backend.crm_models import CandidateAcceptInput
    source=app.state.db.create_run('Apollo discovery',[]);crm.identifiers();app.state.db.update_run(source,status='completed')
    crm.set_run_metadata(source,candidates=[{'id':'p1','name':'Ana','company':'Aurora Asset Management','linkedin_url':None,'partial':True,'raw':{}}])
    ar=ApolloRunner(app.state.runner,Provider(),crm)
    async def go():
        rid=ar.start('accept',CandidateAcceptInput(run_id=source,candidate_ids=['p1'],enrich=True))
        with pytest.raises(RuntimeError): app.state.runner.start('web',[{'text':'equity boutique','phase':'firms'}])
        await asyncio.gather(*list(app.state.runner.tasks))
        assert app.state.db.run(rid)['duplicates']==1 and app.state.db.run(rid)['status']=='completed'
    asyncio.run(go())


def test_large_csv_batch_paginates_without_rewriting_each_row(commercial,monkeypatch):
    client,app,_=commercial;calls=[];original=app.state.crm.export_shared
    def export(): calls.append(1);return original()
    monkeypatch.setattr(app.state.crm,'export_shared',export)
    text='Nombre;Gestora;Cargo;Correo\n'+''.join('Persona '+str(i)+';Gestora de pruebas;CIO;persona'+str(i)+'@example.com\n' for i in range(125))
    body={'text':text,'mapping':{'name':'Nombre','company':'Gestora','role':'Cargo','email':'Correo'}}
    result=client.post('/api/imports/csv',json=body)
    assert result.status_code==200 and result.json()['new']==125
    assert len(calls)<=2
    assert len(client.get('/api/crm/contacts?page=1').json()['items'])==50
    assert len(client.get('/api/crm/contacts?page=3').json()['items'])==25


def test_shared_older_firm_sources_merge_without_false_conflict(commercial):
    client,app,_=commercial
    c=add(client)
    crm=app.state.crm
    path=next((crm.directory/'firms').glob('*.json'))
    snapshot=json.loads(path.read_text(encoding='utf8'))
    firm=app.state.db.firm(c['firm_id'])
    firm['evidence']=firm['evidence']+[evidence('company',firm['name'],'https://aurora.example/team','Nueva observación de la misma gestora')]
    app.state.db.upsert_firm(firm)
    # Re-import a snapshot taken before the latest source was saved.
    imported=crm.import_shared()
    assert imported['conflicts']==0
    assert len(app.state.db.firm(c['firm_id'])['evidence'])==len(snapshot['record']['data']['evidence'])+1
    # Another copy can add a source while keeping the verified fields identical.
    snapshot['record']['data']['evidence'].append(evidence('company',firm['name'],'https://aurora.example/about','Una segunda fuente'))
    path.write_text(json.dumps(snapshot),encoding='utf8')
    assert crm.import_shared()['conflicts']==0
    assert len(app.state.db.firm(c['firm_id'])['evidence'])==len(snapshot['record']['data']['evidence'])+1
    crm.export_shared()
    assert crm.import_shared()['conflicts']==0
