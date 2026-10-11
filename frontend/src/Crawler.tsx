import {useEffect,useRef,useState} from 'react'
import {Bot,ExternalLink,LoaderCircle,Play,Square} from 'lucide-react'
import {api} from './types'

type CrawlerStatus={enabled:boolean;status:string;pages:number;failed_pages:number;new_contacts:number;duplicates:number;new_firms:number;new_signals:number;pending:number;urls:number;model_calls:number;current_url:string;credits_used:number;model_enabled:boolean;errors:{url:string;message:string}[];log:{at:string;url:string;message:string}[]}
type ModelStatus={installed:boolean;ready:boolean;error:string}
const labels:Record<string,string>={running:'Rastreando páginas',waiting:'Fuentes recorridas · pendiente de nuevas páginas',stopped:'Detenido',idle:'Preparado',failed:'Error · revisar avisos',interrupted:'Reanudando'}
const failure=(e:unknown)=>e instanceof Error?e.message:'No se pudo completar la operación.'

export function CrawlerPanel({onRefresh,onContacts}:{onRefresh:()=>void;onContacts:()=>void}){
  const [status,setStatus]=useState<CrawlerStatus|null>(null),[model,setModel]=useState<ModelStatus|null>(null),[seeds,setSeeds]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const refreshRef=useRef(onRefresh),counts=useRef('')
  refreshRef.current=onRefresh
  useEffect(()=>{
    let alive=true,inflight=false
    const load=async()=>{
      if(inflight)return
      inflight=true
      try{
        const [s,m]=await Promise.all([api<CrawlerStatus>('/api/crawler'),api<ModelStatus>('/api/local-model')])
        if(!alive)return
        setStatus(s);setModel(m);setError('')
        const next=[s.new_contacts,s.duplicates,s.new_signals].join(':')
        if(counts.current&&counts.current!==next)refreshRef.current()
        counts.current=next
      }catch(e){if(alive)setError(failure(e))}finally{inflight=false}
    }
    void load()
    const timer=window.setInterval(()=>void load(),5000)
    return()=>{alive=false;window.clearInterval(timer)}
  },[])
  async function toggle(){
    if(!status)return
    setBusy(true);setError('')
    try{
      const path=status.enabled?'/api/crawler/stop':'/api/crawler/start'
      setStatus(await api<CrawlerStatus>(path,{method:'POST',body:JSON.stringify(status.enabled?{}:{seed_urls:seeds.split(/\s+/).filter(Boolean)})}))
      onRefresh()
    }catch(e){setError(failure(e))}finally{setBusy(false)}
  }
  return <section className="panel public-crawler" aria-label="Rastreo web sin créditos">
    <div className="section-line"><div><h2><Bot size={20}/>Rastreo web sin créditos</h2><p>Descubre gestoras desde directorios públicos, sigue sus webs, equipos, biografías y mapas del sitio. Qwen lee las páginas en este equipo.</p></div><button className="secondary small" disabled={busy||!status} onClick={()=>void toggle()}>{busy?<LoaderCircle className="spin" size={14}/>:status?.enabled?<Square size={12}/>:<Play size={14}/>} {status?.enabled?'Detener rastreador':'Activar rastreador'}</button></div>
    {error&&<p className="error-text" role="alert">{error}</p>}
    {status&&<><p role="status">{labels[status.status]||status.status} · funciona en paralelo a Tavily, también cuando su cuota se agota.</p><div className="crawler-metrics"><span><strong>{status.pages}</strong> páginas leídas</span><span><strong>{status.new_firms}</strong> gestoras nuevas</span><span><strong>{status.new_contacts}</strong> contactos nuevos</span><span><strong>{status.duplicates}</strong> coincidencias</span><span><strong>{status.pending}</strong> páginas pendientes</span><span><strong>{status.credits_used}</strong> créditos</span></div>
    <div className="inline-actions"><button className="secondary small" onClick={onContacts}>Ver todos los contactos</button><span className="hint">Incluye los perfiles que todavía no tienen LinkedIn, correo o teléfono.</span></div>
    <p className="hint">{model?.ready?'Qwen listo · '+status.model_calls+' análisis locales':status.model_enabled&&model?.installed?'Qwen está arrancando; el rastreo y la extracción convencional continúan.':status.model_enabled?'Qwen no está disponible; continúa la extracción convencional.':'Al activarlo se arrancará Qwen si está instalado.'}</p>
    {model?.error&&<p className="hint">{model.error}</p>}
    {status.current_url&&<a className="crawler-current" href={status.current_url} target="_blank" rel="noopener noreferrer"><ExternalLink size={13}/>{status.current_url}</a>}
    <details className="settings-extra"><summary>Añadir una web de partida</summary><label>Webs corporativas (una URL por línea)<textarea rows={3} value={seeds} onChange={e=>setSeeds(e.target.value)} placeholder="https://gestora.example/"/></label><p className="hint">Las fuentes añadidas se incorporan al activar el rastreador. Guarda el avance y se reanuda al abrir el programa.</p></details>
    {status.log.length>0&&<details className="settings-extra"><summary>Últimas páginas y resultados</summary><ol className="crawler-log">{status.log.slice(0,10).map((entry,i)=><li key={i}><span>{entry.message}</span>{entry.url&&<a href={entry.url} target="_blank" rel="noopener noreferrer">{entry.url}</a>}</li>)}</ol></details>}
    {status.errors.length>0&&<details className="settings-extra"><summary>Páginas omitidas ({status.errors.length})</summary><ul className="crawler-log">{status.errors.map((entry,i)=><li key={i}><span>{entry.message}</span><span>{entry.url}</span></li>)}</ul></details>}
    </>}
  </section>
}
