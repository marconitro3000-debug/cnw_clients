from datetime import datetime, timezone
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.models import ContactInput
from backend.providers import Settings
from backend.opportunity import opportunity
from backend.signals import extract_signals, save_signal, review_signal

TODAY=datetime.now(timezone.utc).date().isoformat()
FIRM={'name':'Aurora Asset Management','domain':'aurora.example'}

def signal(kind,review='detected',recency='recent'): return {'kind':kind,'review':review,'recency':recency}

def test_answers_and_signals_add_up_and_classify():
    assert opportunity({},[])['opportunity_status']=='pending' and opportunity({},[])['opportunity_score']==0
    full=opportunity({'change':'yes','timing':'yes','decision':'yes'},[signal('fund_launch','confirmed'),signal('hiring','confirmed')])
    assert full['opportunity_score']==25+15+20+40 and full['opportunity_status']=='target'
    # A recent signal substitutes for an unknown timing answer, but an explicit "no" wins.
    assert opportunity({'change':'yes','decision':'yes'},[signal('expansion')])['opportunity_status']=='target'
    assert opportunity({'change':'yes','decision':'yes','timing':'no'},[signal('expansion')])['opportunity_status']=='later'
    assert opportunity({'change':'yes','decision':'yes'},[])['opportunity_status']=='pending'
    assert opportunity({'change':'no','timing':'yes','decision':'yes'},[])['opportunity_status']=='unwilling'
    assert opportunity({'decision':'no'},[])['opportunity_status']=='unwilling'

def test_signal_points_need_recent_unrejected_evidence():
    score=lambda *s:opportunity({},list(s))['opportunity_score']
    assert score(signal('fund_launch'))==12 and score(signal('fund_launch','confirmed'))==25
    assert score(signal('fund_launch'),signal('fund_launch','confirmed'))==25  # one entry per kind
    assert score(signal('hiring','rejected'),signal('hiring','confirmed','old'),signal('hiring','detected','estimated'))==0
    assert score(signal('event_driven','confirmed'))==0  # strategy description, not a reason to buy
    assert score(*[signal(k,'confirmed') for k in ('fund_launch','hiring','expansion','technology')])==40

def test_api_saves_answers_filters_sorts_exports_and_keeps_fit(tmp_path):
    settings=Settings(api_key='tvly-test',database_path=str(tmp_path/'t.sqlite'),shared_path=str(tmp_path/'shared'))
    app=create_app(settings)
    db=app.state.db
    ana=db.save_manual(ContactInput(name='Ana Pérez',company=FIRM['name'],role='CIO',equity=True,employees_min=30,employees_max=30,linkedin_url='https://linkedin.com/in/ana-opp',note='Equipo verificado'))
    db.save_manual(ContactInput(name='Bruno Gil',company='Otra Gestora',role='CIO',equity=True,employees_min=30,employees_max=30,linkedin_url='https://linkedin.com/in/bruno-opp',note='Equipo verificado'))
    db.upsert_firm(FIRM)
    doc={'text':'Aurora Asset Management launches a new equity fund.','title':'Fondo','url':'https://aurora.example/news/fund','published_at':TODAY,'date_basis':'document','observed_at':TODAY}
    key,_=save_signal(app.state.crm,ana['firm_id'],extract_signals(doc,FIRM)[0])
    with TestClient(app) as client:
        before=db.contact(ana['id'])
        assert before['opportunity_score']==12
        response=client.put(f"/api/crm/contacts/{ana['id']}/qualification",json={'change':'yes','decision':'yes'})
        assert response.status_code==200 and response.json()['opportunity_status']=='target'
        assert response.json()['score']==before['score']  # fit is unchanged
        review_signal(app.state.crm,key,'confirmed')
        assert db.contact(ana['id'])['opportunity_score']==25+25+20
        assert client.put(f"/api/crm/contacts/{ana['id']}/qualification",json={'change':'maybe'}).status_code==422
        assert client.put('/api/crm/contacts/9999/qualification',json={}).status_code==404
        assert [c['name'] for c in client.get('/api/crm/contacts?opportunity=target&reachability=all').json()['items']]==['Ana Pérez']
        assert client.get('/api/crm/contacts?opportunity=pending&reachability=all').json()['total']==1
        db.save_manual(ContactInput(name='Aaron Ruiz',company='Tercera Gestora',role='CIO',equity=True,employees_min=30,employees_max=30,linkedin_url='https://linkedin.com/in/aaron-opp',note='Equipo verificado'))
        assert client.get('/api/crm/contacts?reachability=all').json()['items'][0]['name']=='Aaron Ruiz'
        assert client.get('/api/crm/contacts?reachability=all&sort=opportunity').json()['items'][0]['name']=='Ana Pérez'
        assert client.get('/api/crm/contacts?opportunity=bad').status_code==422
        assert client.get('/api/crm/contacts?sort=bad').status_code==422
        csv=client.get('/api/crm/contacts/export?opportunity=target').text
        assert 'Estado oportunidad' in csv and 'Ana Pérez' in csv and 'Bruno Gil' not in csv and ';70;target' in csv
    # Answers travel with the shared copy.
    assert any('"qualification"' in p.read_text('utf-8') for p in (tmp_path/'shared'/'contacts').glob('*.json'))
