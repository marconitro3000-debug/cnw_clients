import csv
import hashlib
import io
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from .domain import identity, linkedin_url, now, normalized

STAGES = ('pending','contacted','no_response','replied','interested','demo','customer','discarded')
CHANNELS = ('call','linkedin','email','note')

def uid(): return str(uuid.uuid4())
def dump(value): return json.dumps(value, ensure_ascii=False, sort_keys=True)
def digest(value): return hashlib.sha256(dump(value).encode()).hexdigest()
def cell(value):
    text = '' if value is None else str(value)
    return "'" + text if text.lstrip().startswith(('=','+','-','@')) else text

def csv_text(headers, rows):
    out = io.StringIO(newline=''); writer = csv.writer(out, delimiter=';')
    writer.writerow(headers)
    for row in rows: writer.writerow([cell(v) for v in row])
    return '\ufeff' + out.getvalue()

class CRM:
    def __init__(self, db, directory):
        self.db, self.directory = db, Path(directory)
        self.lock = threading.RLock()
        self.error = ''
        self.write_cache = {}
        with db.connect() as con:
            for table in ('firms','contacts','runs'):
                if 'uuid' not in [r['name'] for r in con.execute('PRAGMA table_info('+table+')')]:
                    con.execute('ALTER TABLE '+table+' ADD COLUMN uuid TEXT')
                con.execute('CREATE UNIQUE INDEX IF NOT EXISTS '+table+'_uuid ON '+table+'(uuid)')
            con.executescript('''
            CREATE TABLE IF NOT EXISTS contact_crm (contact_id INTEGER PRIMARY KEY REFERENCES contacts(id), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS interactions (uuid TEXT PRIMARY KEY, contact_uuid TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scripts (uuid TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations (contact_uuid TEXT NOT NULL, run_uuid TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(contact_uuid,run_uuid));
            CREATE TABLE IF NOT EXISTS run_meta (run_id INTEGER PRIMARY KEY REFERENCES runs(id), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS local_settings (key TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS shared_aliases (uuid TEXT PRIMARY KEY, canonical TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS shared_conflicts (uuid TEXT PRIMARY KEY, kind TEXT NOT NULL, entity_uuid TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS apollo_reservations (uuid TEXT PRIMARY KEY, account TEXT NOT NULL, cycle TEXT NOT NULL, amount INTEGER NOT NULL, created_at TEXT NOT NULL);
            ''')
        db.crm = self
        self.identifiers()

    def identifiers(self):
        with self.db.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            for table in ('firms','contacts','runs'):
                for row in con.execute('SELECT id FROM '+table+' WHERE uuid IS NULL').fetchall():
                    con.execute('UPDATE '+table+' SET uuid=? WHERE id=?',(uid(),row['id']))

    def setting(self, key, default=None):
        with self.db.connect() as con: row=con.execute('SELECT data FROM local_settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.db.connect() as con: con.execute('INSERT OR REPLACE INTO local_settings VALUES(?,?)',(key,dump(value)))

    def meta(self, contact_id):
        with self.db.connect() as con: row=con.execute('SELECT data FROM contact_crm WHERE contact_id=?',(contact_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def set_meta(self, contact_id, **values):
        with self.db.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row=con.execute('SELECT data FROM contact_crm WHERE contact_id=?',(contact_id,)).fetchone()
            data={**(json.loads(row[0]) if row else {}),**values}
            con.execute('INSERT OR REPLACE INTO contact_crm VALUES(?,?)',(contact_id,dump(data)))

    def save_public_channels(self,contact_id,person):
        m=self.meta(contact_id);updates={}
        email=person.get('email')
        if email and not m.get('email'): updates.update(email=email,email_status='public_unverified')
        elif email and m.get('email') and m['email'].casefold()!=email.casefold():
            updates['email_candidates']=list(dict.fromkeys(m.get('email_candidates',[])+[email]))
        phones=m.get('phones',[])
        def phone_key(value): return ''.join(c for c in value if c.isdigit())
        known={phone_key(p['number']) for p in phones}
        new=[p for p in person.get('phones',[]) if phone_key(p['number']) not in known]
        if new: updates['phones']=phones+new
        channels=[e for e in person.get('evidence',[]) if e['field'] in ('email','phone','linkedin_url','photo_url')]
        if channels:
            sources=m.get('contact_sources',[])
            for item in channels:
                if item not in sources: sources.append(item)
            updates['contact_sources']=sources
        if updates: self.set_meta(contact_id,**updates)

    def all_events(self, include_corrected=False, contact_uuids=None):
        with self.db.connect() as con:
            if contact_uuids is not None:
                if not contact_uuids: return []
                query='SELECT data FROM interactions WHERE contact_uuid IN ('+','.join('?' for _ in contact_uuids)+')'
                records=[json.loads(r[0]) for r in con.execute(query,contact_uuids)]
            else: records=[json.loads(r[0]) for r in con.execute('SELECT data FROM interactions')]
        records.sort(key=lambda e:(e['occurred_at'],e['created_at'],e['uuid']))
        superseded={e.get('supersedes') for e in records}
        return records if include_corrected else [e for e in records if e['uuid'] not in superseded]

    def decorate(self, contacts):
        self.identifiers()
        with self.db.connect() as con:
            keys=[c['id'] for c in contacts]
            limited=0<len(keys)<=50
            where=' WHERE id IN ('+','.join('?' for _ in keys)+')' if limited else ''
            ids={r['id']:r['uuid'] for r in con.execute('SELECT id,uuid FROM contacts'+where,keys if limited else [])}
            where_meta=where.replace('WHERE id','WHERE contact_id')
            meta={r[0]:json.loads(r[1]) for r in con.execute('SELECT contact_id,data FROM contact_crm'+where_meta,keys if limited else [])}
        groups={}
        for e in self.all_events(contact_uuids=list(ids.values()) if limited else None): groups.setdefault(e['contact_uuid'],[]).append(e)
        for c in contacts:
            m=meta.get(c['id'],{}); events=groups.get(ids[c['id']],[])
            outreach=[e for e in events if e['channel']!='note']
            stage=next((e['result'] for e in reversed(events) if e.get('result')), 'pending')
            follow=next((None if e.get('clear_follow_up') else e.get('follow_up') for e in reversed(events) if e.get('follow_up') or e.get('clear_follow_up')),None)
            c.update(uuid=ids[c['id']],stage=stage,blocked=bool(outreach) or stage=='discarded',
                owner=m.get('owner',''),email=m.get('email'),email_status=m.get('email_status',''),
                phones=m.get('phones',[]),apollo_id=m.get('apollo_id'),apollo_contact_id=m.get('apollo_contact_id'),data_sources=m.get('data_sources',[]),
                last_interaction=events[-1]['occurred_at'] if events else None,follow_up=follow,
                interaction_count=len(events),qualified_at=m.get('qualified_at'),
                notes=' | '.join(e['comment'] for e in events if e.get('comment')),contact_sources=m.get('contact_sources',[]),email_candidates=m.get('email_candidates',[]))
            c['reachable']=bool(c.get('linkedin_url') or c.get('email') or c.get('phones'))
            c['photo_origin']='LinkedIn' if c.get('photo_url') and (urlparse(c['photo_url']).hostname or '').lower().removeprefix('www.').endswith('.licdn.com') else 'Fuente pública' if c.get('photo_url') else ''
        return contacts

    def find_person(self, person, firm_id=None):
        url=linkedin_url(person.get('linkedin_url'))
        with self.db.connect() as con:
            row=con.execute('SELECT id FROM contacts WHERE linkedin_url=?',(url,)).fetchone() if url else None
            if not row and person.get('apollo_id'):
                row=con.execute("SELECT contact_id id FROM contact_crm WHERE json_extract(data,'$.apollo_id')=?",(person['apollo_id'],)).fetchone()
            if not row:
                if firm_id:
                    matches=con.execute('SELECT c.id,c.linkedin_url FROM contacts c WHERE c.name_key=? AND c.firm_id=?',(identity(person.get('name','')),firm_id)).fetchall()
                else:
                    matches=con.execute('SELECT c.id,c.linkedin_url FROM contacts c JOIN firms f ON f.id=c.firm_id WHERE c.name_key=? AND f.name_key=?',(identity(person.get('name','')),identity(person.get('company','')))).fetchall()
                if len(matches)==1 and (not url or not matches[0]['linkedin_url']): row=matches[0]
        return self.db.contact(row['id']) if row else None

    def observe(self, contact_id, run_id=None, fresh=False, export=True):
        c=self.db.contact(contact_id)
        if c['status']=='qualified' and not c.get('qualified_at'): self.set_meta(contact_id,qualified_at=now())
        if run_id:
            run=self.db.run(run_id)
            with self.db.connect() as con:
                con.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?)',(c['uuid'],run['uuid'],dump({'contact_uuid':c['uuid'],'run_uuid':run['uuid'],'new':fresh,'observed_at':now()})))
        if export: self.export_shared()

    def interaction(self, contact_id, body, supersedes=None):
        c=self.db.contact(contact_id)
        if not c: raise LookupError('Contacto no encontrado.')
        if supersedes:
            previous=next((e for e in self.all_events() if e['uuid']==supersedes and e['contact_uuid']==c['uuid']),None)
            if not previous: raise LookupError('La interacción ya fue corregida o no existe.')
        data=body.model_dump() if hasattr(body,'model_dump') else dict(body)
        if data.get('script_uuid'):
            script=self.script(data['script_uuid'])
            if not script: raise ValueError('Guion no encontrado.')
            version=data.get('script_version') or script['versions'][-1]['version']
            if not any(v['version']==version for v in script['versions']): raise ValueError('Versión de guion no encontrada.')
            data['script_version']=version
        data.update(uuid=uid(),contact_uuid=c['uuid'],created_at=now(),supersedes=supersedes)
        data['occurred_at']=data.get('occurred_at') or now()
        if data['channel']=='note' and not data.get('result'): data['result']=None
        elif not data.get('result'): data['result']='contacted'
        with self.db.connect() as con: con.execute('INSERT INTO interactions VALUES(?,?,?)',(data['uuid'],c['uuid'],dump(data)))
        if data.get('author'): self.set_meta(contact_id,owner=data['author'])
        self.export_shared()
        return data

    def history(self, contact_id):
        c=self.db.contact(contact_id)
        if not c: raise LookupError('Contacto no encontrado.')
        return [e for e in self.all_events(True) if e['contact_uuid']==c['uuid']]

    def script(self, script_uuid): return next((s for s in self.scripts() if s['uuid']==script_uuid),None)
    def scripts(self):
        with self.db.connect() as con: return [json.loads(r[0]) for r in con.execute('SELECT data FROM scripts ORDER BY uuid')]
    def save_script(self, body, script_uuid=None):
        old=self.script(script_uuid) if script_uuid else None
        if script_uuid and not old: raise LookupError('Guion no encontrado.')
        data=body.model_dump() if hasattr(body,'model_dump') else dict(body)
        if old:
            versions=list(old['versions'])
            if any(versions[-1][k]!=data[k] for k in ('title','channel','text')):
                versions.append({k:data[k] for k in ('title','channel','text')} | {'version':len(versions)+1,'created_at':now()})
            record={**old,**data,'versions':versions,'updated_at':now()}
        else:
            record={**data,'uuid':uid(),'versions':[{k:data[k] for k in ('title','channel','text')} | {'version':1,'created_at':now()}],'created_at':now(),'updated_at':now()}
        with self.db.connect() as con: con.execute('INSERT OR REPLACE INTO scripts VALUES(?,?)',(record['uuid'],dump(record)))
        self.export_shared(); return record

    def script_stats(self):
        events=self.all_events(); groups={}
        for e in events: groups.setdefault(e['contact_uuid'],[]).append(e)
        rows={}
        for s in self.scripts():
            for v in s['versions']:
                key=(s['uuid'],v['version'],v['channel'])
                rows[key]={'script_uuid':s['uuid'],'version':v['version'],'channel':v['channel'],'title':v['title'],
                    **{k:set() for k in ('approached','responses','interested','rejected','demos')}}
        for person, timeline in groups.items():
            last=None; first_demo=False
            for e in timeline:
                if e['channel']!='note' and e.get('script_uuid'):
                    s=self.script(e['script_uuid']); version=next((v for v in (s or {}).get('versions',[]) if v['version']==e.get('script_version')),None)
                    if version:
                        last=(s['uuid'],version['version'],e['channel'])
                        if last not in rows: rows[last]={**rows[(s['uuid'],version['version'],version['channel'])],'channel':e['channel'],**{k:set() for k in ('approached','responses','interested','rejected','demos')}}
                        rows[last]['approached'].add(person)
                if not last: continue
                result=e.get('result'); target=rows[last]
                if result in ('replied','interested','demo','customer','discarded'): target['responses'].add(person)
                if result in ('interested','demo','customer'): target['interested'].add(person)
                if result=='discarded': target['rejected'].add(person)
                if result=='demo' and not first_demo:
                    target['demos'].add(person); first_demo=True
        output=[]
        for row in rows.values():
            counts={k:len(v) if isinstance(v,set) else v for k,v in row.items()}
            counts['conversion']=round(100*counts['demos']/counts['approached'],1) if counts['approached'] else 0
            output.append(counts)
        return output

    def dashboard(self, days=30):
        contacts=self.db.contacts(); events=self.all_events()
        times={k:{} for k in ('identified','qualified','contacted','demos')}
        for c in contacts:
            times['identified'][c['uuid']]=c['created_at']
            if c.get('qualified_at'): times['qualified'][c['uuid']]=c['qualified_at']
            elif c['status']=='qualified': times['qualified'][c['uuid']]=c['created_at']
        for e in events:
            if e['channel']!='note': times['contacted'].setdefault(e['contact_uuid'],e['occurred_at'])
            if e.get('result')=='demo': times['demos'].setdefault(e['contact_uuid'],e['occurred_at'])
        today=datetime.now(timezone.utc).date()
        earliest=min([value[:10] for data in times.values() for value in data.values()]+[today.isoformat()])
        start=today-timedelta(days=days-1) if days else datetime.fromisoformat(earliest).date()
        rows=[]; day=start
        while day<=today:
            date=day.isoformat(); rows.append({'date':date,**{k:sum(v[:10]==date for v in data.values()) for k,data in times.items()}}); day+=timedelta(days=1)
        return {'series':rows,'totals':{k:len(data) for k,data in times.items()},'agenda':{
            'all':len(contacts),'pending':sum(c['stage']=='pending' for c in contacts),
            'followups':sum(bool(c['follow_up']) and c['stage'] not in ('customer','discarded') for c in contacts),
            'burned':sum(c['blocked'] for c in contacts)}}

    def run_metadata(self, run_id):
        with self.db.connect() as con: row=con.execute('SELECT data FROM run_meta WHERE run_id=?',(run_id,)).fetchone()
        return json.loads(row[0]) if row else {}
    def set_run_metadata(self, run_id, **values):
        data={**self.run_metadata(run_id),**values}
        with self.db.connect() as con: con.execute('INSERT OR REPLACE INTO run_meta VALUES(?,?)',(run_id,dump(data)))
    def run_summary(self, run):
        with self.db.connect() as con: obs=[json.loads(r[0]) for r in con.execute('SELECT data FROM observations WHERE run_uuid=?',(run['uuid'],))]
        observed_ids={o['contact_uuid'] for o in obs}
        return {**self.run_metadata(run['id']),'new_contacts':sum(e['new'] for e in obs),'duplicates':sum(not e['new'] for e in obs),
                'review_contacts':sum(c['status']=='review' for c in self.db.contacts(contact_uuids=observed_ids))}

    def records(self):
        self.identifiers()
        with self.db.connect() as con:
            firms=[dict(r) for r in con.execute('SELECT * FROM firms')]
            contacts=[dict(r) for r in con.execute('SELECT * FROM contacts')]
            runs=[dict(r) for r in con.execute('SELECT * FROM runs')]
            observations=[json.loads(r[0]) for r in con.execute('SELECT data FROM observations')]
        result=[]; firm_ids={f['id']:f['uuid'] for f in firms}
        for f in firms: result.append(('firms',f['uuid'],{'uuid':f['uuid'],'data':json.loads(f['data']),'updated_at':f['updated_at']}))
        for c in contacts: result.append(('contacts',c['uuid'],{'uuid':c['uuid'],'firm_uuid':firm_ids[c['firm_id']], 'data':json.loads(c['data']), 'crm':self.meta(c['id']), 'created_at':c['created_at'],'updated_at':c['updated_at']}))
        for s in self.scripts(): result.append(('scripts',s['uuid'],s))
        for e in self.all_events(True): result.append(('interactions',e['uuid'],e))
        for r in runs:
            run=self.db.run(r['id'])
            summary={k:v for k,v in self.run_summary(run).items() if k in ('provider','mode','use_ollama','new_contacts','duplicates','review_contacts','omitted','reserved_credits','phones_pending')}
            result.append(('runs',r['uuid'],{k:run[k] for k in ('uuid','keywords','status','started_at','finished_at','plan','completed_queries','total_queries','credits','contacts_found','errors','queries')} | {'summary':summary}))
        for o in observations: result.append(('observations',o['contact_uuid']+'_'+o['run_uuid'],o))
        return result

    def export_shared(self):
        with self.lock:
            try:
                pending={(c['kind'],c['entity_uuid']) for c in self.conflicts()}
                for kind, key, record in self.records():
                    if (kind,key) in pending: continue
                    target=self.directory/kind/(key+'.json'); target.parent.mkdir(parents=True,exist_ok=True)
                    self.atomic(target,dump({'schema_version':1,'record':record})+'\n')
                contacts=self.db.contacts()
                self.atomic(self.directory/'contactos.csv',self.contact_csv(contacts))
                events=self.all_events(True); names={c['uuid']:c['name'] for c in contacts}
                self.atomic(self.directory/'interacciones.csv',csv_text(['ID','Contacto','Fecha','Autor','Canal','Resultado','Comentario','Guion','Versión','Seguimiento','Corrige'],
                    ([e['uuid'],names.get(e['contact_uuid'],e['contact_uuid']),e['occurred_at'],e['author'],e['channel'],e.get('result'),e['comment'],e.get('script_uuid'),e.get('script_version'),e.get('follow_up'),e.get('supersedes')] for e in events)))
                self.error=''; return {'ok':True,'contacts':len(contacts),'interactions':len(events),'conflicts':len(pending)}
            except (OSError,ValueError) as error:
                self.error='No se pudo guardar shared-data: '+str(error)
                return {'ok':False,'error':self.error}

    def atomic(self, path, text):
        checksum=hashlib.sha256(text.encode()).hexdigest()
        if self.write_cache.get(str(path))==checksum and path.exists(): return
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix(path.suffix+'.tmp'); temporary.write_text(text,encoding='utf-8'); temporary.replace(path)
        self.write_cache[str(path)]=checksum

    def contact_csv(self, contacts):
        return csv_text(['ID','Nombre','Cargo','Gestora','País','Puntuación','Calificación','Etapa','Responsable','LinkedIn','Correo','Verificación correo','Teléfonos','Foto','Última interacción','Seguimiento','Comentarios'],
            ([c['uuid'],c['name'],c.get('role'),c['company'],c.get('country'),c['score'],c['status'],c['stage'],c['owner'],c.get('linkedin_url'),c['email'],c['email_status'],' | '.join(p.get('number','') for p in c['phones']),c.get('photo_url'),c['last_interaction'],c['follow_up'],c['notes']] for c in contacts))

    def conflicts(self):
        with self.db.connect() as con: return [dict(r) | {'data':json.loads(r['data'])} for r in con.execute('SELECT * FROM shared_conflicts')]
    def conflict(self, kind, key, incoming, local=None):
        conflict_id=str(uuid.uuid5(uuid.NAMESPACE_URL,kind+key+digest(incoming)))
        with self.db.connect() as con: con.execute('INSERT OR IGNORE INTO shared_conflicts VALUES(?,?,?,?)',(conflict_id,kind,key,dump({'incoming':incoming,'local':local})))
    def canonical(self, key):
        with self.db.connect() as con: row=con.execute('SELECT canonical FROM shared_aliases WHERE uuid=?',(key,)).fetchone()
        return row[0] if row else key

    def import_shared(self):
        with self.lock:
            self.write_cache.clear()
            imported=0
            for kind in ('firms','contacts','scripts','interactions','runs','observations'):
                for path in sorted((self.directory/kind).glob('*.json')):
                    try:
                        payload=json.loads(path.read_text(encoding='utf-8'))
                        if payload.get('schema_version')!=1: raise ValueError('Versión de archivo no compatible.')
                        record=payload['record']; key=record.get('uuid') or path.stem
                        # Reject traversal and malformed shared identifiers before using file names.
                        if kind!='observations': uuid.UUID(key)
                        self.import_record(kind,key,record); imported+=1
                    except (ValueError,KeyError,TypeError,OSError) as error:
                        self.conflict('invalid',str(uuid.uuid5(uuid.NAMESPACE_URL,str(path))),{'file':str(path.relative_to(self.directory)),'error':str(error)})
            return {'imported':imported,'conflicts':len(self.conflicts())}

    def import_record(self, kind, key, r, force=False):
        key=self.canonical(key)
        if kind=='firms':
            with self.db.connect() as con: row=con.execute('SELECT * FROM firms WHERE uuid=?',(key,)).fetchone()
            if row:
                local=json.loads(row['data'])
                if local!=r['data'] and not force:
                    # Extra source observations are additive, not conflicting profile edits.
                    if {k:v for k,v in local.items() if k!='evidence'} == {k:v for k,v in r['data'].items() if k!='evidence'}:
                        from .db import unique
                        merged={**local,'evidence':unique(local.get('evidence',[])+r['data'].get('evidence',[]))}
                        with self.db.connect() as con:
                            con.execute('UPDATE firms SET data=?,updated_at=? WHERE id=?',(dump(merged),max(row['updated_at'],r.get('updated_at',row['updated_at'])),row['id']))
                        return
                    self.conflict(kind,key,r,{'data':local}); return
                if force:
                    with self.db.connect() as con: con.execute('UPDATE firms SET name=?,name_key=?,domain=?,data=?,updated_at=? WHERE id=?',(r['data']['name'],identity(r['data']['name']),r['data'].get('domain',''),dump(r['data']),now(),row['id']))
                return
            with self.db.connect() as con: before={row['id'] for row in con.execute('SELECT id FROM firms')}
            fid=self.db.upsert_firm(r['data']); self.identifiers()
            if fid not in before:
                with self.db.connect() as con: con.execute('UPDATE firms SET uuid=?,updated_at=? WHERE id=?',(r['uuid'],r['updated_at'],fid))
            existing=self.db.firm(fid)
            with self.db.connect() as con:
                con.execute('INSERT OR REPLACE INTO shared_aliases VALUES(?,?)',(r['uuid'],existing['uuid']))
            return
        if kind=='contacts':
            from .models import ContactInput
            ContactInput(name=r['data']['name'],company='Validación compartida',role=r['data'].get('role',''),linkedin_url=r['data'].get('linkedin_url'),photo_url=r['data'].get('photo_url'))
            for entry in r['data'].get('evidence',[]):
                from .domain import safe_url
                if entry.get('url') and not safe_url(entry['url']): raise ValueError('Fuente compartida no válida.')
            firm_key=self.canonical(r['firm_uuid'])
            with self.db.connect() as con:
                row=con.execute('SELECT * FROM contacts WHERE uuid=?',(key,)).fetchone()
                firm=con.execute('SELECT id FROM firms WHERE uuid=?',(firm_key,)).fetchone()
            if not firm: raise ValueError('Gestora compartida no encontrada.')
            if row:
                if (json.loads(row['data'])!=r['data'] or self.meta(row['id'])!=r.get('crm',{})) and not force:
                    self.conflict(kind,key,r,{'data':json.loads(row['data']),'crm':self.meta(row['id'])}); return
                if force:
                    with self.db.connect() as con: con.execute('UPDATE contacts SET data=?,name_key=?,linkedin_url=?,updated_at=? WHERE id=?',(dump(r['data']),identity(r['data']['name']),linkedin_url(r['data'].get('linkedin_url')),now(),row['id']))
                    self.set_meta(row['id'],**r.get('crm',{}))
                return
            duplicate=self.find_person(r['data'],firm['id'])
            if duplicate:
                with self.db.connect() as con: con.execute('INSERT OR REPLACE INTO shared_aliases VALUES(?,?)',(r['uuid'],duplicate['uuid']))
                self.conflict(kind,duplicate['uuid'],r,{'data':duplicate}); return
            cid,_=self.db.upsert_contact(r['data'],firm['id'])
            with self.db.connect() as con: con.execute('UPDATE contacts SET uuid=?,created_at=?,updated_at=? WHERE id=?',(r['uuid'],r['created_at'],r['updated_at'],cid))
            self.set_meta(cid,**r.get('crm',{})); return
        if kind=='scripts':
            old=self.script(key)
            if old and old!=r and not force: self.conflict(kind,key,r,old); return
            with self.db.connect() as con: con.execute('INSERT OR REPLACE INTO scripts VALUES(?,?)',(key,dump(r)))
        elif kind=='interactions':
            from .crm_models import InteractionInput
            InteractionInput(**r)
            r={**r,'contact_uuid':self.canonical(r['contact_uuid'])}
            with self.db.connect() as con:
                if not con.execute('SELECT id FROM contacts WHERE uuid=?',(r['contact_uuid'],)).fetchone(): raise ValueError('Contacto compartido no encontrado.')
                old=con.execute('SELECT data FROM interactions WHERE uuid=?',(key,)).fetchone()
                if old and json.loads(old[0])!=r and not force: self.conflict(kind,key,r,json.loads(old[0])); return
                con.execute('INSERT OR REPLACE INTO interactions VALUES(?,?,?)',(key,r['contact_uuid'],dump(r)))
        elif kind=='runs':
            with self.db.connect() as con:
                old=con.execute('SELECT id FROM runs WHERE uuid=?',(key,)).fetchone()
                if old: return
                status='interrupted' if r['status'] in ('queued','running','stopping') else r['status']
                rid=con.execute('INSERT INTO runs(uuid,keywords,plan,status,started_at,finished_at,completed_queries,total_queries,credits,contacts_found,errors) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (key,r['keywords'],dump(r.get('plan',[])),status,r['started_at'],r.get('finished_at'),r.get('completed_queries',0),r.get('total_queries',0),r.get('credits',0),r.get('contacts_found',0),dump(r.get('errors',[])))).lastrowid
                for query in r.get('queries',[]): con.execute('INSERT INTO run_queries(run_id,text,phase,status,cached,error) VALUES(?,?,?,?,?,?)',(rid,query['text'],query['phase'],query['status'],query.get('cached',False),query.get('error','')))
                con.execute('INSERT INTO run_meta VALUES(?,?)',(rid,dump(r.get('summary',{}))))
        elif kind=='observations':
            r={**r,'contact_uuid':self.canonical(r['contact_uuid'])}
            with self.db.connect() as con: con.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?)',(r['contact_uuid'],r['run_uuid'],dump(r)))

    def resolve(self, conflict_uuid, choice):
        conflict=next((c for c in self.conflicts() if c['uuid']==conflict_uuid),None)
        if not conflict: raise LookupError('Conflicto no encontrado.')
        if choice=='incoming' and conflict['kind']=='invalid': raise ValueError('Corrige primero el archivo no válido.')
        if choice=='incoming' and conflict['kind']=='apollo': raise ValueError('Revisa y corrige el contacto desde su ficha antes de cerrar esta coincidencia.')
        if choice=='incoming': self.import_record(conflict['kind'],conflict['entity_uuid'],conflict['data']['incoming'],True)
        with self.db.connect() as con: con.execute('DELETE FROM shared_conflicts WHERE uuid=?',(conflict_uuid,))
        return self.export_shared()
