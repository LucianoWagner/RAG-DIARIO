"""
Spanish-aware chunking for newspaper content.
"""

from collections import defaultdict

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings


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


def chunk_documents(
    documents: list[Document],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Document]:
    settings = get_settings()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or settings.chunk_size,
        chunk_overlap=chunk_overlap or settings.chunk_overlap,
        separators=SPANISH_SEPARATORS,
        length_function=len,
        is_separator_regex=False,
        keep_separator=True,
    )

    chunks = splitter.split_documents(documents)
    grouped: dict[str, list[Document]] = defaultdict(list)
    for chunk in chunks:
        grouped[str(chunk.metadata.get("source_id", "unknown"))].append(chunk)

    for group in grouped.values():
        total = len(group)
        for index, chunk in enumerate(group):
            chunk.metadata["chunk_index"] = index
            chunk.metadata["total_chunks"] = total
            source_id = str(chunk.metadata.get("source_id", "unknown"))
            chunk.metadata["chunk_id"] = f"{source_id}::chunk::{index}"

    return chunks
