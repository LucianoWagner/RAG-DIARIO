"""
In-memory BM25 retriever with Spanish tokenization and metadata filtering.
"""

import re
import unicodedata
from rank_bm25 import BM25Okapi
from langchain_core.documents import Document
from loguru import logger

from app.config import get_settings

# Lista optimizada de stopwords en español para evitar dependencias externas
SPANISH_STOPWORDS = {
    "a", "al", "algo", "algunas", "algunos", "ante", "antes", "como", "con", "contra", 
    "cual", "cuando", "de", "del", "desde", "donde", "durante", "e", "el", "la", "las", 
    "le", "les", "lo", "los", "en", "entre", "era", "erais", "eran", "eras", "eres", "es", 
    "esa", "esas", "ese", "esos", "esta", "estaba", "estaban", "estas", "este", "estos", 
    "estoy", "fin", "fue", "fueron", "fui", "fuimos", "ha", "hace", "hacen", "hacer", 
    "hacia", "han", "hasta", "incluso", "mas", "me", "mi", "mis", "mismo", "muchos", "muy", 
    "no", "nos", "nosotros", "o", "otra", "otras", "otro", "otros", "para", "pero", "por", 
    "que", "quien", "quienes", "se", "sea", "sin", "sobre", "sois", "somos", "son", "soy", 
    "su", "sus", "tambien", "tanto", "te", "tenemos", "tener", "tengo", "ti", "tiene", 
    "tienen", "todo", "todos", "trabajo", "tres", "tuyas", "tuyo", "tuyos", "un", "una", 
    "unas", "uno", "unos", "usted", "ustedes", "va", "vamos", "van", "vaya", "verdad", 
    "via", "y", "ya", "yo"
}


def _remove_accents(text: str) -> str:
    """Elimina acentos y diacríticos de un string."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def spanish_tokenize(text: str) -> list[str]:
    """Tokenizador en español: minúsculas, remover acentos y stopwords."""
    text_clean = _remove_accents(text.lower())
    words = re.findall(r"\b\w+\b", text_clean)
    return [w for w in words if w not in SPANISH_STOPWORDS]


class EmptyBM25Retriever:
    def invoke(self, query: str, filters: dict | None = None) -> list[Document]:
        return []


class BM25RetrieverSpanish:
    def __init__(self, documents: list[Document], top_k: int):
        self.documents = documents
        self.top_k = top_k
        
        logger.info(f"Inicializando BM25RetrieverSpanish con {len(documents)} documentos.")
        self.tokenized_corpus = [spanish_tokenize(doc.page_content) for doc in self.documents]
        
        if self.documents:
            self.base_bm25 = BM25Okapi(self.tokenized_corpus)
        else:
            self.base_bm25 = None

    def invoke(self, query: str, filters: dict | None = None) -> list[Document]:
        if not self.documents or self.base_bm25 is None:
            return []

        # 1. Determinar si hay filtros activos
        has_active_filters = False
        if filters:
            for key, value in filters.items():
                if value is not None:
                    has_active_filters = True
                    break

        # 2. Filtrar documentos y corpus en memoria si corresponde
        if not has_active_filters:
            bm25_model = self.base_bm25
            docs_to_score = self.documents
            tokenized_to_score = self.tokenized_corpus
        else:
            filtered_docs = []
            filtered_tokenized = []
            
            for doc, tokens in zip(self.documents, self.tokenized_corpus):
                match = True
                for key, value in filters.items():
                    if value is not None:
                        # Si no hay metadatos o no coincide el valor, se excluye
                        doc_value = doc.metadata.get(key)
                        if doc_value != value:
                            match = False
                            break
                if match:
                    filtered_docs.append(doc)
                    filtered_tokenized.append(tokens)

            if not filtered_docs:
                logger.debug(f"Ningún documento coincide con los filtros de BM25: {filters}")
                return []

            bm25_model = BM25Okapi(filtered_tokenized)
            docs_to_score = filtered_docs

        # 3. Tokenizar query
        tokenized_query = spanish_tokenize(query)
        # Si la consulta se quedó vacía por stopwords, usar palabras crudas normalizadas como fallback
        if not tokenized_query:
            tokenized_query = re.findall(r"\b\w+\b", _remove_accents(query.lower()))

        if not tokenized_query:
            logger.debug("Consulta vacía para BM25 tras tokenización.")
            return docs_to_score[:self.top_k]

        # 4. Calcular relevancia
        scores = bm25_model.get_scores(tokenized_query)

        # 5. Ordenar resultados y adjuntar metadata de score y rank
        scored_docs = []
        for doc, score in zip(docs_to_score, scores):
            scored_docs.append((doc, float(score)))

        scored_docs.sort(key=lambda x: x[1], reverse=True)
        top_scored = scored_docs[:self.top_k]

        results = []
        for rank, (doc, score) in enumerate(top_scored):
            # Copiar documento para no mutar el corpus original en memoria
            doc_copy = Document(page_content=doc.page_content, metadata=dict(doc.metadata))
            doc_copy.metadata["bm25_score"] = score
            doc_copy.metadata["bm25_rank"] = rank
            results.append(doc_copy)

        return results


def create_bm25_retriever(chunks: list[Document]):
    settings = get_settings()
    if not chunks:
        return EmptyBM25Retriever()

    return BM25RetrieverSpanish(chunks, top_k=settings.top_k)
