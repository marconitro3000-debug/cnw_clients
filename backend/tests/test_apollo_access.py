import asyncio
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.providers import Settings, ProviderError
from backend.crm_models import ApolloSearchInput

@pytest.fixture
def configured(tmp_path):
    settings=Settings(apollo_key='private-fixture-key',database_path=str(tmp_path/'test.sqlite'),env_path=str(tmp_path/'.env'),shared_path=str(tmp_path/'shared'))
    app=create_app(settings)
    with TestClient(app) as client:
        yield client,app,settings,tmp_path

@pytest.mark.parametrize('code,payload,status',[
    (200,{'people':[]},'verified'),
    (401,{'error':'invalid secret'},'invalid'),
    (403,{'error_code':'API_INACCESSIBLE','error':'private-fixture-key'},'denied'),
    (403,{},'denied'),
    (429,{},'error'),
    (200,{},'error'),
])
def test_check_search_entitlement_without_enrichment_or_credits(configured,code,payload,status):
    client,app,settings,tmp_path=configured
    calls=[]
    def handle(request):
        calls.append(request)
        assert request.url.path=='/api/v1/mixed_people/api_search'
        assert json.loads(request.content)=={'page':1,'per_page':1}
        return httpx.Response(code,json=payload)
    app.state.apollo.provider.transport=httpx.MockTransport(handle)
    rid=app.state.db.create_run('web active',[]);app.state.db.update_run(rid,status='running')
    app.state.crm.set_run_metadata(rid,provider='web')
    result=client.post('/api/apollo/connection-check',json={})
    assert result.status_code==200
    assert result.json()['configured']
    assert result.json()['access']['status']==status
    assert len(calls)==1 and app.state.db.run(rid)['status']=='running'
    assert result.json()['free_budget']==0
    assert settings.apollo_key not in result.text
    assert 'account' not in result.json()['access']
    assert client.get('/api/settings/apollo').json()['access']['status']==status
    if code==403 and payload.get('error_code')=='API_INACCESSIBLE':
        assert 'master key' in result.json()['access']['message']
    assert app.state.db.contacts()==[]
    assert app.state.crm.export_shared()['ok']
    assert not any('apollo_access' in p.read_text(encoding='utf-8-sig') or settings.apollo_key in p.read_text(encoding='utf-8-sig') for p in (tmp_path/'shared').rglob('*') if p.is_file())

def test_new_key_does_not_inherit_old_access(configured):
    client,app,settings,_=configured
    app.state.apollo.provider.record_access('denied','Old account blocked')
    result=client.post('/api/settings/apollo',json={'api_key':'replacement-fixture-key'})
    assert result.json()['access']['status']=='unverified'
    assert 'Old account' not in result.text

def test_discovery_records_account_restriction(configured):
    _,app,_,_=configured
    app.state.apollo.provider.transport=httpx.MockTransport(lambda _:httpx.Response(403,json={'error_code':'API_INACCESSIBLE'}))
    with pytest.raises(ProviderError,match='plan de esta cuenta'):
        asyncio.run(app.state.apollo.provider.search(ApolloSearchInput()))
    assert app.state.apollo.provider.access_status()['status']=='denied'
