# Contexto para agentes - ProyectoRagFacultad2

Este archivo guarda contexto operativo actualizado para continuar la migracion del RAG original de Docker hacia el RAG de Hemeroteca La Plata. Se debe ir completando a medida que avancen `PLAN_HEMEROTECA_RAG.md` y `FASE1B_SCRAPER_PAGINA12.md`.

## Guia principal

- Skill local: `SKILL.md`, nombre `rag-implementer`.
- Plan general: `PLAN_HEMEROTECA_RAG.md`.
- Fase especifica actual/complementaria: `FASE1B_SCRAPER_PAGINA12.md`.
- Implementar una fase por vez y mantener cambios chicos.
- No reintroducir `translator.py`; el pipeline objetivo trabaja en espanol.
- No tocar `data/raw/` manualmente salvo desde scrapers o pruebas controladas.

## Estado actual relevante

Estamos trabajando sobre Fase 1 / Fase 1B.

Objetivo de esta parte: probar un flujo minimo para una fecha concreta de Pagina/12:

1. descubrir URLs de articulos de una fecha;
2. descargar HTML real de esas URLs;
3. parsear HTML con `trafilatura`;
4. persistir texto limpio + metadata en `backend/data/parsed`.

Esto todavia no indexa en Qdrant. El paso siguiente despues de parsed es chunking, enrichment e indexacion.

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
backend/data/gazetteer/la_plata_partidos.json
```

Busca menciones exactas, case-insensitive, de:

```text
city
neighborhoods
nearby_partidos
landmarks
```

Si encuentra lugares, los guarda en:

```text
location_mentions
```

Y elige:

```text
primary_location
```

Regla actual:

- si aparece `La Plata`, `primary_location = "La Plata"`;
- si no aparece La Plata pero aparece otro lugar del gazetteer, usa el primero;
- si no aparece ningun lugar del gazetteer, `primary_location = null` y `location_mentions = []`.

Esto explica casos como una nota nacional sobre Alfonsin/UCR: aunque sea de 2005 y Pagina/12, si el chunk no menciona La Plata, Berisso, Ensenada, barrios o landmarks cargados, los campos de ubicacion quedan vacios. Es esperado.

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

### `--stage all`

Ejecuta todo:

```text
scrape -> parse -> chunk -> enrich -> index
```

Solo usar cuando se quiera guardar en Qdrant.

## Tests utiles

Desde `E:\ProyectoRagFacultad2`:

```powershell
python -m pytest backend\tests\test_pagina12_scraper.py backend\tests\test_html_parser.py -q
```

Ultima verificacion conocida:

```text
16 passed
```

## Pendientes inmediatos

- Avanzar con chunking, enrichment con NER/gazetteer e indexacion en Qdrant para los documentos parseados.
- Mantener `PLAN_HEMEROTECA_RAG.md` como guia principal y completar este `AGENTS.md` cuando haya decisiones nuevas.
