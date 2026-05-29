# Adaptación del Pipeline RAG a Hemeroteca Página/12

Adaptar el pipeline heredado del RAG de Docker para optimizarlo para la Hemeroteca Argentina con Página/12, utilizando Qdrant, chunks enriquecidos y metadatos históricos para realizar búsquedas híbridas precisas y generación fiel a las fuentes.

## User Review Required

> [!IMPORTANT]
> **Decisión de Scope de Retrieval**: Por defecto, el retrieval filtrará usando `article_country_scope="argentina"` en lugar de `country_scope="argentina"`. Esto permite que si un fragmento conceptual queda marcado como "unknown" a nivel de chunk, pero pertenece a una nota con evidencia argentina fuerte, no se pierda el contexto completo.

> [!TIP]
> **Reranker Configurable**: FlashRank es rápido, pero `ms-marco-MultiBERT-L-12` a veces rinde por debajo de lo esperado en español. Añadiremos soporte configurable en `.env` para usar opcionalmente un CrossEncoder de `sentence-transformers` (ej. `BAAI/bge-reranker-large` o similar) si se prefiere mayor calidad a costa de tiempo de cómputo en CPU.

## Proposed Changes

---

### 1. Query Planning y Extracción de Filtros

Se reemplazará el enrutador binario actual por un `QueryPlanner` más potente.

#### [NEW] [query_planner.py](file:///e:/ProyectoRagFacultad2/backend/app/generation/query_planner.py)
* Encapsulará la llamada estructurada al LLM (`llama-3.3-70b-versatile`) para clasificar la consulta en una de tres categorías (`CHITCHAT`, `ARCHIVE_SEARCH`, `OUT_OF_SCOPE`) y extraer simultáneamente filtros históricos:
  * `year`: Año específico detectado (ej: 2005).
  * `decade`: Década detectada (ej: 1990).
  * `publication_date`: Fecha exacta (YYYY-MM-DD).
  * `section`: Sección normalizada (ej: "elpais", "economia", "espectaculos").
  * `newspaper`: Nombre del diario (por defecto "pagina12").
  * `article_country_scope`: Ámbito geográfico (por defecto "argentina").
  * `search_query`: Consulta optimizada para búsqueda léxica/semántica (eliminando ruido temporal y conversacional).
* Contendrá un fallback por expresiones regulares si falla la API del LLM.

#### [MODIFY] [router.py](file:///e:/ProyectoRagFacultad2/backend/app/generation/router.py)
* Mantener funciones de chitchat simples y respuestas rápidas para saludos o agradecimientos.

---

### 2. Recuperación Semántica con Filtros Qdrant

#### [MODIFY] [vector_store.py](file:///e:/ProyectoRagFacultad2/backend/app/retrieval/vector_store.py)
* Modificar `QdrantSemanticRetriever.invoke(query, filters=None)` para que traduzca el diccionario de filtros extraído a un objeto `qmodels.Filter` de Qdrant.
* Asegurar que se preserve el `semantic_score` en los metadatos de los documentos resultantes.

---

### 3. Recuperación Léxica BM25 en Español

#### [MODIFY] [bm25_retriever.py](file:///e:/ProyectoRagFacultad2/backend/app/retrieval/bm25_retriever.py)
* Reemplazar la dependencia de `langchain_community` por el uso directo de `rank-bm25` (`BM25Okapi`).
* Implementar tokenización en español: conversión a minúsculas, eliminación de acentos/diacríticos (normalización Unicode), extracción de palabras por regex y filtrado de una lista optimizada de stopwords en español.
* Implementar filtrado en memoria por metadatos *antes* de calificar con BM25, de manera que los resultados respeten estrictamente el año, la sección o el alcance temporal solicitado sin recalcular el índice completo en cada llamada.
* Guardar en los metadatos de cada documento: `bm25_score` y `bm25_rank`.

---

### 4. Búsqueda Híbrida y RRF

#### [MODIFY] [hybrid.py](file:///e:/ProyectoRagFacultad2/backend/app/retrieval/hybrid.py)
* Modificar `CustomHybridRetriever` para recibir filtros y transmitirlos a los retrievers léxico y semántico.
* Reemplazar la desduplicación basada en texto por desduplicación basada en `chunk_id`.
* Registrar en los metadatos del chunk fusionado: `rrf_score`, `semantic_rank` y `bm25_rank`.
* Implementar ajuste adaptativo de pesos:
  * Si la consulta contiene fechas, números, nombres propios o títulos: `bm25_weight = 0.6`, `semantic_weight = 0.4`.
  * Si la consulta es conceptual o abstracta: `semantic_weight = 0.6`, `bm25_weight = 0.4`.
  * En otro caso, usar `0.5 / 0.5`.

---

### 5. Reranker y Carga Paginada

#### [MODIFY] [reranker.py](file:///e:/ProyectoRagFacultad2/backend/app/retrieval/reranker.py)
* Permitir configurar a través de variables de entorno si se usa FlashRank o un CrossEncoder de `sentence-transformers` para reranking.
* Asegurar que los metadatos de ranking previos se conserven.

#### [MODIFY] [pipeline.py](file:///e:/ProyectoRagFacultad2/backend/app/pipeline.py)
* Modificar `_load_documents_for_bm25` para realizar una lectura paginada (scroll) de Qdrant hasta descargar todos los puntos existentes (o un límite configurado de 10.000) en lugar de hacer un scroll estático de `limit=5000`.
* Conectar el flujo completo de `QueryPlanner` -> `HybridRetriever(filters)` -> `Reranker` -> `EvidenceChecker` -> `Generator`.

---

### 6. Validación de Evidencia y Generación

#### [MODIFY] [evidence_checker.py](file:///e:/ProyectoRagFacultad2/backend/app/generation/evidence_checker.py)
* Sophisticar la evaluación de suficiencia:
  * Evaluar el score del top chunk y la cantidad de chunks relevantes.
  * Agrupar por `source_id` para contar cuántos artículos distintos se han recuperado.
  * Validar si los chunks recuperados realmente coinciden con los filtros temporales explícitos (ej. si el usuario pidió "2005" y los chunks devueltos son de otro año, marcar `INSUFFICIENT`).
  * Para consultas específicas de datos puntuales: basta 1 artículo fuerte o 2 chunks relevantes.
  * Para consultas abiertas o de resumen general: exigir al menos 3 chunks relevantes y 2 artículos distintos.

#### [MODIFY] [generator.py](file:///e:/ProyectoRagFacultad2/backend/app/generation/generator.py)
* Adaptar prompts para referirse a la Hemeroteca de Página/12 en lugar de La Plata (salvo que la metadata indique lo contrario).
* Validar sintaxis de citas `[Fuente N]` devueltas por el LLM. Si no hay citas factuales o se citan fuentes inexistentes, reformular o abstenerse según el veredicto.
* Ajustar el tono si la evidencia es `LOW_CONFIDENCE` para dar una respuesta cautelosa ("Con la evidencia disponible...").

---

## Verification Plan

### Automated Tests
Ejecutaremos los tests unitarios correspondientes para validar de forma aislada:
1. `QueryPlanner`: clasificación correcta de `CHITCHAT` vs `ARCHIVE_SEARCH` vs `OUT_OF_SCOPE` y extracción precisa de metadatos/fechas.
2. `Qdrant filter builder`: correcto mapeo a filtros Qdrant.
3. `BM25 español`: normalización unicode de acentos, remoción de stopwords y filtrado en memoria pre-ranking.
4. `Hybrid retriever`: deduplicación por `chunk_id` y pesos dinámicos.
5. `Evidence checker`: validación de suficiencia por tipo de consulta y filtros temporales.

Comando para correr los tests unitarios:
```powershell
backend/venv/Scripts/python -m pytest backend/tests/
```

### Manual Verification
* Realizar consultas reales a través de la API (o utilizando un script de prueba interactivo) para evaluar la calidad de las respuestas en los tres escenarios de intención y verificar la inserción exacta de citas.
