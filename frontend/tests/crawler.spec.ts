import {test,expect} from '@playwright/test'

test('free crawler can start with exhausted search credits and remain independent of Tavily',async({page})=>{
  let starts=0,stops=0
  const state:any={enabled:false,status:'idle',pages:12,failed_pages:1,new_contacts:7,duplicates:2,new_firms:4,new_signals:1,pending:34,urls:46,model_calls:3,current_url:'',credits_used:0,model_enabled:false,errors:[],log:[]}
  const scans={web:{enabled:true,status:'running',lots:1,reason:''},public:{enabled:false,status:'idle',lots:0,reason:''},signals:{enabled:false,status:'idle',lots:0,reason:''},apollo:{enabled:false,status:'idle',lots:0,reason:''}}
  await page.route('**/api/health',async route=>{const response=await route.fetch();return route.fulfill({json:{...await response.json(),api_configured:false,credits_used:1000,monthly_limit:1000}})})
  await page.route('**/api/scanning',route=>route.fulfill({json:scans}))
  await page.route('**/api/crawler',route=>route.fulfill({json:state}))
  await page.route('**/api/local-model',route=>route.fulfill({json:{ready:true,installed:true,error:''}}))
  await page.route('**/api/crawler/start',route=>{
    expect(route.request().postDataJSON()).toEqual({seed_urls:['https://aurora.example/']})
    starts++;state.enabled=true;state.status='running';state.model_enabled=true
    return route.fulfill({json:state})
  })
  await page.route('**/api/crawler/stop',route=>{stops++;state.enabled=false;state.status='stopped';return route.fulfill({json:state})})
  await page.goto('/#/busquedas')
  const panel=page.getByRole('region',{name:'Rastreo web sin créditos'})
  await expect(panel).toBeVisible()
  await expect(panel.locator('.crawler-metrics')).toContainText('7 contactos nuevos')
  await expect(panel.locator('.crawler-metrics')).toContainText('0 créditos')
  await panel.getByText('Añadir una web de partida',{exact:true}).click()
  await panel.getByRole('textbox').fill('https://aurora.example/')
  await panel.getByRole('button',{name:'Activar rastreador',exact:true}).click()
  await expect(panel.getByRole('button',{name:'Detener rastreador',exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'Detener web',exact:true})).toBeVisible()
  await panel.getByRole('button',{name:'Detener rastreador',exact:true}).click()
  await expect(panel.getByRole('button',{name:'Activar rastreador',exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'Detener web',exact:true})).toBeVisible()
  expect(starts).toBe(1);expect(stops).toBe(1)
  await page.setViewportSize({width:390,height:844})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  await page.screenshot({path:'test-results/screenshots/free-crawler-mobile.png',fullPage:true})
  await panel.getByRole('button',{name:'Ver todos los contactos',exact:true}).click()
  await expect(page).toHaveURL(/#\/contactos/)
  await expect(page.getByLabel('Datos de contacto disponibles')).toHaveValue('all')
})
