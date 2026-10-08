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

Se procesan hasta cuatro gestoras por lote, máximo 20 búsquedas básicas y 16 lecturas corporativas. Se conservan las gestoras adicionales para lotes posteriores. Las consultas y páginas idénticas se reutilizan durante siete días. Una sola ejecución puede estar activa. Puedes activar web, datos públicos y Apollo a la vez: el servidor alterna los lotes de los orígenes activos, con una pausa de 30 segundos entre lotes de cada origen. Cerrar la pestaña no detiene el escaneo; cerrar el programa sí. Detener conserva resultados y avance. Tras reiniciar el servidor, debes pulsar **Continuar** para reanudar.

Si se agota la cuota gratuita o el proveedor devuelve un error, se detiene ese origen y se muestra el motivo. Cuando se recorren todos los filtros o consultas preparados, permanece en espera y vuelve a comprobarlos a los siete días, sin repetir peticiones continuamente. Puedes detener y configurar otros términos o filtros para avanzar antes.

La aplicación lee resultados públicos y HTML corporativo respetando robots.txt; no automatiza sesiones de LinkedIn. Descarta informes, asociaciones y eslóganes como nombres de gestoras. Extrae datos estructurados, tarjetas de equipo y cargos explícitos, con fuente y fecha. Los datos ambiguos quedan pendientes y pueden corregirse manualmente.

La cuota local de Tavily es un contador conservador: reserva un crédito por petición nueva incluso si falla. MONTHLY_SEARCH_LIMIT puede reducir el máximo de 1.000. No incluye el uso desde otras aplicaciones. Los errores de cuota detienen el lote. [Créditos de Tavily](https://docs.tavily.com/documentation/api-credits).

## Escaneo de datos públicos sin Apollo

En **Búsquedas → Datos de contacto**, pulsa **Buscar datos de contacto**. Revisa las webs corporativas, tarjetas de equipo y biografías de las personas ya descubiertas, y guarda correos, teléfonos, LinkedIn y fotos claramente asociados a cada persona. No requiere una clave adicional ni consume créditos de Tavily o Apollo. La búsqueda web continúa descubriendo personas y este segundo escaneo completa la misma agenda. Ambos pueden permanecer activos y alternan sus lotes.

Cada lote revisa hasta cuatro personas y 16 páginas únicas. El modo continuo espera cinco minutos cuando termina la agenda y vuelve a revisarla; las páginas se reutilizan durante siete días. Las personas ya contactadas se omiten. También puedes seleccionar filas y usar **Buscar datos públicos** para revisar solo esas personas. Se conservan los datos manuales; los correos contradictorios quedan para revisión. No se asigna a una persona el correo general ni el teléfono del pie de página de su gestora.

La disponibilidad depende de lo publicado. Este escaneo no permite revelar correos o móviles privados de LinkedIn. Una foto de su CDN se muestra cuando aparece asociada a la persona en una fuente accesible; si no hay foto pública o no carga, se muestran iniciales.

## Contactos y conversaciones

**Inicio** contiene los indicadores, la gráfica conjunta y los accesos a la agenda. **Búsquedas** contiene los controles de los dos escaneos. Web, Apollo y CSV alimentan esa misma agenda, con un filtro de calificación: objetivo, por verificar o fuera del objetivo. La puntuación representa encaje comercial: cargo decisor 40; gestor 25 o analista 10; renta variable 30; tamaño 5–200 empleados 20; análisis/selección de acciones 10. Cada aportación necesita evidencia. Alta prioridad desde 80; media desde 60.

**Contactos** muestra la agenda en su propia página, con páginas de 50 filas, búsqueda, filtros por país, cargo, tamaño, prioridad, calificación, etapa, responsable y canales disponibles. La búsqueda, la calificación, la puntuación mínima (0–100) y los canales disponibles quedan a la vista; **Más filtros** despliega país, cargo, etapa, tamaño, responsable y canal. Por defecto solo muestra personas con LinkedIn, correo o teléfono; **Sin datos de contacto · revisar** conserva accesibles los perfiles incompletos. Cerrar ese panel conserva los filtros activos, con un contador y botón para limpiarlos. La barra A–Z incluye Ñ y trata los nombres con acentos por su inicial. Puedes exportar la lista filtrada o el CSV completo.

- Los botones de llamada, correo y mensaje abren primero **Información**, con el LinkedIn real, correo, teléfono y fuentes del contacto. Pulsarlos no registra una interacción ni marca a la persona como contactada. **Registrar interacción** muestra el formulario rápido de canal, resultado y nota; **Historial** muestra las conversaciones anteriores. El responsable y la fecha se guardan automáticamente. **Seguimiento y otros detalles** permite cambiarlos y programar la próxima acción; el guion se muestra cuando hay guiones disponibles. Los datos de correo/teléfono se editan en un bloque aparte, cerrado por defecto.
- Cualquier llamada o mensaje excluye a esa persona de nuevos escaneos/enriquecimientos. También se excluyen los descartados.
- Los ya contactados siguen disponibles para seguimiento. **Volver a buscar** permite una actualización web explícita sin borrar conversaciones.
- Los comentarios por sí solos conservan la etapa actual. Puedes cerrar un seguimiento pendiente expresamente.
- Corregir una interacción crea un registro que sustituye al anterior; ambos permanecen en el historial.
- Las fotos se muestran cuando una fuente las asocia al contacto. Una foto ausente o inaccesible se sustituye por iniciales.

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

En Búsquedas, Web y Apollo tienen pestañas propias. Para buscar en la web basta con palabras clave y mercado; el avance continuo está activado por defecto. Las consultas se preparan automáticamente y son editables dentro de Opciones avanzadas. Un escaneo explícito de una persona nunca se utiliza como criterio del siguiente lote general.

## Datos compartidos y copias del repositorio

SQLite operativo: **data/scout.sqlite**, ignorado por Git. Antes de la ampliación se guardó una copia en data/backups/before-crm.sqlite.

Cada cambio genera automáticamente **shared-data/**:

- JSON con identificadores estables de gestoras, contactos, interacciones, guiones, observaciones y resúmenes de ejecuciones.
- contactos.csv e interacciones.csv, legibles con Excel: UTF-8 con BOM, punto y coma y protección frente a fórmulas.

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
- /api/scanning y /api/scanning/{web|apollo|all}/stop, /api/scanning/{web|apollo}/resume: estado, parada y continuación del escaneo continuo.
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
