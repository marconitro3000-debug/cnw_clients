"""Company views and personal client portfolios backed by shared UUID records."""
import json
import uuid
from collections import Counter
from datetime import date
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from .crm import csv_text, dump, uid
from .domain import normalized, now

CLIENT_STAGES = {'saved':'Guardado','researched':'Investigado','viewed':'Perfil revisado',
                 'contacted':'Contactado','evaluating':'En evaluación','customer':'Cliente','archived':'Archivado'}

class PortfolioInput(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    @field_validator('name')
    @classmethod
    def clean_name(cls,value):
        value=value.strip()
        if not value:raise ValueError('Escribe el nombre de tu cartera.')
        return value

class ClientInput(BaseModel):
    stage: str = 'saved'
    notes: str = Field(default='',max_length=10000)
    next_step: str = Field(default='',max_length=1000)
    follow_up: str | None = None
    @field_validator('stage')
    @classmethod
    def valid_stage(cls,value):
        if value not in CLIENT_STAGES:raise ValueError('Estado de cartera no válido.')
        return value
    @field_validator('follow_up')
    @classmethod
    def valid_date(cls,value):
        if value:date.fromisoformat(value)
        return value or None

class SaveClientInput(BaseModel):
    contact_id: int = Field(ge=1)


def records(crm,kind):
    with crm.db.connect() as con:
        return [json.loads(r[0]) for r in con.execute('SELECT data FROM workspace_records WHERE kind=?',(kind,))]


def put(crm,kind,record):
    with crm.db.connect() as con:
        con.execute('INSERT OR REPLACE INTO workspace_records VALUES(?,?,?)',(kind,record['uuid'],dump(record)))


def export_workspace(crm):
    # Portfolio edits do not change contact data; avoid rewriting the entire research archive.
    with crm.lock:
        pending={(r['kind'],r['entity_uuid']) for r in crm.conflicts()}
        for kind in ('portfolios','portfolio_clients'):
            for row in records(crm,kind):
                if (kind,row['uuid']) not in pending:
                    crm.atomic(crm.directory/kind/(row['uuid']+'.json'),dump({'schema_version':1,'record':row})+'\n')


def validate_shared(kind,record):
    uuid.UUID(record['uuid'])
    for field in ('created_at','updated_at'):
        from datetime import datetime
        datetime.fromisoformat(record[field])
    if kind=='portfolios':
        record={**record,**PortfolioInput(**record).model_dump()}
        if not isinstance(record.get('is_default',False),bool):raise ValueError('Cartera predeterminada no válida.')
    else:
        record={**record,**ClientInput(**record).model_dump()}
        for field in ('portfolio_uuid','contact_uuid'):uuid.UUID(record[field])
        if not isinstance(record.get('removed',False),bool):raise ValueError('Estado compartido no válido.')
    return record


def portfolio_list(crm):
    rows=records(crm,'portfolios')
    default=max((r for r in rows if r.get('is_default')),key=lambda r:(r['updated_at'],r['uuid']),default=None)
    default_uuid=default['uuid'] if default else (min(rows,key=lambda r:r['created_at'])['uuid'] if rows else None)
    counts=Counter();seen=set()
    for r in sorted(records(crm,'portfolio_clients'),key=lambda r:r['updated_at'],reverse=True):
        key=(r['portfolio_uuid'],crm.canonical(r['contact_uuid']))
        if key in seen:continue
        seen.add(key)
        if not r.get('removed'):counts[r['portfolio_uuid']]+=1
    return {'items':[{**r,'is_default':r['uuid']==default_uuid,'clients':counts[r['uuid']]} for r in sorted(rows,key=lambda r:normalized(r['name']))],
            'default_uuid':default_uuid,'stages':CLIENT_STAGES}


def company_rows(crm):
    from .segments import firm_segments
    from .signals import list_signals
    contacts=crm.db.contacts()
    groups={}
    for c in contacts:
        if (c.get('quality') or {}).get('status')=='junk':continue
        groups.setdefault(c['firm_id'],[]).append(c)
    signals=list_signals(crm)
    news=Counter(s['firm_id'] for s in signals if s['review']!='rejected')
    recent=Counter(s['firm_id'] for s in signals if s['review']!='rejected' and s['recency'] in ('recent','estimated'))
    with crm.db.connect() as con:firms=[dict(r) for r in con.execute('SELECT id,uuid,name,domain,data FROM firms')]
    eligible={f['id'] for f in firms if f['id'] in groups or news[f['id']]}
    sectors=firm_segments(crm,eligible)
    rows=[]
    for f in firms:
        if f['id'] not in eligible:continue
        data=json.loads(f['data']);people=groups.get(f['id'],[]);sector=sectors[f['id']]
        rows.append({'id':f['id'],'uuid':f['uuid'],'name':f['name'],'domain':f['domain'],'country':data.get('country') or '',
                     'contacts':len(people),'contacted':sum(p['blocked'] for p in people),
                     'best_score':max((p['score'] for p in people),default=0),'news':news[f['id']],'recent_news':recent[f['id']],
                     'segment':sector['segment'],'segment_label':sector['label'],'manual_segment':bool(sector.get('manual'))})
    return sorted(rows,key=lambda f:normalized(f['name']))


def install_workspace(app,crm):
    router=APIRouter(prefix='/api')
    def portfolio(key):
        row=next((p for p in portfolio_list(crm)['items'] if p['uuid']==key),None)
        if not row:raise HTTPException(404,'Cartera no encontrada.')
        return row
    def contact(cid):
        c=crm.db.contact(cid)
        if not c:raise HTTPException(404,'Contacto no encontrado.')
        return c
    def member(key,cid):
        portfolio(key);c=contact(cid)
        existing=next((r for r in records(crm,'portfolio_clients') if r['portfolio_uuid']==key and crm.canonical(r['contact_uuid'])==c['uuid']),None)
        return c,existing
    def members(key):
        portfolio(key)
        by_uuid={c['uuid']:c for c in crm.db.contacts()}
        seen=set();result=[]
        for r in sorted(records(crm,'portfolio_clients'),key=lambda r:r['updated_at'],reverse=True):
            canonical=crm.canonical(r['contact_uuid'])
            if r['portfolio_uuid']!=key or canonical in seen:continue
            seen.add(canonical)
            if r.get('removed') or canonical not in by_uuid:continue
            from .main import compact_contact
            result.append({**r,'contact_uuid':canonical,'contact':compact_contact(by_uuid[canonical])})
        return sorted(result,key=lambda r:normalized(r['contact']['name']))

    @router.get('/companies')
    def companies(q:str='',country:str='',segment:str=''):
        rows=company_rows(crm)
        from .segments import LABELS
        return {'segments':LABELS,'items':[r for r in rows if (not q or normalized(q) in normalized(r['name']+' '+r['domain']))
                        and (not country or r['country']==country) and (not segment or r['segment']==segment)]}
    @router.get('/companies/{key}')
    def company(key:str):
        canonical=crm.canonical(key)
        row=next((f for f in company_rows(crm) if f['uuid']==canonical),None)
        if not row:raise HTTPException(404,'Empresa no encontrada.')
        return row
    @router.get('/portfolios')
    def portfolios():return portfolio_list(crm)
    @router.post('/portfolios',status_code=201)
    def create_portfolio(body:PortfolioInput):
        timestamp=now();row={'uuid':uid(),'name':body.name,'is_default':not bool(records(crm,'portfolios')),'created_at':timestamp,'updated_at':timestamp}
        put(crm,'portfolios',row);export_workspace(crm);return row
    @router.patch('/portfolios/{key}')
    def rename_portfolio(key:str,body:PortfolioInput):
        row=portfolio(key);row.pop('clients',None);row.update(name=body.name,updated_at=now())
        put(crm,'portfolios',row);export_workspace(crm);return row
    @router.post('/portfolios/{key}/default')
    def default_portfolio(key:str):
        portfolio(key)
        with crm.db.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            for row in records(crm,'portfolios'):
                row.update(is_default=row['uuid']==key,updated_at=now())
                con.execute('UPDATE workspace_records SET data=? WHERE kind=? AND uuid=?',(dump(row),'portfolios',row['uuid']))
        export_workspace(crm);return portfolio_list(crm)
    @router.get('/portfolios/{key}/clients')
    def clients(key:str):return {'items':members(key)}
    @router.get('/portfolios/{key}/clients/export')
    def export_clients(key:str):
        p=portfolio(key);rows=members(key)
        return Response(csv_text(['Cartera','Nombre','Empresa','País','Estado','Notas','Siguiente paso','Seguimiento'],
            ([p['name'],r['contact']['name'],r['contact']['company'],r['contact']['country'],CLIENT_STAGES[r['stage']],r['notes'],r['next_step'],r['follow_up']] for r in rows)),
            media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="mis-clientes.csv"'})
    @router.post('/portfolios/{key}/clients',status_code=201)
    def save_client(key:str,body:SaveClientInput):
        c,existing=member(key,body.contact_id)
        if existing and not existing.get('removed'):return existing
        timestamp=now()
        row=existing or {'uuid':str(uuid.uuid5(uuid.NAMESPACE_URL,'kerna:portfolio:'+key+'|'+c['uuid'])),'portfolio_uuid':key,'contact_uuid':c['uuid'],**ClientInput().model_dump(),'created_at':timestamp}
        row.update(removed=False,updated_at=timestamp)
        put(crm,'portfolio_clients',row);export_workspace(crm);return row
    @router.put('/portfolios/{key}/clients/{cid}')
    def edit_client(key:str,cid:int,body:ClientInput):
        _,row=member(key,cid)
        if not row or row.get('removed'):raise HTTPException(404,'Este contacto no está en la cartera.')
        row.update(**body.model_dump(),updated_at=now());put(crm,'portfolio_clients',row);export_workspace(crm);return row
    @router.delete('/portfolios/{key}/clients/{cid}')
    def remove_client(key:str,cid:int):
        _,row=member(key,cid)
        if not row:raise HTTPException(404,'Este contacto no está en la cartera.')
        row.update(removed=True,updated_at=now());put(crm,'portfolio_clients',row);export_workspace(crm);return {'removed':True}
    app.include_router(router)