"""Conversation starters and follow-ups from the user's Kerna messaging playbook."""
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


FOLLOW_UP_SCRIPTS = [
    ('connection','00 · Solicitud de conexión breve','Personas que aún no conocen Kerna',
     'Solo para la invitación a conectar. Personaliza una estrategia real y comprueba el límite de caracteres de la solicitud antes de enviarla. Los cinco primeros mensajes se usan después, cuando puedes escribir con más espacio.',
     'Hola {nombre}, soy {asesor}, de Kerna. Trabajamos con modelos predictivos aplicados a la inversión en renta variable. He visto vuestro enfoque en {estrategia} y me parecía interesante conectar. ¡Un saludo!',
     'Hi {nombre}, I’m {asesor}, from Kerna. We work with predictive models for equity investing. I saw your focus on {estrategia} and thought it would be interesting to connect. Best regards!'),
    ('accepted','06 · Después de aceptar la conexión','Contactos que acaban de aceptar la invitación',
     'Úsalo únicamente si ha aceptado la conexión. Introduce una aplicación concreta de Kerna y abre conversación. No repitas la presentación si ya habéis hablado de ella.',
     'Hola {nombre}, gracias por aceptar.\n\nPor darte algo más de contexto, en Kerna estimamos probabilidades de eventos como sorpresas en resultados, recompras de acciones y cambios de régimen de mercado.\n\nLa idea es complementar el análisis fundamental con información probabilística, sin sustituir las herramientas que ya utiliza el gestor.\n\nPor vuestro enfoque en {estrategia}, pensé que algunas de estas señales podrían resultar relevantes.\n\n¿Habéis tenido ocasión de trabajar con este tipo de información?',
     'Hi {nombre}, thanks for connecting.\n\nTo give you a little more context, at Kerna we estimate probabilities of events such as earnings surprises, share buybacks and changes in market regime.\n\nThe idea is to complement fundamental analysis with probabilistic information, alongside the tools you already use.\n\nGiven your focus on {estrategia}, I thought some of these signals might be relevant.\n\nHave you had a chance to work with this kind of information?'),
    ('reply_yes','07 · Si ya utiliza información probabilística','Contactos que responden que sí',
     'Solo después de una respuesta real. Propón un ejemplo de su universo y verifica la cobertura de Kerna antes de ofrecerlo. La reunión se plantea cuando el ejemplo le resulte útil.',
     'Gracias, {nombre}. ¿En qué parte del análisis os resulta más útil esa información?\n\nPor vuestro enfoque en {estrategia}, podríamos partir de una compañía que sigáis y revisar un ejemplo de Kerna: qué evento estima, en qué horizonte y qué evidencia lo acompaña.\n\n¿Te interesaría ver un ejemplo sobre alguna compañía?',
     'Thanks, {nombre}. Where in your analysis do you find that information most useful?\n\nGiven your focus on {estrategia}, we could start with a company you follow and review a Kerna example: the event it estimates, the time horizon and the supporting evidence.\n\nWould you be interested in seeing an example for a company?'),
    ('reply_no','08 · Si aún no utiliza este tipo de información','Contactos que responden que no',
     'Explica una sola aplicación, sin desplegar todos los modelos ni dar por hecho que existe interés. Si no responde o no le interesa, deja espacio.',
     'Gracias por contármelo, {nombre}. Una aplicación concreta sería revisar la probabilidad de una sorpresa en resultados antes de que publique una compañía que sigáis. Es una perspectiva adicional para contrastar con vuestro análisis.\n\nPor vuestro enfoque en {estrategia}, ¿te resultaría útil ver un ejemplo sobre alguna compañía?',
     'Thanks for sharing, {nombre}. One specific application would be reviewing the probability of an earnings surprise before a company you follow reports. It provides an additional perspective to compare with your own analysis.\n\nGiven your focus on {estrategia}, would an example for a company be useful?'),
]

# Retire the original bundled scripts once, keeping their IDs, versions and results.
LEGACY_SCRIPT_IDS = (
    '1f7c2a73-3d5e-4c87-81c8-23b38d2a0dc5',
    '4fcc8b2f-159b-44ca-babf-7d3f4b9d2268',
    '72ebd4a0-29c2-4c71-9ade-51f696f91671',
    'f55bc824-2ff2-4213-a6ba-2be8865c51e9',
)


def seed_scripts(crm):
    timestamp=now()
    with crm.db.connect() as con:
        for key,title,audience,guidance,text,english in SCRIPTS + FOLLOW_UP_SCRIPTS:
            identifier=str(uuid.uuid5(uuid.NAMESPACE_URL,'kerna:consultative:v1:'+key))
            stage = key if key in ('connection','accepted') else 'reply' if key.startswith('reply_') else 'first'
            metadata = {'moment':stage,'recommended':key in ('fundamental','earnings','senior')}
            old=con.execute('SELECT data FROM scripts WHERE uuid=?',(identifier,)).fetchone()
            if old:
                record=json.loads(old[0])
                if any(record.get(k)!=v for k,v in metadata.items()):
                    record.update(metadata,updated_at=timestamp)
                    con.execute('UPDATE scripts SET data=? WHERE uuid=?',(json.dumps(record,ensure_ascii=False),identifier))
                continue
            data={'uuid':identifier,'title':title,'channel':'linkedin','text':text,'english_text':english,'audience':audience,
                  'guidance':guidance,'archived':False,'created_at':timestamp,'updated_at':timestamp,
                  **metadata,'versions':[{'version':1,'title':title,'channel':'linkedin','text':text,'english_text':english,'created_at':timestamp}]}
            con.execute('INSERT OR IGNORE INTO scripts VALUES(?,?)',(identifier,json.dumps(data,ensure_ascii=False)))
        for identifier in LEGACY_SCRIPT_IDS:
            old=con.execute('SELECT data FROM scripts WHERE uuid=?',(identifier,)).fetchone()
            if not old: continue
            record=json.loads(old[0])
            if record.get('retired_by')=='kerna-messaging-v2': continue
            record.update(archived=True,retired_by='kerna-messaging-v2',updated_at=timestamp)
            con.execute('UPDATE scripts SET data=? WHERE uuid=?',(json.dumps(record,ensure_ascii=False),identifier))
