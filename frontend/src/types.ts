export type Evidence = { field: string; value: unknown; url: string; quote: string; observed_at: string }
export type Reason = { field: string; label: string; points: number; maximum: number; evidence: Evidence[] }
export type Contact = {
  id: number; firm_id: number; name: string; role: string; company: string; country: string
  employees_min: number | null; employees_max: number | null; equity: boolean | null; analysis: boolean | null
  linkedin_url: string | null; photo_url: string | null; photo_origin?:string; score: number
  priority: 'high' | 'medium' | 'low'; status: 'qualified' | 'review' | 'excluded'
  reasons: Reason[]; evidence: Evidence[]; issues: string[]; missing: string[]
  business_signals?:BusinessSignal[]; recent_signal_count?:number
  created_at: string; updated_at: string
}
export type Query = { text: string; phase: 'firms' | 'people' }
export type Run = {
  id: number; keywords: string; status: string; completed_queries: number; total_queries: number
  credits: number; contacts_found: number; errors: string[]; started_at: string; finished_at: string | null
  queries: { id: number; text: string; phase: string; status: string; cached: boolean; error: string }[]
}
export type Health = { ok: boolean; api_configured: boolean; credits_used: number; monthly_limit: number; countries: string[] }

export class ApiError extends Error {
  constructor(message:string,public status:number,public url:string){super(message);this.name='ApiError'}
}

export async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json', ...options?.headers } })
  const value = await response.json()
  if (!response.ok) {
    const detail = value.detail
    throw new ApiError(response.status===404?'Esta opción no está disponible en el servidor actual. Reinicia Kerna Client Research y recarga la página.':typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d: { msg: string }) => d.msg).join(' · ') : 'No se pudo completar la operación.',response.status,url)
  }
  return value as T
}
export const activeRun = (run: Run | null) => !!run && ['queued', 'running', 'stopping'].includes(run.status)
export const formatDate = (date: string) => new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(date))
export const statusLabel: Record<string, string> = {
  queued: 'Preparando', running: 'Buscando', stopping: 'Deteniendo', stopped: 'Detenida',
  completed: 'Completada', failed: 'Error', quota_exhausted: 'Cuota agotada', interrupted: 'Interrumpida',
}
export const issueLabel = (issue: string) => ({
  ai_review: 'Propuesta de IA local: revisa los datos y sus fuentes.',
  possible_duplicate: 'Encontrado también en otra fuente sin LinkedIn: confirma que es la misma persona (no es un duplicado en la agenda).',
  association_unverified: 'La vinculación actual con la gestora no está verificada.',
  role_unverified: 'El cargo actual necesita revisión.',
}[issue] || (issue.startsWith('conflict:') ? 'Fuentes contradictorias: ' + ({
  employees: 'tamaño de la gestora', employees_min: 'mínimo de empleados', employees_max: 'máximo de empleados',
  role: 'cargo', country: 'país', equity: 'especialización', analysis: 'análisis', company: 'gestora',
  name: 'nombre', photo_url: 'foto',
} as Record<string, string>)[issue.split(':')[1]] : issue))

export function matches(c: Contact, f: { status: string; q: string; country: string; role: string; size: string; score: string }) {
  const norm = (v: string) => v.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
  if (c.status !== f.status || (f.country && c.country !== f.country) || (f.role && c.role !== f.role) || c.score < Number(f.score)) return false
  if (f.q && !norm(c.name + ' ' + c.company + ' ' + c.role).includes(norm(f.q))) return false
  if (f.size) {
    const [lo, hi] = f.size.split('-').map(Number)
    if (c.employees_min === null || c.employees_max === null || c.employees_min < lo || c.employees_max > hi) return false
  }
  return true
}

export const stageLabels: Record<string,string> = {pending:'Pendiente',contacted:'Contactado',no_response:'Sin respuesta',replied:'Respondió',interested:'Interesado',demo:'Demo / reunión',customer:'Cliente',discarded:'Descartado'}
export const channelLabels: Record<string,string> = {call:'Llamada',linkedin:'LinkedIn',email:'Correo',note:'Comentario'}
export type CRMContact = Contact & {uuid:string;stage:string;blocked:boolean;owner:string;email:string|null;email_status:string;phones:{number:string;type:string;status:string;source:string;observed_at:string}[];apollo_id:string|null;last_interaction:string|null;follow_up:string|null;notes:string;interaction_count:number;reachable?:boolean;contact_sources?:Evidence[];email_candidates?:string[];opportunity_score:number;opportunity_status:OpportunityStatus;opportunity_reasons:(Omit<Reason,'evidence'>&{answer:Answer})[];qualification:Qualification;segment?:string;segment_label?:string;quality?:{status:'ok'|'junk'|'doubtful_firm';reason:string;by:string;at:string}|null}
export type Answer='yes'|'no'|null
export type Qualification={change:Answer;timing:Answer;decision:Answer;updated_at?:string|null;author?:string|null}
export type OpportunityStatus='target'|'later'|'pending'|'unwilling'
export const opportunityLabels:Record<OpportunityStatus,string>={target:'Cliente objetivo',later:'Más adelante',pending:'Sin cualificar',unwilling:'No quiere cambiar'}
export type Interaction = {uuid:string;contact_uuid:string;author:string;channel:string;result:string|null;comment:string;occurred_at:string;created_at:string;follow_up:string|null;script_uuid:string|null;script_version:number|null;supersedes:string|null;clear_follow_up?:boolean}
export type Script = {moment?:string;recommended?:boolean;english_text?:string;audience?:string;guidance?:string;uuid:string;title:string;channel:string;text:string;archived:boolean;versions:{version:number;title:string;channel:string;text:string;created_at:string}[];created_at:string;updated_at:string}
export type ScriptStat = {script_uuid:string;version:number;channel:string;title:string;approached:number;responses:number;interested:number;rejected:number;demos:number;conversion:number}
export type Candidate = {id:string;name:string;partial:boolean;company:string;role:string;domain:string;country:string;linkedin_url:string|null;photo_url:string|null;existing_id:number|null}
export type ScoutRun = Run & {provider?:string;new_contacts?:number;duplicates?:number;omitted?:number;review_contacts?:number;reserved_credits?:number;phones_pending?:number;signals_found?:number;new_signals?:number;candidates?:Candidate[];mode?:string}
export type SharedStatus = {error:string;directory:string;actor:string;conflicts:{uuid:string;kind:string;entity_uuid:string;data:{incoming:unknown;local:unknown}}[]}
export type OllamaStatus = {enabled:boolean;model:string;reachable:boolean;ready:boolean;models:string[]}

export type ScanStream = {enabled:boolean;status:string;reason:string;lots:number;last_run_id?:number|null;next_at?:string}
export type ScanningState = {web:ScanStream;apollo:ScanStream;public?:ScanStream;signals?:ScanStream}

export type LocalModelStatus = {installed:boolean;ready:boolean;model:string;error:string}

export type BusinessSignal={uuid:string;firm_id:number;firm_uuid:string;company:string;domain:string;kind:string;label:string;title:string;quote:string;source_url:string;published_at:string|null;event_at:string|null;date_basis:string;observed_at:string;method:string;review:string;recency:string;reviews:{decision:string;author:string;at:string}[]}
