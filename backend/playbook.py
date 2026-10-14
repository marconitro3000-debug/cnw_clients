"""Initial consultative scripts based on the user's supplied commercial playbook."""
import json
import uuid
from .domain import now

SCRIPTS = [
    ('fundamental','01 · Gestor fundamental','Gestores y analistas fundamentales',
     'Empieza por su proceso. Personaliza la estrategia con una fuente pública y busca conversación, sin pedir una demo en el primer mensaje.',
     'Hola {nombre}, ¿qué tal?\n\nSoy {asesor}, de Kerna. Somos una plataforma de análisis financiero que utiliza modelos predictivos para estimar probabilidades de eventos como sorpresas en resultados, recompras o cambios en el riesgo de mercado.\n\nHe visto que en {gestora} os enfocáis en {estrategia} y me ha parecido que podría haber conexión con vuestro enfoque de inversión.\n\n¿Soléis utilizar datos cuantitativos como complemento al análisis fundamental?',
     'Hi {nombre}, how are you?\n\nI’m {asesor}, from Kerna. We’re a financial analysis platform using predictive models to estimate probabilities of events such as earnings surprises, buybacks and changes in market risk.\n\nI saw that {gestora} focuses on {estrategia} and thought there could be some overlap with your investment approach.\n\nDo you use quantitative data alongside your fundamental analysis?'),
    ('sector','02 · Una estrategia o sector concreto','Fondos especializados y boutiques',
     'Usa una estrategia o un sector realmente publicado por la gestora. Comprueba la cobertura de Kerna antes de ofrecer un ejemplo.',
     'Hola {nombre}, encantado.\n\nSoy {asesor}, de Kerna. Nos dedicamos al análisis predictivo de compañías cotizadas, especialmente a estimar probabilidades de eventos financieros y cambios de mercado.\n\nVi que en {gestora} estáis especializados en {estrategia} y me llamó la atención porque es un ámbito donde nuestros modelos también tienen aplicación.\n\nMe parecía interesante conectar y compartir perspectivas sobre este tipo de análisis.',
     'Hi {nombre}, pleased to connect.\n\nI’m {asesor}, from Kerna. We work on predictive analysis of listed companies, focusing on probabilities of financial events and market changes.\n\nI saw that {gestora} specialises in {estrategia}, an area where our models may also be relevant.\n\nI thought it would be interesting to connect and exchange perspectives on this kind of analysis.'),
    ('earnings','03 · Earnings y expectativas','Analistas de renta variable y long/short',
     'Concentra la conversación en resultados. Si hay interés, ofrece una compañía de su universo con fecha, horizonte y evidencia histórica.',
     'Hola {nombre}, ¿qué tal?\n\nSoy {asesor}, de Kerna. Tenemos una plataforma que analiza empresas cotizadas mediante modelos probabilísticos, incluyendo estimaciones sobre posibles sorpresas en resultados.\n\nHe visto que en {gestora} trabajáis con {estrategia} y creo que esta información podría complementar el análisis que hacéis de las compañías.\n\n¿Utilizáis habitualmente estimaciones alternativas al consenso cuando preparáis resultados?',
     'Hi {nombre}, how are you?\n\nI’m {asesor}, from Kerna. Our platform analyses listed companies using probabilistic models, including estimates of potential earnings surprises.\n\nI saw that {gestora} works on {estrategia} and thought this information could complement your company analysis.\n\nDo you use estimates beyond consensus when preparing for earnings?'),
    ('valuation','04 · Valoración y modelos financieros','Fondos value, fundamentales y family offices',
     'Presenta Excel como un prototipo si todavía lo es. Separa las probabilidades de Kerna de los supuestos económicos del analista y no prometas valoraciones más precisas.',
     'Hola {nombre}, ¿cómo estás?\n\nSoy {asesor}, de Kerna. Desarrollamos modelos predictivos sobre earnings, eventos corporativos y riesgo de mercado para inversores en renta variable.\n\nUna de las aplicaciones que estamos trabajando es incorporar estas probabilidades a modelos tradicionales de valoración y análisis por escenarios.\n\nPor vuestro enfoque en {estrategia}, pensé que podría resultarte interesante.\n\n¿Habéis utilizado alguna vez modelos probabilísticos para complementar vuestras valoraciones?',
     'Hi {nombre}, how are you?\n\nI’m {asesor}, from Kerna. We develop predictive models covering earnings, corporate events and market risk for equity investors.\n\nOne application we’re exploring is incorporating these probabilities into traditional valuation and scenario analysis.\n\nGiven your focus on {estrategia}, I thought it might be relevant.\n\nHave you used probabilistic models to complement your valuations?'),
    ('senior','05 · Presentación a un CIO o gestor senior','CIO, fundadores y gestores senior',
     'Sé breve y específico. La primera entrada no necesita una pregunta. Si ya os conocéis, retoma una conversación real en lugar de fingir que es un contacto nuevo.',
     'Hola {nombre}, un placer.\n\nSoy {asesor}, de Kerna, una plataforma de inteligencia predictiva para renta variable.\n\nAnalizamos probabilidades de eventos financieros y cambios de mercado, buscando aportar una perspectiva adicional al análisis tradicional de compañías.\n\nHe visto vuestro enfoque de inversión en {estrategia} en {gestora} y me ha parecido interesante establecer contacto.\n\nUn saludo.',
     'Hi {nombre}, pleased to connect.\n\nI’m {asesor}, from Kerna, a predictive intelligence platform for equity investors.\n\nWe analyse probabilities of financial events and market changes to offer an additional perspective on traditional company analysis.\n\nI saw {gestora}’s investment approach in {estrategia} and thought it would be interesting to connect.\n\nBest regards.'),
]


def seed_scripts(crm):
    timestamp=now()
    with crm.db.connect() as con:
        for key,title,audience,guidance,text,english in SCRIPTS:
            identifier=str(uuid.uuid5(uuid.NAMESPACE_URL,'kerna:consultative:v1:'+key))
            data={'uuid':identifier,'title':title,'channel':'linkedin','text':text,'english_text':english,'audience':audience,
                  'guidance':guidance,'archived':False,'created_at':timestamp,'updated_at':timestamp,
                  'versions':[{'version':1,'title':title,'channel':'linkedin','text':text,'english_text':english,'created_at':timestamp}]}
            con.execute('INSERT OR IGNORE INTO scripts VALUES(?,?)',(identifier,json.dumps(data,ensure_ascii=False)))