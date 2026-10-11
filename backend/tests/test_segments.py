from fastapi.testclient import TestClient
from backend.main import create_app
from backend.db import Database
from backend.crm import CRM
from backend.models import ContactInput
from backend.providers import Settings
from backend.segments import classify

def test_classify_cites_sentences_and_breaks_ties_by_specificity():
    info=classify([('We are a quantamental boutique. Our stock picking is bottom-up.','https://a.example/about')])
    assert info['segment']=='quant' and info['tags']==['boutique_equity']  # one sentence each, quant is more specific
    assert info['evidence'][0]=={'segment':'quant','quote':'We are a quantamental boutique.','url':'https://a.example/about'}
    assert classify([('Gestión patrimonial para familias. Family office multi-family.','u')])['segment']=='wealth'
    assert classify([('Nada relevante aquí.','u')])=={'segment':'unclassified','tags':[],'evidence':[],'sources':0}
    # Repeated quotes do not inflate a segment.
    assert classify([('Private equity house.','u'),('Private equity house.','v'),('Long-only equity funds.','w')],equity=True)['segment']=='boutique_equity'

def test_groups_filter_manual_override_csv_and_sharing(tmp_path):
    settings=Settings(api_key='tvly-test',database_path=str(tmp_path/'t.sqlite'),shared_path=str(tmp_path/'shared'))
    app=create_app(settings);db=app.state.db
    ana=db.save_manual(ContactInput(name='Ana Quant',company='Factor Lab',role='CIO · quantitative strategies',equity=True,employees_min=20,employees_max=20,linkedin_url='https://linkedin.com/in/ana-seg',note='Equipo verificado'))
    db.save_manual(ContactInput(name='Bea Value',company='Valor Boutique',role='Portfolio manager, value investing',equity=True,employees_min=20,employees_max=20,linkedin_url='https://linkedin.com/in/bea-seg',note='Equipo verificado'))
    with TestClient(app) as client:
        groups={g['key']:g for g in client.get('/api/segments').json()['groups']}
        assert set(groups)=={'quant','boutique_equity'} and groups['quant']['firms'][0]['name']=='Factor Lab'
        assert [c['name'] for c in client.get('/api/crm/contacts?segment=quant&reachability=all').json()['items']]==['Ana Quant']
        assert client.get('/api/crm/contacts?segment=bad').status_code==422
        moved=client.put(f"/api/firms/{ana['firm_id']}/segment",json={'segment':'hedge_fund'}).json()
        assert moved['segment']=='hedge_fund' and moved['automatic']=='quant' and moved['manual']['author']
        assert client.get('/api/crm/contacts?segment=hedge_fund&reachability=all').json()['total']==1
        assert 'Hedge funds y retorno absoluto' in client.get('/api/crm/contacts/export?segment=hedge_fund').text
        assert client.put(f"/api/firms/{ana['firm_id']}/segment",json={'segment':'nope'}).status_code==422
        assert client.put('/api/firms/9999/segment',json={'segment':'quant'}).status_code==404
    other=Database(tmp_path/'other.sqlite');other.initialize();copy=CRM(other,tmp_path/'shared')
    copy.import_shared();copy.import_shared()
    from backend.segments import firm_segments
    firm=next(c for c in other.contacts() if c['name']=='Ana Quant')['firm_id']
    assert firm_segments(copy,{firm})[firm]['segment']=='hedge_fund' and not copy.conflicts()
    # Returning to automatic removes the override.
    with TestClient(app) as client:
        assert client.put(f"/api/firms/{ana['firm_id']}/segment",json={'segment':None}).json()['segment']=='quant'
