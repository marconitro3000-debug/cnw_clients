# Kerna Client Research

Aplicación local para descubrir decisores de gestoras de renta variable, registrar conversaciones y comparar guiones. React + TypeScript + Vite, FastAPI y SQLite. Interfaz en español, disponible en **http://127.0.0.1:8001**.

## Instalación y arranque en Windows

Requisitos: Python 3.11 o posterior y Node.js 22 o posterior. En PowerShell, dentro de la carpeta:

~~~powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1
~~~

Para actualizar la interfaz después de cambiar el código:

~~~powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Rebuild
~~~

Para detenerla:

~~~powershell
powershell -ExecutionPolicy Bypass -File .\stop.ps1
~~~

El servidor arranca oculto, escucha únicamente en 127.0.0.1 y conserva los datos. El script reinicia exclusivamente el proceso registrado de este proyecto. Logs: server.log y server-error.log.

La agenda, los comentarios, los guiones y las importaciones CSV funcionan sin claves de proveedores.

## Buscar en la web

1. Crea una cuenta gratuita Researcher en [Tavily](https://app.tavily.com) y mantén el pago por uso desactivado.
2. Pega la clave en **Nueva búsqueda** o **Configuración**. Se guarda en .env y queda activa inmediatamente.
3. En **Búsquedas → Web**, indica palabras clave y mercado y pulsa **Iniciar búsqueda**. Las consultas se preparan automáticamente; puedes revisarlas en **Opciones avanzadas**.
4. **Buscar continuamente** está activado por defecto. El servidor prepara y ejecuta automáticamente el siguiente lote: profundiza en gestoras conocidas y avanza por países. Puedes detenerlo o continuarlo desde el bloque **Escaneo web** de la página Búsquedas. Para ejecutar solo un lote, desmarca esa opción.
5. Revisa el resumen y filtra la agenda por **Por verificar**.

Se procesan hasta cuatro gestoras por lote, máximo 20 búsquedas básicas y 16 lecturas corporativas. Se conservan las gestoras adicionales para lotes posteriores. Las consultas y páginas idénticas se reutilizan durante siete días. Una sola ejecución puede estar activa. Puedes activar web, datos públicos, noticias y Apollo a la vez: el servidor alterna los lotes de los orígenes activos, con una pausa de 30 segundos entre lotes de cada origen. Cerrar la pestaña no detiene el escaneo; cerrar el programa sí. Detener conserva resultados y avance. Tras reiniciar el servidor, debes pulsar **Continuar** para reanudar.

Si se agota la cuota gratuita o el proveedor devuelve un error, se detiene ese origen y se muestra el motivo. Cuando se recorren todos los filtros o consultas preparados, permanece en espera y vuelve a comprobarlos a los siete días, sin repetir peticiones continuamente. Puedes detener y configurar otros términos o filtros para avanzar antes.

La aplicación lee resultados públicos y HTML corporativo respetando robots.txt; no automatiza sesiones de LinkedIn. Descarta informes, asociaciones y eslóganes como nombres de gestoras. Extrae datos estructurados, tarjetas de equipo y cargos explícitos, con fuente y fecha. Los datos ambiguos quedan pendientes y pueden corregirse manualmente.

La cuota local de Tavily es un contador conservador: reserva un crédito por petición nueva incluso si falla. MONTHLY_SEARCH_LIMIT puede reducir el máximo de 1.000. No incluye el uso desde otras aplicaciones. Los errores de cuota detienen el lote. [Créditos de Tavily](https://docs.tavily.com/documentation/api-credits).

## Escaneo de datos públicos sin Apollo

En **Búsquedas → Datos de contacto**, pulsa **Buscar datos de contacto**. Revisa las webs corporativas, tarjetas de equipo y biografías de las personas ya descubiertas, y guarda correos, teléfonos, LinkedIn y fotos claramente asociados a cada persona. No requiere una clave adicional ni consume créditos de Tavily o Apollo. La búsqueda web continúa descubriendo personas y este segundo escaneo completa la misma agenda. Ambos pueden permanecer activos y alternan sus lotes.

Cada lote revisa hasta cuatro personas y 16 páginas únicas. El modo continuo espera cinco minutos cuando termina la agenda y vuelve a revisarla; las páginas se reutilizan durante siete días. Las personas ya contactadas se omiten. También puedes seleccionar filas y usar **Buscar datos públicos** para revisar solo esas personas. Se conservan los datos manuales; los correos contradictorios quedan para revisión. No se asigna a una persona el correo general ni el teléfono del pie de página de su gestora.

La disponibilidad depende de lo publicado. Este escaneo no permite revelar correos o móviles privados de LinkedIn. Una foto de su CDN se muestra cuando aparece asociada a la persona en una fuente accesible; si no hay foto pública o no carga, se muestran iniciales.

## Noticias, posts y señales recientes

En **Búsquedas → Noticias y señales**, elige periodo (30–365 días) y una gestora o todas las identificadas. **Buscar noticias y posts** consulta publicaciones públicas sobre lanzamientos de fondos, contrataciones, expansión, nuevos responsables y adopción de herramientas o datos. Busca también estrategias **event-driven**, que se muestran como estrategia de inversión y no aumentan la prioridad por crecimiento.

El modo de vigilancia avanza por gestoras sin pedir lotes: hasta cuatro gestoras, 12 consultas básicas y 16 fuentes por lote. Alterna con los demás escaneos en una única cola; al completar el recorrido espera 24 horas. Se omiten las gestoras cuyos contactos están todos bloqueados. Comparte el límite gratuito configurado de Tavily con el escaneo web; se detiene al agotarlo. Las búsquedas del mismo periodo y día reutilizan caché durante siete días. Encontrar publicaciones consume la cuota de búsqueda; el análisis del modelo local no consume tokens de pago.

Se leen artículos accesibles y fragmentos indexados de posts públicos, incluidos los que el buscador devuelve de LinkedIn. No se inicia sesión ni se recorren publicaciones privadas de LinkedIn. Un artículo sobre la expansión de una participada no se atribuye automáticamente a la gestora. El modelo local instalado ayuda en páginas difíciles, con un máximo de dos análisis por lote; la extracción convencional continúa si falta o falla.

Cada señal guarda la cita literal, URL original, fecha publicada, fecha del evento cuando es explícita, fecha de consulta y método de extracción. Las fechas estimadas por el buscador se distinguen de las de la página: Tavily puede estimar publicación o actualización. Las fechas ausentes o contradictorias quedan para revisión; los eventos antiguos o futuros no cuentan como señales recientes. [Opciones de fecha de Tavily](https://docs.tavily.com/documentation/api-reference/endpoint/search).

**Confirmar señal** y **Descartar señal** conservan autor, fecha e historial de revisión. Confirmar una publicación sin fecha no inventa una fecha. La disposición a cambiar o comprar se confirma en conversación; la puntuación técnica del contacto se mantiene.

Las señales se enlazan a la gestora y aparecen en la ficha de sus contactos, sin crear una segunda lista de personas. **Ver contactos** abre la misma agenda filtrada por gestora. En **Contactos → Más filtros → Señales recientes** puedes mostrar publicaciones recientes fechadas, propuestas por revisar o estrategias event-driven. Los filtros se aplican también al CSV. SQLite conserva las señales y `shared-data/signals/` y `shared-data/senales.csv` permiten compartirlas con otra copia del proyecto; las revisiones contradictorias se presentan como conflictos.

## Contactos y conversaciones

**Inicio** contiene los indicadores, la gráfica conjunta y los accesos a la agenda. **Búsquedas** contiene los controles de web, datos de contacto y noticias. Web, Apollo y CSV alimentan esa misma agenda, con un filtro de calificación: objetivo, por verificar o fuera del objetivo. La puntuación representa encaje comercial: cargo decisor 40; gestor 25 o analista 10; renta variable 30; tamaño 5–200 empleados 20; análisis/selección de acciones 10. Cada aportación necesita evidencia. Alta prioridad desde 80; media desde 60. En una boutique quien compra suele ser el fundador, CEO, managing director, presidente, miembro del comité ejecutivo o head of research, así que también suman 40; los cargos de ventas, desarrollo de negocio, relación con clientes o consultoría no suman. Si las fuentes discrepan de forma compatible (varias oficinas europeas, o varios cargos de decisión) se toma el país más repetido o el cargo más completo en lugar de bloquear el contacto. **Encaja con el objetivo** exige renta variable, país europeo y un cargo verificado; un tamaño desconocido o los avisos de revisión (revisión de IA, posible duplicado) no lo impiden y se muestran como pendientes, mientras que un tamaño conocido fuera de 5–200 o las contradicciones de empresa, país o cargo sí. El botón de la luna, arriba a la derecha, activa el modo oscuro y se recuerda en el navegador.

**Contactos** muestra la agenda en su propia página, con páginas de 50 filas, búsqueda, filtros por país, cargo, tamaño, prioridad, calificación, etapa, responsable y canales disponibles. La búsqueda, la calificación, la puntuación mínima (0–100) y los canales disponibles quedan a la vista; **Más filtros** despliega país, cargo, etapa, tamaño, responsable y canal. Por defecto solo muestra personas con LinkedIn, correo o teléfono; **Sin datos de contacto · revisar** conserva accesibles los perfiles incompletos. Cerrar ese panel conserva los filtros activos, con un contador y botón para limpiarlos. La barra A–Z incluye Ñ y trata los nombres con acentos por su inicial. Puedes exportar la lista filtrada o el CSV completo.

- Los botones de llamada, correo y mensaje abren primero **Información**, con el LinkedIn real, correo, teléfono y fuentes del contacto. Pulsarlos no registra una interacción ni marca a la persona como contactada. **Registrar interacción** muestra el formulario rápido de canal, resultado y nota; **Historial** muestra las conversaciones anteriores. El responsable y la fecha se guardan automáticamente. **Seguimiento y otros detalles** permite cambiarlos y programar la próxima acción; el guion se muestra cuando hay guiones disponibles. Los datos de correo/teléfono se editan en un bloque aparte, cerrado por defecto.
- Cualquier llamada o mensaje excluye a esa persona de nuevos escaneos/enriquecimientos. También se excluyen los descartados.
- Los ya contactados siguen disponibles para seguimiento. **Volver a buscar** permite una actualización web explícita sin borrar conversaciones.
- Los comentarios por sí solos conservan la etapa actual. Puedes cerrar un seguimiento pendiente expresamente.
- Corregir una interacción crea un registro que sustituye al anterior; ambos permanecen en el historial.
- Las fotos se muestran cuando una fuente las asocia al contacto. Una foto ausente o inaccesible se sustituye por iniciales.

### Piloto automático (Qwen)

**Inicio → Piloto automático → Activar** deja la prospección funcionando sola con el modelo local Qwen. Se reanuda automáticamente al reiniciar el servidor; los escaneos manuales siguen esperando a que pulses Continuar.

- **Limpieza:** las reglas ocultan titulares evidentes y Qwen revisa los demás contactos de 8 en 8, decidiendo si el nombre es una persona real y si la empresa es una gestora real. Los ocultados no se borran: están en **Contactos → Ocultados por Qwen**, con el motivo, y se restauran con **No es basura**. Las gestoras con nombre dudoso se marcan en Subsectores.
- **Datos que faltan:** Qwen lee las fuentes ya guardadas y completa el país de la sede, si la gestora invierte en renta variable y el cargo de las personas que no lo tienen. Solo se acepta un dato si la cita que da Qwen está literalmente en una fuente guardada (y, para el país, la cita nombra ese país o una de sus ciudades); cada gestora o persona se revisa como máximo cada dos semanas.
- **Búsquedas dirigidas:** Qwen escribe consultas para descubrir boutiques e independientes de renta variable europeas, rotando países e idiomas y tomando como referencia las gestoras que ya encajan. Si Qwen no está listo se usan plantillas equivalentes. Una ronda de cada dos busca más decisores en gestoras prioritarias (con noticias recientes, que ya encajan o de subsectores boutique, quant, hedge funds y temáticos).
- **LinkedIn y datos públicos:** primero quien encaja sin LinkedIn, después quien encaja, después cargos decisores por verificar. Cada contacto se revisa como máximo una vez por semana y nunca los ocultados ni los ya contactados.
- **Noticias:** página propia en el menú. Se revisan primero las gestoras que encajan y las de subsectores prioritarios, cada una como máximo cada tres días; Qwen analiza hasta cuatro páginas difíciles por ronda. Las señales suman a la oportunidad comercial.

Todo lo que decide aparece en el registro del panel. Sin clave de Tavily solo funcionan la limpieza y los datos públicos.

### Subsectores

**Subsectores** agrupa las gestoras ya escaneadas que tienen contactos: cuantitativa y quantamental, hedge funds y retorno absoluto, boutique de renta variable, temática y sostenible, banca privada y family office, multiactivo y generalista, mercados privados y sin clasificar. La clasificación usa los textos públicos ya guardados de la gestora, de sus contactos (incluido el cargo) y de sus señales no descartadas. Gana el subsector con más frases distintas; en empate, el más específico. Una gestora de renta variable no queda como mercados privados solo por mencionarlos. **Ver por qué** muestra las frases y sus fuentes.

Cada tarjeta resume gestoras, contactos, cuántos encajan y cuántos son cliente objetivo. Las gestoras se ordenan por mayor oportunidad. Puedes asignar el subsector a mano (se comparte en `shared-data/segments/`) o volver al automático. **Ver sus contactos** abre la agenda filtrada; el filtro también está en **Contactos → Más filtros → Subsector** y el CSV incluye la columna Subsector.

### Oportunidad comercial

El encaje dice si la gestora podría usar el producto; la **oportunidad comercial** (0–100) dice si está dispuesta a cambiar ahora. Se calcula aparte y nunca modifica el encaje:

- Señales recientes de la gestora, hasta 40: nuevo fondo 25, contratación 20, expansión 20, herramientas y datos 20, cambio de responsable 15. Cada tipo cuenta una vez; una señal sin revisar cuenta la mitad y las descartadas, antiguas o sin fecha no cuentan. Event-driven describe una estrategia y no suma.
- Respuestas de la llamada de cualificación, marcadas en **Información → Oportunidad comercial**: P3 ha probado o incorporado herramientas en el último año 25, P6 decide y puede aprobar el gasto 20, P4 tiene un motivo para actuar este año 15.

Estados: **No quiere cambiar** si P3 o P6 es No; **Más adelante** si P4 es No; **Cliente objetivo** si P3 y P6 son Sí y además P4 es Sí o hay una señal reciente; en otro caso **Sin cualificar**. **Más filtros** permite filtrar por estado y ordenar por mayor oportunidad. El CSV incluye la oportunidad y su estado, y las respuestas viajan en `shared-data`.

Una gráfica grande superpone las cuatro series en la misma escala y cuenta personas únicas, no peticiones ni repeticiones: primeras identificaciones, primeros contactos que encajan, primer contacto comercial y primera demo/reunión. Puedes elegir 7 días, 30 o todo el historial, ocultar líneas desde la leyenda y pasar el cursor para consultar las cifras de un día. Las métricas de nuevos/duplicados por ejecución se registran desde esta versión; las búsquedas antiguas conservan su total histórico de hallazgos.

## Guiones

Crea guiones de llamada, LinkedIn o correo con **{nombre}** y **{gestora}**. Usa la vista previa, copia el texto y selecciona el guion al registrar la interacción. Editar título, canal o texto crea una nueva versión; archivar conserva el historial.

Las estadísticas muestran personas abordadas, respuestas, interés, rechazo y demos por versión y canal. La conversión principal es demos/reuniones por personas abordadas. Se atribuye la primera demo al último guion usado en una llamada o mensaje antes de conseguirla. Las interacciones corregidas no se cuentan dos veces. La aplicación registra acciones; enviar mensajes y llamar se hace desde las herramientas que tú utilices.

## Apollo: escaneo complementario

En **Configuración**, introduce una clave de [Apollo](https://app.apollo.io), indica el presupuesto de créditos gratuitos **por ciclo de la cuenta** y confirma que utilizas una cuenta gratuita sin recargas. La clave permanece en el backend. El acceso a endpoints puede depender del plan y de que la cuenta esté registrada con correo profesional.

**Búsquedas → Apollo** permite filtrar por países europeos, cargos, palabras clave, tamaño y dominios de gestoras. La búsqueda de personas consume cero créditos. En modo continuo avanza por páginas y guarda automáticamente en la agenda los perfiles con identidad completa, sin gastar créditos de enriquecimiento. Los nombres ocultos quedan como candidatos para revisión. En modo de un solo lote, los resultados se previsualizan antes de incorporar. Apollo puede ocultar apellidos en la búsqueda: completar esos candidatos antes de guardarlos puede consumir hasta un crédito por persona.

**Completar contactos existentes** te lleva a la lista unificada: selecciona allí perfiles y solicita correo o teléfono. El escaneo continuo no hace estas operaciones automáticamente. Antes de cada enriquecimiento se verifica el saldo y ciclo de Apollo y se reserva el máximo: hasta 1 crédito por perfil/correo o 9 con móvil. Si el saldo no puede verificarse, falta presupuesto o se agota la cuota, la operación se bloquea y se conserva lo guardado. Las reservas de peticiones fallidas siguen contando como consumidas; el límite local es deliberadamente conservador. Aumentar el presupuesto no borra el consumo reservado del ciclo.

No se activan compras, suscripciones, recargas, correos personales ni proveedores de waterfall. Las condiciones de facturación de la cuenta se gestionan en Apollo; mantén desactivadas allí las recargas. [Búsqueda](https://docs.apollo.io/reference/people-api-search), [costes de API](https://docs.apollo.io/docs/api-pricing).

Los teléfonos se solicitan con poll_only=true. Se conservan los identificadores y se consultan sin publicar un webhook. Si una solicitud sigue pendiente, se detiene o se reinicia el servidor, usa **Recuperar teléfonos pendientes**; recuperar no repite el enriquecimiento. Las coincidencias de identidad dudosas se conservan para revisión, sin mezclar sus correos con los del contacto conocido.

También puedes importar CSV sin usar la API: carga o pega el archivo, previsualiza hasta cinco filas, asigna columnas y guarda. Máximo 5.000 filas y 3 MB por archivo. Se reconocen cabeceras habituales de Apollo, se informa de duplicados/errores y se omiten los ya contactados. Correos y teléfonos importados quedan identificados como no verificados.

## Modelo local de Hugging Face

La extracción convencional sigue funcionando sin IA. Si el modelo está instalado, Kerna Client Research arranca automáticamente **Qwen3.5-4B Q4_K_M**, descargado de [Hugging Face](https://huggingface.co/lmstudio-community/Qwen3.5-4B-GGUF), con el motor [llama.cpp](https://github.com/ggml-org/llama.cpp). No necesitas Ollama ni activar una casilla en cada búsqueda.

En otra instalación de Windows, descarga una vez el modelo y el motor CPU:

~~~powershell
.\.venv\Scripts\python.exe install-local-model.py
~~~

Después inicia o reinicia la aplicación normalmente. El instalador fija la revisión del modelo y la versión del motor, verifica los SHA-256 de ambos y guarda los archivos en **data/local-model/**, fuera del repositorio y los datos compartidos. Descarga aproximada: 2,7 GB más 20 MB del motor. No se utilizan servicios de inferencia externos ni hay cargos por tokens del modelo local.

El motor escucha exclusivamente en una dirección 127.0.0.1 con puerto privado asignado al arrancar y clave efímera; se inicia sin ventana y se cierra con el servidor. La aplicación pide salida JSON y exige citas presentes literalmente en la página. Rechaza nombres, cargos o enlaces inventados. Las propuestas quedan pendientes de revisión y la puntuación sigue calculándose mediante reglas. Se utiliza para páginas donde la extracción convencional no encuentra personas. Si tarda demasiado o falla, la búsqueda continúa con los resultados convencionales.

**Configuración → Modelo local de Hugging Face** muestra si está instalado y preparado. **GET /api/local-model** expone el estado, sin la clave del motor. Las rutas anteriores de Ollama se mantienen por compatibilidad con clientes existentes.

## Navegación y búsquedas sencillas

Inicio, Contactos, Búsquedas, Guiones, Actividad y Configuración son páginas independientes. Sus rutas se guardan en la URL; recargar y los botones Atrás/Adelante conservan la página. La agenda comparte las personas identificadas por ambos proveedores, pero aparece en Contactos. Inicio muestra los indicadores y una gráfica conjunta; Guiones tiene la acción Nuevo guion.

En Búsquedas, Web, Datos de contacto, Noticias y señales y Apollo tienen pestañas propias. Para buscar en la web basta con palabras clave y mercado; el avance continuo está activado por defecto. Las consultas se preparan automáticamente y son editables dentro de Opciones avanzadas. Un escaneo explícito de una persona nunca se utiliza como criterio del siguiente lote general.

## Datos compartidos y copias del repositorio

SQLite operativo: **data/scout.sqlite**, ignorado por Git. Antes de la ampliación se guardó una copia en data/backups/before-crm.sqlite.

Cada cambio genera automáticamente **shared-data/**:

- JSON con identificadores estables de gestoras, contactos, señales, interacciones, guiones, observaciones y resúmenes de ejecuciones.
- contactos.csv, interacciones.csv y senales.csv, legibles con Excel: UTF-8 con BOM, punto y coma y protección frente a fórmulas.

shared-data no está ignorado por Git. Para compartir, incluye estos archivos en tus commits y actualiza el repositorio. Quien clone/descargue esa versión verá los datos al arrancar: se reconstruye su SQLite y las importaciones repetidas no duplican contactos ni conversaciones. No hay sincronización en tiempo real ni publicación automática mediante Git.

Las modificaciones contradictorias de perfiles o guiones se presentan en **Configuración** para comparar y elegir qué conservar. Los historiales se unen por identificadores. Un archivo corrupto se señala para revisión. Si falla una exportación, SQLite conserva los cambios y aparece un aviso con opción de reintentar.

Las claves, los presupuestos, las solicitudes privadas pendientes y las cachés no se incluyen en shared-data. Cada usuario configura su nombre y sus propias conexiones. SCOUT_SHARED_PATH permite usar otra carpeta portable; SCOUT_DATABASE_PATH y SCOUT_ENV_PATH aíslan instalaciones y pruebas.

## Desarrollo, pruebas y API

~~~powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm.cmd run build
npm.cmd run test:ui
~~~

Para Chromium de pruebas: npx.cmd playwright install chromium. Si ya está instalado, configura PLAYWRIGHT_CHROMIUM_EXECUTABLE con su ruta. Las pruebas usan datos ficticios, bases aisladas y proveedores simulados; no consumen créditos reales.

Para desarrollo, arranca Uvicorn en 8001 y ejecuta npm.cmd run dev; Vite escucha en 127.0.0.1:5173.

Documentación interactiva: **http://127.0.0.1:8001/docs**. Se conservan las rutas originales de contactos, filtros, CSV, búsquedas y configuración de Tavily. Nuevas familias:

- /api/crm/contacts: listado paginado, filtros, CSV, canales, interacciones y actualización explícita.
- /api/scripts y /api/scripts-statistics: guiones, versiones y resultados.
- /api/dashboard y /api/search-history: evolución e historial de ejecuciones.
- /api/searches/{id}/next-batch: preparación del siguiente lote.
- /api/scanning y /api/scanning/{web|public|signals|apollo|all}/stop, /api/scanning/{web|public|signals|apollo}/resume: estado, parada y continuación del escaneo continuo.
- /api/signals, /api/signals/targets, /api/signals/searches y /api/signals/{uuid}/review: noticias, fuentes, vigilancia y revisiones.
- /api/apollo: descubrimiento, incorporación de candidatos, enriquecimiento, saldo y recuperación de teléfonos.
- /api/imports/csv: previsualización y asignación de columnas.
- /api/settings/apollo, /api/settings/ollama, /api/settings/actor y /api/shared: conexiones y datos portables.

### Varias palabras clave en Apollo

En **Búsquedas → Apollo**, guarda tu API key directamente en el bloque de conexión. El descubrimiento usa cero créditos, pero requiere una clave y acceso al endpoint People API Search de tu cuenta; la elegibilidad gratuita puede depender de la cuenta. Puedes dejar el presupuesto de enriquecimiento en cero. [Documentación oficial](https://docs.apollo.io/reference/people-api-search).

Introduce hasta 20 palabras o frases, una por línea o separadas por comas/punto y coma. Cada frase se busca por separado, manteniendo espacios internos, país, cargos y tamaño. Los resultados se unen por identificador de Apollo, LinkedIn o identidad completa. El modo continuo pasa a la siguiente página de esas consultas. Si una consulta falla o detienes la ejecución, se conservan los candidatos anteriores. No se solicitan correos ni teléfonos al descubrir personas.

### Ajustes y resultados de Apollo

La interfaz utiliza la marca **Kerna Client Research**. Ajustes se divide en Conexiones, Mi perfil, Datos e historial y Modelo local. Las claves se muestran en campos protegidos; las opciones de enriquecimiento están plegadas por defecto y conservan sus límites. La tabla de candidatos de Apollo se muestra únicamente cuando hay perfiles disponibles. Los resúmenes de ejecuciones pertenecen al proveedor seleccionado: una búsqueda web no se presenta como una ejecución de Apollo.

### Comprobar acceso gratuito de Apollo

Guardar una clave no verifica el acceso a la API. En Búsquedas → Apollo o Ajustes → Conexiones, pulsa **Comprobar acceso gratuito**. Se consulta únicamente People API Search con un resultado, sin enriquecimiento ni créditos. El estado distingue clave guardada, acceso verificado y cuenta sin acceso. Algunas cuentas Free reciben HTTP 403 `API_INACCESSIBLE`, incluso con master key; en ese caso puedes seguir con la búsqueda web o importar CSV. El diagnóstico queda en la configuración privada y no se incluye en `shared-data/`.

### Apollo gratuito con contactos guardados

En **Búsquedas → Apollo → Origen de Apollo**, puedes seleccionar **Sincronizar contactos guardados**. Usa el endpoint oficial `contacts/search` (0 créditos), lee tu lista guardada y la incorpora a la misma agenda con deduplicación y protección de contactados. No descubre personas nuevas ni solicita enriquecimiento. Las palabras clave y la página se aplican a la lista guardada; los filtros corporativos pertenecen al modo de descubrimiento. En continuo, revisa nuevas incorporaciones cada cinco minutos, alternando con web. Los contactos sin identidad completa permanecen para revisión. Las cuentas gratuitas que usan el descubrimiento API necesitan correo de empresa y cumplir los requisitos de Apollo; consulta https://docs.apollo.io/reference/people-api-search.
