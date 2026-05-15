# Plan de Migración: RAG-Docker → RAG-Hemeroteca La Plata

> Documento de diseño y plan de implementación para adaptar un proyecto RAG existente (originalmente sobre documentación de Docker) a un sistema de consulta sobre archivos de diarios históricos de La Plata, Argentina (período objetivo: 1930-2017).

---

## 1. Contexto del proyecto base

El proyecto actual (`ProyectoRagFacultad2`) es un RAG funcional sobre documentación de Docker con la siguiente estructura:

```
backend/
├── app/
│   ├── generation/
│   │   ├── evidence_checker.py
│   │   ├── generator.py
│   │   ├── prompt_templates.py
│   │   ├── router.py
│   │   └── translator.py          ← se ELIMINA en la migración
│   ├── ingestion/
│   │   ├── chunker.py
│   │   ├── loader.py
│   │   ├── metadata.py
│   │   ├── preprocessor.py
│   │   └── run.py
│   ├── retrieval/
│   │   ├── bm25_retriever.py
│   │   ├── hybrid.py
│   │   ├── reranker.py
│   │   └── vector_store.py
│   ├── config.py
│   ├── main.py
│   ├── models.py
│   └── pipeline.py
├── tests/
├── corpus/
│   ├── processed/
│   └── scripts/
├── docs/
│   ├── architecture.md
│   └── prompts.md
├── docker-compose.yml
├── docker-compose.gpu.yml
└── Makefile
```

**Stack actual:**
- LangChain como framework de orquestación
- ChromaDB como vector store
- Ollama como LLM y servidor de embeddings local
- OpenWebUI como frontend (consume endpoint OpenAI-compatible del backend)
- BM25 + retrieval semántico fusionados con RRF
- FlashRank como reranker
- Evidence checker + router (chitchat/RAG) + traductor ES↔EN

**Lo que se conserva** del pipeline actual:
- Estructura modular (`generation/`, `ingestion/`, `retrieval/`)
- Router de intención (chitchat vs RAG)
- Hybrid retrieval con RRF
- FlashRank como reranker
- Evidence checker / lógica de abstención
- Endpoint OpenAI-compatible para OpenWebUI

**Lo que cambia o se agrega:**
- Vector store: ChromaDB → **Qdrant** (filtros por payload mucho más rápidos, crítico para consultas con filtros temporales/geográficos)
- Embeddings: pasan a `intfloat/multilingual-e5-large` (sin necesidad de traducir)
- Tokenizer BM25: inglés → **español con Snowball + stopwords ES**
- Reranker FlashRank: modelo multilingüe (`ms-marco-MultiBERT-L-12`)
- **Se elimina** `translator.py` (la lógica completa de traducción ES↔EN)
- **Se agrega** `query_filters.py` (extracción de filtros estructurados de la query)
- **Se agrega** `citation.py` (construcción de referencias académicas)
- Se rehace todo `ingestion/` para soportar diarios (scraping, OCR, NER, etc.)

---

## 2. Hardware objetivo y consideraciones

- **CPU:** AMD Ryzen 5 3500U (4 cores / 8 threads)
- **RAM:** 16 GB
- **GPU:** sin GPU dedicada (todo embedding y OCR corre en CPU)

**Implicancias de diseño:**
- Embeddings con `multilingual-e5-large` en CPU: ~50-100 chunks/seg. La ingesta inicial llevará días, debe ser **reanudable**.
- OCR con Tesseract en CPU: ~3-10 segundos por página A3 de diario escaneado.
- Batch size en embeddings: 8 (no más).
- Se desaconseja correr Ollama + Qdrant + indexación pesada en simultáneo: usar `make` targets separados.

---

## 3. Alcance funcional

### 3.1 Tipos de consultas soportadas

1. **Eventos puntuales con fecha:** "¿Qué pasó en La Plata el 2 de abril de 1986?"
2. **Temas o personas a lo largo del tiempo:** "Cobertura de Maradona en El Día durante los 90."
3. **Geográficas:** "Noticias sobre Berisso en los 80."
4. **Mixtas:** "Inundaciones en La Plata entre 1985 y 1995."

**No soportado en v1:** comparativas entre diarios (queda como extensión futura).

### 3.2 Fuentes de datos elegidas

| Fuente | Período | Formato | Acceso |
|---|---|---|---|
| **El Día (sitio web)** | 1996-2017 | HTML | Scraping respetuoso del sitemap.xml |
| **Biblioteca Nacional (BNA)** | 1930-1996 | PDF escaneado con OCR variable | Hemeroteca digital `trapalanda.bn.gov.ar` |
| **Internet Archive** | Variable | PDF / texto | API oficial, complemento de BNA |

> **Nota académica:** se prioriza material de dominio público o de acceso académico abierto. Clarín y La Nación quedan fuera por restricciones de paywall y términos de uso.

### 3.3 Granularidad

- **HTML moderno:** una nota = un documento lógico → chunks de ~500 tokens con overlap 80.
- **PDF escaneado:** una página = un documento → chunks por bloque OCR. Se conserva `block_title` cuando el layout detecta título prominente.

---

## 4. Arquitectura objetivo

### 4.1 Pipeline de ingesta (offline, batch)

```
┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌──────────┐   ┌──────────┐
│ Scrapers │──▶│ Parsers  │──▶│ Enrichers    │──▶│ Chunker  │──▶│ Indexer  │
│  HTML/   │   │  HTML/   │   │ NER, fecha,  │   │  + meta  │   │  Qdrant  │
│  PDF/IA  │   │  PDF/OCR │   │ gazetteer    │   │          │   │          │
└──────────┘   └──────────┘   └──────────────┘   └──────────┘   └──────────┘
   raw/          parsed/         enriched/         chunks/         qdrant
```

### 4.2 Pipeline de query (online)

```
OpenWebUI
   │
   ▼
FastAPI /v1/chat/completions
   │
   ▼
Router (chitchat | RAG)
   │
   ├── chitchat → respuesta amigable y corta
   │
   ▼ RAG
Filter Extractor (LLM corto → {years, locations, persons})
   │
   ▼
Hybrid Retrieval
   ├── BM25 (tokenizer ES + Snowball)
   └── Qdrant semántico con pre-filter de payload
   │
   ▼ fusión con RRF
FlashRank Reranker (multilingüe)
   │
   ▼
Evidence Checker
   │
   ├── evidencia insuficiente → abstención con citas parciales
   │
   ▼ suficiente
Generator (prompt con instrucciones de citar)
   │
   ▼
Citation Builder
   │
   ▼
Respuesta + fuentes ("El Día, 15/03/1986, p.7 [link]")
```

---

## 5. Esquema de metadatos (CRÍTICO)

Definir el schema con cuidado: define qué consultas se pueden responder bien. Va en `backend/app/models.py`.

```python
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field


class NewsChunkMetadata(BaseModel):
    # ───── Identificación ─────
    chunk_id: str
    source_id: str  # id del documento padre (nota o página)

    # ───── Origen ─────
    newspaper: str  # "el_dia", "el_argentino", ...
    source_type: Literal["html", "ocr_pdf"]
    granularity: Literal["article", "page_block"]

    # ───── Temporal (clave para filtros) ─────
    publication_date: date
    year: int           # denormalizado para filtros rápidos
    decade: int         # 1930, 1940, ..., 2010

    # ───── Geográfico ─────
    location_mentions: list[str] = Field(default_factory=list)
    primary_location: str | None = None

    # ───── Contenido editorial ─────
    article_title: str | None = None
    section: str | None = None  # "Política", "Local", "Policiales"...
    author: str | None = None
    page_number: int | None = None

    # ───── Entidades (NER) ─────
    persons: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)

    # ───── Trazabilidad para citas ─────
    source_url: str | None = None
    source_pdf_path: str | None = None
    ocr_confidence: float | None = None

    # ───── Texto ─────
    text: str
    text_clean: str  # versión normalizada para BM25
```

**Índices Qdrant** (en payload, vía `create_payload_index`):
- `year` (integer)
- `decade` (integer)
- `newspaper` (keyword)
- `primary_location` (keyword)
- `persons` (keyword, array)

Esto permite que un filtro tipo `year == 1986 AND primary_location == "La Plata"` se aplique en milisegundos sobre millones de chunks.

---

## 6. Estructura de carpetas objetivo

Adaptada **incrementalmente** desde la estructura actual del proyecto:

```
backend/
├── app/
│   ├── generation/
│   │   ├── __init__.py
│   │   ├── evidence_checker.py          ← se conserva, leves ajustes
│   │   ├── generator.py                 ← prompt en español, instrucciones de citar
│   │   ├── prompt_templates.py          ← templates ES con guías académicas
│   │   ├── router.py                    ← se conserva (chitchat ES)
│   │   ├── query_filters.py             ← NUEVO (extrae años/lugares/personas)
│   │   ├── citation.py                  ← NUEVO (formatea fuentes)
│   │   └── translator.py                ← SE ELIMINA
│   │
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── scrapers/                    ← NUEVO subdir
│   │   │   ├── __init__.py
│   │   │   ├── eldia_web.py
│   │   │   ├── bna_hemeroteca.py
│   │   │   └── archive_org.py
│   │   ├── parsers/                     ← NUEVO subdir
│   │   │   ├── __init__.py
│   │   │   ├── html_parser.py           ← trafilatura
│   │   │   ├── pdf_parser.py            ← pdfplumber + tesseract fallback
│   │   │   └── cleaner.py               ← normalización unicode, OCR fixes
│   │   ├── enrichers/                   ← NUEVO subdir
│   │   │   ├── __init__.py
│   │   │   ├── ner.py                   ← spaCy es_core_news_md
│   │   │   ├── gazetteer.py             ← lugares de La Plata y conurbano
│   │   │   └── date_inference.py
│   │   ├── chunker.py                   ← se adapta (separadores ES)
│   │   ├── metadata.py                  ← rehecho con schema nuevo
│   │   ├── indexer.py                   ← reemplaza loader.py (Qdrant upsert)
│   │   └── run.py                       ← orquesta todo (reanudable)
│   │
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── bm25_retriever.py            ← tokenizer ES + Snowball + stopwords
│   │   ├── hybrid.py                    ← se conserva la lógica RRF
│   │   ├── reranker.py                  ← modelo multilingüe
│   │   └── vector_store.py              ← migra a Qdrant
│   │
│   ├── __init__.py
│   ├── config.py                        ← agrega configs Qdrant/scrapers
│   ├── main.py                          ← endpoint OpenAI-compat (se conserva)
│   ├── models.py                        ← agrega NewsChunkMetadata
│   └── pipeline.py                      ← orquesta sin traductor + con filters
│
├── data/
│   ├── raw/                             ← HTML/PDF intactos (nunca se tocan)
│   │   ├── eldia/YYYY/MM/
│   │   ├── bna/eldia/YYYY/
│   │   └── archive_org/
│   ├── parsed/                          ← JSON intermedio
│   ├── enriched/                        ← JSON con NER/gazetteer aplicado
│   └── gazetteer/
│       └── la_plata_partidos.json       ← lista de barrios/partidos
│
├── tests/
│   ├── test_query_filters.py            ← NUEVO
│   ├── test_pdf_parser.py               ← NUEVO
│   ├── test_ner.py                      ← NUEVO
│   └── ...
│
├── inspect_chunks.py                    ← se adapta
├── inspect_db.py                        ← se adapta a Qdrant
├── requirements.txt                     ← actualizado (ver §11)
├── requirements-eval.txt
└── pyproject.toml (opcional)

docker-compose.yml                       ← Qdrant en lugar de Chroma
docker-compose.gpu.yml                   ← se conserva (Ollama GPU)
Makefile                                 ← agrega targets de ingesta
docs/
├── architecture.md                      ← actualizado
└── prompts.md                           ← prompts ES de hemeroteca
README.md
.env.example
.gitignore
```

---

## 7. docker-compose objetivo

Reemplaza el `chromadb` por `qdrant`. El resto se mantiene.

```yaml
version: "3.8"

services:
  ollama:
    image: ollama/ollama:latest
    container_name: rag-ollama
    ports:
      - "${OLLAMA_PORT:-11434}:11434"
    volumes:
      - ollama_data:/root/.ollama
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:latest
    container_name: rag-qdrant
    ports:
      - "${QDRANT_PORT:-6333}:6333"
      - "${QDRANT_GRPC_PORT:-6334}:6334"
    volumes:
      - qdrant_data:/qdrant/storage
    environment:
      - QDRANT__SERVICE__HTTP_PORT=6333
      - QDRANT__SERVICE__GRPC_PORT=6334
    restart: unless-stopped

  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: rag-openwebui
    ports:
      - "${WEBUI_PORT:-3000}:8080"
    volumes:
      - openwebui_data:/app/backend/data
    environment:
      - ENABLE_OLLAMA_API=false
      - OPENAI_API_BASE_URLS=http://host.docker.internal:${BACKEND_PORT:-8080}/v1
      - OPENAI_API_KEYS=sk-dummy-key
      - WEBUI_AUTH=false
    depends_on:
      - ollama
    restart: unless-stopped

volumes:
  ollama_data:
    name: rag_ollama_data
  qdrant_data:
    name: rag_qdrant_data
  openwebui_data:
    name: rag_openwebui_data
```

---

## 8. Decisiones técnicas clave (con justificación)

### 8.1 ¿Por qué Qdrant y no Chroma?

La consulta típica de este sistema implica filtros estructurados (año, lugar). Sin pre-filter eficiente, los chunks de cualquier año "ganan" por similitud semántica aunque no correspondan al año pedido. Qdrant tiene índices nativos sobre payload; Chroma no. Diferencia esperada: 50ms vs 3s por query con millones de chunks.

### 8.2 ¿Por qué `multilingual-e5-large`?

- Modelo multilingüe de calidad alta (top de MTEB para español).
- No requiere traducción del corpus ni de la query → elimina una capa entera del pipeline.
- Tamaño manejable en CPU (~1.1GB).
- **Importante**: requiere prefijos `query: ...` y `passage: ...`. Hay que envolverlo manualmente porque LangChain no lo hace por default.

### 8.3 ¿Por qué dos granularidades?

Forzar nota individual sobre PDFs escaneados de los 30 es inviable (la segmentación de notas en escaneos viejos es un problema de visión por computadora no trivial). Forzar página entera para HTML moderno tira al tacho la estructura ya disponible. Mejor: usar lo que cada formato ofrece, marcarlo en metadata, y dejar que el reranker decida.

### 8.4 ¿Por qué Filter Extractor con LLM y no regex?

Las queries reales son ambiguas:
- "los 80" → `decade=1980`
- "del 86" → `year=1986`
- "Maradona después del Mundial" → `persons=["Maradona"]` + año inferible

Regex cubre casos básicos pero deja afuera demasiado. Un LLM chico (puede ser el mismo Ollama local) con un prompt few-shot estructurado resuelve esto en ~500ms con buena precisión. **Fallback obligatorio:** si el LLM falla, retrieval sin filtros.

### 8.5 ¿Por qué citas obligatorias en el prompt?

En periodístico, alucinar nombres/fechas es inaceptable y el LLM lo hace seguido. El prompt fuerza el formato:
> "Toda afirmación factual debe ir seguida de `[fuente N]`. Si no hay evidencia suficiente en los fragmentos provistos, respondé 'No tengo suficiente información en el archivo consultado'."

El Citation Builder valida que los `[fuente N]` referenciados existan en los chunks recuperados y los expande a referencias completas.

---

## 9. Fases de implementación

Cada fase deja algo **funcional y testeable**. No avanzar a la siguiente sin que la actual ande.

### Fase 1 — Infraestructura y un año de prueba (1-2 semanas)

**Objetivo:** end-to-end mínimo con un solo año de El Día web.

Tareas:
1. Actualizar `docker-compose.yml` (Qdrant en lugar de Chroma).
2. Crear estructura de carpetas nueva (`scrapers/`, `parsers/`, `enrichers/`, `data/`).
3. Implementar `scrapers/eldia_web.py` limitado a un año (ej. 2005), guardando en `data/raw/eldia/2005/`.
4. Implementar `parsers/html_parser.py` con `trafilatura`.
5. Adaptar `chunker.py` con separadores en español.
6. Implementar `enrichers/ner.py` con spaCy `es_core_news_md`.
7. Crear `enrichers/gazetteer.py` con lista base de La Plata.
8. Migrar `retrieval/vector_store.py` a Qdrant.
9. Adaptar `pipeline.py` quitando traductor.
10. Probar query end-to-end desde OpenWebUI.

**Criterio de aceptación:** "¿Qué pasó en La Plata en 2005?" devuelve respuesta con al menos 3 citas válidas.

### Fase 2 — Calidad de retrieval (1 semana)

**Objetivo:** retrieval robusto sobre el año de prueba.

Tareas:
1. Implementar `query_filters.py` con LLM extractor + fallback regex.
2. Adaptar `bm25_retriever.py` a tokenizer español (NLTK Snowball + stopwords).
3. Actualizar `reranker.py` a modelo multilingüe.
4. Implementar `citation.py`.
5. Reforzar prompt de generación con reglas de citado.
6. Tests unitarios de filter extractor con 20+ queries de ejemplo.

**Criterio de aceptación:** consultas con filtros temporales/geográficos devuelven solo chunks del rango pedido.

### Fase 3 — Escalar a HTML moderno (1-2 semanas)

**Objetivo:** indexar El Día 1996-2017.

Tareas:
1. Scraper reanudable con checkpoint por mes.
2. Política de rate limiting (1 req cada 2s).
3. Dedupe por URL canónica.
4. Indexación incremental (no reprocesar lo ya indexado).
5. Monitoreo con logs estructurados (volumen por mes, errores).

**Criterio de aceptación:** ~20 años de El Día indexados, búsquedas con buena recall.

### Fase 4 — OCR histórico (2-3 semanas)

**Objetivo:** indexar BNA 1930-1996 (priorizando décadas con mejor OCR).

Tareas:
1. Scraper de BNA con catálogo + descarga de PDFs.
2. `pdf_parser.py` con cascada `pdfplumber` → Tesseract.
3. Pipeline de cleaning específico para OCR (guiones, headers, footers).
4. Filtro por `ocr_confidence > 0.6` antes de indexar.
5. Orden de ataque: 1990s → 1980s → 1970s → ... → 1930s.

**Criterio de aceptación:** al menos 1980-1996 indexado con OCR aceptable.

### Fase 5 — Refinamiento (continuo)

- Set de evaluación con 50+ queries de prueba etiquetadas.
- Tuning de pesos RRF.
- Ajustes de prompt según errores observados.
- Documentación final.

---

## 10. Advertencias importantes

1. **OCR de prensa antigua es duro.** Columnas, fotos, tipografías de los 30. Aceptar que 1930-1960 va a tener 30-40% de chunks "ruidosos". El filtro por confidence ayuda pero no resuelve.
2. **Espacio en disco.** ~5-10 GB de PDFs por década por diario. Embeddings: ~3 GB por millón de chunks. Reservar al menos **100 GB libres**.
3. **Tiempo de ingesta.** Primer scraping + indexación: **días**. Todo debe ser reanudable con checkpoints y dedupe por hash.
4. **robots.txt.** Respetarlo siempre. Si El Día bloquea, depender solo de BNA/Archive.org para ese diario.
5. **El proyecto es académico.** Documentar las decisiones de fuente, licencia y uso justo en el README.

---

## 11. requirements.txt objetivo

Cambios respecto al actual (referencial, ajustar versiones según corresponda):

```text
# Framework
langchain>=0.2.0
langchain-community>=0.2.0
fastapi>=0.110
uvicorn[standard]>=0.27
pydantic>=2.6

# Vector store (NUEVO: Qdrant)
qdrant-client>=1.9.0

# Embeddings y reranking
sentence-transformers>=2.7.0
flashrank>=0.2.5

# BM25 en español
rank-bm25>=0.2.2
nltk>=3.8.1

# NLP
spacy>=3.7.0
# Descargar el modelo:
# python -m spacy download es_core_news_md

# Ingesta - scraping
httpx>=0.27
trafilatura>=1.9.0
beautifulsoup4>=4.12
lxml>=5.1
internetarchive>=3.6.0

# Ingesta - PDF/OCR
pdfplumber>=0.11
pytesseract>=0.3.10
pdf2image>=1.17.0
# Requiere instalación de sistema:
# sudo apt install tesseract-ocr tesseract-ocr-spa poppler-utils

# LLM client
ollama>=0.2.0

# Utilidades
python-dotenv>=1.0
tqdm>=4.66
tenacity>=8.2

# SE ELIMINAN dependencias de traducción
```

---

## 12. Makefile - targets sugeridos

```makefile
# Infra
up:               docker compose up -d
down:             docker compose down
reset-qdrant:     docker compose down -v && docker compose up -d qdrant

# Ingesta (todos reanudables)
scrape-eldia-web YEAR=2005:
	python -m backend.app.ingestion.scrapers.eldia_web --year $(YEAR)

scrape-bna YEAR=1986:
	python -m backend.app.ingestion.scrapers.bna_hemeroteca --year $(YEAR)

parse:
	python -m backend.app.ingestion.run --stage parse

enrich:
	python -m backend.app.ingestion.run --stage enrich

index:
	python -m backend.app.ingestion.run --stage index

ingest-all:       parse enrich index

# Backend
serve:            uvicorn backend.app.main:app --reload --port 8080

# Inspección
inspect-chunks:   python backend/inspect_chunks.py
inspect-db:      python backend/inspect_db.py

# Tests
test:             pytest backend/tests/ -v
```

---

## 13. Variables de entorno (`.env.example`)

```env
# Puertos
OLLAMA_PORT=11434
QDRANT_PORT=6333
QDRANT_GRPC_PORT=6334
WEBUI_PORT=3000
BACKEND_PORT=8080

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=hemeroteca_la_plata

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_LLM_MODEL=qwen2.5:7b-instruct
OLLAMA_EMBEDDING_MODEL=intfloat/multilingual-e5-large
# Nota: si preferís servir e5 fuera de Ollama, usar sentence-transformers directo.

# Scraping
SCRAPER_USER_AGENT=HemerotecaLaPlataAcademic/1.0
SCRAPER_RATE_LIMIT_SECONDS=2

# Pipeline
RRF_K=60
RETRIEVAL_TOP_K=20
RERANK_TOP_K=8
EVIDENCE_MIN_SCORE=0.35
```

---

## 14. Instrucciones para Claude (IDE)

Cuando trabajes este proyecto:

1. **Respetá la estructura actual** del repo. No renombres módulos existentes salvo que el plan lo indique.
2. **Implementá una fase por vez.** No saltees fases.
3. **Antes de cada PR/cambio grande**, revisá si afecta a `models.py` (schema de metadata). Si sí, documentalo en `docs/architecture.md`.
4. **Toda función que toque red** (scraping, Ollama, Qdrant) debe usar `tenacity` con retry exponencial.
5. **Logs estructurados** con `logging` configurado en `config.py`. Nada de `print` en producción.
6. **Tests obligatorios** para `query_filters.py`, `pdf_parser.py` (con un PDF chico de fixture) y `citation.py`.
7. **No reproduzcas texto de diarios verbatim** en tests o documentación: usar fragmentos sintéticos o muy cortos para evitar problemas de copyright.
8. **No tocar `data/raw/`** desde código que no sea scraping. Es inmutable.
9. **Embeddings con prefijos:** envolvé `multilingual-e5-large` para que documentos lleven `passage: ` y queries `query: `. Es un error frecuente olvidarlo y degrada calidad seriamente.
10. **Reanudabilidad:** cada stage de ingesta debe poder cortarse y retomar leyendo qué ya está en disco / qué ya está indexado por `chunk_id`.

---

## 15. Anexo: gazetteer base de La Plata

Lista mínima a poner en `data/gazetteer/la_plata_partidos.json` para arrancar (ampliable):

```json
{
  "city": "La Plata",
  "neighborhoods": [
    "Casco Urbano", "Tolosa", "Ringuelet", "Gonnet", "City Bell",
    "Villa Elisa", "Manuel B. Gonnet", "Los Hornos", "San Carlos",
    "Altos de San Lorenzo", "Villa Elvira", "Olmos", "Etcheverry",
    "Abasto", "Hernández", "Arana", "El Peligro", "Lisandro Olmos"
  ],
  "nearby_partidos": [
    "Berisso", "Ensenada", "Magdalena", "Brandsen",
    "San Vicente", "Cañuelas", "Florencio Varela"
  ],
  "landmarks": [
    "Catedral de La Plata", "Plaza Moreno", "Bosque de La Plata",
    "Estadio Único", "Estadio Ciudad de La Plata", "Estación La Plata",
    "Hipódromo de La Plata", "Teatro Argentino", "Pasaje Dardo Rocha",
    "Estadio José María Minella" 
  ]
}
```

---

## 16. Criterios finales de éxito

- Sistema funcional end-to-end desde OpenWebUI.
- Mínimo 20 años de cobertura indexada.
- Respuestas con citas verificables (link/PDF/página).
- Abstención correcta cuando no hay evidencia.
- Filtros temporales y geográficos funcionando con precisión >85% en un set de evaluación de 50 queries.
- Documentación actualizada en `docs/architecture.md` y `README.md`.
- Pipeline de ingesta reanudable, sin pérdida de progreso ante cortes.

---

*Fin del plan de implementación.*
