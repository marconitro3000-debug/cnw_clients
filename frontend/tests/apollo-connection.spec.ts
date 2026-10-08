import {test,expect} from '@playwright/test'

test('connect Apollo on its own tab and search several phrases without enrichment',async({page})=>{
  let connected=false
  const status=()=>({configured:connected,free_budget:0,free_account:false,pending:0,access:connected?{status:'verified',message:'Acceso verificado. 0 créditos.'}:undefined})
  await page.route('**/api/settings/apollo',async route=>{
    if(route.request().method()==='POST'){
      expect(route.request().postDataJSON()).toEqual({api_key:'apollo-fixture-key',free_budget:0,free_account:false})
      connected=true
    }
    await route.fulfill({json:status()})
  })
  let started=false
  await page.route('**/api/apollo/searches',async route=>{
    const body=route.request().postDataJSON()
    expect(body.keywords).toBe('renta variable\nequity\nasset management')
    expect(body.continuous).toBe(true)
    expect(body).not.toHaveProperty('phone')
    started=true
    await route.fulfill({status:202,json:{id:901,provider:'apollo',mode:'discover',keywords:'Apollo',status:'completed',completed_queries:3,total_queries:3,credits:0,contacts_found:0,errors:[],queries:[],started_at:'2026-10-07T10:00:00Z',finished_at:'2026-10-07T10:01:00Z',candidates:[]}})
  })
  await page.route('**/api/apollo/connection-check',route=>route.fulfill({json:{configured:true,free_budget:0,free_account:false,pending:0,access:{status:'verified',message:'Acceso verificado. 0 créditos.'}}}))
  await page.goto('/#/busquedas')
  await page.getByRole('tab',{name:'Apollo',exact:true}).click()
  const connection=page.getByRole('region',{name:'Conexión de Apollo'})
  await expect(connection.getByText('Conecta Apollo para empezar')).toBeVisible()
  await expect(page.getByRole('button',{name:'Buscar en Apollo'})).toBeDisabled()
  const key=connection.getByLabel('API key de Apollo')
  await expect(key).toHaveAttribute('type','password')
  await key.fill('apollo-fixture-key')
  await connection.getByRole('button',{name:'Guardar clave',exact:true}).click()
  await expect(connection.getByText('Apollo · Acceso verificado',{exact:true})).toBeVisible()
  await expect(key).toHaveCount(0)
  await expect(page.getByRole('button',{name:'Buscar en Apollo'})).toBeEnabled()
  await page.getByLabel('Palabras clave de Apollo').fill('renta variable\nequity\nasset management')
  await page.screenshot({path:'test-results/screenshots/apollo-multiple-keywords.png',fullPage:true})
  await page.getByRole('button',{name:'Buscar en Apollo'}).click()
  expect(started).toBe(true)
  await page.reload()
  await page.getByRole('tab',{name:'Apollo',exact:true}).click()
  await expect(connection.getByText('Apollo · Acceso verificado',{exact:true})).toBeVisible()
})


test('Apollo connects while web is running and settings stays available',async({page})=>{
  const run={id:999,provider:'web',keywords:'equity',status:'running',completed_queries:1,total_queries:8,credits:1,contacts_found:0,errors:[],queries:[],started_at:'2026-10-08T10:00:00Z',finished_at:null}
  await page.route('**/api/searches/latest',route=>route.fulfill({json:run}))
  let connected=false
  await page.route('**/api/settings/apollo',route=>{if(route.request().method()==='POST')connected=true;return route.fulfill({json:{configured:connected,free_budget:0,free_account:false,pending:0}})})
  await page.route('**/api/apollo/connection-check',route=>route.fulfill({json:{configured:true,free_budget:0,free_account:false,pending:0,access:{status:'verified',message:'Acceso verificado. 0 créditos.'}}}))
  await page.goto('/#/busquedas')
  await page.getByRole('tab',{name:'Apollo',exact:true}).click()
  const section=page.getByRole('region',{name:'Conexión de Apollo'})
  await section.getByLabel('API key de Apollo').fill('apollo-fixture-running-web')
  await section.getByRole('button',{name:'Guardar clave',exact:true}).click()
  await expect(section.getByText('Apollo · Acceso verificado',{exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'Buscar en Apollo',exact:true})).toBeEnabled()
  await page.locator('.sidebar').getByRole('button',{name:'Ajustes',exact:true}).click()
  await page.getByLabel('API key de Apollo').fill('apollo-fixture-replacement')
  await expect(page.getByRole('button',{name:'Guardar Apollo',exact:true})).toBeEnabled()
  await page.getByRole('button',{name:'Guardar Apollo',exact:true}).click()
  await expect(page.locator('.settings-feedback')).toContainText('Clave de Apollo guardada.')
})


test('saved master key is not presented as verified when free API access is denied',async({page})=>{
  let checked=false
  const status=()=>({configured:true,free_budget:0,free_account:false,pending:0,access:{status:checked?'denied':'unverified',message:checked?'Apollo no incluye la búsqueda por API en el plan de esta cuenta, incluso con una master key. Puedes continuar con el escaneo web o importar un CSV de Apollo.':'Falta comprobar el acceso.'}})
  await page.route('**/api/settings/apollo',route=>route.fulfill({json:status()}))
  await page.route('**/api/apollo/connection-check',route=>{checked=true;return route.fulfill({json:status()})})
  await page.goto('/#/busquedas')
  await page.getByRole('tab',{name:'Apollo',exact:true}).click()
  const connection=page.getByRole('region',{name:'Conexión de Apollo'})
  await expect(connection.getByText('Apollo · Clave guardada',{exact:true})).toBeVisible()
  await connection.getByRole('button',{name:'Comprobar acceso gratuito'}).click()
  await expect(connection.getByText('Apollo · Sin acceso',{exact:true})).toBeVisible()
  await expect(connection.getByRole('status')).toContainText('master key')
  await expect(page.getByRole('button',{name:'Buscar en Apollo',exact:true})).toBeDisabled()
  await expect(page.getByRole('button',{name:'Importar CSV',exact:true})).toBeEnabled()
  await page.screenshot({path:'test-results/screenshots/apollo-access-denied.png',fullPage:true})
  await page.reload()
  await page.getByRole('tab',{name:'Apollo',exact:true}).click()
  await expect(connection.getByText('Apollo · Sin acceso',{exact:true})).toBeVisible()
  await page.locator('.sidebar').getByRole('button',{name:'Ajustes',exact:true}).click()
  await expect(page.locator('.settings-card').filter({has:page.getByRole('heading',{name:'Apollo',exact:true})})).toContainText('Sin acceso')
  await expect(page.getByRole('button',{name:'Comprobar acceso gratuito'})).toBeEnabled()
})


test('free saved-contact source remains usable when discovery is denied',async({page})=>{
  const status={configured:true,free_budget:0,free_account:false,pending:0,access:{status:'denied',message:'Cuenta sin acceso a descubrir'},saved_access:{status:'verified',message:'Contactos guardados disponibles. 0 créditos.'}}
  await page.route('**/api/settings/apollo',route=>route.fulfill({json:status}))
  let started=false
  await page.route('**/api/apollo/searches',route=>{
    const body=route.request().postDataJSON();expect(body.source).toBe('saved_contacts');expect(body.keywords).toBe('');expect(body.continuous).toBe(true);expect(body).not.toHaveProperty('phone');started=true
    return route.fulfill({status:202,json:{id:904,provider:'apollo',mode:'discover',keywords:'Apollo',status:'completed',completed_queries:1,total_queries:1,contacts_found:0,errors:[],queries:[],started_at:'2026-10-08T10:00:00Z',candidates:[]}})
  })
  await page.goto('/#/busquedas')
  await page.getByRole('tab',{name:'Apollo',exact:true}).click()
  await expect(page.getByRole('button',{name:'Buscar en Apollo',exact:true})).toBeDisabled()
  await page.getByLabel('Origen de Apollo').selectOption('saved_contacts')
  await expect(page.getByLabel('País de la gestora')).toHaveCount(0)
  await expect(page.getByText('No descubre personas nuevas.',{exact:false})).toBeVisible()
  await expect(page.getByRole('button',{name:'Sincronizar contactos de Apollo',exact:true})).toBeEnabled()
  await page.getByRole('button',{name:'Sincronizar contactos de Apollo',exact:true}).click()
  expect(started).toBe(true)
  await page.screenshot({path:'test-results/screenshots/apollo-saved-contacts.png',fullPage:true})
  await page.getByRole('button',{name:'Actualizar clave',exact:true}).click()
  await expect(page.getByLabel('API key de Apollo')).toBeVisible()
})
