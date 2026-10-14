import {test,expect,type Page} from '@playwright/test'

async function setup(page:Page,suffix:string,count=2){
  const p=await (await page.request.post('/api/portfolios',{data:{name:'Cartera estable '+suffix}})).json()
  await page.request.post('/api/portfolios/'+p.uuid+'/default')
  const people=[]
  for(let i=0;i<count;i++){
    const r=await page.request.post('/api/contacts',{data:{name:'Persona Estable '+suffix+' '+i,company:'Gestora Estable '+suffix,role:'CIO',country:'España',linkedin_url:'https://linkedin.com/in/estable-'+suffix+'-'+i,note:'Fixture de estabilidad'}})
    expect(r.ok(),await r.text()).toBeTruthy();const c=await r.json();people.push(c)
    await page.request.post('/api/portfolios/'+p.uuid+'/clients',{data:{contact_id:c.id}})
  }
  return {p,people}
}

test('background reads and a slow save preserve drafts, focus, DOM and scroll position',async({page})=>{
  const {p,people}=await setup(page,'race')
  const url='/api/portfolios/'+p.uuid+'/clients'
  let hold=false,held=false,release=()=>{}
  await page.route('**'+url,async route=>{
    if(route.request().method()==='GET'&&hold&&!held){
      const response=await route.fetch();const body=await response.json();held=true
      await new Promise<void>(resolve=>{release=resolve})
      return route.fulfill({json:body})
    }
    return route.continue()
  })
  await page.route('**/api/scanning',route=>route.fulfill({json:{web:{enabled:true,status:'waiting',lots:0},public:{enabled:false,status:'idle',lots:0},signals:{enabled:false,status:'idle',lots:0},apollo:{enabled:false,status:'idle',lots:0}}}))
  await page.goto('/#/clientes')
  const a=page.locator('.client-record').filter({hasText:people[0].name}),b=page.locator('.client-record').filter({hasText:people[1].name})
  await a.getByLabel('Notas de cartera').fill('Nota que debe quedar guardada')
  await a.getByLabel('Siguiente paso').fill('Compartir un caso concreto')
  await a.getByLabel('Fecha de seguimiento').fill('2026-11-17')
  await b.getByLabel('Notas de cartera').fill('Borrador de otra ficha sin guardar')
  await a.evaluate(el=>el.setAttribute('data-dom-probe','same-card'))
  hold=true
  await page.request.post('/api/contacts',{data:{name:'Nueva Persona Refresco Race',company:'Gestora Refresco Race',role:'CIO',note:'Trigger background refresh'}})
  await expect.poll(()=>held,{timeout:15000}).toBe(true)
  await expect(b.getByLabel('Notas de cartera')).toBeFocused()
  await expect(a).toHaveAttribute('data-dom-probe','same-card')
  let saving=false,finishSave=()=>{}
  await page.route('**'+url+'/'+people[0].id,async route=>{saving=true;await new Promise<void>(resolve=>{finishSave=resolve});return route.continue()})
  const button=a.getByRole('button',{name:'Guardar seguimiento',exact:true})
  await button.scrollIntoViewIfNeeded()
  const before=await a.evaluate(el=>({top:el.getBoundingClientRect().top,scroll:window.scrollY}))
  await button.click()
  await expect.poll(()=>saving).toBe(true)
  await expect(button).toHaveAttribute('aria-busy','true')
  await expect(button).toContainText('Guardando')
  await expect(a.getByLabel('Notas de cartera')).toHaveValue('Nota que debe quedar guardada')
  finishSave()
  await expect(page.locator('.toast-stack')).toContainText('Notas y seguimiento de '+people[0].name+' guardados.')
  release()
  await expect(page.getByText('Actualizando cartera…',{exact:true})).toHaveCount(0)
  await expect(a).toHaveAttribute('data-dom-probe','same-card')
  await expect(a.getByLabel('Notas de cartera')).toHaveValue('Nota que debe quedar guardada')
  await expect(b.getByLabel('Notas de cartera')).toHaveValue('Borrador de otra ficha sin guardar')
  const after=await a.evaluate(el=>({top:el.getBoundingClientRect().top,scroll:window.scrollY}))
  expect(Math.abs(before.top-after.top)).toBeLessThan(2)
  expect(Math.abs(before.scroll-after.scroll)).toBeLessThan(2)
  await page.screenshot({path:'test-results/screenshots/stable-save-toast.png',fullPage:true})
  await page.reload()
  await expect(a.getByLabel('Notas de cartera')).toHaveValue('Nota que debe quedar guardada')
  await expect(a.getByLabel('Fecha de seguimiento')).toHaveValue('2026-11-17')
  await expect(a.getByLabel('Siguiente paso')).toHaveValue('Compartir un caso concreto')
  await expect(b.getByLabel('Notas de cartera')).toHaveValue('Borrador de otra ficha sin guardar')
  await expect(b).toContainText('Borrador sin guardar')
  const rows=await (await page.request.get(url)).json()
  expect(rows.items.find((r:any)=>r.contact.id===people[0].id).notes).toBe('Nota que debe quedar guardada')
})

test('failed saves retain the draft and edits made during saving remain unsaved instead of disappearing',async({page})=>{
  const {p,people}=await setup(page,'failure',1)
  const url='/api/portfolios/'+p.uuid+'/clients/'+people[0].id
  await page.goto('/#/clientes')
  const card=page.locator('.client-record').filter({hasText:people[0].name})
  await card.getByLabel('Notas de cartera').fill('Conservar incluso si el servidor falla')
  await page.route('**'+url,route=>route.fulfill({status:500,json:{detail:'Error de prueba'}}))
  await card.getByRole('button',{name:'Guardar seguimiento',exact:true}).click()
  await expect(page.locator('.toast-error')).toContainText('Tu borrador se conserva')
  await expect(card.getByLabel('Notas de cartera')).toHaveValue('Conservar incluso si el servidor falla')
  await expect(card).toContainText('Error de prueba')
  await page.unroute('**'+url)
  let pending=false,release=()=>{}
  await page.route('**'+url,async route=>{pending=true;await new Promise<void>(resolve=>{release=resolve});return route.continue()})
  await card.getByRole('button',{name:'Guardar seguimiento',exact:true}).click()
  await expect.poll(()=>pending).toBe(true)
  await card.getByLabel('Notas de cartera').fill('Edición nueva mientras guardaba')
  release()
  await expect(card.getByRole('button',{name:'Guardar seguimiento',exact:true})).toBeEnabled()
  await expect(card.getByLabel('Notas de cartera')).toHaveValue('Edición nueva mientras guardaba')
  await expect(card).toContainText('Borrador sin guardar')
  const rows=await (await page.request.get('/api/portfolios/'+p.uuid+'/clients')).json()
  expect(rows.items[0].notes).toBe('Conservar incluso si el servidor falla')
  await page.reload()
  await expect(card.getByLabel('Notas de cartera')).toHaveValue('Edición nueva mientras guardaba')
})

test('company refresh keeps an open contact form and confirmation appears above its dialog',async({page})=>{
  const {people}=await setup(page,'dialog',1)
  const companies=await (await page.request.get('/api/companies')).json(),company=companies.items.find((c:any)=>c.id===people[0].firm_id)
  await page.goto('/#/empresas/'+company.uuid)
  await page.getByRole('button',{name:'Registrar llamada a '+people[0].name,exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'Ficha de '+people[0].name})
  await dialog.getByRole('tab',{name:'Registrar interacción',exact:true}).click()
  await dialog.getByLabel('Comentario de interacción').fill('Nota escrita antes de una recarga de empresa')
  await dialog.evaluate(el=>el.setAttribute('data-dom-probe','same-dialog'))
  await dialog.getByRole('button',{name:'Guardar interacción',exact:true}).click()
  await expect(page.locator('.toast-stack')).toContainText('Interacción guardada.')
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveAttribute('data-dom-probe','same-dialog')
  await expect(dialog.getByRole('status')).toContainText('Guardado en el historial')
  await expect(page.locator('.toast-stack')).toHaveJSProperty('popover','manual')
  expect(await page.locator('.toast-stack').evaluate(el=>el.matches(':popover-open'))).toBe(true)
  await page.screenshot({path:'test-results/screenshots/dialog-save-toast.png',fullPage:true})
  await page.locator('.toast-stack').getByRole('button',{name:'Descartar notificación'}).last().click()
  await expect(page.locator('.toast-stack .toast')).toHaveCount(0)
})