import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.providers import Settings
from backend.crm import CRM
from backend.db import Database
from backend.playbook import seed_scripts
from backend.signals import extract_signals, save_signal

@pytest.fixture
def workspace(tmp_path):
    settings=Settings(database_path=str(tmp_path/'workspace.sqlite'),shared_path=str(tmp_path/'shared'))
    app=create_app(settings)
    with TestClient(app) as client:
        yield client,app,tmp_path

def add(client,name,company='Aurora Asset Management',country='España'):
    response=client.post('/api/contacts',json={'name':name,'company':company,'country':country,'role':'CIO','linkedin_url':'https://linkedin.com/in/'+name.lower().replace(' ','-'),'note':'Fixture verificada'})
    assert response.status_code==201,response.text
    return response.json()

def create(client,name):
    response=client.post('/api/portfolios',json={'name':name})
    assert response.status_code==201,response.text
    return response.json()

def test_company_grouping_exact_contact_filter_and_export(workspace):
    client,app,_=workspace
    a=add(client,'Ana Company QA');b=add(client,'Luis Company QA')
    other=add(client,'Sofia Other QA','Aurora Asset Management Partners','Francia')
    rows=client.get('/api/companies').json()['items']
    assert len(rows)==2
    firm=next(f for f in rows if f['id']==a['firm_id'])
    assert firm['contacts']==2 and firm['country']=='España'
    assert client.get('/api/companies/'+firm['uuid']).json()['contacts']==2
    filtered=client.get('/api/crm/contacts',params={'firm_id':a['firm_id']}).json()
    assert {c['id'] for c in filtered['items']}=={a['id'],b['id']}
    exported=client.get('/api/crm/contacts/export',params={'firm_id':a['firm_id']}).text
    assert a['name'] in exported and b['name'] in exported and other['name'] not in exported
    assert len(client.get('/api/companies',params={'country':'España'}).json()['items'])==1

def test_portfolio_default_and_memberships_are_independent_and_idempotent(workspace):
    client,app,_=workspace;c=add(client,'Ana Portfolio QA')
    marco=create(client,'Marco');team=create(client,'Equipo')
    assert client.get('/api/portfolios').json()['default_uuid']==marco['uuid']
    assert client.post('/api/portfolios/'+team['uuid']+'/default').status_code==200
    portfolios=client.get('/api/portfolios').json()
    assert portfolios['default_uuid']==team['uuid'] and sum(p['is_default'] for p in portfolios['items'])==1
    base='/api/portfolios/'+marco['uuid']+'/clients'
    first=client.post(base,json={'contact_id':c['id']}).json()
    assert client.put(base+'/'+str(c['id']),json={'stage':'viewed','notes':'Carta revisada','next_step':'Compartir earnings','follow_up':'2026-11-05'}).status_code==200
    repeated=client.post(base,json={'contact_id':c['id']}).json()
    assert repeated['uuid']==first['uuid'] and repeated['notes']=='Carta revisada' and repeated['stage']=='viewed'
    client.post('/api/portfolios/'+team['uuid']+'/clients',json={'contact_id':c['id']})
    assert len(client.get(base).json()['items'])==1
    assert client.get('/api/portfolios/'+team['uuid']+'/clients').json()['items'][0]['stage']=='saved'
    assert not app.state.db.contact(c['id'])['blocked'] and not app.state.crm.history(c['id'])
    assert 'Carta revisada' in client.get(base+'/export').text

def test_portfolios_and_removal_tombstones_roundtrip_without_losing_contacts(workspace):
    client,app,tmp=workspace;c=add(client,'Ana Shared Portfolio QA');p=create(client,'Marco')
    base='/api/portfolios/'+p['uuid']+'/clients'
    client.post(base,json={'contact_id':c['id']})
    client.delete(base+'/'+str(c['id']))
    assert client.get(base).json()['items']==[]
    db=Database(tmp/'copy.sqlite');db.initialize();crm=CRM(db,tmp/'shared')
    imported=crm.import_shared()
    assert imported['conflicts']==0 and len(db.contacts())==1
    from backend.workspace import portfolio_list,records
    assert portfolio_list(crm)['default_uuid']==p['uuid']
    assert records(crm,'portfolio_clients')[0]['removed']
    # Saving again reactivates the same membership, rather than creating a duplicate.
    again=client.post(base,json={'contact_id':c['id']}).json()
    assert not again['removed'] and len(client.get(base).json()['items'])==1

def test_invalid_portfolio_inputs_do_not_create_clients_or_interactions(workspace):
    client,app,_=workspace;c=add(client,'Ana Validation QA');p=create(client,'Marco')
    assert client.post('/api/portfolios',json={'name':'   '}).status_code==422
    base='/api/portfolios/'+p['uuid']+'/clients'
    assert client.post(base,json={'contact_id':999999}).status_code==404
    client.post(base,json={'contact_id':c['id']})
    assert client.put(base+'/'+str(c['id']),json={'stage':'sent_a_message'}).status_code==422
    assert client.put(base+'/'+str(c['id']),json={'follow_up':'tomorrow'}).status_code==422
    assert not app.state.crm.history(c['id'])

def test_initial_scripts_are_bilingual_and_never_overwrite_user_edits(workspace):
    client,app,_=workspace
    scripts=client.get('/api/scripts').json()
    assert len(scripts)==5 and all(s['english_text'] and '{estrategia}' in s['text'] for s in scripts)
    script=scripts[0]
    changed={**script,'text':'Apertura personalizada','english_text':'Personal message','archived':True}
    assert client.patch('/api/scripts/'+script['uuid'],json=changed).status_code==200
    seed_scripts(app.state.crm)
    stored=app.state.crm.script(script['uuid'])
    assert stored['text']=='Apertura personalizada' and stored['archived'] and len(stored['versions'])==2
    assert len(client.get('/api/scripts').json())==5

def test_company_news_are_filtered_by_firm_and_not_other_companies(workspace):
    from datetime import date
    client,app,_=workspace
    a=add(client,'Ana News Company QA');b=add(client,'Luis News Company QA','Boreal Asset Management')
    for c in (a,b):
        app.state.db.upsert_firm({'name':c['company'],'domain':('aurora' if c['id']==a['id'] else 'boreal')+'.example','equity':True})
        firm=app.state.db.firm(c['firm_id'])
        document={'text':firm['name']+' launches a new equity fund.','title':'New fund','url':'https://news.example/'+str(c['firm_id']),
                  'published_at':date.today().isoformat(),'date_basis':'document','observed_at':date.today().isoformat()}
        records=extract_signals(document,firm)
        assert records
        save_signal(app.state.crm,c['firm_id'],records[0])
    client.post('/api/crm/contacts/'+str(a['id'])+'/interactions',json={'author':'Marco','channel':'linkedin','result':'contacted','comment':'Fixture de contacto previo'})
    rows=client.get('/api/companies').json()['items']
    assert all(f['news']==1 for f in rows)
    signals=client.get('/api/signals',params={'firm_id':a['firm_id'],'recent_only':'false'}).json()['items']
    assert len(signals)==1 and signals[0]['firm_id']==a['firm_id']
