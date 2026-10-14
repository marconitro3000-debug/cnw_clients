import {createContext,useContext,useEffect,useRef,useState,type ReactNode} from 'react'
import {BookmarkPlus,Check,LoaderCircle,Plus,Star,Trash2,Users,Search} from 'lucide-react'
import {api,type CRMContact,type Contact} from './types'
import {ContactHistory} from './Commercial'
import {LoadingCards,LoadingStatus,useNotify} from './Feedback'

export type Portfolio={uuid:string;name:string;is_default:boolean;clients:number}
type Membership={uuid:string;portfolio_uuid:string;contact_uuid:string;stage:string;notes:string;next_step:string;follow_up:string|null;updated_at:string;contact:CRMContact}
type ClientForm={stage:string;notes:string;next_step:string;follow_up:string}
type PortfolioState={items:Portfolio[];default_uuid:string|null;stages:Record<string,string>}
type Context=PortfolioState&{selected:string;select:(id:string)=>void;reload:()=>Promise<void>;version:number;error:string;loading:boolean}
const PortfolioContext=createContext<Context|null>(null)
const failure=(e:unknown)=>e instanceof Error?e.message:'No se pudo guardar el cambio.'
export function PortfolioProvider({children,revision}:{children:ReactNode;revision:number}){
  const [data,setData]=useState<PortfolioState>({items:[],default_uuid:null,stages:{}}),[selected,setSelected]=useState(''),[version,setVersion]=useState(0),[error,setError]=useState(''),[loading,setLoading]=useState(true)
  const sequence=useRef(0),snapshot=useRef('')
  function select(id:string){setSelected(id)}
  async function reload(){
    const request=++sequence.current
    try{const next=await api<PortfolioState>('/api/portfolios');if(request!==sequence.current)return
      const signature=JSON.stringify(next);if(signature!==snapshot.current){snapshot.current=signature;setData(next);setVersion(v=>v+1)}
      setSelected(current=>next.items.some(p=>p.uuid===current)?current:next.default_uuid||'');setError('')
    }catch(e){if(request===sequence.current)setError(failure(e))}finally{if(request===sequence.current)setLoading(false)}
  }
  useEffect(()=>{void reload()},[revision])
  return <PortfolioContext.Provider value={{...data,selected,select,reload,version,error,loading}}>{children}</PortfolioContext.Provider>
}
export function usePortfolios(){const value=useContext(PortfolioContext);if(!value)throw new Error('Portfolio provider missing');return value}
export function ClientSaveButton({contact,compact=false}:{contact:Contact;compact?:boolean}){
  const ctx=usePortfolios(),portfolio=ctx.items.find(p=>p.uuid===ctx.selected),notify=useNotify()
  const [busy,setBusy]=useState(false),[saved,setSaved]=useState(false),[error,setError]=useState('')
  useEffect(()=>{setSaved(false);setError('')},[contact.id,ctx.selected])
  async function save(){
    if(!portfolio){window.location.hash='/clientes';notify('Crea una cartera para guardar este contacto.','info');return}
    setBusy(true);setError('')
    try{await api('/api/portfolios/'+portfolio.uuid+'/clients',{method:'POST',body:JSON.stringify({contact_id:contact.id})});setSaved(true);notify(contact.name+' guardado en '+portfolio.name+'.');void ctx.reload()}
    catch(e){setError(failure(e));notify(failure(e),'error')}finally{setBusy(false)}
  }
  const label=portfolio?(saved?'Guardado en ':'Guardar en ')+portfolio.name:'Guardar en Mis clientes'
  return <span className="client-save-action"><button className={compact?'':'secondary small'} title={busy?'Guardando…':label} aria-label={label+' · '+contact.name} aria-busy={busy} disabled={busy} onClick={()=>void save()}>{busy?<LoaderCircle size={15} className="spin"/>:saved?<Check size={15}/>:<BookmarkPlus size={15}/>} {!compact&&label}</button>{error&&<small role="alert">{error}</small>}</span>
}
const formOf=(r:Membership):ClientForm=>({stage:r.stage,notes:r.notes,next_step:r.next_step,follow_up:r.follow_up||''})
const draftKey=(id:string)=>'kerna.client-draft.'+id
function readDraft(row:Membership):ClientForm|null{
  try{const text=sessionStorage.getItem(draftKey(row.uuid));if(!text)return null;const data=JSON.parse(text)
    if(!['stage','notes','next_step','follow_up'].every(k=>typeof data[k]==='string'))return null
    const result:ClientForm={stage:data.stage,notes:data.notes,next_step:data.next_step,follow_up:data.follow_up}
    if(JSON.stringify(result)===JSON.stringify(formOf(row))){sessionStorage.removeItem(draftKey(row.uuid));return null}return result
  }catch{return null}
}
function ClientRecord({row,stages,onSave,onRemove,onDetail,onCompany}:{row:Membership;stages:Record<string,string>;onSave:(r:Membership,f:ClientForm)=>Promise<Membership>;onRemove:(r:Membership)=>Promise<void>;onDetail:(c:CRMContact)=>void;onCompany:(c:CRMContact)=>Promise<void>}){
  const [initial]=useState(()=>readDraft(row)),[form,setForm]=useState<ClientForm>(()=>initial||formOf(row)),[dirty,setDirty]=useState(!!initial),[busy,setBusy]=useState(''),[saved,setSaved]=useState(false),[error,setError]=useState('')
  const current=useRef(form),edited=useRef(dirty),notify=useNotify()
  useEffect(()=>{if(!edited.current){const next=formOf(row);current.current=next;setForm(next)}},[row.updated_at,row.stage,row.notes,row.next_step,row.follow_up])
  function edit(key:keyof ClientForm,value:string){const next={...current.current,[key]:value};current.current=next;edited.current=true;setForm(next);setDirty(true);setSaved(false);try{sessionStorage.setItem(draftKey(row.uuid),JSON.stringify(next))}catch{/* The in-memory draft remains available. */}}
  async function save(){
    const sent={...current.current};setBusy('save');setError('')
    try{const result=await onSave(row,sent)
      if(JSON.stringify(current.current)===JSON.stringify(sent)){const next=formOf(result);current.current=next;edited.current=false;setForm(next);setDirty(false);setSaved(true);try{sessionStorage.removeItem(draftKey(row.uuid))}catch{/* optional recovery cache */}}
      notify(JSON.stringify(current.current)===JSON.stringify(formOf(result))?'Notas y seguimiento de '+row.contact.name+' guardados.':'Guardado. Quedan cambios nuevos sin guardar.')
    }catch(e){setError(failure(e));notify('No se pudo guardar. Tu borrador se conserva. '+failure(e),'error')}finally{setBusy('')}
  }
  async function remove(){setBusy('remove');setError('');try{await onRemove(row);try{sessionStorage.removeItem(draftKey(row.uuid))}catch{/* optional recovery cache */}notify(row.contact.name+' quitado de esta cartera.')}catch(e){setError(failure(e));notify(failure(e),'error')}finally{setBusy('')}}
  async function company(){setBusy('company');try{await onCompany(row.contact)}catch(e){setError(failure(e));notify(failure(e),'error')}finally{setBusy('')}}
  return <article className="panel client-record"><div className="section-line"><div><h3>{row.contact.name}</h3><p>{row.contact.company} · {row.contact.role||'Cargo pendiente'} · {row.contact.country||'País pendiente'}</p></div><button className="secondary small" onClick={()=>onDetail(row.contact)}>Abrir ficha</button></div>
    <div className="form-grid"><label>Estado de {row.contact.name}<select value={form.stage} onChange={e=>edit('stage',e.target.value)}>{Object.entries(stages).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label><label>Siguiente paso<input value={form.next_step} maxLength={1000} onChange={e=>edit('next_step',e.target.value)} placeholder="Ej. compartir un caso de earnings"/></label><label>Fecha de seguimiento<input type="date" value={form.follow_up} onChange={e=>edit('follow_up',e.target.value)}/></label><label className="full">Notas de cartera<textarea rows={2} value={form.notes} maxLength={10000} onChange={e=>edit('notes',e.target.value)}/></label></div>
    <div className="inline-actions"><button className="primary small save-client-button" aria-label="Guardar seguimiento" aria-busy={busy==='save'} disabled={!!busy} onClick={()=>void save()}>{busy==='save'?<><LoaderCircle size={14} className="spin"/>Guardando…</>:<><Check size={14}/>Guardar seguimiento</>}</button><button className="secondary small" aria-busy={busy==='company'} disabled={!!busy} onClick={()=>void company()}>{busy==='company'&&<LoaderCircle size={13} className="spin"/>}Ver empresa</button><button className="text-button" disabled={!!busy} onClick={()=>void remove()}>{busy==='remove'?<LoaderCircle size={13} className="spin"/>:<Trash2 size={13}/>}Quitar de esta cartera</button></div>
    <div className="client-save-status" aria-live="polite">{error?<span className="error-text">{error}</span>:dirty?<span className="draft-indicator">Borrador sin guardar</span>:saved?<span className="save-confirmation">Seguimiento guardado.</span>:null}</div>
  </article>
}
export function ClientsWorkspace({revision,onRefresh,onReview,onCompany}:{revision:number;onRefresh:()=>void;onReview:(c:Contact)=>void;onCompany:(uuid:string)=>void}){
  const ctx=usePortfolios(),portfolio=ctx.items.find(p=>p.uuid===ctx.selected),notify=useNotify()
  const [name,setName]=useState(''),[collections,setCollections]=useState<Record<string,Membership[]>>({}),[q,setQ]=useState(''),[stage,setStage]=useState(''),[country,setCountry]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(''),[refreshing,setRefreshing]=useState(false),[detail,setDetail]=useState<CRMContact|null>(null)
  const requests=useRef(0),key=portfolio?.uuid||'',rows=collections[key]||[],loaded=Object.hasOwn(collections,key)
  useEffect(()=>{let alive=true;if(!key)return;const request=++requests.current;setRefreshing(true)
    void api<{items:Membership[]}>('/api/portfolios/'+key+'/clients').then(r=>{if(alive&&request===requests.current){setCollections(old=>({...old,[key]:r.items}));setError('')}}).catch(e=>{if(alive&&request===requests.current)setError(failure(e))}).finally(()=>{if(alive&&request===requests.current)setRefreshing(false)})
    return()=>{alive=false}
  },[key,ctx.version,revision])
  async function create(e:React.FormEvent){e.preventDefault();setBusy('create');setError('');try{const p=await api<Portfolio>('/api/portfolios',{method:'POST',body:JSON.stringify({name})});ctx.select(p.uuid);setName('');await ctx.reload();notify('Cartera '+p.name+' creada.')}catch(e){setError(failure(e));notify(failure(e),'error')}finally{setBusy('')}}
  async function makeDefault(){if(!portfolio)return;setBusy('default');try{await api('/api/portfolios/'+portfolio.uuid+'/default',{method:'POST'});await ctx.reload();notify(portfolio.name+' es tu cartera predeterminada.')}catch(e){setError(failure(e));notify(failure(e),'error')}finally{setBusy('')}}
  async function update(row:Membership,form:ClientForm){
    ++requests.current
    let result:Omit<Membership,'contact'>
    try{result=await api<Omit<Membership,'contact'>>('/api/portfolios/'+row.portfolio_uuid+'/clients/'+row.contact.id,{method:'PUT',body:JSON.stringify({...form,follow_up:form.follow_up||null})})}
    finally{++requests.current;setRefreshing(false)}
    const merged={...row,...result};setCollections(old=>({...old,[row.portfolio_uuid]:(old[row.portfolio_uuid]||[]).map(r=>r.uuid===row.uuid?merged:r)}))
    return merged
  }
  async function remove(row:Membership){++requests.current;await api('/api/portfolios/'+row.portfolio_uuid+'/clients/'+row.contact.id,{method:'DELETE'});++requests.current;setRefreshing(false);setCollections(old=>({...old,[row.portfolio_uuid]:(old[row.portfolio_uuid]||[]).filter(r=>r.uuid!==row.uuid)}));void ctx.reload()}
  async function company(contact:CRMContact){const result=await api<{items:{id:number;uuid:string}[]}>('/api/companies');const found=result.items.find(c=>c.id===contact.firm_id);if(!found)throw new Error('No se ha encontrado la empresa.');onCompany(found.uuid)}
  const visible=rows.filter(r=>(!q||(r.contact.name+' '+r.contact.company).toLocaleLowerCase().includes(q.toLocaleLowerCase()))&&(!stage||r.stage===stage)&&(!country||r.contact.country===country))
  return <section className="clients-workspace"><div className="panel portfolio-toolbar"><div><h2>Tu cartera de clientes</h2><p>Guarda a las personas que investigas, revisas o contactas. Cada cartera conserva sus notas y próximos pasos.</p></div><form onSubmit={e=>void create(e)}><label>Nombre de tu cartera<input required maxLength={100} value={name} onChange={e=>setName(e.target.value)} placeholder="Ej. Marco"/></label><button className="primary small" aria-busy={busy==='create'} disabled={!!busy||!name.trim()}>{busy==='create'?<LoaderCircle size={15} className="spin"/>:<Plus size={15}/>}Crear cartera</button></form>
    {ctx.items.length>0&&<div className="portfolio-selection"><label>Cartera activa<select value={ctx.selected} onChange={e=>ctx.select(e.target.value)}>{ctx.items.map(p=><option key={p.uuid} value={p.uuid}>{p.name}{p.is_default?' · Predeterminada':''}</option>)}</select></label><button className="secondary small" aria-busy={busy==='default'} disabled={!!busy||!portfolio||portfolio.is_default} onClick={()=>void makeDefault()}>{busy==='default'?<LoaderCircle size={14} className="spin"/>:<Star size={14}/>} {portfolio?.is_default?'Cartera predeterminada':'Usar como predeterminada'}</button>{portfolio&&<a className="secondary small" href={'/api/portfolios/'+portfolio.uuid+'/clients/export'}>Exportar cartera</a>}</div>}</div>
    {(error||ctx.error)&&<p className="error-text" role="alert">{error||ctx.error}</p>}
    {ctx.loading?<LoadingCards label="Cargando tus carteras" count={1}/>:!portfolio?<div className="panel compact-empty"><Users size={24}/><h3>Crea tu primera cartera</h3><p>Después guarda contactos desde la agenda o desde una empresa. Guardarlos no registra una llamada ni un mensaje.</p></div>:<>
      <div className="simple-filters"><label className="filter-search"><Search size={17}/><input aria-label="Buscar en mi cartera" placeholder="Nombre o empresa…" value={q} onChange={e=>setQ(e.target.value)}/></label><select aria-label="Estado en mi cartera" value={stage} onChange={e=>setStage(e.target.value)}><option value="">Todos los estados</option>{Object.entries(ctx.stages).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select><button className="secondary small" aria-pressed={country==='España'} onClick={()=>setCountry(c=>c?'':'España')}>Solo España</button><span>{visible.length} {visible.length===1?'contacto':'contactos'} en {portfolio.name}</span></div>
      <div className="async-status-slot">{refreshing&&loaded&&<LoadingStatus label="Actualizando cartera…"/>}</div>
      {!loaded&&!error?<LoadingCards label="Cargando clientes"/>:!visible.length?<div className="panel compact-empty">{rows.length?'No hay clientes con estos filtros.':'Todavía no hay clientes guardados. Abre Contactos o una empresa y pulsa Guardar en '+portfolio.name+'.'}</div>:<div className="client-records">{visible.map(r=><ClientRecord key={r.uuid} row={r} stages={ctx.stages} onSave={update} onRemove={remove} onDetail={setDetail} onCompany={company}/>)}</div>}
    </>}
    {detail&&<ContactHistory contact={detail} onClose={()=>setDetail(null)} onRefresh={onRefresh} onReview={()=>{onReview(detail);setDetail(null)}}/>}
  </section>
}