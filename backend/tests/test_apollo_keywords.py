import asyncio
import pytest
from backend.crm_models import ApolloSearchInput
from backend.crm import CRM
from backend.db import Database
from backend.runner import Runner
from backend.enrichment import ApolloRunner
from backend.providers import Settings,ProviderError
from pydantic import ValidationError

def test_multiple_keywords_preserve_phrases_trim_and_deduplicate():
    body=ApolloSearchInput(keywords=' renta variable, equity; RENTA VARIABLE\n asset   management ')
    assert body.keyword_terms==['renta variable','equity','asset management']
    assert ApolloSearchInput(keywords=['equity','renta variable','equity']).keyword_terms==['equity','renta variable']
    assert ApolloSearchInput(keywords='').keyword_terms==['']
    with pytest.raises(ValidationError):ApolloSearchInput(keywords=['x']*21+['y'+str(i) for i in range(21)])
    with pytest.raises(ValidationError):ApolloSearchInput(keywords=['equity',7])

def setup(tmp_path,provider):
    settings=Settings(database_path=str(tmp_path/'test.sqlite'))
    db=Database(settings.database_path);db.initialize();crm=CRM(db,tmp_path/'shared')
    runner=Runner(db,settings);return db,crm,runner,ApolloRunner(runner,provider,crm)

RAW={'id':'p1','name':'Ana Pérez','title':'CIO','linkedin_url':'https://linkedin.com/in/ana-keyword','organization':{'name':'Aurora Asset Management','primary_domain':'aurora.example'}}

def test_searches_each_phrase_and_unites_candidates_without_enrichment(tmp_path):
    calls=[]
    class Provider:
        async def search(self,body):
            calls.append((body.keywords,body.page))
            return [RAW,{**RAW,'id':'p2'}]
        async def enrich(self,**kwargs):raise AssertionError('Must not enrich during discovery')
    db,crm,runner,apollo=setup(tmp_path,Provider())
    async def run():
        rid=apollo.start('discover',ApolloSearchInput(keywords='equity\nrenta variable',page=3))
        await asyncio.gather(*list(runner.tasks))
        result=db.run(rid)
        assert result['status']=='completed' and result['completed_queries']==2 and result['total_queries']==2
        assert result['credits']==0 and len(result['queries'])==2
        assert len(crm.run_metadata(rid)['candidates'])==1
        assert not db.contacts()
    asyncio.run(run())
    assert calls==[('equity',3),('renta variable',3)]

def test_partial_results_survive_later_phrase_failure(tmp_path):
    class Provider:
        async def search(self,body):
            if body.keywords=='error':raise ProviderError('API temporarily unavailable')
            return [RAW]
    db,crm,runner,apollo=setup(tmp_path,Provider())
    async def run():
        rid=apollo.start('discover',ApolloSearchInput(keywords='equity\nerror'))
        await asyncio.gather(*list(runner.tasks))
        result=db.run(rid)
        assert result['status']=='failed' and result['completed_queries']==1
        assert len(crm.run_metadata(rid)['candidates'])==1
        assert result['queries'][-1]['status']=='failed'
    asyncio.run(run())

def test_cancel_stops_before_remaining_keywords_and_preserves_candidates(tmp_path):
    calls=[]
    class Provider:
        async def search(self,body):
            calls.append(body.keywords)
            if len(calls)==2:db.update_run(db.latest_run()['id'],cancel_requested=1)
            return [RAW]
    db,crm,runner,apollo=setup(tmp_path,Provider())
    async def run():
        rid=apollo.start('discover',ApolloSearchInput(keywords='equity\ncancel\nthird'))
        await asyncio.gather(*list(runner.tasks))
        assert db.run(rid)['status']=='stopped'
        assert len(crm.run_metadata(rid)['candidates'])==1
    asyncio.run(run())
    assert calls==['equity','cancel']
