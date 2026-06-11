# Contexto para agentes - ProyectoRagFacultad2

Este archivo guarda contexto operativo actualizado para continuar la migracion del RAG original de Docker hacia el RAG de Hemeroteca Argentina con Pagina/12. Se debe ir completando a medida que avancen `PLAN_HEMEROTECA_RAG.md`, `FASE1B_SCRAPER_PAGINA12.md` y `Fase1C.md`.

## Guia principal

- Skill local: `SKILL.md`, nombre `rag-implementer`.
- Plan general: `PLAN_HEMEROTECA_RAG.md`.
- Fase especifica actual/complementaria: `FASE1B_SCRAPER_PAGINA12.md` + `Fase1C.md`.
- Implementar una fase por vez y mantener cambios chicos.
- No reintroducir `translator.py`; el pipeline objetivo trabaja en espanol.
- No tocar `data/raw/` manualmente salvo desde scrapers o pruebas controladas.

## Estado actual relevante

Estamos trabajando sobre Fase 1 / Fase 1B / Fase 1C.

Objetivo de esta parte: probar un flujo minimo para una fecha concreta de Pagina/12:

1. descubrir URLs de articulos de una fecha;
2. descargar HTML real de esas URLs;
3. parsear HTML con `trafilatura`;
4. persistir texto limpio + metadata en `backend/data/parsed`;
5. chunquear texto;
6. enriquecer metadata con NER, gazetteer, scope por chunk y scope por articulo.

El stage `preview` no indexa en Qdrant. `all`/`index` ejecuta tambien indexacion.

`backend/app/ingestion/run.py` ya fue adaptado para usar Pagina/12 como fuente principal. El scraper viejo de El Dia fue eliminado.

## Flujo Pagina/12 implementado

Archivo principal:

```text
backend/app/ingestion/scrapers/pagina12.py
```

Tests:

```text
backend/tests/test_pagina12_scraper.py
backend/tests/test_html_parser.py
```

### 1. Descubrir URLs por fecha

Desde `E:\ProyectoRagFacultad2\backend`, con venv activado:

```powershell
python -m app.ingestion.scrapers.pagina12 --date 06-03-2005
```

Genera o reutiliza:

```text
E:\ProyectoRagFacultad2\data\raw\pagina12\2005\03\urls_06-03-2005.json
```

Ese JSON contiene URLs, titulo y snippet. No contiene el cuerpo completo del articulo.

### 2. Descargar HTML real de las URLs

Ejemplo con solo 1 articulo:

```powershell
python -m app.ingestion.scrapers.pagina12 --date 06-03-2005 --download --urls-path ..\data\raw\pagina12\2005\03\urls_06-03-2005.json --max-articles 1
```

Genera:

```text
E:\ProyectoRagFacultad2\backend\data\raw\pagina12\2005\03\*.html
E:\ProyectoRagFacultad2\backend\data\raw\pagina12\2005\03\*.json
```

El `.html` es la fuente cruda completa. El `.json` al lado es un sidecar con metadata de trazabilidad: `source_url`, `publication_date`, `newspaper`, `article_title`, `section`, `snippet`.

### 3. Parsear HTML y obtener texto limpio

Archivo principal:

```text
backend/app/ingestion/parsers/html_parser.py
```

Comando:

```powershell
python -m app.ingestion.run --stage parse --date 06-03-2005
```

Genera:

```text
E:\ProyectoRagFacultad2\backend\data\parsed\pagina12\2005\03\documents_06-03-2005.json
```

El contenido del articulo sin HTML queda en:

```json
documents[0].page_content
```

La metadata queda en:

```json
documents[0].metadata
```

### 4. Verificar contenido parseado rapido

Desde `E:\ProyectoRagFacultad2\backend`:

```powershell
python -c "import json; p=json.load(open('data/parsed/pagina12/2005/03/documents_06-03-2005.json', encoding='utf-8')); print(p['total_documents']); print(p['documents'][0]['page_content'][:1000])"
```

## Separacion de carpetas

```text
data/raw/pagina12/.../urls_DD-MM-YYYY.json
```

Indice de URLs descubiertas. Esta fuera de `backend/` porque fue el output inicial de Fase 1B.

```text
backend/data/raw/pagina12/.../*.html
backend/data/raw/pagina12/.../*.json
```

HTML crudo descargado y sidecar de metadata por articulo.

```text
backend/data/parsed/pagina12/.../documents_DD-MM-YYYY.json
```

Texto limpio extraido por `trafilatura` + metadata. Este es el input esperado para chunking/enrichment/indexacion.

## Detalles tecnicos implementados

- `pagina12.py` valida fechas `DD-MM-YYYY`.
- Descubrimiento reanudable: si existe `urls_DD-MM-YYYY.json`, no redescubre.
- Descarga de HTML reanudable: si existen `.html` y `.json` sidecar, saltea salvo `--force`.
- Se usa `httpx`, `tenacity`, `logging` y rate limit.
- Se verifica `robots.txt` antes de requests cuando es posible.
- El scraper filtra notas de archivo por fecha embebida en la URL para evitar duplicados de suplementos de otros dias.
- `html_parser.py` usa `trafilatura.extract`.
- El parser persiste JSON de parsed con escritura atomica.
- El parser repara mojibake comun de HTML historico durante normalizacion.
- El enrichment calcula `country_scope` y `scope_signals` para clasificar articulos vinculados con Argentina mediante cascada heuristica -> embeddings -> LLM local opcional.
- El gazetteer activo es nacional: `backend/data/gazetteer/argentina.json`.

## Flujo completo de `run.py`

`backend/app/ingestion/run.py` orquesta el flujo principal de Fase 1 con Pagina/12.

Stages:

```text
scrape -> parse -> chunk -> enrich -> index
```

### `--stage scrape`

Hace descubrimiento de URLs y descarga HTML real.

```powershell
python -m app.ingestion.run --stage scrape --date 06-03-2005 --max-articles 1
```

Produce:

```text
data/raw/pagina12/YYYY/MM/urls_DD-MM-YYYY.json
backend/data/raw/pagina12/YYYY/MM/*.html
backend/data/raw/pagina12/YYYY/MM/*.json
```

El `.json` junto al HTML es sidecar de metadata cruda. No contiene el texto completo limpio.

### `--stage parse`

Lee HTML crudo + sidecar y produce documentos parseados.

```powershell
python -m app.ingestion.run --stage parse --date 06-03-2005
```

Produce:

```text
backend/data/parsed/pagina12/YYYY/MM/documents_DD-MM-YYYY.json
```

Cada documento parseado tiene:

```text
Document.page_content = texto limpio completo del articulo
Document.metadata = metadata base del articulo
```

### Chunking

El chunking se hace sobre `Document.page_content`, no sobre la metadata.

La metadata del articulo se copia a cada chunk. Luego el chunker agrega campos propios:

```text
chunk_index
total_chunks
chunk_id
```

Modelo mental:

```text
articulo completo + metadata
        ↓
chunk 0: fragmento de texto + copia de metadata + chunk_index=0
chunk 1: fragmento de texto + copia de metadata + chunk_index=1
...
```

### Enrichment

`backend/app/ingestion/metadata.py` enriquece cada chunk individualmente.

Usa:

```text
backend/app/ingestion/enrichers/ner.py
backend/app/ingestion/enrichers/gazetteer.py
```

Campos agregados o normalizados:

```text
publication_date
year
decade
persons
organizations
location_mentions
primary_location
text
text_clean
source_pdf_path
ocr_confidence
page_number
```

`text` y `text_clean` son el texto del chunk, no el articulo completo.

### spaCy NER

`ner.py` carga `es_core_news_md` de spaCy de forma lazy y cacheada. Se usa para detectar entidades dentro del texto de cada chunk.

Actualmente se conservan:

```text
PER/PERSON -> persons
ORG        -> organizations
```

Importante: spaCy puede equivocarse. Por ejemplo puede detectar palabras comunes como persona u organizacion si el contexto lo confunde. El preview sirve para inspeccionar estos casos.

### Gazetteer

`gazetteer.py` carga:

```text
backend/data/gazetteer/argentina.json
```

Busca menciones exactas, case-insensitive, de:

```text
provinces
cities
institutions
political_organizations
clubs
landmarks si existieran
```

Si encuentra lugares, los guarda en:

```text
location_mentions
```

Y elige:

```text
primary_location
```

Regla actual de ubicacion:

- si aparece `Argentina`, `primary_location = "Argentina"`;
- si no aparece Argentina pero aparece otro lugar del gazetteer, usa el primero;
- si no aparece ningun lugar del gazetteer, `primary_location = null` y `location_mentions = []`.

Esto explica casos como una nota nacional sobre Alfonsin/UCR: aunque sea de 2005 y Pagina/12, si el chunk no menciona topónimos cargados, los campos de ubicacion quedan vacios. Es esperado.

Importante: el matcher del gazetteer usa limites de palabra y normalizacion de acentos. No debe detectar `CABA` dentro de palabras como `caballito`; solo detecta `CABA` como termino independiente.

### Country scope

El sistema no depende de que el texto diga literalmente `Argentina`.

`scope_classifier.py` clasifica cada chunk con:

```text
country_scope = argentina | international | unknown
scope_signals = lista de senales usadas
article_country_scope = argentina | international | unknown
article_scope_signals = senales agregadas a nivel articulo
```

Clasificador actual (`Fase1C.md`):

- Capa 1 heuristica: secciones nacionales y suplementos nacionales clasifican `argentina` por `seccion:<nombre>`.
- Capa 1 distingue senales fuertes y debiles. Senales fuertes: ubicaciones argentinas validadas, instituciones inequivocas argentinas, organizaciones politicas argentinas, clubes argentinos detectados como organizacion y terminos explicitamente argentinos.
- Senales debiles como `weak_institution:Senado`, `weak_institution:Congreso` o `contextual_term:derechos humanos` no clasifican `argentina` por si solas; quedan auditadas y el chunk pasa a embeddings/LLM.
- Secciones no directas como `elmundo`, `espectaculos`, `contratapa`, `cultura`, `plastica`, `psicologia`, `deportes`, `suplementos/libero` y `suplementos/libros` nunca clasifican por seccion sola.
- `elmundo` sin señales argentinas ya no clasifica directo como `international`; queda `unknown` y pasa a embeddings si estan disponibles.
- Chunks con menos de 100 caracteres quedan `unknown` directo.
- Capa 2 embeddings: compara el chunk contra anclas argentinas, internacionales y `unknown`. Clasifica solo si el ganador supera al segundo por `SCOPE_EMBEDDING_THRESHOLD`.
- Las senales de capa 2 son `emb_arg:<score>`, `emb_int:<score>`, `emb_unknown:<score>` y `emb_margin:<margin>`.
- Capa 2 usa embeddings tipo `passage:` (`embed_documents`) para anclas y chunk. Si calcula el embedding del chunk, lo guarda temporalmente en `_index_vector` para que Qdrant pueda reutilizarlo.
- `_index_vector` es interno y transitorio: no debe escribirse en JSON parsed ni subirse como payload a Qdrant.
- Capa 3 LLM local: solo se usa en zona gris de embeddings, contra Ollama local si `SCOPE_LLM_ENABLED=true`.
- El prompt de capa 3 tiene few-shot estricto para evitar falsos positivos en textos literarios/conceptuales sin evidencia argentina.
- Modelo LLM default: `qwen2.5:3b-instruct`, configurable con `SCOPE_LLM_MODEL`.
- Si el LLM esta deshabilitado, no disponible, el texto es corto o responde algo invalido, el resultado queda `unknown` y deja una senal auditable (`llm_skipped:*`, `llm_error:*` o `llm_local:<modelo>:unknown`).
- Un chunk puede tener `country_scope="argentina"` y a la vez `location_mentions=[]`. Ejemplo: una nota de `elpais` sobre Alfonsin/UCR sin topónimos explícitos.
- `metadata.py` agrega scope por articulo agrupando por `source_id`. Un chunk puede quedar `country_scope="unknown"` pero `article_country_scope="argentina"` si otro chunk del mismo articulo tiene evidencia fuerte.

- Un unico `country_scope="argentina"` decidido solo por LLM no alcanza para elevar todo el articulo; se requieren senales no LLM o multiples chunks LLM.
- Caso esperado: un chunk conceptual puede quedar `country_scope="unknown"` y `article_country_scope="argentina"` si otros chunks del mismo articulo mencionan Argentina, Rosario, CABA, instituciones o terminos argentinos.

### `--stage preview`

Stage de prueba agregado para inspeccionar flujo sin indexar.

```powershell
python -m app.ingestion.run --stage preview --date 06-03-2005 --max-articles 1 --preview-limit 2 --preview-chars 600
```

Ejecuta:

```text
scrape -> parse -> chunk -> enrich -> imprimir chunks enriquecidos
```

No indexa en Qdrant.

El preview debe mostrar `country_scope`, `scope_signals`, `article_country_scope`, `article_scope_signals`, `section`, `location_mentions`, `organizations` y `persons`.

Para probar secciones ambiguas y evitar que los primeros articulos sean todos `elpais`, se puede usar `--sections`:

```powershell
python -m app.ingestion.run --stage preview --date 06-03-2005 --sections suplementos/libros,elmundo,cultura,contratapa --max-articles 5 --force --preview-limit 40 --preview-chars 700
```

### `--stage all`

Ejecuta todo:

```text
scrape -> parse -> chunk -> enrich -> index
```

Solo usar cuando se quiera guardar en Qdrant.

Para indexacion definitiva se usa `--reset-index` si se quiere borrar/recrear la coleccion Qdrant antes de cargar. `--force` solo redescarga/redescarga archivos HTML existentes; no debe usarse como sinonimo de reset de Qdrant.

Por defecto la indexacion guarda solo chunks cuyo `article_country_scope` entra en `--index-scope argentina`. Para mayor recall se puede usar `--index-scope argentina,unknown`; para debug completo, `--index-scope all`.

Carga anual 2005 recomendada:

```powershell
python -m app.ingestion.run --stage all --year 2005 --reset-index --index-scope argentina
```

Carga por rango, util para hacerlo por mes:

```powershell
python -m app.ingestion.run --stage all --date-from 01-01-2005 --date-to 31-01-2005 --reset-index --index-scope argentina
python -m app.ingestion.run --stage all --date-from 01-02-2005 --date-to 28-02-2005 --index-scope argentina
```

Estructura de datos esperada:

```text
data/raw/pagina12/YYYY/MM/urls_DD-MM-YYYY.json
backend/data/raw/pagina12/YYYY/MM/*.html
backend/data/raw/pagina12/YYYY/MM/*.json
backend/data/parsed/pagina12/YYYY/MM/documents_DD-MM-YYYY.json
```

Qdrant recibe payload completo del chunk, incluyendo `country_scope`, `article_country_scope`, fechas, seccion, entidades, ubicaciones y `text`.

`vector_store.index_documents()` reutiliza `_index_vector` cuando esta disponible y calcula embeddings solo para chunks faltantes. Soporta mezcla de chunks con y sin `_index_vector`; el orden de vectores se conserva y `_index_vector` se elimina del payload antes del upsert.

Para inspeccionar lo cargado en Qdrant:

```powershell
python -m app.retrieval.inspect_store --date 2005-01-02 --article-scope argentina --limit 10 --chars 700
```

Filtros utiles:

```powershell
python -m app.retrieval.inspect_store --date 2005-01-02 --section elpais --limit 5
python -m app.retrieval.inspect_store --article-scope argentina --scope unknown --limit 10
python -m app.retrieval.inspect_store --limit 20 --chars 300
```

## Tests utiles

Desde `E:\ProyectoRagFacultad2`:

```powershell
python -m pytest backend\tests\test_pagina12_scraper.py backend\tests\test_html_parser.py backend\tests\test_run_ingestion.py backend\tests\test_gazetteer.py backend\tests\test_scope_classifier.py backend\tests\test_metadata_enrichment.py backend\tests\test_vector_store_reuse.py -q
```

Ultima verificacion conocida:

```text
43 passed, 1 skipped
```

## Detalles técnicos de recuperación y generación (Fase 2 / Rerank & Hybrid)

- **Qdrant API Update**: Se migró de `client.search` (removido/deprecado en `qdrant-client>=1.18.0`) a `client.query_points` en `vector_store.py`.
- **QueryPlanner robusto**: 
  - Se hizo que `search_query` en `QueryPlan` sea opcional (`str | None = None`) con fallback al `question` original para evitar excepciones cuando OpenWebUI genera llamadas internas (como títulos automáticos o tags) y devuelve `search_query` nulo.
  - Se implementó un filtro de post-procesamiento de fechas: si el planner infiere erróneamente un primer día del mes (`YYYY-MM-01`) sin que la consulta lo especifique explícitamente (ej: "enero de 2005" vs "1 de enero"), se remueve el filtro de fecha exacta y se mantiene el año general, evitando que se excluyan los documentos indexados de otros días de ese mes.
- **Fuentes en OpenWebUI**: Se puebla el campo `sources` en la respuesta RAG para delegar la visualización de referencias directamente al arreglo que maneja el frontend, permitiendo citar correctamente sin interferir con la coherencia gramatical del prompt de generación.

## Flujo del Retriever y Pipeline RAG (Detalles de Implementación)

### 1. Planificación de Consultas (`query_planner.py`)
El `QueryPlanner` utiliza un LLM estructurado (Groq `llama-3.3-70b-versatile`) para clasificar la intención (`CHITCHAT`, `ARCHIVE_SEARCH`, `OUT_OF_SCOPE`) y extraer metadatos estructurados como `year`, `decade`, `publication_date`, y `section`.
* **Heurística de Saludos**: Se interceptan saludos y despedidas de forma local y ultrarrápida usando expresiones regulares para evitar llamadas innecesarias al LLM.
* **Limpieza de Fechas**: Si el LLM infiere una fecha exacta del tipo `YYYY-MM-01` (por ejemplo, al leer "enero de 2005") sin que el usuario haya especificado un día real (como "1ro" o "1"), el planificador limpia el campo `publication_date` dejándolo en `None` para evitar que un filtro exacto descarte notas de otros días del mes (ej. del `2005-01-03`).

### 2. Recuperación Híbrida (`hybrid.py`)
La búsqueda combina el buscador léxico (BM25) y el semántico (Qdrant) mediante la clase `CustomHybridRetriever`.
* **Inicialización de BM25**: Como el retriever de BM25 corre en memoria, al iniciar el pipeline se realiza un scroll paginado de Qdrant (`_load_documents_for_bm25` en `pipeline.py`) para descargar todos los chunks y construir el corpus tokenizado en español.
* **Filtros cruzados**: Tanto el buscador léxico como el semántico reciben y aplican los filtros de metadatos (año, sección, diario) de forma estricta antes de puntuar.
* **Pesos Adaptativos Heurísticos (`_determine_retrieval_weights`)**:
  * Utiliza **spaCy** (`es_core_news_md`) para analizar la estructura sintáctica de la consulta.
  * Si la consulta es **puntual/fáctica** (contiene números, entidades `PER`, `ORG` o fechas): Se asigna `bm25_weight = 0.6` y `semantic_weight = 0.4`.
  * Si la consulta es **conceptual/abstracta** (no contiene números ni entidades y posee mayor densidad de verbos/adjetivos genéricos): Se asigna `semantic_weight = 0.6` y `bm25_weight = 0.4`.
  * Por defecto: Pesos equilibrados de `0.5` / `0.5`.
* **Fusión por RRF (Reciprocal Rank Fusion)**: Combina los rankings de BM25 y Qdrant aplicando la fórmula estándar de RRF con constante de suavizado $k=60$.

### 3. Reranking (`reranker.py`)
Los chunks recuperados se pasan por un reranker de paso secundario para refinar la relevancia semántica de los textos respecto a la consulta.
* Admite dos modos:
  1. **FlashRank** (por defecto, usando el modelo multilingüe `ms-marco-MultiBERT-L-12` para CPU liviano).
  2. **CrossEncoder de SentenceTransformers** (si se configura una ruta de modelo en settings).
* El reranker anota en los metadatos de cada chunk: `rrf_score`, `bm25_rank`, `semantic_rank`, y el score final del rerankeo (`rerank_score`).

### 4. Verificación de Evidencia (`evidence_checker.py`)
Antes de llamar al LLM generador, el RAG evalúa si los chunks recuperados contienen suficiente evidencia para responder con certeza y evitar alucinaciones.
* **Consistencia Temporal Estricta**: Si la consulta menciona un año (ej. `2005`) pero ningún chunk de los recuperados corresponde a ese año en su metadata, se rechaza la búsqueda por inconsistencia temporal y se retorna `INSUFFICIENT`.
* **Umbrales adaptativos según intención**:
  * **Consultas Puntuales/Fácticas** (peso de BM25 > 0.5): Requiere que pertenezcan al menos a 1 artículo único y (que haya al menos 2 fragmentos relevantes o al menos 1 fragmento con un score superior a `min_top_score`).
  * **Consultas Amplias/Resumen** (peso Semántico > 0.5): Requiere al menos 3 fragmentos relevantes distribuidos en un mínimo de 2 artículos distintos para asegurar representatividad. De lo contrario, se retorna `LOW_CONFIDENCE` para permitir una respuesta parcial.
  * En caso de no superar los umbrales mínimos, el sistema se abstiene y devuelve el mensaje de abstención configurado: `"No tengo suficiente información en el archivo consultado."` sin llamar al LLM de generación.

### 5. Generación de Respuesta (`generator.py`)
Si la evidencia es suficiente, se formatea el contexto incluyendo identificadores de documento, títulos, fechas y URLs.
* Se invoca a Groq (`llama-3.3-70b-versatile`) con instrucciones estrictas de no inventar datos y responder solo con el contexto provisto.
* Toda la metadata y fragmentos recuperados se inyectan en el arreglo `sources` para que el frontend de OpenWebUI renderice las tarjetas de fuentes correctamente debajo de la respuesta (los títulos de las fuentes ahora se formatean como enlaces Markdown clickeables y se deduplican en la lista de "Fuentes" al final del texto).

### 6. Proveedor de Embeddings API (Google gemini-embedding-001)
Se implementó soporte dinámico de proveedores de embeddings configurables en `.env`:
* **Variables**:
  * `EMBEDDING_PROVIDER`: `"local"` (SentenceTransformer local) o `"gemini"` (Google AI Studio embeddings API).
  * `GEMINI_API_KEY`: Tu API key de Google AI Studio (requerida si `EMBEDDING_PROVIDER=gemini`).
* **Modelo**: `gemini-embedding-001` (dimensión `768`).
* **Reset de Indexación**: Debido al cambio de dimensión (de `1024` del modelo local a `768` de Google), es obligatorio reiniciar la colección de Qdrant pasando el flag `--reset-index` al momento de la ingesta para que recree la colección con la dimensión correcta.
* **Control de Rate Limits y Reintentos (Gemini)**:
  - Para la clave gratuita de Gemini (15 RPM), se redujo el tamaño de lote a `batch_size = 20` con una espera de `time.sleep(4.0)` entre lotes en `vector_store.py` para mantenerse por debajo del límite de tasa.
  - Se configuró un decorador de reintento (`tenacity`) de hasta 7 intentos con espera exponencial de hasta 30s en peticiones HTTP para tolerar picos o demoras de la API externa de manera resiliente.

### 7. Reconstrucción Dinámica de Artículos
Para evitar problemas de fragmentación y pérdida de contexto (como el caso en el que la respuesta a una pregunta compleja se encuentra en partes distantes de una misma nota de Página/12):
* El pipeline recibe los chunks rerankeados y extrae los primeros `max_articles=3` identificadores únicos de artículos (`source_id`).
* Consulta a Qdrant mediante scroll filtrado todos los fragmentos pertenecientes a esos artículos y los une ordenándolos según su `chunk_index`.
* Esto proporciona al LLM el artículo completo unificado en el prompt de generación, lo cual de-duplica el contexto y previene alucinaciones o respuestas incompletas.

### 8. Logging de recuperación detallado en Terminal
Se agregaron logs descriptivos en `pipeline.py` para visualizar en tiempo real:
* El listado ordenado de chunks recuperados indicando su score del reranker, score RRF, fecha, sección, título del artículo, y un snippet de su contenido.
* El veredicto del verificador de evidencia con sus métricas clave.

## Tests utiles

Desde `E:\ProyectoRagFacultad2`:

```powershell
python -m pytest backend\tests\test_pagina12_scraper.py backend\tests\test_html_parser.py backend\tests\test_run_ingestion.py backend\tests\test_gazetteer.py backend\tests\test_scope_classifier.py backend\tests\test_metadata_enrichment.py backend\tests\test_vector_store_reuse.py backend\tests\test_gemini_embeddings.py backend\tests\test_reranker_and_pipeline.py -q
```

Ultima verificacion conocida:

```text
63 passed, 1 skipped
```

## Pendientes inmediatos

- Validar con `preview` varias fechas/secciones adicionales.
- Expandir la ingesta de fechas del año 2005 (`--stage all --year 2005`) para contar con un volumen mayor de documentos.
- Avanzar con la Fase 4 del plan para el soporte de archivos PDF históricos con OCR (BNA/Internet Archive).
- Mantener `PLAN_HEMEROTECA_RAG.md` como guía principal.
