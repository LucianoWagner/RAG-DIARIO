# Arquitectura del Sistema RAG

## Estado de Fase 1

La migracion inicial reemplaza el pipeline Docker-docs por una base Hemeroteca centrada en HTML de `El Dia` para un ano de prueba.

## Diagrama General

```
OpenWebUI -> FastAPI (/v1/chat/completions) -> Router -> Hybrid Retrieval -> Evidence Check -> Generator
                                                |                |
                                                |                +-> BM25 en memoria
                                                +-> Qdrant <- sentence-transformers (multilingual-e5-large)

Ingesta offline:
scrapers/eldia_web.py -> parsers/html_parser.py -> chunker.py -> enrichers/ner.py + gazetteer.py -> Qdrant
```

## Metadata de Fase 1

El schema principal del proyecto es [models.py](E:/ProyectoRagFacultad2/backend/app/models.py).

- `chunk_id`
- `source_id`
- `newspaper`
- `source_type`
- `granularity`
- `publication_date`
- `year`
- `decade`
- `primary_location`
- `location_mentions`
- `persons`
- `organizations`
- `source_url`
- `page_number`
- `ocr_confidence`
- `text`
- `text_clean`

## Decisiones activas

- ChromaDB fue reemplazado por Qdrant para soportar filtros por payload.
- La traduccion ES<->EN se removio del `pipeline.py`; la fase 1 ya opera directamente en espanol.
- El parser inicial cubre HTML moderno con `trafilatura`.
- OCR historico, filtros estructurados y citation builder academico quedan para fases posteriores.
