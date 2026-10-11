import {useEffect,useState} from 'react'
import {ArrowRight,Building2,ExternalLink} from 'lucide-react'
import {api,opportunityLabels,stageLabels,type OpportunityStatus} from './types'

type SegmentFirm={id:number;name:string;doubtful_name:boolean;domain:string;country:string;segment:string;label:string;tags:string[];evidence:{segment:string;quote:string;url:string}[];sources:number
  automatic?:string;manual?:{author:string;updated_at:string};contacts:number;qualified:number;best_score:number;best_opportunity:number;targets:number;unwilling:number;contacted:number
  people:{id:number;name:string;role:string;linkedin_url:string|null;score:number;status:string;opportunity_score:number;opportunity_status:OpportunityStatus;stage:string}[]}
type SegmentGroup={key:string;label:string;description:string;firms:SegmentFirm[];firm_count:number;contact_count:number;qualified:number;targets:number;unwilling:number}
const failure=(e:unknown)=>e instanceof Error?e.message:'No se pudo completar la operación.'

export function SegmentsWorkspace({revision,onAgenda,onCompany}:{revision:number;onAgenda:(segment:string)=>void;onCompany:(company:string)=>void}){
  const [groups,setGroups]=useState<SegmentGroup[]>([]),[labels,setLabels]=useState<Record<string,string>>({}),[selected,setSelected]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[loaded,setLoaded]=useState(false)
  const load=()=>api<{groups:SegmentGroup[];labels:Record<string,string>}>('/api/segments').then(d=>{setGroups(d.groups);setLabels(d.labels);setError('')}).catch(e=>setError(failure(e))).finally(()=>setLoaded(true))
  useEffect(()=>{void load()},[revision])
  const group=groups.find(g=>g.key===selected)||groups[0]
  async function move(firm:SegmentFirm,segment:string){setBusy(true);setError('');try{await api('/api/firms/'+firm.id+'/segment',{method:'PUT',body:JSON.stringify({segment:segment||null})});await load()}catch(e){setError(failure(e))}finally{setBusy(false)}}
  if(loaded&&!groups.length)return <div className="panel compact-empty">{error||'Todavía no hay gestoras con contactos. Cuando escanees, aparecerán agrupadas por subsector.'}</div>
  return <section className="segments-workspace">
    <p className="hint">Cada gestora se clasifica con los textos públicos que ya tenemos de ella, de sus contactos y de sus noticias. Puedes cambiar el subsector a mano si no es correcto.</p>
    {error&&<div className="error-text" role="alert">{error}</div>}
    <div className="segment-grid" role="tablist" aria-label="Subsectores">{groups.map(g=><button key={g.key} role="tab" aria-selected={group?.key===g.key} className={'panel segment-card '+(group?.key===g.key?'active':'')} onClick={()=>setSelected(g.key)}>
      <strong>{g.label}</strong><small>{g.description}</small>
      <span className="segment-counts"><b>{g.firm_count}</b> gestoras · <b>{g.contact_count}</b> contactos</span>
      <span className="segment-counts">{g.qualified} encajan · {g.targets} cliente objetivo{g.unwilling?' · '+g.unwilling+' no quieren cambiar':''}</span>
    </button>)}</div>
    {group&&<section className="panel segment-detail" aria-label={'Gestoras de '+group.label}>
      <div className="section-line"><div><h2>{group.label}</h2><p className="hint">{group.firm_count} gestoras, ordenadas por mayor oportunidad comercial.</p></div><button className="primary small" onClick={()=>onAgenda(group.key)}>Ver sus {group.contact_count} contactos<ArrowRight size={14}/></button></div>
      <div className="segment-firms">{group.firms.map(f=><article key={f.id} className="segment-firm">
        <div className="section-line"><div><h3><Building2 size={15}/>{f.name}{f.doubtful_name&&<span className="junk-reason">Nombre dudoso · revisar</span>}</h3><small>{[f.country,f.domain].filter(Boolean).join(' · ')}</small></div>
          <label className="segment-move">Subsector<select aria-label={'Subsector de '+f.name} disabled={busy} value={f.manual?f.segment:''} onChange={e=>void move(f,e.target.value)}><option value="">Automático · {labels[f.automatic||f.segment]}</option>{Object.entries(labels).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label></div>
        <p className="segment-stats">{f.contacts} contactos · {f.qualified} encajan · mejor encaje {f.best_score}/100 · mejor oportunidad {f.best_opportunity}/100{f.targets?' · '+f.targets+' cliente objetivo':''}{f.contacted?' · '+f.contacted+' ya contactados':''}</p>
        {f.manual?<small>Asignado a mano por {f.manual.author}.</small>:<small>{f.sources?f.sources+(f.sources===1?' fuente':' fuentes')+' para este subsector':'Sin texto suficiente para clasificar'}{f.tags.length?' · también: '+f.tags.map(t=>labels[t]).join(', '):''}</small>}
        {f.evidence.length>0&&<details className="settings-extra"><summary>Ver por qué</summary>{f.evidence.map((e,i)=><div className="segment-evidence" key={i}><span className="stage-pill">{labels[e.segment]}</span><blockquote>{e.quote}</blockquote>{e.url&&<a href={e.url} target="_blank" rel="noopener noreferrer">Abrir fuente<ExternalLink size={12}/></a>}</div>)}</details>}
        <ul className="segment-people">{f.people.map(p=><li key={p.id}>{p.linkedin_url?<a className="person-link" href={p.linkedin_url} target="_blank" rel="noopener noreferrer">{p.name} ↗</a>:<span className="person-link no-link" title="Sin LinkedIn localizado">{p.name}</span>}<small>{p.role||'Cargo por verificar'}</small><span className={'segment-fit '+p.status}>{p.status==='qualified'?'Encaja':p.status==='review'?'Por verificar':'Fuera'} · {p.score}/100</span><span className={'opportunity-pill '+p.opportunity_status}>{opportunityLabels[p.opportunity_status]}</span>{p.stage!=='pending'&&<span className="stage-pill">{stageLabels[p.stage]}</span>}</li>)}</ul>
        <button className="text-button" onClick={()=>onCompany(f.name)}>Abrir en la agenda<ArrowRight size={13}/></button>
      </article>)}</div>
    </section>}
  </section>
}
