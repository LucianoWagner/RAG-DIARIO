from langchain_core.documents import Document

from app.retrieval import vector_store


class FakeEmbeddingFunction:
    def __init__(self):
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(index), 9.0] for index, _text in enumerate(texts, start=1)]


def test_resolve_embeddings_reutiliza_vectores_y_calcula_faltantes(monkeypatch):
    fake_embeddings = FakeEmbeddingFunction()
    monkeypatch.setattr(vector_store, "get_embedding_function", lambda: fake_embeddings)
    chunks = [
        Document(page_content="ya tiene vector", metadata={"_index_vector": [0.1, 0.2]}),
        Document(page_content="falta vector", metadata={}),
        Document(page_content="tambien tiene vector", metadata={"_index_vector": [0.3, 0.4]}),
    ]

    resolved = vector_store._resolve_embeddings(chunks)

    assert resolved == [[0.1, 0.2], [1.0, 9.0], [0.3, 0.4]]
    assert fake_embeddings.calls == [["falta vector"]]


def test_payload_no_persiste_index_vector():
    chunk = Document(page_content="texto", metadata={"_index_vector": [0.1, 0.2], "source_id": "a"})

    payload = dict(chunk.metadata)
    payload.pop("_index_vector", None)
    payload["text"] = chunk.page_content

    assert "_index_vector" not in payload
    assert payload["text"] == "texto"
