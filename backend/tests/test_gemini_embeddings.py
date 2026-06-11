from unittest.mock import MagicMock, patch
import pytest
from app.retrieval.vector_store import GeminiEmbeddings

def test_gemini_embeddings_single():
    gemini = GeminiEmbeddings(api_key="fake_key")
    
    with patch("httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": {"values": [0.1, 0.2, 0.3]}}
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__enter__.return_value = mock_client
        
        vector = gemini.embed_query("hola")
        
        assert vector == [0.1, 0.2, 0.3]
        mock_client.post.assert_called_once()
        args, kwargs = mock_client.post.call_args
        assert "gemini-embedding-001" in args[0]
        assert "key=fake_key" in args[0]
        assert kwargs["json"]["content"]["parts"][0]["text"] == "hola"

def test_gemini_embeddings_batch():
    gemini = GeminiEmbeddings(api_key="fake_key")
    
    with patch("httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embeddings": [
                {"values": [0.1, 0.2]},
                {"values": [0.3, 0.4]}
            ]
        }
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__enter__.return_value = mock_client
        
        vectors = gemini.embed_documents(["hola", "chau"])
        
        assert vectors == [[0.1, 0.2], [0.3, 0.4]]
        mock_client.post.assert_called_once()
        args, kwargs = mock_client.post.call_args
        assert "gemini-embedding-001" in args[0]
        assert "key=fake_key" in args[0]
        requests = kwargs["json"]["requests"]
        assert len(requests) == 2
        assert requests[0]["content"]["parts"][0]["text"] == "hola"
        assert requests[1]["content"]["parts"][0]["text"] == "chau"
