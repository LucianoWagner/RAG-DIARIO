---
name: rag-implementer
description: Implement or modify the Hemeroteca La Plata RAG migration from the existing Docker documentation RAG project. Use when working on phase-based implementation, ingestion, scraping, parsing, OCR, Qdrant vector storage, Spanish BM25, multilingual embeddings, reranking, query filters, citation building, evidence checking, OpenWebUI compatibility, or tests for the Hemeroteca RAG system.
---

# Hemeroteca RAG Implementer

Use this skill to implement the migration from the Docker documentation RAG system to a Hemeroteca La Plata historical newspaper RAG system.

## Core Rules

- Preserve the existing FastAPI and LangChain architecture unless the task explicitly requires a migration step.
- Implement one phase at a time.
- Prefer minimal diffs over broad rewrites.
- Inspect only the files relevant to the current task before editing.
- Keep user-facing answers and prompts in Spanish unless the surrounding code requires English.
- Do not reintroduce `translator.py`; the Hemeroteca pipeline operates directly in Spanish.
- Do not add production dependencies without explaining why they are needed.
- Do not touch `data/raw/` except from scraper code; treat raw sources as immutable.

## Phase Order

Follow this order unless the user explicitly selects a different phase:

1. Infrastructure and one test year.
2. Retrieval quality.
3. Modern HTML scaling.
4. Historical OCR.
5. Evaluation and refinement.

Before coding, identify the current phase from the request, existing files, or `PLAN_HEMEROTECA_RAG.md`.

## Expected Architecture

Keep changes within the existing module boundaries:

- `backend/app/ingestion/`
- `backend/app/retrieval/`
- `backend/app/generation/`
- `backend/app/models.py`
- `backend/app/pipeline.py`
- `backend/app/config.py`
- `backend/app/main.py`

Expected target modules include:

- `backend/app/ingestion/scrapers/`
- `backend/app/ingestion/parsers/`
- `backend/app/ingestion/enrichers/`
- `backend/app/ingestion/indexer.py`
- `backend/app/retrieval/vector_store.py`
- `backend/app/retrieval/bm25_retriever.py`
- `backend/app/retrieval/hybrid.py`
- `backend/app/retrieval/reranker.py`
- `backend/app/generation/query_filters.py`
- `backend/app/generation/citation.py`
- `backend/app/generation/evidence_checker.py`
- `backend/app/generation/generator.py`

## Technical Decisions

- Use Qdrant instead of ChromaDB.
- Use multilingual embeddings suitable for Spanish.
- If using `intfloat/multilingual-e5-large`, prefix queries with `query: ` and passages with `passage: `.
- Use Spanish BM25 tokenization with stemming and Spanish stopwords.
- Use a multilingual reranker.
- Preserve OpenWebUI compatibility through the OpenAI-compatible backend endpoints.
- Use `tenacity` with exponential retry around network calls such as scraping, Ollama, and Qdrant operations.
- Use structured logging configured through `config.py`; avoid production `print` calls.

## Metadata Contract

Use structured metadata for retrieved and indexed chunks:

- `publication_date`
- `year`
- `decade`
- `newspaper`
- `source_type`
- `primary_location`
- `location_mentions`
- `persons`
- `organizations`
- `source_url`
- `source_pdf_path`
- `page_number`
- `ocr_confidence`

When changing metadata schema, check whether `backend/app/models.py`, ingestion, retrieval filters, citation formatting, and `docs/architecture.md` must be updated together.

## Retrieval Rules

- Prefer filtered retrieval when a query includes years, decades, date ranges, locations, people, or organizations.
- Do not allow semantic similarity to override explicit temporal filters.
- Implement fallback behavior when filter extraction fails.
- Keep RRF-based hybrid retrieval unless there is a specific reason to change it.
- Build citations only from chunks that were actually retrieved.

## Evidence And Citation Rules

- Require citations for factual claims.
- Abstain when evidence is insufficient instead of guessing.
- Validate that generated citation markers refer to retrieved sources.
- Include page numbers or source URLs when available.
- Avoid reproducing long newspaper text verbatim in tests or documentation; use synthetic snippets or very short excerpts.

## Phase Guidance

### Phase 1: Infrastructure And One Test Year

Implement a minimal end-to-end path for one year of El Dia web content.

Typical tasks:

- Replace ChromaDB with Qdrant in Docker and config.
- Add ingestion subdirectories for scrapers, parsers, enrichers, and local data.
- Implement a limited `eldia_web` scraper for one year.
- Parse modern HTML with `trafilatura` or existing planned parsers.
- Add metadata enrichment for dates, locations, people, and organizations.
- Migrate `vector_store.py` to Qdrant.
- Remove translator usage from `pipeline.py`.
- Verify an OpenWebUI query returns cited results.

Acceptance target: a query like `¿Qué pasó en La Plata en 2005?` returns at least three valid citations.

### Phase 2: Retrieval Quality

Improve retrieval over the test year.

Typical tasks:

- Implement `query_filters.py` with structured extraction and regex fallback.
- Update `bm25_retriever.py` for Spanish tokenization.
- Update `reranker.py` to a multilingual model.
- Implement `citation.py`.
- Strengthen generation prompts around citations and abstention.
- Add focused unit tests for filters and citations.

Acceptance target: temporal and geographic filters return only chunks from the requested scope.

### Phase 3: Modern HTML Scaling

Scale from the test year to El Dia web coverage.

Typical tasks:

- Add resumable scraping and indexing.
- Add deduplication by stable source ID or content hash.
- Add rate limiting and checkpointing.
- Add inspection tools for indexed years and chunk quality.

### Phase 4: Historical OCR

Add historical scanned newspaper support only after modern HTML works end to end.

Typical tasks:

- Implement BNA or Internet Archive discovery and download.
- Parse PDFs with `pdfplumber` and Tesseract fallback.
- Clean OCR-specific artifacts.
- Store page-level metadata and OCR confidence.
- Filter or down-rank low-confidence OCR chunks.

### Phase 5: Evaluation And Refinement

Add evaluation after retrieval and citations are stable.

Typical tasks:

- Create a labeled query set.
- Measure temporal filter precision, citation validity, abstention behavior, and answer usefulness.
- Refine prompts, filters, and reranking based on failures.

## Testing Rules

Add or update focused tests when changing:

- `query_filters.py`
- `citation.py`
- `pdf_parser.py`
- `bm25_retriever.py`
- `vector_store.py`
- metadata schema

Prefer small unit tests over full pipeline tests unless the change crosses multiple modules. Run the most relevant test command available in the repo after edits.

## Completion Summary

After implementing a change, summarize:

- files changed
- what was implemented
- tests or commands run
- what remains
- risks or assumptions
