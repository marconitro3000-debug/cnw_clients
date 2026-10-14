"""Regressions for saving while research continues in the background."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.providers import Settings
from backend.models import ContactInput

@pytest.fixture
def workspace(tmp_path):
    app=create_app(Settings(database_path=str(tmp_path/'perf.sqlite'),shared_path=str(tmp_path/'shared')))
    with TestClient(app) as client:
        contact=client.post('/api/contacts',json={'name':'Ana Performance','company':'Aurora Management','role':'CIO','note':'Verified fixture'}).json()
        portfolio=client.post('/api/portfolios',json={'name':'Marco'}).json()
        base='/api/portfolios/'+portfolio['uuid']+'/clients'
        member=client.post(base,json={'contact_id':contact['id']}).json()
        yield client,app,base,contact,member


def test_save_does_not_wait_for_research_export_or_build_contacts(workspace,monkeypatch):
    client,app,base,c,member=workspace
    def unexpected(*args,**kwargs):raise AssertionError('Full archive work during portfolio save')
    monkeypatch.setattr(app.state.db,'contacts',unexpected)
    monkeypatch.setattr(app.state.crm,'export_shared',unexpected)
    with ThreadPoolExecutor() as pool:
        with app.state.crm.lock:
            result=pool.submit(client.put,base+'/'+str(c['id']),json={'notes':'Saved during research','follow_up':'2026-11-05'}).result(timeout=3)
            assert result.status_code==200
            # Creating another portfolio must not trigger the global middleware export.
            assert client.post('/api/portfolios',json={'name':'Team'}).status_code==201
    path=app.state.crm.directory/'portfolio_clients'/(member['uuid']+'.json')
    assert json.loads(path.read_text(encoding='utf-8'))['record']['notes']=='Saved during research'


def test_portfolio_load_fetches_only_its_members(workspace,monkeypatch):
    client,app,base,c,member=workspace
    original=app.state.db.contacts;calls=[]
    def contacts(contact_id=None,contact_uuids=None):
        calls.append((contact_id,contact_uuids))
        assert contact_uuids=={c['uuid']}
        return original(contact_id,contact_uuids)
    monkeypatch.setattr(app.state.db,'contacts',contacts)
    response=client.get(base)
    assert response.status_code==200 and len(response.json()['items'])==1 and len(calls)==1


def test_full_export_cannot_overwrite_new_portfolio_notes(workspace,monkeypatch):
    client,app,base,c,member=workspace;crm=app.state.crm
    original=crm.records;snapshot_ready=threading.Event();resume=threading.Event()
    def snapshot():
        rows=original();snapshot_ready.set()
        assert resume.wait(5)
        return rows
    monkeypatch.setattr(crm,'records',snapshot)
    with ThreadPoolExecutor() as pool:
        future=pool.submit(crm.export_shared)
        try:
            assert snapshot_ready.wait(3)
            assert client.put(base+'/'+str(c['id']),json={'notes':'Newer than the research snapshot'}).status_code==200
        finally:resume.set()
        assert future.result(timeout=5)['ok']
    path=crm.directory/'portfolio_clients'/(member['uuid']+'.json')
    assert json.loads(path.read_text(encoding='utf-8'))['record']['notes']=='Newer than the research snapshot'


def test_slow_profile_export_leaves_health_responsive(workspace,monkeypatch):
    client,app,base,c,member=workspace;entered=threading.Event();release=threading.Event()
    def export():
        entered.set();assert release.wait(5)
    monkeypatch.setattr(app.state.crm,'export_shared',export)
    with ThreadPoolExecutor() as pool:
        profile=pool.submit(client.post,'/api/contacts',json={'name':'Luis Performance','company':'Aurora Management','role':'CIO','note':'Fixture'})
        try:
            assert entered.wait(3)
            health=pool.submit(client.get,'/api/health')
            assert health.result(timeout=2).status_code==200
        finally:release.set()
        assert profile.result(timeout=3).status_code==201


def test_contact_cache_survives_progress_updates_but_refreshes_profile_changes(workspace,monkeypatch):
    client,app,base,c,member=workspace;db=app.state.db;crm=app.state.crm
    db._contacts_cache=None
    original=db._build_contacts;calls=[]
    def build(*args):calls.append(args);return original(*args)
    monkeypatch.setattr(db,'_build_contacts',build)
    first=db.contacts();first[0]['name']='Local edit'
    crm.set_setting('crawler_progress',{'pages':100})
    assert db.contacts()[0]['name']==c['name'] and len(calls)==1
    crm.set_meta(c['id'],owner='New owner')
    assert db.contacts()[0]['owner']=='New owner' and len(calls)==2
    client.put(base+'/'+str(c['id']),json={'notes':'Portfolio only'})
    db.contacts();assert len(calls)==2


def test_export_batches_contact_metadata_and_run_queries(workspace,monkeypatch):
    client,app,base,c,member=workspace;db=app.state.db;crm=app.state.crm
    rid=db.create_run('Fixture',[{'phase':'firms','text':'Aurora Management'}])
    crm.set_run_metadata(rid,provider='web',omitted=2)
    crm.observe(c['id'],rid,fresh=True,export=False)
    run=db.run(rid);expected=crm.run_summary(run)
    def unexpected(*args,**kwargs):raise AssertionError('Per-record SQL query in bulk export')
    monkeypatch.setattr(crm,'meta',unexpected);monkeypatch.setattr(crm,'run_summary',unexpected);monkeypatch.setattr(db,'run',unexpected)
    rows=crm.records();exported=next(row for kind,key,row in rows if kind=='runs' and key==run['uuid'])
    assert exported['queries']==run['queries']
    assert exported['summary']['new_contacts']==expected['new_contacts']==1
    assert exported['summary']['omitted']==2


def test_navigation_index_omits_evidence_without_altering_full_profiles(workspace):
    client,app,base,c,member=workspace
    index=client.get('/api/contacts?status=all&summary=true').json()
    full=client.get('/api/contacts/'+str(c['id'])).json()
    assert index[0]['id']==full['id'] and index[0]['score']==full['score']
    assert index[0]['evidence']==[] and index[0]['reasons']==[]
    assert full['evidence'] and full['reasons']
    assert client.get('/api/contacts?status=all').json()[0]['evidence']
