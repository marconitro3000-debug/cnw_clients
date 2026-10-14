import {createContext,useContext,useEffect,useState,type ReactNode} from 'react'
import {BookmarkPlus,Check,Plus,Star,Trash2,Users,Search} from 'lucide-react'
import {api,type CRMContact,type Contact} from './types'
import {ContactHistory} from './Commercial'

export type Portfolio={uuid:string;name:string;is_default:boolean;clients:number}
type Membership={uuid:string;portfolio_uuid:string;contact_uuid:string;stage:string;notes:string;next_step:string;follow_up:string|null;contact:CRMContact}
type PortfolioState={items:Portfolio[];default_uuid:string|null;stages:Record<string,string>}
type Context=PortfolioState&{selected:string;select:(id:string)=>void;reload:()=>Promise<void>;version:number;error:string}
const PortfolioContext=createContext<Context|null>(null)
const failure=(e:unknown)=>e instanceof Error?e.message:'No se pudo guardar el cambio.'
export function PortfolioProvider({children,revision}:{children:ReactNode;revision:number}){
  const [data,setData]=useState<PortfolioState>({items:[],default_uuid:null,stages:{}}),[selected,setSelected]=useState(''),[version,setVersion]=useState(0),[error,setError]=useState('')
  function select(id:string){setSelected(id)}
  async function reload(){
    try{const next=await api<PortfolioState>('/api/portfolios');setData(next);setSelected(current=>next.items.some(p=>p.uuid===current)?current:next.default_uuid||'');setVersion(v=>v+1);setError('')}
    catch(e){setError(failure(e))}
  }
  useEffect(()=>{void reload()},[revision])
  return <PortfolioContext.Provider value={{...data,selected,select,reload,version,error}}>{children}</PortfolioContext.Provider>
}
export function usePortfolios(){const value=useContext(PortfolioContext);if(!value)throw new Error('Portfolio provider missing');return value}
export function ClientSaveButton({contact,compact=false}:{contact:Contact;compact?:boolean}){
  const ctx=usePortfolios(),portfolio=ctx.items.find(p=>p.uuid===ctx.selected)
  const [busy,setBusy]=useState(false),[saved,setSaved]=useState(false),[error,setError]=useState('')
  useEffect(()=>{setSaved(false);setError('')},[contact.id,ctx.selected])
  async function save(){
    if(!portfolio){window.location.hash='/clientes';return}
    setBusy(true);setError('')
    try{await api('/api/portfolios/'+portfolio.uuid+'/clients',{method:'POST',body:JSON.stringify({contact_id:contact.id})});setSaved(true);await ctx.reload()}
    catch(e){setError(failure(e))}finally{setBusy(false)}
  }
  const label=portfolio?(saved?'Guardado en ':'Guardar en ')+portfolio.name:'Guardar en Mis clientes'
  return <span className="client-save-action"><button className={compact?'':'secondary small'} title={label} aria-label={label+' · '+contact.name} disabled={busy} onClick={()=>void save()}>{saved?<Check size={15}/>:<BookmarkPlus size={15}/>} {!compact&&label}</button>{error&&<small role="alert">{error}</small>}</span>
}
export function ClientsWorkspace({revision,onRefresh,onReview,onCompany}:{revision:number;onRefresh:()=>void;onReview:(c:Contact)=>void;onCompany:(uuid:string)=>void}){
  const ctx=usePortfolios(),portfolio=ctx.items.find(p=>p.uuid===ctx.selected)
  const [name,setName]=useState(''),[rows,setRows]=useState<Membership[]>([]),[q,setQ]=useState(''),[stage,setStage]=useState(''),[country,setCountry]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[loaded,setLoaded]=useState(false),[detail,setDetail]=useState<CRMContact|null>(null),[saved,setSaved]=useState('')
  useEffect(()=>{let alive=true;setLoaded(false);setRows([]);if(!portfolio){setLoaded(true);return}void api<{items:Membership[]}>('/api/portfolios/'+portfolio.uuid+'/clients').then(r=>{if(alive){setRows(r.items);setLoaded(true);setError('')}}).catch(e=>{if(alive){setError(failure(e));setLoaded(true)}});return()=>{alive=false}},[portfolio?.uuid,ctx.version,revision])
  async function create(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');try{const p=await api<Portfolio>('/api/portfolios',{method:'POST',body:JSON.stringify({name})});ctx.select(p.uuid);setName('');await ctx.reload()}catch(e){setError(failure(e))}finally{setBusy(false)}}
  async function makeDefault(){if(!portfolio)return;setBusy(true);try{await api('/api/portfolios/'+portfolio.uuid+'/default',{method:'POST'});await ctx.reload()}catch(e){setError(failure(e))}finally{setBusy(false)}}
  async function update(row:Membership,remove=false){if(!portfolio)return;setBusy(true);setError('');try{await api('/api/portfolios/'+portfolio.uuid+'/clients/'+row.contact.id,{method:remove?'DELETE':'PUT',...(remove?{}:{body:JSON.stringify({stage:row.stage,notes:row.notes,next_step:row.next_step,follow_up:row.follow_up||null})})});await ctx.reload();setSaved(remove?'':row.uuid);onRefresh()}catch(e){setError(failure(e))}finally{setBusy(false)}}
  function edit(id:string,key:string,value:string){setSaved('');setRows(current=>current.map(r=>r.uuid===id?{...r,[key]:value}:r))}
  const visible=rows.filter(r=>(!q||(r.contact.name+' '+r.contact.company).toLocaleLowerCase().includes(q.toLocaleLowerCase()))&&(!stage||r.stage===stage)&&(!country||r.contact.country===country))
  return <section className="clients-workspace">
    <div className="panel portfolio-toolbar"><div><h2>Tu cartera de clientes</h2><p>Guarda a las personas que investigas, revisas o contactas. Cada cartera conserva sus notas y próximos pasos.</p></div><form onSubmit={e=>void create(e)}><label>Nombre de tu cartera<input required maxLength={100} value={name} onChange={e=>setName(e.target.value)} placeholder="Ej. Marco"/></label><button className="primary small" disabled={busy||!name.trim()}><Plus size={15}/>Crear cartera</button></form>
      {ctx.items.length>0&&<div className="portfolio-selection"><label>Cartera activa<select value={ctx.selected} onChange={e=>ctx.select(e.target.value)}>{ctx.items.map(p=><option key={p.uuid} value={p.uuid}>{p.name}{p.is_default?' · Predeterminada':''}</option>)}</select></label><button className="secondary small" disabled={busy||!portfolio||portfolio.is_default} onClick={()=>void makeDefault()}><Star size={14}/>{portfolio?.is_default?'Cartera predeterminada':'Usar como predeterminada'}</button>{portfolio&&<a className="secondary small" href={'/api/portfolios/'+portfolio.uuid+'/clients/export'}>Exportar cartera</a>}</div>}
    </div>
    {(error||ctx.error)&&<p className="error-text" role="alert">{error||ctx.error}</p>}
    {!portfolio?<div className="panel compact-empty"><Users size={24}/><h3>Crea tu primera cartera</h3><p>Después guarda contactos desde la agenda o desde una empresa. Guardarlos no registra una llamada ni un mensaje.</p></div>:<>
      <div className="simple-filters"><label className="filter-search"><Search size={17}/><input aria-label="Buscar en mi cartera" placeholder="Nombre o empresa…" value={q} onChange={e=>setQ(e.target.value)}/></label><select aria-label="Estado en mi cartera" value={stage} onChange={e=>setStage(e.target.value)}><option value="">Todos los estados</option>{Object.entries(ctx.stages).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select><button className="secondary small" aria-pressed={country==='España'} onClick={()=>setCountry(c=>c?'':'España')}>Solo España</button><span>{visible.length} {visible.length===1?'contacto':'contactos'} en {portfolio.name}</span></div>
      {!visible.length&&<div className="panel compact-empty">{!loaded?'Cargando cartera…':rows.length?'No hay clientes con estos filtros.':'Todavía no hay clientes guardados. Abre Contactos o una empresa y pulsa Guardar en '+portfolio.name+'.'}</div>}
      <div className="client-records">{visible.map(r=><article className="panel client-record" key={r.uuid}><div className="section-line"><div><h3>{r.contact.name}</h3><p>{r.contact.company} · {r.contact.role||'Cargo pendiente'} · {r.contact.country||'País pendiente'}</p></div><button className="secondary small" onClick={()=>setDetail(r.contact)}>Abrir ficha</button></div><div className="form-grid"><label>Estado de {r.contact.name}<select value={r.stage} onChange={e=>edit(r.uuid,'stage',e.target.value)}>{Object.entries(ctx.stages).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label><label>Siguiente paso<input value={r.next_step} maxLength={1000} onChange={e=>edit(r.uuid,'next_step',e.target.value)} placeholder="Ej. compartir un caso de earnings"/></label><label>Fecha de seguimiento<input type="date" value={r.follow_up||''} onChange={e=>edit(r.uuid,'follow_up',e.target.value)}/></label><label className="full">Notas de cartera<textarea rows={2} value={r.notes} maxLength={10000} onChange={e=>edit(r.uuid,'notes',e.target.value)}/></label></div><div className="inline-actions"><button className="primary small" disabled={busy} onClick={()=>void update(r)}>Guardar seguimiento</button><button className="secondary small" onClick={()=>void api<{items:{id:number;uuid:string}[]}>('/api/companies').then(f=>{const company=f.items.find(c=>c.id===r.contact.firm_id);if(company)onCompany(company.uuid)}).catch(e=>setError(failure(e)))}>Ver empresa</button><button className="text-button" disabled={busy} onClick={()=>void update(r,true)}><Trash2 size={13}/>Quitar de esta cartera</button></div>{saved===r.uuid&&<p className="save-confirmation" role="status">Seguimiento guardado.</p>}</article>)}</div>
    </>}
    {detail&&<ContactHistory contact={detail} onClose={()=>setDetail(null)} onRefresh={onRefresh} onReview={()=>{onReview(detail);setDetail(null)}}/>}
  </section>
}