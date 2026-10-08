import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.providers import Settings

@pytest.mark.parametrize('status',['queued','running','stopping'])
def test_web_job_does_not_block_saving_apollo_key(tmp_path,status):
    settings=Settings(api_key='tvly-existing-fixture',database_path=str(tmp_path/'test.sqlite'),env_path=str(tmp_path/'.env'))
    app=create_app(settings)
    with TestClient(app) as client:
        rid=app.state.db.create_run('equity',[]);app.state.db.update_run(rid,status=status)
        app.state.crm.set_run_metadata(rid,provider='web')
        response=client.post('/api/settings/apollo',json={'api_key':'apollo-fixture-key','free_budget':0,'free_account':False})
        assert response.status_code==200 and response.json()['configured']
        assert settings.apollo_key=='apollo-fixture-key'
        assert settings.api_key=='tvly-existing-fixture'
        assert app.state.db.run(rid)['status']==status
        assert client.get('/api/settings/apollo').json()['configured']
        assert 'apollo-fixture-key' not in response.text
        assert 'APOLLO_API_KEY' in (tmp_path/'.env').read_text()
        assert not any('apollo-fixture-key' in p.read_text(encoding='utf-8-sig') for p in (tmp_path/'test.shared').rglob('*') if p.is_file())

@pytest.mark.parametrize('status',['queued','running','stopping'])
def test_apollo_job_blocks_changing_key_and_budget(tmp_path,status):
    settings=Settings(apollo_key='apollo-original-key',database_path=str(tmp_path/'test.sqlite'),env_path=str(tmp_path/'.env'))
    app=create_app(settings)
    with TestClient(app) as client:
        app.state.crm.set_setting('apollo',{'free_budget':8,'free_account':True})
        rid=app.state.db.create_run('Apollo',[]);app.state.db.update_run(rid,status=status)
        app.state.crm.set_run_metadata(rid,provider='apollo')
        response=client.post('/api/settings/apollo',json={'api_key':'apollo-replacement-key','free_budget':20,'free_account':True})
        assert response.status_code==409 and 'operación de Apollo' in response.json()['detail']
        assert settings.apollo_key=='apollo-original-key'
        assert app.state.crm.setting('apollo')['free_budget']==8
        assert not (tmp_path/'.env').exists()


def test_existing_web_scan_with_legacy_metadata_allows_apollo_connection(tmp_path):
    app=create_app(Settings(database_path=str(tmp_path/'test.sqlite'),env_path=str(tmp_path/'.env')))
    with TestClient(app) as client:
        rid=app.state.db.create_run('legacy web',[]);app.state.db.update_run(rid,status='running')
        assert client.post('/api/settings/apollo',json={'api_key':'apollo-fixture-key'}).status_code==200
