import {PortfolioProvider,ClientsWorkspace} from './Clients'
import {CompaniesWorkspace,openCompany} from './Companies'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Moon, Sun, ArrowDownToLine, ArrowRight, ArrowUpRight, Building2, Check, CheckCircle2, ChevronRight, CircleHelp, ClipboardList, FileText, RefreshCw, ScanSearch, Clock3, ExternalLink, Globe2, History, Info, Linkedin, LoaderCircle, MapPin, Plus, Search, Settings2, ShieldCheck, SlidersHorizontal, Sparkles, Square, Target, Users, X } from 'lucide-react'
import { api, ApiError, activeRun, formatDate, issueLabel, matches, statusLabel, type Contact, type Health, type Query, type Run, type ScoutRun, type SharedStatus, type ScanningState } from './types'
import { DEMO } from './demo'
import { Modal, Avatar } from './ui'
import { DashboardPanel, ContactWorkspace, ScriptsWorkspace, ScreenerWorkspace, IntegrationSettings, NextBatchDialog, PublicDataWorkspace } from './Commercial'
import { CrawlerPanel } from './Crawler'
import { SignalsWorkspace } from './Signals'
import { SegmentsWorkspace } from './Segments'
import { AutopilotPanel } from './Autopilot'
import './commercial.css'

function ContactCard({ contact: c, onDetail }: { contact: Contact; onDetail: (c: Contact) => void }) {
  return <article className="contact-card">
    <div className="card-top">
      {c.linkedin_url ? <a href={c.linkedin_url} target="_blank" rel="noopener noreferrer" aria-label={'Abrir LinkedIn de ' + c.name}><Avatar contact={c} /></a> : <Avatar contact={c} />}
      <span className={'priority ' + c.priority}><span />{c.priority === 'high' ? 'Alta prioridad' : c.priority === 'medium' ? 'Prioridad media' : 'Baja prioridad'}</span>
    </div>
    <div className="person-name">{c.linkedin_url ? <a href={c.linkedin_url} target="_blank" rel="noopener noreferrer">{c.name}<ArrowUpRight size={16} /></a> : <h3>{c.name}</h3>}</div>
    <p className="person-role">{c.role || 'Cargo por verificar'}</p>
    <div className="company-line"><Building2 size={15} /><span>{c.company}</span></div>
    <div className="person-meta"><span><MapPin size={13} />{c.country || 'País por verificar'}</span><span><Users size={13} />{c.employees_min === null ? 'Tamaño por verificar' : c.employees_min === c.employees_max ? c.employees_min + ' empleados' : c.employees_min + '–' + c.employees_max + ' empleados'}</span></div>
    <div className="card-tags">{c.equity === true && <span>Renta variable</span>}{c.analysis === true && <span>Análisis de acciones</span>}{c.status === 'review' && <span className="pending-tag">Por verificar</span>}{c.status === 'excluded' && <span className="pending-tag">Fuera del objetivo</span>}</div>
    <div className="card-bottom"><div className="score-mini"><strong>{c.score}<small>/100</small></strong><span>Encaje comercial</span></div><button className="detail-button" onClick={() => onDetail(c)}>Ver detalles<ChevronRight size={16} /></button></div>
  </article>
}


function TavilyConnection({ configured, disabled = false, onConfigured }: { configured: boolean; disabled?: boolean; onConfigured: (health: Health) => void }) {
  const [key, setKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  async function connect(event: React.FormEvent) {
    event.preventDefault(); setSaving(true); setError(''); setSaved(false)
    try {
      const health = await api<Health>('/api/settings/tavily', { method: 'POST', body: JSON.stringify({ api_key: key.trim() }) })
      setKey(''); setSaved(true); onConfigured(health)
    } catch (e) { setError((e as Error).message) } finally { setSaving(false) }
  }
  return <section className="connection-panel" aria-label="Conectar Tavily">
    <div className="connection-heading"><Settings2 size={18} /><div><strong>{configured ? 'Actualizar clave de búsqueda' : 'Conecta la búsqueda gratuita'}</strong><p>Copia tu API key del panel de Tavily y pégala aquí.</p></div>
      <a href="https://app.tavily.com" target="_blank" rel="noopener noreferrer">Obtener clave gratis<ArrowUpRight size={14} /></a>
    </div>
    <form onSubmit={event => void connect(event)}><label>API key de Tavily<input type="password" autoComplete="off" spellCheck={false} placeholder="tvly-…" value={key} maxLength={512} onChange={event => { setKey(event.target.value); setSaved(false); setError('') }} /></label><button className="primary" disabled={saving || disabled || !key.trim()}>{saving ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />}{saving ? 'Guardando…' : 'Guardar y conectar'}</button></form>
    <p className="hint">Se guarda en tu equipo y queda activa al instante. No necesitas editar archivos ni reiniciar.</p>
    {disabled && <p className="hint">Espera a que termine la búsqueda antes de cambiar la clave.</p>}
    {error && <div className="error-text" role="alert">{error}</div>}
    {saved && <p className="connection-success" role="status"><CheckCircle2 size={15} />Clave guardada. Ya puedes iniciar una búsqueda.</p>}
  </section>
}

function SearchDialog({ health, onClose, onStart, onConfigured, onFreeStart }: { health: Health | null; onClose: () => void; onStart: (run: Run) => void; onConfigured: (health: Health) => void; onFreeStart: () => void }) {
  const unavailable=!!health&&(!health.api_configured||health.credits_used>=health.monthly_limit)
  const [continuous, setContinuous] = useState(true)
  const [advanced, setAdvanced] = useState(false)
  const [keywords, setKeywords] = useState('renta variable')
  const [country, setCountry] = useState('')
  const [terms, setTerms] = useState<string[]>([])
  const expansionSequence=useRef(0),[preparedFor,setPreparedFor]=useState('')
  const [firms, setFirms] = useState('')
  const [people, setPeople] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const expand = useCallback(async (words: string, geo: string) => {
    const sequence=++expansionSequence.current
    setBusy(true); setError('')
    try {
      const result = await api<{ terms: string[]; queries: Query[] }>('/api/queries/expand', { method: 'POST', body: JSON.stringify({ keywords: words, country: geo }) })
      if(sequence!==expansionSequence.current)return
      setPreparedFor(JSON.stringify([words,geo]));setTerms(result.terms); setFirms(result.queries.filter(q => q.phase === 'firms').map(q => q.text).join('\n'))
      setPeople(result.queries.filter(q => q.phase === 'people').map(q => q.text).join('\n'))
    } catch (e) { if(sequence===expansionSequence.current)setError((e as Error).message) } finally { if(sequence===expansionSequence.current)setBusy(false) }
  }, [])
  useEffect(() => {const timer=window.setTimeout(()=>void expand(keywords,country),300);return()=>window.clearTimeout(timer)}, [expand,keywords,country])
  const lines = (text: string) => text.split('\n').map(t => t.trim()).filter(Boolean)
  const queries: Query[] = [...lines(firms).map(text => ({ text, phase: 'firms' as const })), ...lines(people).map(text => ({ text, phase: 'people' as const }))]
  async function start() {
    setError(''); setBusy(true)
    try {
      if (queries.length > 20) throw new Error('El plan admite hasta 20 líneas de consultas.')
      const run = await api<Run>('/api/searches', { method: 'POST', body: JSON.stringify({ keywords, queries, continuous }) })
      onStart(run); onClose()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  async function startFree(){
    setBusy(true);setError('')
    try{await api('/api/crawler/start',{method:'POST',body:JSON.stringify({seed_urls:[]})});onFreeStart();onClose()}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  return <Modal title="Nueva búsqueda" subtitle="Encuentra gestoras y después a las personas que deciden." onClose={onClose} wide>
    <div className="search-inputs"><label>Palabras clave<input value={keywords} onChange={e => setKeywords(e.target.value)} maxLength={300} placeholder="Ej. renta variable europea, value investing" /></label><label>Mercado<select value={country} onChange={e => setCountry(e.target.value)}><option value="">España y Europa</option>{health?.countries.map(c => <option key={c}>{c}</option>)}</select></label></div>
    <p className="search-summary">Buscaremos gestoras de renta variable y sus responsables. Las consultas se preparan automáticamente.</p>
    <button className="text-button" aria-expanded={advanced} onClick={()=>setAdvanced(v=>!v)}><SlidersHorizontal size={15}/>{advanced?'Ocultar opciones avanzadas':'Opciones avanzadas'}</button>
    {advanced&&<>
    <div className="expanded-terms">{terms.map(term => <span key={term}>{term}</span>)}</div>
    <div className="query-grid"><label><span className="step-title">Descubrir gestoras</span><textarea aria-label="Consultas de gestoras" rows={5} value={firms} onChange={e => setFirms(e.target.value)} /></label><label><span className="step-title">Encontrar decisores</span><textarea aria-label="Consultas de decisores" rows={5} value={people} onChange={e => setPeople(e.target.value)} /></label></div>
    <p className="hint">Una consulta por línea. Las plantillas <code>{'{gestora}'}</code> y <code>{'{dominio}'}</code> se rellenan para hasta 4 gestoras. Máximo 20 búsquedas por ejecución.</p></>}
    <label className="checkbox-label"><input type="checkbox" checked={continuous} onChange={e => setContinuous(e.target.checked)} />Buscar continuamente · avanzar sin pedir el siguiente lote</label><p className="hint">Continúa mientras el servidor esté abierto, hasta detenerlo o agotar la cuota gratuita. Cada lote conserva el máximo de 20 consultas.</p>
    {!health?.api_configured && <TavilyConnection configured={false} onConfigured={onConfigured} />}
    {unavailable&&<div className="notice" role="status"><Info size={17}/><span>{health?.api_configured?'Tavily ha agotado su cuota.':'Tavily no está conectado.'} Puedes continuar con Qwen y el rastreador sin créditos. Sigue directorios y webs identificadas; las consultas y el mercado de arriba corresponden a Tavily.</span><button className="primary" disabled={busy} onClick={()=>void startFree()}>Iniciar rastreo sin créditos</button></div>}
    {error && <div className="error-text" role="alert">{error}</div>}
    <div className="modal-actions"><span><ShieldCheck size={16} />Fuentes públicas · Cuota limitada</span><button className="primary" disabled={unavailable || busy || preparedFor!==JSON.stringify([keywords,country]) || !health?.api_configured || !lines(firms).length || !keywords.trim()} onClick={() => void start()}>{busy ? <LoaderCircle size={16} className="spin" /> : <Search size={16} />}Iniciar búsqueda</button></div>
  </Modal>
}

function EditDialog({ contact, health, onClose, onSave }: { contact: Contact | null; health: Health | null; onClose: () => void; onSave: () => void }) {
  const [form, setForm] = useState({
    name: contact?.name || '', role: contact?.role || '', company: contact?.company || '', country: contact?.country || '',
    employees_min: contact?.employees_min?.toString() || '', employees_max: contact?.employees_max?.toString() || '',
    equity: contact?.equity === null || contact?.equity === undefined ? '' : String(contact.equity),
    analysis: contact?.analysis === null || contact?.analysis === undefined ? '' : String(contact.analysis),
    linkedin_url: contact?.linkedin_url || '', photo_url: contact?.photo_url || '', note: '',
  })
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const set = (key: keyof typeof form, value: string) => setForm(f => ({ ...f, [key]: value }))
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    const body = { ...form, employees_min: form.employees_min === '' ? null : Number(form.employees_min),
      employees_max: form.employees_max === '' ? null : Number(form.employees_max),
      equity: form.equity === '' ? null : form.equity === 'true', analysis: form.analysis === '' ? null : form.analysis === 'true',
      linkedin_url: form.linkedin_url || null, photo_url: form.photo_url || null }
    try {
      await api(contact ? '/api/contacts/' + contact.id : '/api/contacts', { method: contact ? 'PATCH' : 'POST', body: JSON.stringify(body) })
      onSave(); onClose()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <Modal title={contact ? 'Revisar contacto' : 'Añadir contacto'} subtitle="Guarda solo datos que hayas comprobado. Los campos vacíos seguirán pendientes." onClose={onClose} wide>
    <form onSubmit={e => void save(e)}><div className="form-grid">
      <label>Nombre<input required minLength={2} maxLength={150} value={form.name} onChange={e => set('name', e.target.value)} /></label>
      <label>Cargo actual<input maxLength={200} value={form.role} onChange={e => set('role', e.target.value)} /></label>
      <label>Gestora<input required minLength={2} maxLength={200} value={form.company} onChange={e => set('company', e.target.value)} /></label>
      <label>País<select value={form.country} onChange={e => set('country', e.target.value)}><option value="">Sin verificar</option>{[...new Set([...(health?.countries || []), ...(form.country ? [form.country] : [])])].map(c => <option key={c}>{c}</option>)}</select></label>
      <label>Empleados · mínimo<input type="number" min={0} max={10000000} value={form.employees_min} onChange={e => set('employees_min', e.target.value)} /></label>
      <label>Empleados · máximo<input type="number" min={0} max={10000000} value={form.employees_max} onChange={e => set('employees_max', e.target.value)} /></label>
      <label>Invierte en renta variable<select value={form.equity} onChange={e => set('equity', e.target.value)}><option value="">Sin verificar</option><option value="true">Sí, confirmado</option><option value="false">No, confirmado</option></select></label>
      <label>Análisis o selección de acciones<select value={form.analysis} onChange={e => set('analysis', e.target.value)}><option value="">Sin verificar</option><option value="true">Sí, confirmado</option><option value="false">No, confirmado</option></select></label>
      <label>URL de LinkedIn<input type="url" value={form.linkedin_url} onChange={e => set('linkedin_url', e.target.value)} placeholder="https://www.linkedin.com/in/…" /></label>
      <label>URL de foto verificada<input type="url" value={form.photo_url} onChange={e => set('photo_url', e.target.value)} /></label>
      <label className="full">Fuente o motivo de la revisión<textarea required rows={3} maxLength={1500} value={form.note} onChange={e => set('note', e.target.value)} placeholder="Indica la fuente y lo que has comprobado." /></label>
    </div><p className="hint">El país, el tamaño y la especialización se comparten con los contactos de la misma gestora. Guardar confirma los datos y resuelve sus contradicciones.</p>
      {error && <div className="error-text" role="alert">{error}</div>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Cancelar</button><button className="primary" disabled={busy}>{busy ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />}Guardar revisión</button></div>
    </form>
  </Modal>
}

function DetailDialog({ contact: c, demo, onClose, onEdit }: { contact: Contact; demo: boolean; onClose: () => void; onEdit: () => void }) {
  return <Modal title="Detalle del decisor" onClose={onClose} wide>
    <div className="detail-person"><Avatar contact={c} /><div><h2>{c.name}</h2><p>{c.role} · {c.company}</p></div><strong className="detail-score">{c.score}<small>/100</small></strong></div>
    <div className="detail-section"><h3>Por qué encaja</h3><p className="hint">La puntuación mide encaje comercial con la información disponible.</p>
      {c.reasons.map(r => <div className="reason" key={r.field}><div><span>{r.label}</span><strong>{r.points}<small> / {r.maximum}</small></strong></div><div className="reason-track"><span style={{ width: (r.points / r.maximum * 100) + '%' }} /></div>{r.evidence.length ? <p>{r.evidence[0].quote}</p> : <p>Sin evidencia suficiente.</p>}</div>)}
    </div>
    {(c.missing.length > 0 || c.issues.length > 0) && <div className="notice"><Info size={18} /><div><strong>Pendiente de comprobar</strong><ul>{c.missing.map(s => <li key={s}>{s}</li>)}{c.issues.map(s => <li key={s}>{issueLabel(s)}</li>)}</ul></div></div>}
    <div className="detail-section"><h3>Fuentes y observaciones</h3><div className="source-list">{c.evidence.map((e, i) => <div className="source" key={i}><div>{e.url ? <a href={e.url} target="_blank" rel="noopener noreferrer">{new URL(e.url).hostname}<ExternalLink size={12} /></a> : <span>{demo ? 'Ejemplo ficticio' : 'Revisión manual'}</span>}<time>{formatDate(e.observed_at)}</time></div><p>{e.quote}</p><small>{({ role: 'Cargo', employees: 'Tamaño', equity: 'Renta variable', analysis: 'Análisis', name: 'Nombre', company: 'Gestora', country: 'País', photo_url: 'Foto', linkedin_url: 'LinkedIn' } as Record<string, string>)[e.field] || e.field}</small></div>)}</div></div>
    <div className="modal-actions"><button className="secondary" disabled={demo} onClick={onEdit}><Settings2 size={16} />Revisar datos</button>{c.linkedin_url ? <a className="primary" href={c.linkedin_url} target="_blank" rel="noopener noreferrer"><Linkedin size={16} />Abrir LinkedIn<ArrowUpRight size={16} /></a> : <span className="hint">LinkedIn no localizado</span>}</div>
  </Modal>
}

function ActivityDialog({ run, onClose, embedded=false }: { run: Run | null; onClose: () => void; embedded?: boolean }) {
  const Wrapper = embedded ? ActivityPage : Modal
  return <Wrapper title="Actividad de búsqueda" subtitle="Consultas ejecutadas, resultados parciales y fuentes omitidas." onClose={onClose} wide>
    {!run ? <div className="modal-empty"><History size={28} /><p>Todavía no has ejecutado una búsqueda.</p></div> : <>
      <div className="run-summary"><span>#{run.id} · {statusLabel[run.status]}</span><span>{run.completed_queries}/{run.total_queries} consultas · {run.credits} créditos · {(run as ScoutRun).provider==='signals'?((run as ScoutRun).signals_found||0)+' señales':run.contacts_found+' contactos'}</span></div>
      <p className="hint">{run.keywords} · {formatDate(run.started_at)}</p>
      <div className="query-log">{run.queries.map(q => <div key={q.id}><span className={'log-status ' + q.status}>{q.status === 'completed' ? <CheckCircle2 size={16} /> : q.status === 'running' ? <LoaderCircle className="spin" size={16} /> : <Info size={16} />}</span><div><p>{q.text}</p><small>{q.phase === 'firms' ? 'Descubrimiento de gestoras' : q.phase === 'signals' ? 'Noticias y publicaciones' : 'Búsqueda de decisores'}{q.cached ? ' · Caché, sin consumir crédito' : ''}{q.error ? ' · ' + q.error : ''}</small></div></div>)}</div>
      {run.errors.length > 0 && <div className="activity-errors"><h3>Avisos de la ejecución</h3>{run.errors.map((e, i) => <p key={i}><Info size={14} />{e}</p>)}</div>}
      {run.status === 'completed' && run.contacts_found === 0 && (run as ScoutRun).provider!=='signals' && <div className="notice"><Info size={16} /><span>No se han identificado contactos con evidencia suficiente. Prueba palabras clave o mercados más concretos.</span></div>}
    </>}
  </Wrapper>
}

function ActivityPage({children}:{children:React.ReactNode;title?:string;subtitle?:string;onClose?:()=>void;wide?:boolean}){return <section className="panel activity-page">{children}</section>}

type Page = 'empresas' | 'clientes' | 'inicio' | 'contactos' | 'subsectores' | 'noticias' | 'busquedas' | 'scripts' | 'actividad' | 'configuracion'
const pagePaths: Record<Page,string> = {empresas:'empresas',clientes:'clientes',inicio:'inicio',contactos:'contactos',subsectores:'subsectores',noticias:'noticias',busquedas:'busquedas',scripts:'guiones',actividad:'actividad',configuracion:'configuracion'}
function currentPage(): Page {return (Object.entries(pagePaths).find(([,path])=>window.location.hash.split('/')[1]===path)?.[0] as Page)||'inicio'}
export default function App() {
  const [page, setPage] = useState<Page>(currentPage)
  const navigate = (next: Page) => {window.location.hash='/'+pagePaths[next];setPage(next);setModal(null);setDemo(false);window.scrollTo(0,0)}
  useEffect(()=>{const change=()=>{setPage(currentPage());setModal(null);window.scrollTo(0,0)};window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change)},[])
  const [connectionNotice, setConnectionNotice] = useState('')
  const [dark,setDark]=useState(()=>document.documentElement.dataset.theme==='dark')
  const toggleTheme=()=>{const next=!dark;setDark(next);if(next)document.documentElement.dataset.theme='dark';else delete document.documentElement.dataset.theme;try{localStorage.setItem('kerna-theme',next?'dark':'light')}catch{/* the preference is optional */}}
  const [providerTab,setProviderTab]=useState<'web'|'public'|'signals'|'apollo'>('web')
  const [scanBusy, setScanBusy] = useState(false), [agendaQualification, setAgendaQualification] = useState('all')
  const [agendaAllProfiles,setAgendaAllProfiles]=useState(false)
  const [agendaSearch,setAgendaSearch]=useState(''),[agendaSegment,setAgendaSegment]=useState(''),[agendaKey,setAgendaKey]=useState(0)
  const [agendaView, setAgendaView] = useState('all'), [revision, setRevision] = useState(0), [shared, setShared] = useState<SharedStatus | null>(null)
  const [scanning, setScanning] = useState<ScanningState | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [contacts, setContacts] = useState<Contact[]>([])
  const [run, setRun] = useState<Run | null>(null)
  const [demo, setDemo] = useState(false), [loading, setLoading] = useState(true), [error, setError] = useState('')
  const [modal, setModal] = useState<'search' | 'apollo' | 'next' | 'settings' | 'activity' | 'edit' | null>(null)
  const [detail, setDetail] = useState<Contact | null>(null), [editing, setEditing] = useState<Contact | null>(null)
  const [filters, setFilters] = useState({ status: 'qualified', q: '', country: '', role: '', size: '', score: '0' })
  const filter = (key: keyof typeof filters, value: string) => setFilters(f => ({ ...f, [key]: value }))
  const refreshing = useRef(false), queued = useRef(false), lastSnapshot = useRef('')
  // Background polls only reload the agenda and charts when the data changed; explicit refreshes always do.
  const refresh = useCallback(async (force = true) => {
    // Polls never overlap: the contact list is large and a second request would only queue behind the first.
    if (refreshing.current) { if (force) queued.current = true; return }
    refreshing.current = true
    try {
      const [[h,c,r],extras] = await Promise.all([
        Promise.all([api<Health>('/api/health'),api<Contact[]>('/api/contacts?status=all'),api<Run|null>('/api/searches/latest')]),
        Promise.allSettled([api<SharedStatus>('/api/shared/status'),api<ScanningState>('/api/scanning')]),
      ])
      const snapshot=JSON.stringify([c.length,c.reduce((m,x)=>Math.max(m,x.id),0),r&&[r.id,r.status,r.completed_queries,r.contacts_found]])
      setHealth(h);setContacts(c);setRun(r);setError('')
      if(force||snapshot!==lastSnapshot.current){lastSnapshot.current=snapshot;setRevision(v=>v+1)}
      if(extras[0].status==='fulfilled')setShared(extras[0].value as SharedStatus)
      if(extras[1].status==='fulfilled')setScanning(extras[1].value as ScanningState)
      const missing=extras.find(result=>result.status==='rejected')
      setConnectionNotice(missing?.status==='rejected'?(missing.reason instanceof ApiError&&missing.reason.status===404?'El servidor tiene una versión anterior. Reinicia Kerna Client Research y recarga la página para activar todas las opciones.':'Tu agenda está disponible, pero alguna opción no ha podido cargarse. Pulsa Reintentar.'):'')
    } catch(e) {setError(e instanceof ApiError?e.message:'No se pudo conectar con el servidor local. Comprueba que Kerna Client Research esté abierto.')} finally {setLoading(false);refreshing.current=false;if(queued.current){queued.current=false;void refresh(true)}}
  }, [])
  useEffect(() => { void refresh() }, [refresh])
  const runInfo = run as ScoutRun | null
  const running = activeRun(run)
  const visibleSearchRun = !!run && ((runInfo?.provider||'web') === providerTab)
  const labels:Record<Page,string> = {empresas:'Empresas',clientes:'Mis clientes',inicio:'Tu espacio comercial',contactos:'Contactos',subsectores:'Subsectores',noticias:'Noticias y señales',busquedas:'Búsquedas',scripts:'Guiones comerciales',actividad:'Actividad de búsqueda',configuracion:'Ajustes'}
  const descriptions:Record<Page,string> = {empresas:'Tus gestoras, sus equipos y sus noticias, reunidos en una ficha.',clientes:'Tus carteras personales y el siguiente paso de cada relación.',inicio:'Tu evolución y próximas conversaciones, de un vistazo.',contactos:'Una agenda para todas las personas, sus conversaciones y próximos pasos.',subsectores:'Las gestoras ya escaneadas, agrupadas por tipo de negocio.',noticias:'Lanzamientos, contrataciones y expansión de tus gestoras. Suman a la oportunidad comercial y deciden a quién se busca primero.',busquedas:'Encuentra personas y señales recientes. Una misma agenda.',scripts:'Escribe tus aperturas y descubre cuáles consiguen reuniones.',actividad:'Consulta el avance, las fuentes y los avisos de la última ejecución.',configuracion:'Conexiones y preferencias de este equipo.'}
  const showAgenda = (view: string) => {setAgendaAllProfiles(false);setAgendaKey(k=>k+1);setAgendaView(view);setAgendaSearch('');setAgendaSegment('');setAgendaQualification('all');navigate('contactos')}
  const addContact = () => { setEditing(null); setModal("edit") }
  const reviewContact = (c: Contact) => { setEditing(c); setModal("edit") }
  const newRun = (r: Run) => { setRun(r); setDemo(false); void refresh() }
  useEffect(() => { if (!running && !scanning?.web.enabled && !scanning?.public?.enabled && !scanning?.signals?.enabled && !scanning?.apollo.enabled) return; const timer = window.setInterval(() => void refresh(false), 4000); return () => clearInterval(timer) }, [running, scanning?.web.enabled, scanning?.public?.enabled, scanning?.signals?.enabled, scanning?.apollo.enabled, refresh])
  const source = demo ? DEMO : contacts
  const list = source.filter(c => matches(c, filters)).sort((a, b) => b.score-a.score || a.name.localeCompare(b.name))
  const count = (status: string) => source.filter(c => c.status === status).length
  const high = source.filter(c => c.status === 'qualified' && c.score >= 80).length
  const countries = Array.from(new Set(source.map(c => c.country).filter(Boolean))).sort()
  const roles = Array.from(new Set(source.map(c => c.role).filter(Boolean))).sort()
  const exportParams = new URLSearchParams({ status: filters.status, q: filters.q, country: filters.country, role: filters.role, min_score: filters.score })
  if (filters.size) { const [lo, hi] = filters.size.split('-'); exportParams.set('size_min', lo); exportParams.set('size_max', hi) }
  async function cancel() {
    if (!run) return
    try { setRun(await api<Run>('/api/searches/' + run.id + '/cancel', { method: 'POST' })) } catch (e) { setError((e as Error).message) }
  }
  async function changeScan(source:'web'|'public'|'signals'|'apollo',enabled:boolean) {
    setScanBusy(true);setError('')
    try {
      if(!enabled&&(source==='web'||source==='signals')&&health&&(!health.api_configured||health.credits_used>=health.monthly_limit)){
        setProviderTab('web');navigate('busquedas');await api('/api/crawler/start',{method:'POST',body:JSON.stringify({seed_urls:[]})})
      }else setScanning(await api<ScanningState>('/api/scanning/'+source+'/'+(enabled?'stop':'resume'),{method:'POST'}))
      await refresh()
    }
    catch(e){setError((e as Error).message)}finally{setScanBusy(false)}
  }
  const resetFilters = () => setFilters(f => ({ ...f, q: '', country: '', role: '', size: '', score: '0' }))
  return <PortfolioProvider revision={revision}><div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#/inicio" aria-label="Kerna Client Research, inicio"><span className="kerna-wordmark">kerna<small>CLIENT RESEARCH</small></span></a>
      <div className="workspace"><span className="workspace-icon"><Building2 size={17} /></span><div>Espacio comercial<small>Terminal cuantitativo</small></div><span className="workspace-dot" /></div>
      <p className="nav-label">PROSPECCIÓN</p>
      <nav>{([{id:'inicio',label:'Inicio',icon:Target},{id:'contactos',label:'Contactos',icon:ClipboardList},{id:'empresas',label:'Empresas',icon:Building2},{id:'clientes',label:'Mis clientes',icon:Users},{id:'busquedas',label:'Búsquedas',icon:ScanSearch},{id:'scripts',label:'Guiones',icon:FileText},{id:'actividad',label:'Actividad',icon:History}] as const).map(item=><button key={item.id} className={'nav-item '+(page===item.id?'selected':'')} aria-current={page===item.id?'page':undefined} onClick={()=>navigate(item.id)}><item.icon size={18}/>{item.label}{item.id==='contactos'&&<span>{contacts.length}</span>}</button>)}</nav>
      <div className="sidebar-target"><div><Target size={16} /><span>TU PERFIL OBJETIVO</span></div><h3>Gestoras de<br />renta variable</h3><p>España y Europa<br />Entre 5 y 200 empleados</p><span className="target-badge"><span />CIO · Responsables de inversión</span></div>
      <div className="sidebar-bottom"><button className="nav-item" onClick={() => navigate('configuracion')}><Settings2 size={18} />Ajustes</button><div className="local-status"><span />Entorno local<small>Datos guardados en tu equipo</small></div></div>
    </aside>
    <main className="main">
      <header className="topbar"><div><span>Prospección</span><ChevronRight size={14} /><strong>{labels[page]}</strong></div><div className="topbar-right"><span className="local-pill"><span />LOCALHOST</span><button className="icon-button theme-toggle" aria-label={dark?'Cambiar a modo claro':'Cambiar a modo oscuro'} title={dark?'Modo claro':'Modo oscuro'} aria-pressed={dark} onClick={toggleTheme}>{dark?<Sun size={19}/>:<Moon size={19}/>}</button><button className="icon-button" aria-label="Ayuda y configuración" onClick={() => navigate('configuracion')}><CircleHelp size={19} /></button><span className="user-avatar">ES</span></div></header>
      <div className="main-content">
        <div className="page-heading"><div><h1>{labels[page]}<span>.</span></h1><p>{descriptions[page]}</p></div>{page==='inicio'&&<button className="primary" onClick={()=>navigate('busquedas')}><Search size={17}/>Buscar personas</button>}{page==='busquedas'&&providerTab==='web'&&<button className="primary" onClick={()=>setModal('search')} disabled={!!scanning?.web.enabled}><Plus size={17}/>Nueva búsqueda web</button>}</div>
        {page==='inicio'&&<div className="market-strip"><span><Globe2 size={14} />España + Europa</span><i /><span><Building2 size={14} />5–200 empleados</span><i /><span><ShieldCheck size={14} />Fuentes públicas</span><button onClick={() => { setDemo(v => !v); resetFilters() }}>{demo ? 'Volver a datos reales' : 'Explorar un ejemplo'}<ArrowUpRight size={13} /></button></div>}
        {page === 'busquedas' && !demo && <section className="scan-controls" aria-label="Escaneos de la lista unificada">{(['web','public','signals'] as const).map(source=>{
          const stream=scanning?.[source],enabled=!!stream?.enabled,title=source==='web'?'Escaneo web':source==='public'?'Datos de contacto':'Noticias y señales'
          return <article className={'panel scan-card '+(enabled?'scan-enabled':'')} key={source}><div className="section-line"><div><h2>{title}</h2></div>{enabled?<LoaderCircle size={20} className="spin"/>:<ScanSearch size={20}/>}</div><p>{source==='web'?'Descubre gestoras y responsables. Avanza automáticamente por consultas y países.':source==='public'?'Recoge correos, teléfonos, LinkedIn y fotos publicados en webs corporativas.':'Detecta lanzamientos, contrataciones, expansión y cambios de herramientas.'}</p><div className="scan-state"><span className={enabled?'scan-dot active':'scan-dot'}/><strong>{enabled?(stream?.status==='running'?'Escaneando continuamente':stream?.status==='queued'?'En cola':'Continuo activado'):stream?.status==='quota_exhausted'?'Cuota gratuita agotada':stream?.status==='failed'?'Revisar conexión':stream?.status==='interrupted'?'Interrumpido':stream?.status==='stopped'?'Detenido':'Preparado'}</strong><span>{stream?.lots||0} lotes completados</span></div>{stream?.reason&&<small className="scan-reason">{stream.reason}</small>}<div className="inline-actions"><button className="secondary small" disabled={enabled||scanBusy} onClick={()=>{setProviderTab(source);if(source==='web')setModal('search')}}>{source==='web'?'Configurar escaneo web':source==='public'?'Buscar datos públicos':'Buscar noticias y posts'}</button>{(enabled || stream?.last_run_id || source==='web'&&runInfo?.provider==='web'&&run) && <button className={enabled?'secondary small':'primary small'} disabled={scanBusy} onClick={()=>void changeScan(source,enabled)}>{enabled?<Square size={12}/>:<RefreshCw size={14}/>} {!enabled&&(source==='web'||source==='signals')&&health&&(!health.api_configured||health.credits_used>=health.monthly_limit)?'Rastrear sin créditos':<>{enabled?'Detener':'Continuar'} {source==='web'?'web':source==='public'?'datos':'noticias'}</>}</button>}</div><small>{source!=='public'?(source==='signals'?'Misma cuota de Tavily · ':'')+Math.max(0,(health?.monthly_limit||1000)-(health?.credits_used||0))+' créditos gratuitos disponibles en la aplicación':'Lectura pública · sin Apollo ni créditos de búsqueda'}</small></article>
        })}<p className="scan-explanation">Los tres escaneos alimentan la misma agenda y alternan sin solaparse. Puedes cerrar esta pestaña: siguen mientras el servidor esté abierto. Detener conserva todo.</p></section>}

        {page==='busquedas'&&<AutopilotPanel compact onRefresh={()=>void refresh()}/>}
        {page==='busquedas'&&providerTab==='web'&&<CrawlerPanel onRefresh={()=>void refresh()} onContacts={()=>{showAgenda("all");setAgendaAllProfiles(true)}}/>}
        {page==='busquedas'&&<section className="search-provider-workspace"><div className="tabs" role="tablist" aria-label="Tipo de búsqueda"><button role="tab" aria-selected={providerTab==='web'} className={providerTab==='web'?'active':''} onClick={()=>setProviderTab('web')}>Web</button><button role="tab" aria-selected={providerTab==='public'} className={providerTab==='public'?'active':''} onClick={()=>setProviderTab('public')}>Datos de contacto</button><button role="tab" aria-selected={providerTab==='signals'} className={providerTab==='signals'?'active':''} onClick={()=>setProviderTab('signals')}>Noticias y señales</button><button role="tab" aria-selected={providerTab==='apollo'} className={providerTab==='apollo'?'active':''} onClick={()=>setProviderTab('apollo')}>Apollo</button></div>{providerTab==='web'?<div className="panel search-provider-summary"><h2>Búsqueda web</h2><p>Encontramos gestoras y decisores en fuentes públicas. El escaneo continuo avanza solo y omite a las personas ya contactadas.</p><button className="primary small" onClick={()=>setModal('search')} disabled={!!scanning?.web.enabled}><Search size={15}/>Preparar búsqueda</button></div>:providerTab==='public'?<PublicDataWorkspace scanning={scanning} onRefresh={()=>void refresh()}/>:providerTab==='signals'?<SignalsWorkspace scanning={scanning} health={health} revision={revision} onRefresh={()=>void refresh()} onAgenda={company=>{showAgenda('all');setAgendaSearch(company)}}/>:<ScreenerWorkspace contacts={contacts} health={health} run={run} revision={revision} onRefresh={()=>void refresh()} onRun={newRun} onAgenda={()=>showAgenda('all')}/>}</section>}

        {connectionNotice && <div className="local-warning" role="status"><Info size={17}/><span>{connectionNotice}</span><button className="secondary small" onClick={()=>void refresh()}>Reintentar conexión</button></div>}
        {error && <div className="error-banner" role="alert"><Info size={18} /><span>{error}</span><button className="secondary small" onClick={() => void refresh()}>Reintentar</button></div>}
        {demo && <div className="demo-banner"><Sparkles size={17} /><span><strong>Vista de ejemplo.</strong> Datos ficticios para explorar la interfaz. No se guardan ni se exportan.</span><button onClick={() => setDemo(false)} aria-label="Cerrar vista de ejemplo"><X size={16} /></button></div>}
        {page==='inicio'&&<AutopilotPanel onRefresh={()=>void refresh()}/>}
        {page==='inicio'&&<section className="stats-grid" aria-label="Resumen de contactos">
          {[{ label: 'Contactos descubiertos', value: source.length, icon: Users, note: 'Tu universo de oportunidades', cls: '' },
            { label: 'Encajan con el objetivo', value: count('qualified'), icon: Target, note: 'Gestora, tamaño y cargo verificados', cls: 'green' },
            { label: 'Alta prioridad', value: high, icon: Sparkles, note: 'Calificación de 80 puntos o más', cls: 'green' },
            { label: 'Pendientes de verificar', value: count('review'), icon: Clock3, note: 'Completa los datos para priorizar', cls: 'amber' }].map(s => <div className={'stat ' + s.cls} key={s.label}><div><span>{s.label}</span><s.icon size={17} /></div><strong>{s.value}</strong><p>{s.note}</p></div>)}
        </section>}
        {page === "inicio" && !demo && <DashboardPanel revision={revision} onView={showAgenda} />}
        {shared && (shared.error || shared.conflicts.length > 0) && <div className="notice"><Info size={17}/><span>{shared.error || (shared.conflicts.length + " revisiones pendientes en los datos compartidos o en Apollo.")}</span><button className="text-button" onClick={() => navigate("configuracion")}>Revisar configuración</button></div>}
        {page==='busquedas' && visibleSearchRun && running && run && <section className="progress-panel" aria-live="polite"><div><LoaderCircle className="spin" size={19} /><div><strong>{statusLabel[run.status]} oportunidades</strong><p>{run.completed_queries} de {run.total_queries} consultas · {runInfo?.provider==='signals'?(runInfo.signals_found||0)+' señales encontradas':run.contacts_found+' contactos encontrados'}</p></div><button className="secondary small" disabled={run.status === 'stopping'} onClick={() => void cancel()}><Square size={12} />Detener</button></div><div className="progress-track"><span style={{ width: (run.total_queries ? run.completed_queries / run.total_queries * 100 : 0) + '%' }} /></div></section>}
        {page==='busquedas' && visibleSearchRun && !running && run && <div className="last-run"><CheckCircle2 size={15} /><span>Última búsqueda: {statusLabel[run.status]} · {runInfo?.provider==='signals'?(runInfo.signals_found||0)+' señales':run.contacts_found+' contactos'} · {formatDate(run.started_at)}</span><button onClick={() => navigate('actividad')}>Ver actividad<ArrowRight size={13} /></button></div>}
        {page==='busquedas' && visibleSearchRun && !running && run && !demo && <div className="scan-summary"><span>{runInfo?.provider==='signals'?(runInfo.new_signals||0)+' señales nuevas · '+(runInfo.signals_found||0)+' evidencias recogidas':runInfo?.provider === "public" ? run.contacts_found + " fichas con datos públicos · " + run.completed_queries + " revisadas" : (runInfo?.new_contacts ?? run.contacts_found) + " nuevos · " + (runInfo?.duplicates ?? 0) + " coincidencias · " + (runInfo?.omitted ?? 0) + " omitidos · " + (runInfo?.review_contacts ?? 0) + " por verificar"}{runInfo?.reserved_credits ? " · " + runInfo.reserved_credits + " créditos Apollo reservados" : ""}{runInfo?.phones_pending ? " · " + runInfo.phones_pending + " teléfonos pendientes" : ""}</span><div>{!!runInfo?.review_contacts && <button className="text-button" onClick={() => { showAgenda("all"); setAgendaQualification("review") }}>Ver pendientes</button>}{runInfo?.provider === "web" && !scanning?.web.enabled && <button className="secondary small" onClick={() => setModal("next")}>Siguiente lote<ArrowRight size={14}/></button>}</div></div>}
        {page==='busquedas' && visibleSearchRun && modal !== "activity" && !running && run && ["failed", "quota_exhausted"].includes(run.status) && run.errors.length > 0 && <div className="notice"><Info size={17}/><span>{run.errors[run.errors.length - 1]}</span><button className="text-button" onClick={() => navigate("actividad")}>Ver avisos</button></div>}
        {page === "inicio" && demo && <section className="results-section">
          <div className="results-heading"><div><h2>Tu lista de decisores</h2><p>Prioriza el encaje antes de iniciar una conversación.</p></div><div className="results-actions"><button className="text-button" onClick={() => { setEditing(null); setModal('edit') }} disabled={demo}><Plus size={15} />Añadir contacto</button><a className={'secondary small ' + (!list.length || demo ? 'disabled' : '')} href={'/api/contacts/export?' + exportParams} aria-disabled={!list.length || demo} onClick={e => { if (!list.length || demo) e.preventDefault() }}><ArrowDownToLine size={15} />Exportar CSV</a></div></div>
          <div className="tabs" role="tablist" aria-label="Estado de los contactos">{([{ id: 'qualified', label: 'Lista objetivo' }, { id: 'review', label: 'Por verificar' }, { id: 'excluded', label: 'Fuera del objetivo' }]).map(t => <button role="tab" aria-selected={filters.status === t.id} className={filters.status === t.id ? 'active' : ''} key={t.id} onClick={() => filter('status', t.id)}>{t.label}<span>{count(t.id)}</span></button>)}</div>
          <div className="filter-bar"><label className="filter-search"><Search size={17} /><input aria-label="Buscar en contactos" placeholder="Buscar nombre, cargo o gestora…" value={filters.q} onChange={e => filter('q', e.target.value)} /></label><label className="filter-select"><Globe2 size={15} /><select aria-label="Filtrar por país" value={filters.country} onChange={e => filter('country', e.target.value)}><option value="">Todos los países</option>{countries.map(c => <option key={c}>{c}</option>)}</select></label><select aria-label="Filtrar por cargo" value={filters.role} onChange={e => filter('role', e.target.value)}><option value="">Todos los cargos</option>{roles.map(r => <option key={r}>{r}</option>)}</select><select aria-label="Filtrar por tamaño" value={filters.size} onChange={e => filter('size', e.target.value)}><option value="">Todos los tamaños</option><option value="5-20">5–20 empleados</option><option value="21-50">21–50 empleados</option><option value="51-200">51–200 empleados</option></select><label className="filter-select"><SlidersHorizontal size={15} /><select aria-label="Filtrar por prioridad" value={filters.score} onChange={e => filter('score', e.target.value)}><option value="0">Toda prioridad</option><option value="80">Alta · ≥80</option><option value="60">Alta y media · ≥60</option></select></label></div>
          <div className="list-caption"><span><b>{list.length}</b> {list.length === 1 ? 'decisor' : 'decisores'}{demo ? ' de ejemplo' : ''}</span><span>Ordenados por encaje comercial ↓</span></div>
          {loading && !demo ? <div className="empty-state"><LoaderCircle className="spin" size={30} /><h3>Cargando tu lista…</h3></div> : list.length ? <div className="contact-grid">{list.map(c => <ContactCard key={c.id} contact={c} onDetail={setDetail} />)}</div> : <div className="empty-state"><span className="empty-icon"><Search size={29} /></span><h3>{source.length ? 'No hay contactos con estos filtros' : 'Tu próxima oportunidad empieza aquí'}</h3><p>{source.length ? 'Ajusta los filtros o revisa las otras listas para ver más contactos.' : 'Busca gestoras de renta variable y descubre quién toma las decisiones.'}</p>{source.length ? <button className="secondary" onClick={resetFilters}>Restablecer filtros</button> : <button className="primary" disabled={running} onClick={() => setModal('search')}><Sparkles size={16} />Preparar primera búsqueda<ArrowRight size={16} /></button>}<div className="empty-steps"><span>Define tus palabras clave</span><ChevronRight size={14} /><span>Descubre decisores</span><ChevronRight size={14} /><span>Prioriza con evidencia</span></div></div>}
        </section>}
        {page === "contactos" && <div id="agenda-unificada"><ContactWorkspace includeIncomplete={agendaAllProfiles} key={agendaKey} search={agendaSearch} segment={agendaSegment} qualification={agendaQualification} contacts={contacts} health={health} run={run} revision={revision} view={agendaView} onView={setAgendaView} onRefresh={() => void refresh()} onRun={newRun} onAdd={addContact} onReview={reviewContact}/></div>}
        {page === "empresas" && <CompaniesWorkspace scanning={scanning} workspace={{contacts,health,run,revision,view:'all',onView:setAgendaView,onRefresh:()=>void refresh(),onRun:newRun,onAdd:addContact,onReview:reviewContact}} onAgenda={company=>{showAgenda('all');setAgendaSearch(company)}}/>}
        {page === "clientes" && <ClientsWorkspace revision={revision} onRefresh={()=>void refresh()} onReview={reviewContact} onCompany={openCompany}/>}
        {page === "noticias" && <SignalsWorkspace scanning={scanning} health={health} revision={revision} onRefresh={() => void refresh()} onAgenda={company=>{showAgenda('all');setAgendaSearch(company)}}/>}
        {page === "subsectores" && <SegmentsWorkspace revision={revision} onAgenda={segment=>{showAgenda('all');setAgendaSegment(segment)}} onCompany={company=>{showAgenda('all');setAgendaSearch(company)}}/>}
        {page === "scripts" && <ScriptsWorkspace revision={revision} onRefresh={() => void refresh()}/>}

        {page==='actividad'&&<ActivityDialog run={run} onClose={()=>navigate('busquedas')} embedded/>}
        {page==='configuracion'&&<IntegrationSettings apolloRunning={running&&runInfo?.provider==='apollo'} running={running} onRefresh={()=>void refresh()} tavilyConfigured={!!health?.api_configured} tavily={<TavilyConnection configured={!!health?.api_configured} disabled={running} onConfigured={setHealth}/>} />}

        {page==='busquedas' && providerTab==='web' && !health?.api_configured && !demo && <div className="setup-banner"><div className="setup-icon"><Settings2 size={19} /></div><div><strong>Conecta tu búsqueda gratuita</strong><p>Configura Tavily para descubrir perfiles. Tu lista y tus revisiones se guardan localmente.</p></div><button className="secondary small" onClick={() => navigate('configuracion')}>Conectar Tavily<ArrowRight size={14} /></button></div>}
        <footer><span><ShieldCheck size={13} />Cada calificación se apoya en fuentes o revisiones documentadas.</span><span>Kerna Client Research · Hecho para encontrar encaje</span></footer>
      </div>
    </main>
    {modal === 'search' && <SearchDialog health={health} onConfigured={setHealth} onClose={() => setModal(null)} onStart={newRun} onFreeStart={()=>void refresh()} />}
    {modal === 'apollo' && <Modal title="Screener Apollo" subtitle="Segundo escaneo · todas las personas se guardan en la misma agenda." onClose={() => setModal(null)} wide><ScreenerWorkspace contacts={contacts} health={health} run={run} revision={revision} onRefresh={() => void refresh()} onRun={newRun} onAgenda={() => {setModal(null);showAgenda('all')}}/></Modal>}
    {modal === 'next' && run && <NextBatchDialog run={run} onClose={() => setModal(null)} onStart={newRun}/>}
    {modal === 'edit' && <EditDialog contact={editing} health={health} onClose={() => setModal(null)} onSave={() => void refresh()} />}
    {modal === 'activity' && <ActivityDialog run={run} onClose={() => setModal(null)} />}
    {modal === 'settings' && <Modal title="Configuración local" subtitle="Una cuenta gratuita para descubrir oportunidades; tus contactos se guardan en tu equipo." onClose={() => setModal(null)}>
      <div className="settings-status"><span className={health?.api_configured ? 'connected' : 'pending'} />{health?.api_configured ? 'Clave de Tavily configurada' : 'Clave de Tavily pendiente'}<strong>{health?.credits_used || 0} / {health?.monthly_limit ?? 1000}</strong></div>
      <p className="hint">Créditos reservados por esta aplicación este mes. El uso desde otras herramientas no se incluye; Tavily aplica también la cuota de tu cuenta.</p>
      <TavilyConnection configured={!!health?.api_configured} disabled={running} onConfigured={setHealth} />
      <div className="notice"><ShieldCheck size={18} /><span>La clave se utiliza exclusivamente en el servidor. La búsqueda se detiene al llegar al límite configurado o cuando Tavily comunica cuota agotada.</span></div>
      <IntegrationSettings running={running} onRefresh={() => void refresh()} />
      <div className="detail-section"><h3>Qué se considera un buen contacto</h3><p className="hint">Cargo decisor: 40 puntos · Renta variable: 30 · Gestora de 5–200 empleados: 20 · Análisis de acciones: 10. Gestores: 25 puntos por cargo; analistas: 10.</p></div>
    </Modal>}
    {detail && <DetailDialog contact={detail} demo={demo} onClose={() => setDetail(null)} onEdit={() => { setEditing(detail); setDetail(null); setModal('edit') }} />}
  </div></PortfolioProvider>
}
