import type { Contact, Evidence } from './types'
const stamp = '2026-10-07T09:00:00Z'
function sample(id: number, name: string, role: string, company: string, country: string, employees: number | null, points: number, status: Contact['status'], analysis = true): Contact {
  const quote = 'Datos ficticios para explorar la interfaz. No representan personas ni gestoras reales.'
  const evidence: Evidence[] = ['role', 'equity', ...(employees === null ? [] : ['employees']), ...(analysis ? ['analysis'] : [])].map(field => ({
    field, value: field === 'role' ? role : field === 'employees' ? employees : true, url: '', quote, observed_at: stamp,
  }))
  const reasonData: [string, string, number, number][] = [
    ['role', 'Cargo decisor', points, 40], ['equity', 'Renta variable', 30, 30],
    ['employees', 'Gestora de 5 a 200 empleados', employees !== null && employees <= 200 ? 20 : 0, 20],
    ['analysis', 'Análisis y selección de acciones', analysis ? 10 : 0, 10],
  ]
  const score = reasonData.reduce((n, r) => n+r[2], 0)
  return { id, firm_id: id, name, role, company, country, employees_min: employees, employees_max: employees,
    equity: true, analysis: analysis ? true : null, linkedin_url: null, photo_url: null, score,
    priority: score >= 80 ? 'high' : score >= 60 ? 'medium' : 'low', status,
    reasons: reasonData.map(([field, label, points, maximum]) => ({ field, label, points, maximum, evidence: evidence.filter(e => e.field === field) })),
    evidence, issues: [], missing: ['LinkedIn no localizado', ...(employees === null ? ['Tamaño sin verificar'] : [])],
    created_at: stamp, updated_at: stamp }
}
export const DEMO: Contact[] = [
  sample(-1, 'Elena Martín', 'Chief Investment Officer', 'Atlántico AM · Ejemplo', 'España', 34, 40, 'qualified'),
  sample(-2, 'Marc Dubois', 'Head of Equities', 'Rivage Capital · Ejemplo', 'Francia', 68, 40, 'qualified'),
  sample(-3, 'Thomas Keller', 'Portfolio Manager', 'Nord Equity · Ejemplo', 'Alemania', 22, 25, 'qualified'),
  sample(-4, 'Sofia Rossi', 'Investment Analyst', 'Arco Investments · Ejemplo', 'Italia', 14, 10, 'qualified', false),
  sample(-5, 'Lucía Navarro', 'Directora de inversiones', 'Alba Gestión · Ejemplo', 'España', null, 40, 'review'),
  sample(-6, 'Oliver Bennett', 'Fund Manager', 'Oakbridge AM · Ejemplo', 'Reino Unido', null, 25, 'review', false),
  sample(-7, 'Eva Laurent', 'Chief Investment Officer', 'Grand Asset · Ejemplo', 'Francia', 500, 40, 'excluded'),
]
