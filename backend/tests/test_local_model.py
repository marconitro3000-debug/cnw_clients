import asyncio
import json
import httpx
import pytest
from backend.local_model import LocalModel, grounded_people
from backend.batches import prepare_next_batch
from backend.main import create_app
from backend.providers import Settings, ProviderError
from backend.db import Database
from backend.crm import CRM
from backend.domain import now
from fastapi.testclient import TestClient

PAGE={'html':'<p>Ana Pérez es CIO de Aurora.</p>','url':'https://aurora.example/team','observed_at':now()}
TEXT='Ana Pérez es CIO de Aurora.'
PERSON={'name':'Ana Pérez','role':'CIO','quote':TEXT,'linkedin_url':'https://linkedin.com/in/ana-perez'}

def test_grounding_rejects_invented_people_roles_quotes_and_links():
    people=grounded_people({'people':[PERSON,{**PERSON,'name':'Lucía López'},{**PERSON,'role':'CEO'},{**PERSON,'quote':'Ana Pérez es CIO de otra empresa.'},None]},TEXT,[],PAGE)
    assert len(people)==1 and people[0]['linkedin_url'] is None
    assert people[0]['issues']==['ai_review']
    assert len(people[0]['evidence'])==2
    assert grounded_people({'people':'invalid'},TEXT,[],PAGE)==[]

def test_absent_model_does_not_spawn_or_request(tmp_path):
    def reject(request): raise AssertionError('Must not connect for an absent model')
    model=LocalModel(tmp_path)
    model.start()
    assert model.process is None
    assert asyncio.run(model.extract(PAGE))==[]
    assert not asyncio.run(model.health())['ready']

def test_structured_local_response_and_provider_failure(tmp_path):
    captured=[]
    def handler(request):
        assert request.url.host=='127.0.0.1'
        if request.url.path=='/health':return httpx.Response(200,json={'status':'ok'})
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'people':[PERSON]})}}]})
    model=LocalModel(tmp_path,transport=httpx.MockTransport(handler));model.port=45678
    people=asyncio.run(model.extract(PAGE))
    assert people[0]['name']=='Ana Pérez'
    assert captured[0]['chat_template_kwargs']['enable_thinking'] is False
    assert captured[0]['response_format']['type']=='json_schema'
    def broken(request):
        if request.url.path=='/health':return httpx.Response(200,json={'status':'ok'})
        return httpx.Response(500,json={'error':'failed'})
    model.transport=httpx.MockTransport(broken)
    with pytest.raises(ProviderError):asyncio.run(model.extract(PAGE))

def test_local_generation_can_be_canceled(tmp_path):
    async def exercise():
        entered=asyncio.Event();stopped=asyncio.Event()
        async def slow(request):
            if request.url.path=='/health':return httpx.Response(200,json={'status':'ok'})
            entered.set()
            try:await asyncio.sleep(60)
            finally:stopped.set()
        model=LocalModel(tmp_path,transport=httpx.MockTransport(slow));model.port=45678
        task=asyncio.create_task(model.extract(PAGE));await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert stopped.is_set()
    asyncio.run(exercise())

def test_alternative_installations_do_not_launch_production_model(tmp_path):
    app=create_app(Settings(database_path=str(tmp_path/'test.sqlite'),env_path=str(tmp_path/'.env')))
    with TestClient(app) as client:
        state=client.get('/api/local-model').json()
        assert not state['installed'] and not state['ready']
        assert app.state.local_model.process is None

def test_person_rescan_is_never_next_batch_seed(tmp_path):
    db=Database(tmp_path/'test.sqlite');db.initialize();crm=CRM(db,tmp_path/'shared')
    first=db.create_run('renta variable',[{'text':'gestoras europeas','phase':'firms'}]);db.update_run(first,status='completed');crm.set_run_metadata(first,provider='web')
    person=db.create_run('Antonio Gutiérrez MFIA',[{'text':'Antonio Gutiérrez','phase':'people'}]);db.update_run(person,status='completed');crm.set_run_metadata(person,provider='web',force_contact_id=77)
    preview=prepare_next_batch(db,person)
    assert preview['keywords']=='renta variable' and preview['parent_run_id']==first
    assert not any('Antonio' in q['text'] for q in preview['queries'])

def test_person_rescan_without_general_search_uses_default(tmp_path):
    db=Database(tmp_path/'test.sqlite');db.initialize();crm=CRM(db,tmp_path/'shared')
    person=db.create_run('Antonio Gutiérrez',[{'text':'Antonio Gutiérrez','phase':'people'}]);db.update_run(person,status='completed');crm.set_run_metadata(person,force_contact_id=77)
    assert prepare_next_batch(db,person)['keywords']=='renta variable'


def test_automatic_local_extraction_and_fast_runner_cancellation(tmp_path):
    from backend.runner import Runner
    db=Database(tmp_path/'test.sqlite');db.initialize();CRM(db,tmp_path/'shared')
    settings=Settings(database_path=str(tmp_path/'test.sqlite'))
    class Provider:
        async def search(self,q,rid):return [{'url':'https://aurora.example','title':'Aurora Asset Management','content':'equity asset management'}],False
    class Fetcher:
        async def page(self,url):return {'url':url,'html':'<title>Aurora Asset Management</title><p>equity asset management</p>','observed_at':now()}
    async def exercise():
        started=asyncio.Event();stopped=asyncio.Event()
        class Model:
            async def extract(self,page):
                started.set()
                try:await asyncio.sleep(60)
                finally:stopped.set()
                return []
        runner=Runner(db,settings,Provider(),lambda:Fetcher());runner.local_model=Model()
        rid=runner.start('equity',[{'text':'equity boutique gestora','phase':'firms'}])
        await asyncio.wait_for(started.wait(),3)
        db.update_run(rid,cancel_requested=1,status='stopping')
        await asyncio.wait_for(asyncio.gather(*list(runner.tasks)),3)
        assert stopped.is_set() and db.run(rid)['status']=='stopped'
    asyncio.run(exercise())


def test_legacy_continuous_descendants_do_not_inherit_person_seed(tmp_path):
    from backend.batches import general_web_seed
    db=Database(tmp_path/'test.sqlite');db.initialize();crm=CRM(db,tmp_path/'shared')
    first=db.create_run('renta variable',[{'text':'gestoras','phase':'firms'}]);db.update_run(first,status='completed')
    person=db.create_run('Antonio Gutiérrez',[{'text':'Antonio','phase':'people'}]);db.update_run(person,status='completed');crm.set_run_metadata(person,force_contact_id=77)
    previous=person
    for _ in range(5):
        child=db.create_run('Antonio Gutiérrez',[{'text':'Antonio gestoras','phase':'firms'}]);db.update_run(child,status='completed');crm.set_run_metadata(child,parent_run_id=previous,continuous=True);previous=child
    assert general_web_seed(db,previous)['id']==first
    batch=prepare_next_batch(db,previous)
    assert batch['keywords']=='renta variable' and batch['parent_run_id']==first
