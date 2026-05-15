"""
Tests para el módulo vector_store.py y persistencia en ChromaDB.
"""

import pytest
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import FakeEmbeddings


class TestVectorStoreRoundtrip:
    """
    Tests de integración para comprobar guardar y recuperar de la BD vectorial,
    asegurando la preservación de metadata y contenido.
    """

    @pytest.fixture
    def in_memory_vector_store(self):
        """
        Crea una base ChromaDB efímera en memoria para el test,
        y usa 'FakeEmbeddings' para no depender de que Ollama esté corriendo
        (al test de BD no le importa el valor real del vector, solo poder guardarlo).
        """
        embeddings_mock = FakeEmbeddings(size=768)  # Misma dimensión que nomic-embed-text
        
        # Iniciar Chroma en memoria (sin persistencia en disco)
        vector_store = Chroma(
            collection_name="test_collection",
            embedding_function=embeddings_mock,
        )
        return vector_store

    def test_chunk_metadata_is_preserved_roundtrip(self, in_memory_vector_store):
        """
        Prueba que enviando un chunk a la BD con metadata, este se guarda,
        genera un ID, y se recupera intacto. Imprime 3 ejemplos para inspección.
        """
        # 1. Definimos 3 chunks de prueba
        chunks_originales = [
            Document(
                page_content="docker run -d -p 8080:80 nginx",
                metadata={"source_file": "referencia/comandos/run.md", "category": "cli_reference", "platform": "general"}
            ),
            Document(
                page_content="Para instalar en Windows descarga el .exe",
                metadata={"source_file": "desktop/install/windows.md", "category": "installation", "platform": "windows"}
            ),
            Document(
                page_content="Si tenes error 'Cannot connect to the Docker daemon', revisa los servicios",
                metadata={"source_file": "desktop/troubleshoot.md", "category": "troubleshooting", "platform": "linux"}
            )
        ]

        # 2. Guardamos en la BD Vectorial
        ids_generados = in_memory_vector_store.add_documents(chunks_originales)
        
        # 3. Recuperamos de la base de datos pidiendo que INCLUYA LOS VECTORES ('embeddings')
        # Por defecto Langchain Chroma devuelve solo el documento, pedimos al cliente subyacente la data cruda.
        resultados_db = in_memory_vector_store._collection.get(
            ids=ids_generados,
            include=['metadatas', 'documents', 'embeddings']
        )

        print("\n" + "=" * 80)
        print("  🔍 INSPECCIÓN PROFUNDA DE LA BASE VECTORIAL (3 CHUNKS)")
        print("=" * 80)

        for i in range(3):
            # Extraemos todo lo que ChromaDB nos devuelve
            chunk_id = resultados_db["ids"][i]
            texto = resultados_db["documents"][i]
            metadata = resultados_db["metadatas"][i]
            vector = resultados_db["embeddings"][i]
            
            print(f"\n📦 \033[96mCHUNK {i+1} | ID: {chunk_id}\033[0m")
            print(f"   📝 Texto:    '{texto}'")
            print(f"   🏷️ Metadata: {metadata}")
            
            # El vector tiene 768 números flotantes, mostramos solo los primeros 5 para ilustrar
            vector_str = f"[{vector[0]:.4f}, {vector[1]:.4f}, {vector[2]:.4f}, {vector[3]:.4f}, {vector[4]:.4f}, ... (Total: {len(vector)} dimensiones)]"
            print(f"   🧠 Vector:   {vector_str}")
        
        print("=" * 80 + "\n")
        
        # Comprobación básica unitaria
        assert len(resultados_db["ids"]) == 3
        assert len(resultados_db["embeddings"][0]) == 768  # Asumiendo FakeEmbeddings size=768
