import json
import re
import unicodedata
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from dotenv import set_key
from .crm import CRM, CHANNELS, STAGES
from .crm_models import (PublicSearchInput, InteractionInput, ScriptInput, ApolloSettingsInput, ApolloSearchInput, ApolloEnrichInput,
    CandidateAcceptInput, CSVPreviewInput, CSVImportInput, CRMContactInput, ResolveInput, OllamaInput)
from .domain import EUROPE, expand_queries, evidence, identity, now, normalized, linkedin_url, safe_url
from .enrichment import Apollo, ApolloRunner, Ollama, apollo_into_contact, csv_preview, COUNTRY_NAMES
from .extract import valid_firm_name
from .providers import ROOT, ProviderError

def install_extensions(app,db,settings,runner):
    # Tests and non-production databases get their own portable directory.
    directory=settings.shared_path or (str(ROOT/'shared-data') if Path(settings.database_path).resolve()==(ROOT/'data'/'scout.sqlite').resolve() else str(Path(settings.database_path).with_suffix('.shared')))
    crm=CRM(db,directory); provider=Apollo(settings,crm); apollo_runner=ApolloRunner(runner,provider,crm); ollama=Ollama(crm); runner.ollama=ollama
    from .local_model import LocalModel
    runner.local_model=LocalModel(enabled=Path(settings.database_path).resolve()==(ROOT/'data'/'scout.sqlite').resolve())
    app.state.local_model=runner.local_model
    from .continuous import ContinuousScanner
    scanning=ContinuousScanner(runner,apollo_runner,crm)
    app.state.scanning=scanning
    app.state.crm,app.state.apollo,app.state.ollama=crm,apollo_runner,ollama
    router=APIRouter(prefix='/api')

    @router.get('/local-model')
    async def local_model_health(): return await runner.local_model.health()

    def found(cid):
        contact=db.contact(cid)
        if not contact: raise HTTPException(404,'Contacto no encontrado.')
        return contact
    def begin(kind,body):
        try: return db.run(apollo_runner.start(kind,body))
        except RuntimeError: raise HTTPException(409,'Ya hay un escaneo en curso. Espera o deténlo.') from None
    def guard():
        latest=db.latest_run()
        if latest and latest['status'] in ('queued','running','stopping'): raise HTTPException(409,'Espera a que termine el escaneo.')
    def filtered(q='',status='all',stage='',country='',role='',min_score=0,size_min=None,size_max=None,channel='',owner='',letter='',view='all',reachability='all'):
        from .main import select_contacts
        contacts=select_contacts(db.contacts(),country,role,min_score,size_min,size_max,status,q)
        def initial(name):
            first=name.strip()[0].upper() if name.strip() else '#'
            return first if first=='Ñ' else unicodedata.normalize('NFD',first)[0]
        result=[]
        for c in contacts:
            if reachability=='reachable' and not c['reachable'] or reachability=='missing' and c['reachable']: continue
            if stage and c['stage']!=stage: continue
            if owner and c['owner']!=owner: continue
            if letter and initial(c['name'])!=letter.upper(): continue
            if channel=='email' and not c['email'] or channel=='call' and not c['phones'] or channel=='linkedin' and not c.get('linkedin_url'): continue
            if view=='pending' and c['stage']!='pending': continue
            if view=='followups' and (not c['follow_up'] or c['stage'] in ('customer','discarded')): continue
            if view=='burned' and not c['blocked']: continue
            result.append(c)
        return sorted(result,key=lambda c:normalized(c['name'].replace('ñ','nzz').replace('Ñ','Nzz')))

    @router.get('/crm/contacts')
    def contacts(page:int=Query(default=1,ge=1),page_size:int=Query(default=50,ge=1,le=50),q:str='',status:str='all',stage:str='',country:str='',role:str='',min_score:int=0,size_min:int|None=None,size_max:int|None=None,channel:str='',owner:str='',letter:str='',view:str='all',reachability:str='all'):
        if status not in ('all','qualified','review','excluded') or stage and stage not in STAGES or channel and channel not in CHANNELS or view not in ('all','pending','followups','burned'): raise HTTPException(422,'Filtro no válido.')
        if reachability not in ('all','reachable','missing') or not 0<=min_score<=100: raise HTTPException(422,'Filtro no válido.')
        rows=filtered(q,status,stage,country,role,min_score,size_min,size_max,channel,owner,letter,view,reachability)
        start=(page-1)*page_size
        return {'items':rows[start:start+page_size],'total':len(rows),'page':page,'page_size':page_size}

    @router.get('/crm/contacts/export')
    def export(q:str='',status:str='all',stage:str='',country:str='',role:str='',min_score:int=0,size_min:int|None=None,size_max:int|None=None,channel:str='',owner:str='',letter:str='',view:str='all',reachability:str='all'):
        return Response(crm.contact_csv(filtered(q,status,stage,country,role,min_score,size_min,size_max,channel,owner,letter,view,reachability)),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="agenda-equity-scout.csv"'})

    @router.patch('/crm/contacts/{cid}')
    def metadata(cid:int,body:CRMContactInput):
        found(cid); changes={'owner':body.owner,'email':body.email,'email_status':'manual' if body.email else ''}
        if body.phone:
            previous=crm.meta(cid).get('phones',[])
            if previous and previous[0]['number']==body.phone: changes['phones']=previous
            else: changes['phones']=list({p['number']:p for p in [{'number':body.phone,'type':'manual','status':'manual','source':'Revisión manual','observed_at':now()}]+previous[1:]}.values())
        else: changes['phones']=[]
        crm.set_meta(cid,**changes); return db.contact(cid)

    @router.get('/crm/contacts/{cid}/interactions')
    def history(cid:int): found(cid); return crm.history(cid)
    @router.post('/crm/contacts/{cid}/interactions',status_code=201)
    def interaction(cid:int,body:InteractionInput):
        found(cid)
        try: return crm.interaction(cid,body)
        except ValueError as e: raise HTTPException(422,str(e)) from None
    @router.patch('/crm/contacts/{cid}/interactions/{event_uuid}')
    def correction(cid:int,event_uuid:str,body:InteractionInput):
        found(cid)
        try: return crm.interaction(cid,body,event_uuid)
        except LookupError as e: raise HTTPException(404,str(e)) from None
        except ValueError as e: raise HTTPException(422,str(e)) from None

    @router.get('/scripts')
    def scripts(): return crm.scripts()
    @router.post('/scripts',status_code=201)
    def script_create(body:ScriptInput): return crm.save_script(body)
    @router.patch('/scripts/{script_uuid}')
    def script_edit(script_uuid:str,body:ScriptInput):
        try: return crm.save_script(body,script_uuid)
        except LookupError as e: raise HTTPException(404,str(e)) from None
    @router.get('/scripts-statistics')
    def script_stats(): return crm.script_stats()
    @router.get('/dashboard')
    def dashboard(days:int=Query(default=30,ge=0,le=365)): return crm.dashboard(days)

    @router.get('/shared/status')
    def shared_status(): return {'directory':str(crm.directory),'error':crm.error,'conflicts':crm.conflicts(),'actor':crm.setting('actor','Marco')}
    @router.post('/shared/export')
    def shared_export(): return crm.export_shared()
    @router.post('/shared/import')
    def shared_import(): guard(); result=crm.import_shared(); crm.export_shared(); return result
    @router.post('/shared/conflicts/{conflict_uuid}/resolve')
    def resolve(conflict_uuid:str,body:ResolveInput):
        guard()
        try: return crm.resolve(conflict_uuid,body.choice)
        except (ValueError,LookupError) as e: raise HTTPException(422,str(e)) from None
    @router.post('/settings/actor')
    def actor(body:dict):
        name=str(body.get('actor','')).strip()
        if not 1<=len(name)<=100: raise HTTPException(422,'Indica un nombre de responsable.')
        crm.set_setting('actor',name); return {'actor':name}

    @router.get('/search-history')
    def search_history():
        with db.connect() as con: ids=[r[0] for r in con.execute('SELECT id FROM runs ORDER BY id DESC LIMIT 30')]
        return [db.run(rid) for rid in ids]

    @router.get('/searches/{rid}/next-batch')
    def next_batch(rid:int):
        from .batches import prepare_next_batch
        try: return prepare_next_batch(db,rid)
        except LookupError as e: raise HTTPException(404,str(e)) from None

    @router.post('/crm/contacts/{cid}/rescan',status_code=202)
    async def rescan(cid:int,body:dict|None=None):
        c=found(cid); mode=(body or {}).get('provider','web')
        if mode=='apollo': return begin('enrich',ApolloEnrichInput(contact_ids=[cid],phone=bool((body or {}).get('phone')),force_contact_id=cid))
        if not settings.api_key: raise HTTPException(400,'Configura Tavily antes de volver a buscar.')
        queries=[{'text':'site:linkedin.com/in/ "'+c['company']+'" "'+c['name']+'" '+c.get('role',''),'phase':'people'}]
        if c['domain']: queries.append({'text':'site:'+c['domain']+' "'+c['name']+'" team equipo','phase':'people'})
        try: rid=runner.start(c['name'],queries,{'force_contact_id':cid})
        except RuntimeError: raise HTTPException(409,'Ya hay una búsqueda en curso.') from None
        return db.run(rid)

    @router.get('/settings/apollo')
    def apollo_settings(): return {**crm.setting('apollo',{'free_budget':0,'free_account':False}),'configured':bool(settings.apollo_key),'pending':len(crm.setting('apollo_pending',[])),'access':provider.access_status(),'saved_access':provider.access_status('saved_contacts')}
    @router.post('/settings/apollo')
    async def apollo_settings_save(body:ApolloSettingsInput):
        # Settings changes are atomic on the event loop; web discovery uses a separate key.
        latest=db.latest_run()
        if latest and latest['status'] in ('queued','running','stopping') and crm.run_metadata(latest['id']).get('provider')=='apollo':
            raise HTTPException(409,'Hay una operación de Apollo en curso. Detén Apollo antes de cambiar su clave o presupuesto.')
        if body.api_key:
            key=body.api_key.get_secret_value().strip()
            if not 5<=len(key)<=512 or any(c.isspace() for c in key): raise HTTPException(422,'Clave de Apollo no válida.')
            set_key(settings.env_path,'APOLLO_API_KEY',key,quote_mode='always'); settings.apollo_key=key
        crm.set_setting('apollo',{'free_budget':body.free_budget,'free_account':body.free_account}); return apollo_settings()
    @router.post('/apollo/connection-check')
    async def apollo_connection_check(source:str='people'):
        if source not in ('people','saved_contacts'): raise HTTPException(422,'Origen de Apollo no válido.')
        await provider.check_access(source)
        return apollo_settings()
    @router.get('/apollo/balance')
    async def balance():
        try: return await provider.balance()
        except ProviderError as e: raise HTTPException(400,str(e)) from None
    @router.post('/apollo/searches',status_code=202)
    async def apollo_search(body:ApolloSearchInput):
        if not body.continuous: return begin('discover',body)
        try: return await scanning.start_apollo(body)
        except ValueError as e: raise HTTPException(400,str(e)) from None
        except RuntimeError as e: raise HTTPException(409,str(e)) from None

    @router.post('/public/searches',status_code=202)
    async def public_search(body:PublicSearchInput):
        try: return await scanning.start_public(body)
        except RuntimeError as e: raise HTTPException(409,str(e)) from None

    @router.get('/scanning')
    def scanning_status(): return scanning.snapshot()
    @router.post('/scanning/{source}/resume')
    async def scanning_resume(source:str):
        if source not in ('web','public','apollo'): raise HTTPException(422,'Escaneo no válido.')
        try: return await scanning.resume(source)
        except ValueError as e: raise HTTPException(400,str(e)) from None
    @router.post('/scanning/{source}/stop')
    async def scanning_stop(source:str):
        if source not in ('web','public','apollo','all'): raise HTTPException(422,'Escaneo no válido.')
        return scanning.stop(None if source=='all' else source)

    @router.post('/apollo/enrich',status_code=202)
    async def apollo_enrich(body:ApolloEnrichInput):
        if body.force_contact_id and body.contact_ids!=[body.force_contact_id]: raise HTTPException(422,'La actualización explícita admite un solo contacto.')
        for cid in body.contact_ids: found(cid)
        return begin('enrich',body)
    @router.post('/apollo/candidates/accept',status_code=202)
    async def accept(body:CandidateAcceptInput):
        source=crm.run_metadata(body.run_id)
        if not source or source.get('mode')!='discover': raise HTTPException(404,'Lista de candidatos no encontrada.')
        return begin('accept',body)
    @router.post('/apollo/pending/resume',status_code=202)
    async def pending_resume(): return begin('poll',{})

    @router.post('/imports/csv/preview')
    def preview(body:CSVPreviewInput):
        try:
            data=csv_preview(body.text); data.pop('all_rows'); return data
        except ValueError as e: raise HTTPException(422,str(e)) from None
    @router.post('/imports/csv')
    def import_csv(body:CSVImportInput):
        guard()
        try: rows=csv_preview(body.text)['all_rows']
        except ValueError as e: raise HTTPException(422,str(e)) from None
        count={'new':0,'duplicates':0,'omitted':0,'errors':[]}
        for index,row in enumerate(rows):
            try:
                v=lambda key: row.get(body.mapping.get(key,''),'').strip()
                name=v('name') or (v('first_name')+' '+v('last_name')).strip(); company=v('company')
                if not name or not company: raise ValueError('Faltan nombre o gestora.')
                link=linkedin_url(v('linkedin_url'))
                if v('linkedin_url') and not link: raise ValueError('LinkedIn no válido.')
                domain=v('domain').removeprefix('https://').removeprefix('http://').split('/')[0].removeprefix('www.')
                role=v('role'); country=COUNTRY_NAMES.get(v('country'),v('country')); employees=int(v('employees')) if v('employees').isdigit() else None
                firm={'name':company,'domain':domain,'country':country,'employees_min':employees,'employees_max':employees,'equity':None,'analysis':None,
                    'evidence':[evidence('company',company,'','Importación CSV: '+company),evidence('country',country,'','Importación CSV: '+country)]}
                if employees is not None: firm['evidence'].append(evidence('employees',[employees,employees],'','Importación CSV: '+str(employees)))
                fid=db.upsert_firm(firm); person={'name':name,'role':role,'linkedin_url':link,'photo_url':v('photo_url') if safe_url(v('photo_url')) else None,
                    'evidence':[evidence('name',name,'','Importación CSV: '+name),evidence('role',role,'','Importación CSV: '+role)],'issues':[]}
                known=crm.find_person(person,fid)
                if known and known['blocked']: count['omitted']+=1; continue
                cid,fresh=db.upsert_contact(person,fid); meta=crm.meta(cid); changes={}
                email=v('email')
                if email and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): changes.update(email=email,email_status='imported_unverified')
                if v('phone'): changes['phones']=list({p['number']:p for p in meta.get('phones',[])+[{'number':v('phone'),'type':'imported','status':'imported_unverified','source':'CSV','observed_at':now()}]}.values())
                crm.set_meta(cid,**changes); crm.observe(cid, export=False); count['new' if fresh else 'duplicates']+=1
            except (ValueError,KeyError) as e:
                if len(count['errors'])<50: count['errors'].append('Fila '+str(index+2)+': '+str(e))
        crm.export_shared(); return count

    @router.get('/settings/ollama')
    async def ollama_settings(): return await ollama.health()
    @router.post('/settings/ollama')
    async def ollama_save(body:OllamaInput):
        guard(); crm.set_setting('ollama',body.model_dump()); return await ollama.health()

    app.include_router(router)
    return crm
