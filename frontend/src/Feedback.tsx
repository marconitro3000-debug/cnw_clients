import {createPortal} from 'react-dom'
import {createContext,useCallback,useContext,useEffect,useRef,useState,type ReactNode} from 'react'
import {CheckCircle2,Info,LoaderCircle,TriangleAlert,X} from 'lucide-react'

type Kind='success'|'error'|'info'
type Notice={id:number;message:string;kind:Kind}
const DialogFeedbackContext=createContext<(dialog:HTMLDialogElement)=>()=>void>(()=>()=>{})
const FeedbackContext=createContext<(message:string,kind?:Kind)=>void>(()=>{})
export function FeedbackProvider({children}:{children:ReactNode}){
  const [dialog,setDialog]=useState<HTMLDialogElement|null>(null),[notices,setNotices]=useState<Notice[]>([]),sequence=useRef(0),timers=useRef(new Map<number,number>()),host=useRef<HTMLDivElement>(null)
  const registerDialog=useCallback((node:HTMLDialogElement)=>{setDialog(node);return()=>setDialog(current=>current===node?null:current)},[])
  const dismiss=useCallback((id:number)=>{window.clearTimeout(timers.current.get(id));timers.current.delete(id);setNotices(rows=>rows.filter(r=>r.id!==id))},[])
  const notify=useCallback((message:string,kind:Kind='success')=>{
    const id=++sequence.current;setNotices(rows=>[...rows.slice(-2),{id,message,kind}])
    timers.current.set(id,window.setTimeout(()=>dismiss(id),kind==='error'?8500:5000))
  },[dismiss])
  useEffect(()=>{const node=host.current;if(!node)return;try{if(notices.length){if(node.matches(':popover-open'))node.hidePopover();node.showPopover()}else node.hidePopover()}catch{/* Fixed positioning is the fallback for older browsers. */}},[notices,dialog])
  useEffect(()=>()=>{for(const timer of timers.current.values())window.clearTimeout(timer)},[])
  return <DialogFeedbackContext.Provider value={registerDialog}><FeedbackContext.Provider value={notify}>{children}{createPortal(<div className="toast-stack" ref={host} popover="manual" aria-label="Notificaciones" aria-live="polite">{notices.map(n=><div key={n.id} className={'toast toast-'+n.kind} role={n.kind==='error'?'alert':dialog?undefined:'status'}>{n.kind==='success'?<CheckCircle2 size={20}/>:n.kind==='error'?<TriangleAlert size={20}/>:<Info size={20}/>}<span>{n.message}</span><button type="button" aria-label="Descartar notificación" onClick={()=>dismiss(n.id)}><X size={15}/></button></div>)}</div>,dialog||document.body)}</FeedbackContext.Provider></DialogFeedbackContext.Provider>
}
export const useFeedbackDialog=()=>useContext(DialogFeedbackContext)
export const useNotify=()=>useContext(FeedbackContext)
export function LoadingStatus({label='Cargando…'}:{label?:string}){return <span className="loading-status" role="status"><LoaderCircle size={15} className="spin"/>{label}</span>}
export function LoadingCards({label='Cargando…',count=2}:{label?:string;count?:number}){return <div className="loading-cards" role="status" aria-label={label}>{Array.from({length:count},(_,i)=><div className="panel skeleton-card" key={i} aria-hidden="true"><span className="skeleton skeleton-heading"/><span className="skeleton"/><span className="skeleton"/><span className="skeleton skeleton-short"/></div>)}</div>}