# Adaptación del Pipeline RAG a Hemeroteca Página/12 (Revisado)

Adaptar el pipeline heredado del RAG de Docker para optimizarlo para la Hemeroteca Argentina con Página/12, utilizando Qdrant, chunks enriquecidos y metadatos históricos para realizar búsquedas híbridas precisas y generación fiel a las fuentes.

## User Review Required

> [!NOTE]
> **Modificaciones según feedback**:
> 1. **Enrutamiento optimizado**: El `QueryPlanner` utilizará la clasificación heurística local (regex y keywords) primero. Si detecta chitchat de forma inequívoca, resolverá la consulta inmediatamente sin llamadas al LLM.
> 2. **Sin filtros de ámbito geográfico forzados**: No limitaremos la búsqueda aplicando filtros duros de `article_country_scope` para evitar falsos negativos. Dejaremos que la búsqueda vectorial traiga los mejores candidatos y el `EvidenceChecker` valide la suficiencia.
> 3. **Búsquedas abiertas y sin fecha**: El sistema tolerará de forma nativa búsquedas sin metadatos explícitos (ej. "accidente de moto que ingresó a un hospital"), realizando búsqueda semántica e híbrida limpia sin filtros de fecha obligatorios.
> 4. **Citas simplificadas**: Simplificaremos el prompt de generación para no forzar una validación compleja de citas inline `[Fuente N]`. Delegaremos la visualización de fuentes directamente a la respuesta estructurada que consume OpenWebUI para renderizar los enlaces.
> 5. **Reranker de Alta Calidad**: Se integrará soporte nativo para un CrossEncoder de `sentence-transformers` (ej. `BAAI/bge-reranker-large`) como opción de máxima calidad, configurable por entorno.

## Proposed Changes

---

### 1. Query Planning y Extracción de Filtros

Se reemplazará el enrutador binario actual por un `QueryPlanner` más potente.

#### [NEW] [query_planner.py](file:///e:/ProyectoRagFacultad2/backend/app/generation/query_planner.py)
* Encapsulará la lógica de enrutamiento y extracción:
  * **Paso 1: Heurística Local**. Comprobar patrones de saludo, gracias o despedidas de forma local. Si coincide, clasificar como `CHITCHAT` inmediatamente.
  * **Paso 2: Clasificación y Extracción vía LLM**. Si no es chitchat básico, llamar al LLM estructurado para clasificar entre `ARCHIVE_SEARCH` u `OUT_OF_SCOPE` (preguntas completamente fuera de un archivo periodístico como código, recetas de cocina, etc.) y extraer de forma opcional filtros históricos:
    * `year`: Año específico detectado (ej: 2005).
    * `decade`: Década detectada (ej: 1990).
    * `publication_date`: Fecha exacta (YYYY-MM-DD).
    * `section`: Sección normalizada (ej: "elpais", "economia", "espectaculos").
    * `newspaper`: Nombre del diario (por defecto "pagina12").
    * `search_query`: Consulta optimizada para búsqueda léxica/semántica (eliminando ruido conversacional).
* Si no se extrae ningún filtro de fecha o sección, los filtros quedarán vacíos (`None`), ejecutando una búsqueda híbrida abierta.

#### [MODIFY] [router.py](file:///e:/ProyectoRagFacultad2/backend/app/generation/router.py)
* Limpiar o redirigir las funciones de enrutamiento heredadas hacia el nuevo `QueryPlanner`.

---

### 2. Recuperación Semántica con Filtros Qdrant

#### [MODIFY] [vector_store.py](file:///e:/ProyectoRagFacultad2/backend/app/retrieval/vector_store.py)
* Modificar `QdrantSemanticRetriever.invoke(query, filters=None)` para que construya y aplique filtros estructurados Qdrant (`qmodels.Filter`) si están presentes en la planificación de la query (ej. año o sección).
* Preservar el `semantic_score` en la metadata de los documentos.

---

### 3. Recuperación Léxica BM25 en Español

#### [MODIFY] [bm25_retriever.py](file:///e:/ProyectoRagFacultad2/backend/app/retrieval/bm25_retriever.py)
* Reemplazar `langchain_community` por el uso directo de `rank-bm25` (`BM25Okapi`).
* Implementar tokenización en español: minúsculas, remover acentos/diacríticos y quitar stopwords españolas.
* Aplicar los mismos filtros de metadatos (año, sección) sobre los documentos cargados en memoria *antes* de calificar con BM25.
* Preservar `bm25_score` y `bm25_rank` en la metadata.

---

### 4. Búsqueda Híbrida y RRF

#### [MODIFY] [hybrid.py](file:///e:/ProyectoRagFacultad2/backend/app/retrieval/hybrid.py)
* Modificar `CustomHybridRetriever` para recibir filtros y transmitirlos a los retrievers léxico y semántico.
* Reemplazar la desduplicación basada en texto por desduplicación basada en `chunk_id`.
* Registrar `rrf_score`, `semantic_rank` y `bm25_rank` en los metadatos.
* Ponderación dinámica de pesos:
  * Si la consulta contiene números, fechas, nombres propios o títulos: `bm25_weight = 0.6`, `semantic_weight = 0.4`.
  * Si la consulta es conceptual o abstracta: `semantic_weight = 0.6`, `bm25_weight = 0.4`.
  * En otro caso, usar `0.5 / 0.5`.

---

### 5. Reranker CrossEncoder de Alta Calidad y Carga Paginada

#### [MODIFY] [reranker.py](file:///e:/ProyectoRagFacultad2/backend/app/retrieval/reranker.py)
* Configurar soporte para CrossEncoder de `sentence-transformers` (usando un modelo multilingüe o español potente como `BAAI/bge-reranker-large` o `cross-encoder/ms-marco-MiniLM-L-6-v2`) como opción por defecto en `.env`.

#### [MODIFY] [pipeline.py](file:///e:/ProyectoRagFacultad2/backend/app/pipeline.py)
* Cambiar la carga de BM25 a scroll paginado para no recortar la base en 5.000 documentos.
* Conectar el flujo con el `QueryPlanner`.

---

### 6. Validación de Evidencia y Generación

#### [MODIFY] [evidence_checker.py](file:///e:/ProyectoRagFacultad2/backend/app/generation/evidence_checker.py)
* Evaluar suficiencia considerando el score del top chunk, cantidad de chunks relevantes y cantidad de artículos únicos (`source_id`).
* Comprobar temporalidad: si se especificó un año/fecha y ningún chunk recuperado coincide, marcar `INSUFFICIENT`.
* Definir umbrales diferenciados para consultas puntuales (1 artículo o 2 chunks fuertes) y consultas de resumen/amplias (al menos 3 chunks y 2 artículos distintos).

#### [MODIFY] [generator.py](file:///e:/ProyectoRagFacultad2/backend/app/generation/generator.py)
* Actualizar prompts para referirse a la Hemeroteca de Página/12.
* Devolver las referencias de los documentos cargados directamente en el arreglo `sources` para que OpenWebUI renderice los links, simplificando la exigencia de citado inline del LLM.

---

## Verification Plan

### Automated Tests
* Escribir y ejecutar tests unitarios sobre:
  1. `QueryPlanner` (heurísticas y llamadas con pocos ejemplos).
  2. Filtros Qdrant y BM25 (filtrado en memoria).
  3. RRF con deduplicación por ID.
  4. Suficiencia en `EvidenceChecker`.
  
Comando:
```powershell
backend/venv/Scripts/python -m pytest backend/tests/
```
