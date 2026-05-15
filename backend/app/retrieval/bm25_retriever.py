"""
In-memory BM25 retriever.
"""

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from app.config import get_settings


class EmptyBM25Retriever:
    def invoke(self, query: str) -> list[Document]:
        return []


def create_bm25_retriever(chunks: list[Document]):
    settings = get_settings()
    if not chunks:
        return EmptyBM25Retriever()

    retriever = BM25Retriever.from_documents(chunks)
    retriever.k = settings.top_k
    return retriever
