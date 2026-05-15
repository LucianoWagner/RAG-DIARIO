"""
FastAPI entrypoint for the Hemeroteca RAG backend.
"""

import time
from functools import lru_cache

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.models import ChatCompletionRequest

settings = get_settings()

app = FastAPI(
    title="Hemeroteca RAG API",
    description="Asistente RAG para hemeroteca historica de La Plata",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
        "qdrant_url": settings.qdrant_url,
    }


@lru_cache()
def get_pipeline():
    from app.pipeline import RAGPipeline

    return RAGPipeline()


@app.post("/query")
async def query_rag(question: str):
    pipeline = get_pipeline()
    return pipeline.run(question).model_dump()


@app.post("/ingest")
async def ingest_corpus(background_tasks: BackgroundTasks, force: bool = False, year: int | None = None):
    from app.ingestion.run import run_ingestion

    background_tasks.add_task(run_ingestion, force=force, year=year)
    return {
        "status": "processing",
        "message": "Ingesta iniciada en segundo plano.",
        "force_applied": force,
        "year": year or settings.scraper_target_year,
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "hemeroteca-rag-assistant",
                "object": "model",
                "owned_by": "local",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    question = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            question = msg.content
            break

    if not question:
        question = "Hola"

    try:
        rag_response = get_pipeline().run(question)
        final_answer = rag_response.answer
        if rag_response.sources:
            final_answer += "\n\nFuentes:\n"
            for src in rag_response.sources:
                date_text = src.publication_date.isoformat() if src.publication_date else "s/f"
                final_answer += f"- {src.source_label} | {date_text}\n"
    except Exception as exc:
        final_answer = f"Error procesando la solicitud: {exc}"

    return {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": final_answer,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
