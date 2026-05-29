import pytest
from langchain_core.documents import Document
from app.retrieval.bm25_retriever import BM25RetrieverSpanish, spanish_tokenize, _remove_accents


def test_spanish_tokenize():
    # Test normalización de acentos y minúsculas
    tokens = spanish_tokenize("Constitución y Elección de Presidente, en La Plata.")
    # Stopwords eliminadas: y, de, en, la
    assert "constitucion" in tokens
    assert "eleccion" in tokens
    # Verificamos acento removido
    assert "ó" not in "".join(tokens)
    assert "ú" not in "".join(tokens)
    
    # Test eliminación de stopwords
    tokens_sw = spanish_tokenize("el la los un una que de y en")
    assert tokens_sw == []


def test_bm25_spanish_retrieval_and_ranking():
    docs = [
        Document(page_content="La Plata sufrió una gran inundación.", metadata={"year": 2013, "section": "sociedad"}),
        Document(page_content="Las elecciones legislativas del 2005 fueron ganadas.", metadata={"year": 2005, "section": "elpais"}),
        Document(page_content="Inundación histórica en la provincia.", metadata={"year": 2005, "section": "sociedad"}),
    ]
    
    retriever = BM25RetrieverSpanish(docs, top_k=2)
    
    # Búsqueda sin filtros
    results = retriever.invoke("inundación")
    assert len(results) == 2
    assert results[0].page_content == "Inundación histórica en la provincia." or results[0].page_content == "La Plata sufrió una gran inundación."
    assert "bm25_score" in results[0].metadata
    assert results[0].metadata["bm25_rank"] == 0
    assert results[1].metadata["bm25_rank"] == 1


def test_bm25_spanish_metadata_filtering():
    docs = [
        Document(page_content="Inundación histórica en 2013.", metadata={"year": 2013, "section": "sociedad"}),
        Document(page_content="Inundación en 2005.", metadata={"year": 2005, "section": "elpais"}),
        Document(page_content="Otra inundación en 2005.", metadata={"year": 2005, "section": "sociedad"}),
    ]
    
    retriever = BM25RetrieverSpanish(docs, top_k=5)
    
    # Filtro por año 2005
    results_2005 = retriever.invoke("inundación", filters={"year": 2005})
    assert len(results_2005) == 2
    for doc in results_2005:
        assert doc.metadata["year"] == 2005
        
    # Filtro por sección elpais
    results_elpais = retriever.invoke("inundación", filters={"section": "elpais"})
    assert len(results_elpais) == 1
    assert results_elpais[0].metadata["section"] == "elpais"
    assert results_elpais[0].metadata["year"] == 2005
    
    # Filtro por año y sección combinados
    results_comb = retriever.invoke("inundación", filters={"year": 2005, "section": "sociedad"})
    assert len(results_comb) == 1
    assert results_comb[0].metadata["year"] == 2005
    assert results_comb[0].metadata["section"] == "sociedad"


def test_bm25_spanish_query_fallback():
    docs = [
        Document(page_content="El gobierno de la provincia.", metadata={"year": 2005}),
    ]
    retriever = BM25RetrieverSpanish(docs, top_k=1)
    
    # Si la query contiene solo stopwords ("el la"), el tokenizador devuelve vacío, 
    # pero el retriever tiene un fallback para usar las palabras crudas normalizadas.
    results = retriever.invoke("el la")
    assert len(results) == 1
    assert "bm25_score" in results[0].metadata
