import {useEffect,useState} from 'react'
import {Bot,LoaderCircle,Power} from 'lucide-react'
import {api} from './types'

type Stream={enabled:boolean;status:string;reason:string;lots:number}
type AutopilotStatus={enabled:boolean;activity:string;model_ready:boolean;model_installed:boolean;search_configured:boolean;queue:string[]
  log:{at:string;kind:string;text:string}[];hidden:number;reviewed:number;contacts:number;streams:Record<string,Stream>}
const failure=(e:unknown)=>e instanceof Error?e.message:'No se pudo completar la operación.'
const streamLabels:Record<string,string>={web:'Gestoras nuevas',public:'LinkedIn y datos públicos',signals:'Noticias'}
const statusLabels:Record<string,string>={running:'Trabajando',queued:'En cola',waiting:'Esperando turno',idle:'Parado',stopped:'Parado',interrupted:'Interrumpido',failed:'Error',quota_exhausted:'Cuota agotada',completed:'Terminado'}
const time=(value:string)=>new Date(value).toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'})

export function AutopilotPanel({onRefresh,compact=false}:{onRefresh:()=>void;compact?:boolean}){
  const [status,setStatus]=useState<AutopilotStatus|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const load=()=>api<AutopilotStatus>('/api/autopilot').then(s=>{setStatus(s);setError('')}).catch(e=>setError(failure(e)))
  useEffect(()=>{void load();const timer=window.setInterval(()=>void load(),5000);return()=>window.clearInterval(timer)},[])
  async function toggle(){if(!status)return;setBusy(true);setError('');try{setStatus(await api<AutopilotStatus>('/api/autopilot',{method:'POST',body:JSON.stringify({enabled:!status.enabled})}));onRefresh()}catch(e){setError(failure(e))}finally{setBusy(false)}}
  if(!status)return error?<div className="error-text" role="alert">{error}</div>:null
  return <section className={'panel autopilot '+(status.enabled?'on':'')} aria-label="Piloto automático">
    <div className="section-line"><div className="autopilot-title"><Bot size={22}/><div><h2>Piloto automático</h2><p>{status.enabled?'Qwen limpia la agenda, decide qué buscar y completa LinkedIn por prioridad, sin que tengas que pulsar nada.':'Actívalo y Qwen trabajará solo: limpia la agenda, busca boutiques de tu perfil, completa LinkedIn de quien encaja y vigila noticias.'}</p></div></div>
      <button className={status.enabled?'secondary':'primary'} disabled={busy} onClick={()=>void toggle()}>{busy?<LoaderCircle className="spin" size={16}/>:<Power size={16}/>}{status.enabled?'Detener':'Activar piloto automático'}</button></div>
    {error&&<div className="error-text" role="alert">{error}</div>}
    <div className="autopilot-facts">
      <span className={status.model_ready?'ok':''}>{status.model_ready?'Qwen listo en tu equipo':status.model_installed?'Qwen arrancando…':'Qwen no instalado · solo reglas'}</span>
      <span className={status.search_configured?'ok':''}>{status.search_configured?'Búsqueda web conectada':'Sin Tavily · solo datos públicos'}</span>
      <span>{status.reviewed}/{status.contacts} contactos revisados · {status.hidden} ocultados</span>
      {status.activity&&<span className="ok"><LoaderCircle className="spin" size={12}/>{status.activity}</span>}
    </div>
    {status.enabled&&<div className="autopilot-streams">{Object.entries(streamLabels).map(([key,label])=>{const s=status.streams[key];return <div key={key}><strong>{label}</strong><span>{s?.enabled?statusLabels[s.status]||s.status:'Parado'}{s?.lots?' · '+s.lots+' rondas':''}</span>{s?.reason&&<small>{s.reason}</small>}</div>})}</div>}
    {!compact&&status.queue.length>0&&<details className="settings-extra"><summary>Próximas búsquedas preparadas por Qwen ({status.queue.length})</summary><ul className="autopilot-queue">{status.queue.map(q=><li key={q}>{q}</li>)}</ul></details>}
    {status.log.length>0&&<ol className="autopilot-log" aria-label="Actividad del piloto automático">{status.log.slice(0,compact?4:10).map((entry,i)=><li key={i} className={entry.kind}><time>{time(entry.at)}</time><span>{entry.text}</span></li>)}</ol>}
  </section>
}
