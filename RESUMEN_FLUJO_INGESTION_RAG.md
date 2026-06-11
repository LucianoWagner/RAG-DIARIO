# Resumen del flujo de ingestion RAG

Este documento explica la parte de ingestion del proyecto `ProyectoRagFacultad2`: desde el scraping de Pagina/12 hasta la creacion de embeddings y el guardado de chunks en Qdrant.

La fuente principal para entender el flujo es:

```text
backend/app/ingestion/run.py
```

Ese archivo orquesta los pasos:

```text
scrape -> parse -> chunk -> enrich -> index
```

El pipeline actual esta pensado para trabajar en espanol y con articulos historicos de Pagina/12. No usa `translator.py`.

## Objetivo general

El objetivo de esta fase es convertir articulos HTML de Pagina/12 en documentos indexables para un sistema RAG:

1. Descubrir URLs de articulos de una fecha.
2. Descargar el HTML real de cada articulo.
3. Extraer texto limpio con `trafilatura`.
4. Guardar documentos parseados con metadata base.
5. Dividir cada articulo en chunks.
6. Enriquecer cada chunk con entidades, ubicaciones y alcance nacional.
7. Crear embeddings.
8. Guardar los chunks como puntos en Qdrant.

Modelo mental completo:

```text
Fecha Pagina/12
  |
  v
urls_DD-MM-YYYY.json
  |
  v
HTML crudo + sidecar JSON por articulo
  |
  v
Document(page_content=texto limpio, metadata=metadata articulo)
  |
  v
chunks con metadata heredada
  |
  v
chunks enriquecidos con NER + gazetteer + country_scope
  |
  v
embedding vectorial
  |
  v
Qdrant: vector + payload metadata + text
```

## Archivos principales

| Responsabilidad | Archivo |
|---|---|
| Orquestacion de ingestion | `backend/app/ingestion/run.py` |
| Scraper Pagina/12 | `backend/app/ingestion/scrapers/pagina12.py` |
| Parser HTML con trafilatura | `backend/app/ingestion/parsers/html_parser.py` |
| Chunking | `backend/app/ingestion/chunker.py` |
| Enriquecimiento de metadata | `backend/app/ingestion/metadata.py` |
| NER con spaCy | `backend/app/ingestion/enrichers/ner.py` |
| Gazetteer Argentina | `backend/app/ingestion/enrichers/gazetteer.py` |
| Clasificador de alcance nacional | `backend/app/ingestion/enrichers/scope_classifier.py` |
| Embeddings y Qdrant | `backend/app/retrieval/vector_store.py` |
| Configuracion central | `backend/app/config.py` |
| Gazetteer activo | `backend/data/gazetteer/argentina.json` |

## Configuracion base

La configuracion se centraliza en `backend/app/config.py` mediante `pydantic-settings`.

Valores relevantes actuales:

```python
embedding_model: str = "intfloat/multilingual-e5-large"
scope_embedding_threshold: float = 0.15
scope_llm_model: str = "qwen2.5:3b-instruct"
scope_llm_enabled: bool = True

qdrant_url: str = "http://localhost:6333"
qdrant_collection: str = "hemeroteca_la_plata"

chunk_size: int = 900
chunk_overlap: int = 120

parsed_data_dir: str = "backend/data/parsed"
gazetteer_path: str = "backend/data/gazetteer/argentina.json"
```

Puntos importantes:

- El modelo de embeddings por defecto es `intfloat/multilingual-e5-large`.
- Los chunks se crean con `chunk_size=900` y `chunk_overlap=120`, salvo que se pasen parametros manuales.
- Qdrant guarda los vectores en la coleccion `hemeroteca_la_plata`.
- El clasificador de alcance puede usar un LLM local por Ollama si `scope_llm_enabled` esta activo.

## Entrada principal: run.py

La funcion central es `run_ingestion()`:

```python
def run_ingestion(
    force: bool = False,
    reset_index: bool = False,
    stage: str = "all",
    date: str | None = None,
    max_articles: int | None = None,
    sections: list[str] | None = None,
    index_scope: str = "argentina",
    preview_limit: int = 3,
    preview_chars: int = 800,
) -> list[Document]:
```

`run.py` toma una fecha, calcula rutas de trabajo y ejecuta cada etapa segun el `stage`.

Fragmento clave:

```python
if stage in {"scrape", "all", "preview"}:
    urls_path = discover_urls_for_date(target_date)
    scraped_files = download_articles_from_url_file(
        urls_path=urls_path,
        force=force,
        max_articles=max_articles,
        sections=sections,
    )

documents = _parse_html_files(scraped_files) if scraped_files is not None else _parse_html_for_date(raw_date_dir, parsed_date)
write_parsed_documents(documents, parsed_output_path)

chunks = chunk_documents(documents)
chunks = enrich_metadata(chunks)

chunks_to_index = _filter_chunks_for_index(chunks, index_scope=index_scope)
indexed_count = index_documents(chunks_to_index, force=reset_index)
```

Ese fragmento muestra la cadena completa:

```text
discover_urls_for_date()
download_articles_from_url_file()
parse_html_file()
write_parsed_documents()
chunk_documents()
enrich_metadata()
_filter_chunks_for_index()
index_documents()
```

## Stages disponibles

`run.py` acepta estos stages:

| Stage | Que ejecuta | Indexa en Qdrant |
|---|---|---|
| `scrape` | Descubre URLs y descarga HTML | No |
| `parse` | Parsea HTML ya descargado | No |
| `enrich` | Parse + chunk + enrichment | No |
| `preview` | Scrape + parse + chunk + enrich + muestra preview | No |
| `all` | Scrape + parse + chunk + enrich + index | Si |
| `index` | Alias interno de `all` | Si |

Comando de prueba recomendado:

```powershell
cd E:\ProyectoRagFacultad2\backend
python -m app.ingestion.run --stage preview --date 06-03-2005 --max-articles 1 --preview-limit 2 --preview-chars 600
```

Comando para indexar:

```powershell
cd E:\ProyectoRagFacultad2\backend
python -m app.ingestion.run --stage all --date 06-03-2005 --max-articles 1 --index-scope argentina
```

## Estructura de datos en disco

El proyecto separa los datos raw descubiertos, los HTML descargados y los documentos parseados:

```text
data/raw/pagina12/YYYY/MM/urls_DD-MM-YYYY.json
backend/data/raw/pagina12/YYYY/MM/*.html
backend/data/raw/pagina12/YYYY/MM/*.json
backend/data/parsed/pagina12/YYYY/MM/documents_DD-MM-YYYY.json
```

Cada archivo cumple una funcion distinta:

| Ruta | Contenido |
|---|---|
| `data/raw/pagina12/.../urls_DD-MM-YYYY.json` | Lista de URLs descubiertas, titulo, snippet, seccion |
| `backend/data/raw/pagina12/.../*.html` | HTML crudo real del articulo |
| `backend/data/raw/pagina12/.../*.json` | Sidecar de trazabilidad del articulo |
| `backend/data/parsed/pagina12/.../documents_DD-MM-YYYY.json` | Texto limpio + metadata base |

## Paso 1: scraping de Pagina/12

Archivo:

```text
backend/app/ingestion/scrapers/pagina12.py
```

El scraping tiene dos subpasos:

1. Descubrimiento de URLs.
2. Descarga de HTML real.

### 1.1 Validacion y rutas

La fecha esperada es `DD-MM-YYYY`.

```python
def parse_date_arg(raw_date: str) -> date:
    try:
        return datetime.strptime(raw_date, "%d-%m-%Y").date()
    except ValueError as exc:
        raise ValueError(f"Fecha invalida: {raw_date}. Usar formato DD-MM-YYYY.") from exc
```

El JSON de URLs se guarda fuera de `backend/`:

```python
def build_output_path(raw_date: str, output_root: Path | None = None) -> Path:
    parsed_date = parse_date_arg(raw_date)
    base_dir = output_root or (_project_root() / "data" / "raw" / "pagina12")
    return (
        base_dir
        / str(parsed_date.year)
        / f"{parsed_date.month:02d}"
        / f"urls_{raw_date}.json"
    )
```

Los HTML descargados se guardan dentro de `backend/data/raw`:

```python
def build_articles_output_dir(raw_date: str, output_root: Path | None = None) -> Path:
    parsed_date = parse_date_arg(raw_date)
    base_dir = output_root or (_project_root() / "backend" / "data" / "raw" / "pagina12")
    return base_dir / str(parsed_date.year) / f"{parsed_date.month:02d}"
```

### 1.2 Descubrimiento de URLs

La funcion principal es:

```python
def discover_urls_for_date(raw_date: str, output_root: Path | None = None) -> Path:
```

Responsabilidades:

- Validar la fecha.
- Construir el path de salida.
- Si el JSON ya existe, reutilizarlo.
- Verificar `robots.txt`.
- Buscar la edicion diaria de Pagina/12.
- Extraer URLs de notas que pertenecen a esa fecha.
- Guardar el JSON de URLs con escritura atomica.

Fragmento clave:

```python
if output_path.exists():
    logger.info("Ya existe %s, salteando.", output_path)
    return output_path

with _http_client() as client:
    verify_robots_allowed(client, parsed_date)
    urls = discover_with_daily_edition(client, parsed_date)
    mechanism_used = "edicion_del_dia"

save_output(output_path, raw_date, mechanism_used, urls)
```

Pagina/12 historica usa URLs como:

```text
https://www.pagina12.com.ar/diario/elpais/1-48573-2005-03-17.html
```

El scraper valida que la URL sea una nota de archivo y que su fecha coincida con la fecha pedida:

```python
def _is_archive_article_url(url: str, expected_date: date | None = None) -> bool:
    parsed = urlparse(url)
    path = parsed.path
    if not path.startswith("/diario/") or path.startswith(
        ("/diario/secciones/", "/diario/principal/")
    ):
        return False

    article_date = _archive_article_date(url)
    if article_date is None:
        return False

    return expected_date is None or article_date == expected_date
```

Esto evita mezclar suplementos o notas de otros dias.

### 1.3 Formato del JSON de URLs

Ejemplo conceptual:

```json
{
  "date": "17-03-2005",
  "source": "pagina12",
  "mechanism_used": "edicion_del_dia",
  "total_urls": 1,
  "scraped_at": "2026-05-15T10:30:00",
  "urls": [
    {
      "url": "https://www.pagina12.com.ar/diario/elpais/1-48573-2005-03-17.html",
      "title": "Llegaron vientos de cambio",
      "snippet": "Bajada de prueba",
      "section": "elpais"
    }
  ]
}
```

Este archivo no contiene el cuerpo completo del articulo. Solo sirve como indice de URLs descubiertas.

### 1.4 Descarga de HTML real

La funcion principal es:

```python
def download_articles_from_url_file(
    urls_path: Path,
    output_root: Path | None = None,
    force: bool = False,
    max_articles: int | None = None,
    sections: list[str] | None = None,
) -> list[Path]:
```

Responsabilidades:

- Leer el JSON de URLs.
- Filtrar por secciones si se paso `--sections`.
- Limitar cantidad de articulos si se paso `--max-articles`.
- Verificar `robots.txt`.
- Descargar cada HTML.
- Guardar el `.html`.
- Guardar un sidecar `.json` con metadata basica.
- Reutilizar archivos existentes si no se usa `--force`.

Fragmento importante:

```python
if html_path.exists() and sidecar_path.exists() and not force:
    logger.info("[%s/%s] Ya existe HTML: %s", index, len(url_items), html_path)
    stored_files.append(html_path)
    continue
```

Sidecar generado junto al HTML:

```python
{
    "source_url": article_url,
    "publication_date": parsed_date.isoformat(),
    "newspaper": "pagina12",
    "article_title": item.get("title"),
    "section": item.get("section") or _article_section(article_url),
    "snippet": item.get("snippet"),
}
```

Este sidecar es importante porque despues el parser lo usa para no depender solamente de metatags HTML.

## Paso 2: parser HTML con trafilatura

Archivo:

```text
backend/app/ingestion/parsers/html_parser.py
```

El parser convierte HTML crudo en objetos `Document` de LangChain.

Entrada:

```text
backend/data/raw/pagina12/YYYY/MM/*.html
backend/data/raw/pagina12/YYYY/MM/*.json
```

Salida:

```text
backend/data/parsed/pagina12/YYYY/MM/documents_DD-MM-YYYY.json
```

### 2.1 Extraccion de texto

La funcion `_extract_text()` usa `trafilatura.extract`:

```python
extracted = trafilatura.extract(
    html_text,
    url=source_url,
    output_format="txt",
    include_comments=False,
    include_links=False,
    include_images=False,
    include_tables=False,
    favor_precision=True,
    deduplicate=True,
)
```

Decisiones importantes:

- `output_format="txt"`: devuelve texto plano.
- `include_comments=False`: evita comentarios.
- `include_links=False`: evita URLs en el texto.
- `include_images=False`: descarta imagenes.
- `include_tables=False`: descarta tablas.
- `favor_precision=True`: prioriza precision sobre recall.
- `deduplicate=True`: intenta quitar duplicados.

Despues normaliza whitespace y repara mojibake comun:

```python
def _normalize_whitespace(text: str | None) -> str | None:
    if not text:
        return None
    normalized = " ".join(_repair_mojibake(text).split())
    return normalized or None
```

### 2.2 Filtro de texto insuficiente

Si el texto extraido es demasiado corto, se omite el documento:

```python
MIN_TEXT_CHARS = 120

if not extracted_text or len(extracted_text) < min_text_chars:
    logger.warning(
        f"HTML omitido por poco texto extraido | path={html_path} | chars={len(extracted_text or '')}"
    )
    return None
```

Esto evita indexar basura, paginas vacias o HTML que no representa una nota completa.

### 2.3 Metadata base del documento

`parse_html_file()` devuelve un `Document`:

```python
return Document(
    page_content=extracted_text,
    metadata={
        "chunk_id": f"{source_id}::chunk::0",
        "source_id": source_id,
        "newspaper": sidecar.get("newspaper", "pagina12"),
        "source_type": "html",
        "granularity": "article",
        "publication_date": _extract_publication_date(soup, trafilatura_metadata, sidecar),
        "article_title": sidecar.get("article_title") or _extract_title(soup, trafilatura_metadata),
        "section": sidecar.get("section") or _extract_section(soup),
        "author": sidecar.get("author") or _extract_author(soup, trafilatura_metadata),
        "page_number": None,
        "source_url": source_url,
        "source_file": str(html_path),
    },
)
```

Conceptualmente:

```text
Document.page_content = texto limpio completo del articulo
Document.metadata = metadata base del articulo
```

### 2.4 Persistencia de parsed

`write_parsed_documents()` guarda JSON con escritura atomica:

```python
payload = {
    "total_documents": len(documents),
    "documents": [_document_to_payload(document) for document in documents],
}

tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp_path.replace(output_path)
```

Formato resultante:

```json
{
  "total_documents": 1,
  "documents": [
    {
      "page_content": "Texto limpio completo del articulo...",
      "metadata": {
        "source_id": "backend/data/raw/pagina12/2005/03/1-48573-2005-03-17.html",
        "newspaper": "pagina12",
        "source_type": "html",
        "granularity": "article",
        "publication_date": "2005-03-17",
        "article_title": "Llegaron vientos de cambio",
        "section": "elpais",
        "source_url": "https://www.pagina12.com.ar/diario/elpais/1-48573-2005-03-17.html"
      }
    }
  ]
}
```

## Paso 3: chunking

Archivo:

```text
backend/app/ingestion/chunker.py
```

El chunking divide el texto completo de cada articulo en fragmentos mas chicos para que puedan ser embebidos y recuperados por similitud semantica.

Funcion principal:

```python
def chunk_documents(
    documents: list[Document],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Document]:
```

Usa:

```python
RecursiveCharacterTextSplitter
```

con separadores adaptados al espanol:

```python
SPANISH_SEPARATORS = [
    "\n## ",
    "\n### ",
    "\n#### ",
    "\n\n",
    "\n",
    ". ",
    "? ",
    "! ",
    "; ",
    ", ",
    " ",
]
```

Configuracion:

```python
splitter = RecursiveCharacterTextSplitter(
    chunk_size=chunk_size or settings.chunk_size,
    chunk_overlap=chunk_overlap or settings.chunk_overlap,
    separators=SPANISH_SEPARATORS,
    length_function=len,
    is_separator_regex=False,
    keep_separator=True,
)
```

### 3.1 Que pasa con la metadata

LangChain copia la metadata del documento original a cada chunk. Luego el chunker agrega:

```python
chunk.metadata["chunk_index"] = index
chunk.metadata["total_chunks"] = total
chunk.metadata["chunk_id"] = f"{source_id}::chunk::{index}"
```

Ejemplo:

```text
Articulo A
  source_id = backend/data/raw/pagina12/2005/03/nota.html
  page_content = texto completo

Chunk 0
  page_content = primera parte del texto
  metadata.source_id = mismo source_id
  metadata.chunk_index = 0
  metadata.total_chunks = 3
  metadata.chunk_id = source_id::chunk::0

Chunk 1
  page_content = segunda parte del texto
  metadata.source_id = mismo source_id
  metadata.chunk_index = 1
  metadata.total_chunks = 3
  metadata.chunk_id = source_id::chunk::1
```

Punto clave: el chunking se hace sobre `Document.page_content`, no sobre la metadata.

## Paso 4: enriquecimiento de metadata

Archivo:

```text
backend/app/ingestion/metadata.py
```

La funcion principal es:

```python
def enrich_metadata(
    chunks: list[Document],
    gazetteer: Gazetteer | None = None,
    scope_classifier: ScopeClassifier | None = None,
) -> list[Document]:
```

Esta etapa trabaja sobre cada chunk individualmente.

### 4.1 Flujo interno del enrichment

Fragmento central:

```python
for index, chunk in enumerate(chunks, start=1):
    publication_date = _parse_date(chunk.metadata.get("publication_date"))
    entities = extract_entities(chunk.page_content)
    locations = gazetteer.find_locations(chunk.page_content)
    primary_location = gazetteer.pick_primary_location(locations)

    classifier_metadata = dict(chunk.metadata)
    classifier_metadata["organizations"] = entities["organizations"]
    classifier_metadata["location_mentions"] = locations

    country_scope, scope_signals = scope_classifier.classify(
        chunk.page_content,
        classifier_metadata,
    )
```

Despues escribe campos normalizados:

```python
chunk.metadata["publication_date"] = publication_date.isoformat()
chunk.metadata["year"] = publication_date.year
chunk.metadata["decade"] = int(publication_date.year / 10) * 10
chunk.metadata["persons"] = entities["persons"]
chunk.metadata["organizations"] = entities["organizations"]
chunk.metadata["location_mentions"] = locations
chunk.metadata["primary_location"] = primary_location
chunk.metadata["country_scope"] = country_scope
chunk.metadata["scope_signals"] = scope_signals
chunk.metadata["text"] = chunk.page_content
chunk.metadata["text_clean"] = " ".join(chunk.page_content.split())
```

### 4.2 NER con spaCy

Archivo:

```text
backend/app/ingestion/enrichers/ner.py
```

Usa `es_core_news_md` de spaCy con carga lazy y cacheada:

```python
@lru_cache()
def _load_model():
    return spacy.load("es_core_news_md")
```

Extrae:

```python
_PERSON_LABELS = {"PER", "PERSON"}
_ORG_LABELS = {"ORG"}
```

Resultado:

```python
return {"persons": persons, "organizations": organizations}
```

Ejemplo de metadata:

```json
{
  "persons": ["Alfonsin"],
  "organizations": ["UCR"]
}
```

Nota importante: NER puede equivocarse. Por eso `preview` es util para revisar manualmente entidades detectadas.

### 4.3 Gazetteer Argentina

Archivo:

```text
backend/app/ingestion/enrichers/gazetteer.py
```

Datos:

```text
backend/data/gazetteer/argentina.json
```

El gazetteer carga:

- Pais.
- Provincias.
- Ciudades.
- Barrios o localidades.
- Partidos cercanos.
- Instituciones.
- Organizaciones politicas.
- Clubes.
- Secciones que clasifican directo como Argentina.
- Keywords nacionales.

La busqueda de lugares es exacta, case-insensitive y tolera acentos:

```python
def find_locations(self, text: str) -> list[str]:
    normalized_text = _strip_accents(text).lower()
    found: list[str] = []
    for alias in self.aliases:
        normalized_alias = _strip_accents(alias).lower().strip()
        if normalized_alias and _contains_term(normalized_text, normalized_alias) and alias not in found:
            found.append(alias)
    return found
```

El matcher usa limites de palabra:

```python
pattern = rf"(?<!\w){re.escape(normalized_term)}(?!\w)"
```

Esto evita falsos positivos como detectar `CABA` dentro de `caballito`.

`primary_location` se decide asi:

```python
def pick_primary_location(self, locations: list[str]) -> str | None:
    if self.city in locations:
        return self.city
    return locations[0] if locations else None
```

En este proyecto `city` esta configurado como `Argentina`, por lo tanto:

- Si aparece `Argentina`, `primary_location = "Argentina"`.
- Si no aparece Argentina pero aparece otra ubicacion, usa la primera.
- Si no aparece ninguna, queda `None`.

### 4.4 Clasificador de alcance nacional

Archivo:

```text
backend/app/ingestion/enrichers/scope_classifier.py
```

El campo principal es:

```text
country_scope = argentina | international | unknown
```

Y las razones quedan en:

```text
scope_signals = [...]
```

El clasificador usa una cascada de tres capas:

```text
Capa 1: heuristicas auditables
Capa 2: similitud semantica con embeddings
Capa 3: LLM local opcional para zona gris
```

#### Capa 1: heuristicas

Primero revisa si la seccion esta en `direct_argentina_sections`:

```python
section = _normalize_section(metadata.get("section"))
if section in _normalized_set(self.gazetteer.direct_argentina_sections if self.gazetteer else []):
    return ScopeResult("argentina", [f"seccion:{section}"])
```

Despues busca senales argentinas en dos niveles: fuertes y debiles.

- `location_mentions`.
- `organizations`.
- Titulo del articulo.
- Texto del chunk.
- Keywords nacionales.

Las senales fuertes pueden clasificar `argentina`. Las senales debiles solo quedan para auditoria y dejan que el chunk pase a capa 2 o capa 3.

Fragmento simplificado:

```python
strong_signals = []
weak_signals = []

for location in location_mentions:
    if self.gazetteer is not None and not self.gazetteer.is_known_location(location):
        continue
    _append_signal(strong_signals, f"gazetteer:{location}")

for org in _contains_any(" ".join(organizations), gazetteer_institutions):
    _append_signal(strong_signals, f"institution:{org}")

for org in _contains_any(" ".join(organizations), gazetteer_political_orgs):
    _append_signal(strong_signals, f"political_org:{org}")

for club in _contains_any(" ".join(organizations), gazetteer_clubs):
    _append_signal(strong_signals, f"club:{club}")

for term in _contains_any(haystack, gazetteer_keywords):
    _append_signal(strong_signals, f"term:{term}")

for term in _contains_any(haystack, gazetteer_contextual_terms):
    _append_signal(weak_signals, f"contextual_term:{term}")

if strong_signals:
    return ScopeResult("argentina", strong_signals + weak_signals)
return ScopeResult("unknown", weak_signals)
```

La capa 1 no acepta cualquier `location_mentions` a ciegas: revalida que la ubicacion exista en los aliases del gazetteer. Ademas separa categorias para que el preview sea mas auditable:

```text
gazetteer:Buenos Aires
institution:Banco Central
political_org:UCR
club:River
term:estado argentino
weak_institution:Senado
contextual_term:derechos humanos
```

`weak_institution:*` y `contextual_term:*` no alcanzan para clasificar Argentina por si solas. Ejemplos: `Senado`, `Congreso`, `Diputados` o `derechos humanos` en una nota de `elmundo` quedan como evidencia debil y pasan a embeddings/LLM. No se buscan clubes directamente en texto para evitar falsos positivos con palabras ambiguas.

Si un chunk es muy corto, queda `unknown`:

```python
if len(chunk_text.strip()) < 100:
    return "unknown", []
```

#### Capa 2: embeddings contra anclas

Si la capa 1 no decide, compara el chunk contra tres grupos de anclas:

```python
ANCLAS_ARGENTINA = [
    "noticias de Argentina",
    "politica argentina",
    "economia argentina",
    ...
]

ANCLAS_INTERNACIONAL = [
    "noticias internacionales",
    "politica exterior mundial",
    ...
]

ANCLAS_UNKNOWN = [
    "fragmento ambiguo sin contexto nacional",
    "ensayo literario conceptual",
    ...
]
```

Calcula similitud coseno contra el mejor anchor de cada grupo:

```python
score_arg = max(_cosine_similarity(chunk_embedding, anchor) for anchor in self._arg_anchor_embeddings)
score_int = max(_cosine_similarity(chunk_embedding, anchor) for anchor in self._int_anchor_embeddings)
score_unknown = max(
    _cosine_similarity(chunk_embedding, anchor) for anchor in self._unknown_anchor_embeddings
)
```

Luego ordena scores y calcula margen:

```python
ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
winner, winner_score = ordered[0]
runner_up_score = ordered[1][1]
margin = winner_score - runner_up_score
```

Solo decide si el margen supera el threshold:

```python
if margin > self.embedding_threshold:
    return EmbeddingDecision(ScopeResult(winner, signals), final=True)
```

Las senales quedan asi:

```text
emb_arg:0.812
emb_int:0.744
emb_unknown:0.702
emb_margin:0.068
```

#### Reutilizacion del embedding para indexar

Cuando la capa 2 calcula el embedding del chunk, lo guarda temporalmente:

```python
metadata["_index_vector"] = chunk_embedding
```

Ese vector no debe persistirse como payload. Sirve para evitar calcular dos veces el mismo embedding:

1. Una vez para clasificar scope.
2. Otra vez para indexar en Qdrant.

#### Capa 3: LLM local opcional

Si los embeddings quedan en zona gris, puede consultar Ollama:

```python
if self.llm_client is None:
    return ScopeResult("unknown", ["llm_skipped:disabled"])
```

El LLM debe responder solo:

```text
argentina
international
unknown
```

El prompt es estricto: no permite inferir Argentina solo porque el texto este en espanol o porque venga de Pagina/12.

### 4.5 Scope por articulo

Despues de clasificar cada chunk, `metadata.py` agrupa chunks por `source_id`:

```python
grouped: dict[str, list[Document]] = defaultdict(list)
for chunk in chunks:
    grouped[str(chunk.metadata.get("source_id", "unknown"))].append(chunk)
```

Luego resuelve:

```text
article_country_scope
article_scope_signals
```

Reglas:

- Si algun chunk tiene senal argentina no LLM, el articulo completo queda `argentina`.
- Si hay al menos dos chunks clasificados como Argentina solo por LLM, tambien puede elevar a `argentina`.
- Un unico chunk `argentina` decidido solo por LLM no alcanza.
- Si no hay Argentina pero hay senales internacionales, queda `international`.
- Si no hay evidencia suficiente, queda `unknown`.

Fragmento:

```python
if argentina_non_llm:
    return "argentina", _dedupe(["article:chunk_argentina_non_llm", *argentina_non_llm])
if len(argentina_llm) >= 2:
    return "argentina", _dedupe(["article:multi_llm_argentina", *argentina_llm])
if international_signals:
    return "international", _dedupe(["article:chunk_international", *international_signals])
return "unknown", []
```

Esto permite que un chunk conceptual quede `country_scope="unknown"` pero herede:

```text
article_country_scope="argentina"
```

si otro chunk del mismo articulo contiene evidencia argentina fuerte.

## Paso 5: filtro antes de indexar

Antes de guardar en Qdrant, `run.py` filtra chunks segun `--index-scope`.

Funcion:

```python
def _filter_chunks_for_index(chunks: list[Document], index_scope: str) -> list[Document]:
```

Regla:

```python
filtered = [
    chunk
    for chunk in chunks
    if str(chunk.metadata.get("article_country_scope") or chunk.metadata.get("country_scope") or "").lower()
    in allowed_scopes
]
```

Por defecto:

```text
--index-scope argentina
```

Opciones utiles:

```powershell
--index-scope argentina
--index-scope argentina,unknown
--index-scope all
```

Diferencia importante:

- `force=True` redescarga/redescarga HTML.
- `reset_index=True` borra y recrea la coleccion Qdrant.

## Paso 6: embeddings

Archivo:

```text
backend/app/retrieval/vector_store.py
```

Clase principal:

```python
class E5Embeddings:
```

Carga el modelo:

```python
self.model = SentenceTransformer(model_name, cache_folder=cache_folder)
```

### 6.1 Prefijos E5

El modelo E5 necesita prefijos distintos para documentos y queries.

Para documentos/chunks:

```python
def embed_documents(self, texts: list[str]) -> list[list[float]]:
    passages = [f"passage: {_normalize_text(text)}" for text in texts]
    return self.model.encode(passages, normalize_embeddings=True).tolist()
```

Para consultas:

```python
def embed_query(self, query: str) -> list[float]:
    return self.model.encode(
        [f"query: {_normalize_text(query)}"],
        normalize_embeddings=True,
    )[0].tolist()
```

Esto es clave para que la similitud semantica funcione bien con `intfloat/multilingual-e5-large`.

### 6.2 Cache de funcion de embeddings

```python
@lru_cache()
def get_embedding_function() -> E5Embeddings:
    settings = get_settings()
    return E5Embeddings(settings.embedding_model, cache_folder=settings.model_cache_dir)
```

El modelo se carga una vez por proceso y se reutiliza.

### 6.3 Reutilizacion de `_index_vector`

Si el clasificador de scope ya calculo el embedding, `vector_store.py` lo reutiliza:

```python
for index, chunk in enumerate(chunks):
    vector = chunk.metadata.get("_index_vector")
    if _is_valid_vector(vector):
        embeddings[index] = [float(value) for value in vector]
    else:
        missing_indices.append(index)
        missing_texts.append(chunk.page_content)
```

Solo calcula embeddings faltantes:

```python
if missing_texts:
    generated = get_embedding_function().embed_documents(missing_texts)
    for index, vector in zip(missing_indices, generated):
        embeddings[index] = vector
```

Esto conserva el orden de los chunks y evita trabajo duplicado.

## Paso 7: guardado en Qdrant

Archivo:

```text
backend/app/retrieval/vector_store.py
```

Funcion principal:

```python
def index_documents(chunks: list[Document], force: bool = False) -> int:
```

### 7.1 Cliente Qdrant

```python
@lru_cache()
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        prefer_grpc=settings.qdrant_prefer_grpc,
    )
```

### 7.2 Creacion/verificacion de coleccion

`ensure_collection()`:

1. Calcula el tamano del vector usando una query de prueba.
2. Verifica si la coleccion existe.
3. Si no existe, la crea con distancia coseno.
4. Crea indices de payload.

Fragmento:

```python
vector_size = len(get_embedding_function().embed_query("La Plata"))

client.create_collection(
    collection_name=settings.qdrant_collection,
    vectors_config=qmodels.VectorParams(
        size=vector_size,
        distance=qmodels.Distance.COSINE,
    ),
)
```

Indices de payload:

```python
("year", qmodels.IntegerIndexParams(type="integer"))
("decade", qmodels.IntegerIndexParams(type="integer"))
("newspaper", qmodels.KeywordIndexParams(type="keyword"))
("section", qmodels.KeywordIndexParams(type="keyword"))
("country_scope", qmodels.KeywordIndexParams(type="keyword"))
("article_country_scope", qmodels.KeywordIndexParams(type="keyword"))
("primary_location", qmodels.KeywordIndexParams(type="keyword"))
("persons", qmodels.KeywordIndexParams(type="keyword"))
("organizations", qmodels.KeywordIndexParams(type="keyword"))
("publication_date", qmodels.KeywordIndexParams(type="keyword"))
```

Estos indices permiten filtrar resultados por fecha, seccion, personas, organizaciones, ubicacion y scope.

### 7.3 ID estable del punto

Cada chunk se guarda con un ID deterministico basado en `chunk_id`:

```python
def _build_point_id(chunk: Document) -> str:
    chunk_id = chunk.metadata.get("chunk_id")
    if chunk_id:
        return str(uuid5(NAMESPACE_URL, str(chunk_id)))
    digest = hashlib.sha1(chunk.page_content.encode("utf-8")).hexdigest()
    return str(uuid5(NAMESPACE_URL, digest))
```

Esto ayuda a que el mismo chunk tenga el mismo ID entre ejecuciones.

### 7.4 Payload final

Antes de subir a Qdrant:

```python
payload = dict(chunk.metadata)
payload.pop("_index_vector", None)
payload["text"] = chunk.page_content
```

Punto clave:

```text
_index_vector no se guarda como payload.
```

Se guarda:

- Vector numerico en `vector`.
- Metadata en `payload`.
- Texto del chunk en `payload["text"]`.

Creacion del punto:

```python
qmodels.PointStruct(
    id=_build_point_id(chunk),
    vector=vector,
    payload=payload,
)
```

Upsert:

```python
client.upsert(
    collection_name=settings.qdrant_collection,
    points=points,
    wait=True,
)
```

## Metadata final de un chunk indexado

Un chunk enriquecido e indexable termina con campos como:

```json
{
  "chunk_id": "backend/data/raw/pagina12/2005/03/nota.html::chunk::0",
  "source_id": "backend/data/raw/pagina12/2005/03/nota.html",
  "newspaper": "pagina12",
  "source_type": "html",
  "granularity": "article",
  "publication_date": "2005-03-17",
  "year": 2005,
  "decade": 2000,
  "article_title": "Titulo de la nota",
  "section": "elpais",
  "source_url": "https://www.pagina12.com.ar/diario/elpais/1-48573-2005-03-17.html",
  "page_number": null,
  "source_pdf_path": null,
  "ocr_confidence": null,
  "chunk_index": 0,
  "total_chunks": 3,
  "persons": ["Alfonsin"],
  "organizations": ["UCR"],
  "location_mentions": [],
  "primary_location": null,
  "country_scope": "argentina",
  "scope_signals": ["seccion:elpais"],
  "article_country_scope": "argentina",
  "article_scope_signals": ["article:chunk_argentina_non_llm", "chunk:0:seccion:elpais"],
  "text": "Texto del chunk...",
  "text_clean": "Texto del chunk..."
}
```

## Preview: inspeccion sin indexar

`preview` es el stage mas util para validar calidad antes de tocar Qdrant:

```powershell
python -m app.ingestion.run --stage preview --date 06-03-2005 --max-articles 1 --preview-limit 2 --preview-chars 600
```

Ejecuta:

```text
scrape -> parse -> chunk -> enrich
```

No ejecuta:

```text
index
```

El preview imprime metadata relevante:

```python
preview_metadata = {
    "chunk_id": chunk.metadata.get("chunk_id"),
    "source_id": chunk.metadata.get("source_id"),
    "newspaper": chunk.metadata.get("newspaper"),
    "publication_date": chunk.metadata.get("publication_date"),
    "year": chunk.metadata.get("year"),
    "decade": chunk.metadata.get("decade"),
    "article_title": chunk.metadata.get("article_title"),
    "section": chunk.metadata.get("section"),
    "source_url": chunk.metadata.get("source_url"),
    "country_scope": chunk.metadata.get("country_scope"),
    "scope_signals": chunk.metadata.get("scope_signals"),
    "article_country_scope": chunk.metadata.get("article_country_scope"),
    "article_scope_signals": chunk.metadata.get("article_scope_signals"),
    "primary_location": chunk.metadata.get("primary_location"),
    "location_mentions": chunk.metadata.get("location_mentions"),
    "persons": chunk.metadata.get("persons"),
    "organizations": chunk.metadata.get("organizations"),
    "chunk_index": chunk.metadata.get("chunk_index"),
    "total_chunks": chunk.metadata.get("total_chunks"),
}
```

Ademas de imprimir los primeros chunks, el preview muestra un bloque de representantes por tipo de senal:

```text
PREVIEW CASOS POR SENAL
CASO CAPA 1 - SECCION
CASO CAPA 1 - GAZETTEER/TERMINOS
CASO CAPA 2 - EMBEDDINGS
CASO CAPA 3 - LLM
```

Si en la muestra procesada no aparece alguno de esos casos, lo informa como `no encontrado en esta muestra`. Esto es util porque los primeros articulos de una fecha pueden venir todos de `elpais` y clasificar por `seccion:elpais`, aunque existan otros mecanismos activos.

Sirve para revisar:

- Si `trafilatura` extrajo texto util.
- Si el chunking conserva fragmentos legibles.
- Si spaCy detecto personas y organizaciones razonables.
- Si el gazetteer encontro ubicaciones correctas.
- Si `country_scope` y `article_country_scope` tienen sentido.
- Si conviene indexar solo `argentina` o tambien `unknown`.

## Procesamiento por rango o por anio

`run.py` tambien soporta rangos:

```powershell
python -m app.ingestion.run --stage all --date-from 01-01-2005 --date-to 31-01-2005 --reset-index --index-scope argentina
```

Y anio completo:

```powershell
python -m app.ingestion.run --stage all --year 2005 --reset-index --index-scope argentina
```

La funcion es:

```python
def run_ingestion_range(
    start_date: date_type,
    end_date: date_type,
    force: bool = False,
    reset_index: bool = False,
    stage: str = "all",
    max_articles: int | None = None,
    sections: list[str] | None = None,
    index_scope: str = "argentina",
    continue_on_error: bool = True,
) -> list[Document]:
```

Detalle importante: si se usa `--reset-index` en un rango, solo resetea Qdrant el primer dia:

```python
reset_index=reset_index and day_index == 1
```

Esto evita borrar lo indexado en dias anteriores del mismo rango.

## Recuperacion semantica basica

Aunque este documento se enfoca en ingestion, `vector_store.py` tambien define un retriever semantico:

```python
class QdrantSemanticRetriever:
    def invoke(self, query: str) -> list[Document]:
        vector = self.embeddings.embed_query(query)
        results = self.client.search(
            collection_name=self.settings.qdrant_collection,
            query_vector=vector,
            limit=self.settings.top_k,
            with_payload=True,
        )
```

El query se embebe con prefijo:

```text
query: ...
```

Los documentos se habian embebido con:

```text
passage: ...
```

Qdrant devuelve payloads, y el retriever reconstruye `Document`:

```python
payload = dict(item.payload or {})
page_content = str(payload.pop("text", ""))
payload["semantic_score"] = float(item.score)
documents.append(Document(page_content=page_content, metadata=payload))
```

## Comandos utiles

Desde:

```powershell
cd E:\ProyectoRagFacultad2\backend
```

Descubrir URLs:

```powershell
python -m app.ingestion.scrapers.pagina12 --date 06-03-2005
```

Descargar un articulo:

```powershell
python -m app.ingestion.scrapers.pagina12 --date 06-03-2005 --download --max-articles 1
```

Parsear:

```powershell
python -m app.ingestion.run --stage parse --date 06-03-2005
```

Preview sin indexar:

```powershell
python -m app.ingestion.run --stage preview --date 06-03-2005 --max-articles 1 --preview-limit 2 --preview-chars 600
```

Preview filtrando secciones:

```powershell
python -m app.ingestion.run --stage preview --date 06-03-2005 --sections suplementos/libros,elmundo,cultura,contratapa --max-articles 5 --force --preview-limit 40 --preview-chars 700
```

Preview con muestra balanceada por seccion:

```powershell
python -m app.ingestion.run --stage preview --date 03-01-2005 --sections elpais,economia,elmundo,espectaculos,contratapa --max-articles-per-section 2 --preview-limit 80 --preview-chars 700
```

`--max-articles-per-section` evita que `--max-articles` tome solo las primeras secciones del JSON, que suelen ser `elpais`, `economia` o `sociedad`. Es util para probar en una misma corrida casos de seccion nacional directa y casos que pasan a gazetteer, embeddings o LLM.

Indexar fecha:

```powershell
python -m app.ingestion.run --stage all --date 06-03-2005 --index-scope argentina
```

Indexar anio completo:

```powershell
python -m app.ingestion.run --stage all --year 2005 --reset-index --index-scope argentina
```

Inspeccionar Qdrant:

```powershell
python -m app.retrieval.inspect_store --date 2005-01-02 --article-scope argentina --limit 10 --chars 700
```

## Tests relacionados

Tests utiles:

```text
backend/tests/test_pagina12_scraper.py
backend/tests/test_html_parser.py
backend/tests/test_run_ingestion.py
backend/tests/test_gazetteer.py
backend/tests/test_scope_classifier.py
backend/tests/test_metadata_enrichment.py
backend/tests/test_vector_store_reuse.py
backend/tests/test_gemini_embeddings.py
backend/tests/test_reranker_and_pipeline.py
```

Comando:

```powershell
cd E:\ProyectoRagFacultad2
python -m pytest backend\tests\test_pagina12_scraper.py backend\tests\test_html_parser.py backend\tests\test_run_ingestion.py backend\tests\test_gazetteer.py backend\tests\test_scope_classifier.py backend\tests\test_metadata_enrichment.py backend\tests\test_vector_store_reuse.py backend\tests\test_gemini_embeddings.py backend\tests\test_reranker_and_pipeline.py -q
```

Que cubren:

- Rutas y formato de salida del scraper.
- Reutilizacion de archivos existentes.
- Filtro de URLs por fecha.
- Guardado de HTML y sidecar.
- Extraccion de texto y metadata del parser.
- Omision de HTML con poco texto.
- Reparacion de mojibake.
- Gazetteer con limites de palabra.
- Clasificador de scope por heuristicas, embeddings y LLM.
- Scope agregado por articulo.
- Filtro `index_scope`.
- Reutilizacion de `_index_vector`.
- No persistencia de `_index_vector` en payload.

## Decisiones de diseno importantes

### 1. Raw no se toca manualmente

Los datos raw se generan desde scrapers o pruebas controladas. Esto conserva trazabilidad y reproducibilidad.

### 2. La metadata nace temprano

El scraper ya guarda sidecars con:

```text
source_url
publication_date
newspaper
article_title
section
snippet
```

Eso hace que el parser no dependa completamente de HTML historico irregular.

### 3. El texto limpio vive en `page_content`

Durante parse y chunking:

```text
Document.page_content
```

es la fuente del texto a chunquear, enriquecer, embeber e indexar.

### 4. El scope por chunk y por articulo son distintos

Un chunk puede ser ambiguo:

```text
country_scope = unknown
```

pero pertenecer a un articulo argentino:

```text
article_country_scope = argentina
```

Por eso el filtro de indexacion usa primero `article_country_scope`.

### 5. `_index_vector` es transitorio

Sirve para reutilizar embeddings calculados durante scope classification, pero se elimina antes de subir a Qdrant:

```python
payload.pop("_index_vector", None)
```

### 6. `preview` es el control de calidad

Antes de indexar una carga grande conviene revisar varias fechas y secciones con `preview`.

### 7. Reconstrucción de Artículos en Caliente
Para mitigar la pérdida de contexto que produce el chunking en preguntas complejas (donde la respuesta involucra hechos separados en un mismo artículo), el pipeline agrupa los chunks recuperados por su `source_id`, obtiene el artículo completo reconstruyendo sus chunks originales de Qdrant, y le entrega al LLM el texto de los top 3 artículos completos en vez de fragmentos inconexos.

### 8. Rate Limiting de Embeddings API
Dado que las claves gratuitas de Gemini tienen un límite estricto de 15 RPM (y que cada elemento de un lote cuenta para la cuota), se implementó un loteo reducido (`batch_size=20`) junto a esperas obligatorias de 4 segundos entre lotes y reintentos automáticos mediante `tenacity`. Esto permite subir miles de documentos de forma gratuita sin fallas por rate limit.

## Resumen final del flujo

El flujo actual hace esto:

```text
run.py
  |
  |-- [1] scrape
  |      |-- discover_urls_for_date()
  |      |-- download_articles_from_url_file()
  |
  |-- [2] parse
  |      |-- parse_html_file()
  |      |-- trafilatura.extract()
  |      |-- write_parsed_documents()
  |
  |-- [3] chunk
  |      |-- RecursiveCharacterTextSplitter
  |      |-- chunk_id, chunk_index, total_chunks
  |
  |-- [4] enrich
  |      |-- spaCy NER
  |      |-- Gazetteer Argentina
  |      |-- ScopeClassifier
  |      |     |-- heuristicas
  |      |     |-- embeddings contra anclas
  |      |     |-- LLM local opcional
  |      |
  |      |-- article_country_scope
  |
  |-- [5] index
         |-- filtro por index_scope
         |-- embeddings E5 con passage:
         |-- ensure_collection()
         |-- payload indexes
         |-- upsert en Qdrant
```

En terminos de RAG, el resultado final es una base vectorial donde cada punto representa un chunk de articulo, con:

- Vector semantico.
- Texto del chunk.
- Fecha.
- Diario.
- Seccion.
- Titulo.
- URL fuente.
- Personas detectadas.
- Organizaciones detectadas.
- Lugares detectados.
- Alcance nacional por chunk.
- Alcance nacional por articulo.

Eso permite luego recuperar evidencia historica por similitud semantica y filtrar por metadata estructurada.
