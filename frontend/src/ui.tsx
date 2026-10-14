import {useFeedbackDialog} from './Feedback'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { type Contact } from './types'

export function Modal({ title, subtitle, children, onClose, wide = false }: { title: string; subtitle?: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null),registerDialog=useFeedbackDialog()
  useEffect(() => { const dialog = ref.current!; if (!dialog.open) dialog.showModal(); const unregister=registerDialog(dialog);return () => {unregister();dialog.close()} }, [registerDialog])
  return <dialog ref={ref} className={'modal ' + (wide ? 'wide' : '')} onCancel={onClose} onClick={e => { if (e.target === e.currentTarget) onClose() }} aria-label={title}>
    <div className="modal-top"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-button" onClick={onClose} aria-label="Cerrar ventana"><X size={20} /></button></div>
    {children}
  </dialog>
}

export function Avatar({ contact }: { contact: Contact }) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [contact.photo_url])
  const initials = contact.name.split(/\s+/).slice(0, 2).map(w => w[0]).join('')
  return <span className={'avatar avatar-' + Math.abs(contact.id % 5)}>
    {contact.photo_url && !failed ? <img src={contact.photo_url} alt={contact.name} referrerPolicy="no-referrer" onError={() => setFailed(true)} /> : initials}
  </span>
}

