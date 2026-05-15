"""
FlashRank reranking for retrieved chunks.
"""

from flashrank import Ranker, RerankRequest
from langchain_core.documents import Document

from app.config import get_settings

try:
    _ranker = Ranker(model_name=get_settings().reranker_model_name)
except Exception:
    _ranker = None


def rerank_documents(query: str, documents: list[Document]) -> list[Document]:
    settings = get_settings()
    if not documents:
        return []

    global _ranker
    if _ranker is None:
        _ranker = Ranker(model_name=settings.reranker_model_name)

    passages = [
        {"id": index, "text": document.page_content, "meta": document.metadata}
        for index, document in enumerate(documents)
    ]
    results = _ranker.rerank(RerankRequest(query=query, passages=passages))

    ranked_docs = []
    for rank, result in enumerate(results[: settings.rerank_top_n], start=1):
        doc = Document(page_content=result["text"], metadata=result.get("meta", {}))
        doc.metadata["rerank_score"] = result.get("score", 0.0)
        doc.metadata["rerank_position"] = rank
        ranked_docs.append(doc)
    return ranked_docs
