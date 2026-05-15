"""
Tests para el módulo de ingestion.

Cubre: loader, preprocessor, chunker, metadata.
"""

import pytest
from pathlib import Path
from langchain_core.documents import Document

from app.ingestion.loader import load_markdown_files, _read_file_safe
from app.ingestion.preprocessor import clean_text, extract_frontmatter, preprocess_documents
from app.ingestion.chunker import chunk_documents, MARKDOWN_SEPARATORS
from app.ingestion.metadata import detect_category, detect_platform, enrich_metadata
from app.models import DocCategory


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_doc_with_frontmatter():
    """Documento con frontmatter YAML y contenido Markdown."""
    return Document(
        page_content=(
            "---\n"
            "title: Install Docker on Windows\n"
            "description: How to install Docker Desktop on Windows\n"
            "keywords: Docker, install, Windows\n"
            "tags: [Installation]\n"
            "---\n\n"
            "## System requirements\n\n"
            "Before you install Docker Desktop, make sure your system meets "
            "the following requirements.\n\n"
            "## Install Docker Desktop\n\n"
            "1. Download the installer.\n"
            "2. Double-click the installer.\n\n"
            "```powershell\n"
            "net localgroup docker-users <user> /ADD\n"
            "```\n"
        ),
        metadata={"source_file": "desktop/install/windows-install.md", "file_name": "windows-install.md"},
    )


@pytest.fixture
def sample_doc_with_hugo():
    """Documento con shortcodes Hugo y HTML."""
    return Document(
        page_content=(
            "## Download Docker\n\n"
            '{{< youtube-embed C2bPVhiNU-0 >}}\n\n'
            "Docker Desktop is the all-in-one package.\n\n"
            '<div class="not-prose">\n'
            '{{< card title="Docker for Mac" description="Download" >}}\n'
            '{{< card title="Docker for Windows" description="Download" >}}\n'
            "</div>\n\n"
            "Once installed, complete the setup.\n\n"
            "```console\n"
            "$ docker run -d -p 8080:80 docker/welcome-to-docker\n"
            "```\n\n"
            '![Dashboard](../images/dashboard.png?border=true)\n\n'
            '{{< button text="Next step" url="next" >}}\n'
        ),
        metadata={"source_file": "get-started/introduction/get-docker-desktop.md", "file_name": "get-docker-desktop.md"},
    )


@pytest.fixture
def sample_documents(sample_doc_with_frontmatter, sample_doc_with_hugo):
    """Lista de documentos de prueba."""
    return [sample_doc_with_frontmatter, sample_doc_with_hugo]


# =============================================================================
# Tests — Loader
# =============================================================================

class TestLoader:
    """Tests para loader.py."""

    def test_load_from_existing_dir(self, tmp_path):
        """Debe cargar archivos .md de un directorio."""
        # Crear archivos de prueba
        (tmp_path / "doc1.md").write_text("# Hello\n\nThis is a test document.", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "doc2.md").write_text("# Nested\n\nNested document content here.", encoding="utf-8")

        docs = load_markdown_files(str(tmp_path))

        assert len(docs) == 2
        # Verificar metadata
        sources = {d.metadata["source_file"] for d in docs}
        assert "doc1.md" in sources
        assert "sub/doc2.md" in sources

    def test_load_nonexistent_dir_raises(self):
        """Debe lanzar FileNotFoundError si el directorio no existe."""
        with pytest.raises(FileNotFoundError):
            load_markdown_files("/path/que/no/existe")

    def test_load_empty_dir_raises(self, tmp_path):
        """Debe lanzar ValueError si no hay archivos .md."""
        (tmp_path / "readme.txt").write_text("No soy markdown")
        with pytest.raises(ValueError, match="No se encontraron archivos .md"):
            load_markdown_files(str(tmp_path))

    def test_skips_tiny_files(self, tmp_path):
        """Archivos muy cortos deben ser omitidos."""
        (tmp_path / "tiny.md").write_text("hi", encoding="utf-8")
        (tmp_path / "normal.md").write_text("# Normal\n\nThis is a normal document.", encoding="utf-8")

        docs = load_markdown_files(str(tmp_path))
        assert len(docs) == 1
        assert docs[0].metadata["file_name"] == "normal.md"

    def test_handles_utf8_bom(self, tmp_path):
        """Debe manejar archivos con BOM de UTF-8."""
        content = "\ufeff# BOM Document\n\nContent with BOM marker."
        (tmp_path / "bom.md").write_text(content, encoding="utf-8-sig")

        docs = load_markdown_files(str(tmp_path))
        assert len(docs) == 1
        assert "BOM Document" in docs[0].page_content


# =============================================================================
# Tests — Preprocessor
# =============================================================================

class TestCleanText:
    """Tests para la función clean_text."""

    def test_removes_hugo_shortcodes(self):
        """Debe eliminar shortcodes Hugo {{< >}} y {{% %}}."""
        text = 'Hello {{< youtube-embed abc123 >}} world'
        result = clean_text(text)
        assert "{{<" not in result
        assert "Hello" in result
        assert "world" in result

    def test_removes_html_tags(self):
        """Debe eliminar tags HTML."""
        text = '<div class="not-prose">\nSome content\n</div>'
        result = clean_text(text)
        assert "<div" not in result
        assert "</div>" not in result
        assert "Some content" in result

    def test_preserves_code_blocks(self):
        """Los bloques de código deben preservarse intactos."""
        text = (
            "Run this:\n\n"
            "```powershell\n"
            "docker run -d -p 8080:80 nginx\n"
            "```\n\n"
            "Done."
        )
        result = clean_text(text)
        assert "```powershell" in result
        assert "docker run -d -p 8080:80 nginx" in result

    def test_code_blocks_survive_html_removal(self):
        """HTML dentro de bloques de código no debe eliminarse."""
        text = (
            "Example:\n\n"
            "```html\n"
            "<div>Hello</div>\n"
            "```\n"
        )
        result = clean_text(text)
        assert "<div>Hello</div>" in result

    def test_replaces_local_images_with_description(self):
        """Imágenes locales deben reemplazarse con su alt text."""
        text = "See below:\n\n![Docker Dashboard](../images/dashboard.png?border=true)"
        result = clean_text(text)
        assert "[Imagen: Docker Dashboard]" in result
        assert "dashboard.png" not in result

    def test_preserves_external_images(self):
        """Imágenes con URLs completas no deben alterarse."""
        text = "![Logo](https://example.com/logo.png)"
        result = clean_text(text)
        assert "https://example.com/logo.png" in result

    def test_normalizes_multiple_newlines(self):
        """Más de 2 saltos de línea consecutivos deben reducirse a 2."""
        text = "First paragraph\n\n\n\n\n\nSecond paragraph"
        result = clean_text(text)
        assert "\n\n\n" not in result
        assert "First paragraph" in result
        assert "Second paragraph" in result


class TestExtractFrontmatter:
    """Tests para extract_frontmatter."""

    def test_extracts_yaml_frontmatter(self):
        """Debe extraer campos del frontmatter YAML."""
        text = (
            "---\n"
            "title: My Document\n"
            "description: A test document\n"
            "keywords: test, docker\n"
            "---\n\n"
            "## Content here\n"
        )
        meta, body = extract_frontmatter(text)
        assert meta["doc_title"] == "My Document"
        assert meta["doc_description"] == "A test document"
        assert "Content here" in body
        assert "---" not in body

    def test_no_frontmatter_returns_empty(self):
        """Sin frontmatter debe retornar dict vacío y texto original."""
        text = "## Just a heading\n\nSome content."
        meta, body = extract_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_extracts_tags(self):
        """Debe extraer tags como string separado por comas."""
        text = "---\ntitle: Test\ntags: [Installation, Setup]\n---\n\nBody"
        meta, body = extract_frontmatter(text)
        assert "Installation" in meta.get("tags", "")
        assert "Setup" in meta.get("tags", "")

    def test_handles_malformed_yaml(self):
        """YAML malformado no debe romper el pipeline."""
        text = "---\ntitle: [unclosed bracket\n---\n\nBody"
        meta, body = extract_frontmatter(text)
        # No debe lanzar excepción, puede retornar {} o parcial
        assert isinstance(meta, dict)


class TestPreprocessDocuments:
    """Tests para preprocess_documents (integración)."""

    def test_filters_empty_documents(self):
        """Documentos que quedan vacíos post-limpieza deben filtrarse."""
        docs = [
            Document(page_content='{{< shortcode >}}\n<div></div>', metadata={"source_file": "empty.md"}),
            Document(page_content="## Real content\n\nThis has useful text.", metadata={"source_file": "real.md"}),
        ]
        result = preprocess_documents(docs)
        assert len(result) == 1
        assert result[0].metadata["source_file"] == "real.md"

    def test_frontmatter_merged_into_metadata(self, sample_doc_with_frontmatter):
        """El frontmatter debe mergearse en la metadata del documento."""
        result = preprocess_documents([sample_doc_with_frontmatter])
        assert len(result) == 1
        assert result[0].metadata["doc_title"] == "Install Docker on Windows"
        assert result[0].metadata["source_file"] == "desktop/install/windows-install.md"


# =============================================================================
# Tests — Chunker
# =============================================================================

class TestChunker:
    """Tests para chunker.py."""

    def test_chunks_generated(self):
        """Debe generar chunks de un documento largo."""
        long_content = "## Section\n\n" + ("Docker is great. " * 200)
        doc = Document(page_content=long_content, metadata={"source_file": "test.md"})

        chunks = chunk_documents([doc], chunk_size=500, chunk_overlap=100)
        assert len(chunks) > 1

    def test_chunk_size_respected(self):
        """Ningún chunk debe exceder el chunk_size configurado (con margen)."""
        long_content = "## Section\n\n" + ("Docker containers are portable. " * 100)
        doc = Document(page_content=long_content, metadata={"source_file": "test.md"})

        chunks = chunk_documents([doc], chunk_size=500, chunk_overlap=50)
        for chunk in chunks:
            # Permitimos un margen del 50% por el keep_separator
            assert len(chunk.page_content) < 500 * 1.5

    def test_metadata_inherited(self):
        """Los chunks deben heredar la metadata del documento original."""
        doc = Document(
            page_content="## Section\n\n" + ("Word " * 500),
            metadata={"source_file": "test.md", "doc_title": "Test Doc"},
        )
        chunks = chunk_documents([doc], chunk_size=300, chunk_overlap=50)
        for chunk in chunks:
            assert chunk.metadata["source_file"] == "test.md"
            assert chunk.metadata["doc_title"] == "Test Doc"

    def test_chunk_index_assigned(self):
        """Cada chunk debe tener chunk_index y total_chunks."""
        doc = Document(
            page_content="## Section\n\n" + ("Docker is great. " * 300),
            metadata={"source_file": "test.md"},
        )
        chunks = chunk_documents([doc], chunk_size=400, chunk_overlap=50)

        for chunk in chunks:
            assert "chunk_index" in chunk.metadata
            assert "total_chunks" in chunk.metadata

        # chunk_index debe ser secuencial
        indices = [c.metadata["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_short_document_single_chunk(self):
        """Un documento corto debe generar un solo chunk."""
        doc = Document(
            page_content="## Short\n\nShort content here.",
            metadata={"source_file": "short.md"},
        )
        chunks = chunk_documents([doc], chunk_size=800, chunk_overlap=200)
        assert len(chunks) == 1
        assert chunks[0].metadata["chunk_index"] == 0
        assert chunks[0].metadata["total_chunks"] == 1


# =============================================================================
# Tests — Metadata
# =============================================================================

class TestDetectCategory:
    """Tests para detect_category."""

    def test_install_path(self):
        """Path con 'install' debe detectar INSTALLATION."""
        assert detect_category("desktop/install/windows.md", "") == DocCategory.INSTALLATION

    def test_troubleshoot_path(self):
        """Path con 'troubleshoot' debe detectar TROUBLESHOOTING."""
        assert detect_category("desktop/troubleshoot/index.md", "") == DocCategory.TROUBLESHOOTING

    def test_cli_path(self):
        """Path con 'cli' o 'reference' debe detectar CLI_REFERENCE."""
        assert detect_category("reference/cli/docker-run.md", "") == DocCategory.CLI_REFERENCE

    def test_getting_started_path(self):
        """Path con 'get-started' debe detectar GETTING_STARTED."""
        assert detect_category("get-started/overview.md", "") == DocCategory.GETTING_STARTED

    def test_fallback_to_content(self):
        """Si el path no da info, debe buscar en el contenido."""
        result = detect_category("docs/misc.md", "How to install Docker on your machine")
        assert result == DocCategory.INSTALLATION

    def test_default_is_getting_started(self):
        """Sin match en path ni contenido, default es GETTING_STARTED."""
        result = detect_category("docs/misc.md", "Some generic text")
        assert result == DocCategory.GETTING_STARTED


class TestDetectPlatform:
    """Tests para detect_platform."""

    def test_windows_path(self):
        """Path con 'windows' debe detectar plataforma windows."""
        assert detect_platform("desktop/install/windows-install.md", "") == "windows"

    def test_mac_path(self):
        """Path con 'mac' debe detectar plataforma mac."""
        assert detect_platform("desktop/install/mac-install.md", "") == "mac"

    def test_linux_path(self):
        """Path con 'ubuntu' debe detectar plataforma linux."""
        assert detect_platform("engine/install/ubuntu.md", "") == "linux"

    def test_general_default(self):
        """Sin indicador de plataforma debe retornar 'general'."""
        assert detect_platform("get-started/overview.md", "Docker is portable") == "general"

    def test_content_detection_requires_threshold(self):
        """Detección por contenido requiere >= 3 menciones."""
        # Solo 1 mención: no debe detectar
        assert detect_platform("docs/misc.md", "This runs on Windows.") == "general"
        # 3+ menciones: debe detectar
        text = "Windows setup. Windows config. Windows troubleshoot."
        assert detect_platform("docs/misc.md", text) == "windows"


class TestEnrichMetadata:
    """Tests integración para enrich_metadata."""

    def test_enriches_all_fields(self):
        """Cada chunk debe tener todos los campos de metadata esperados."""
        chunks = [
            Document(
                page_content="## Install Docker\n\nRun the installer on Windows.",
                metadata={"source_file": "desktop/install/windows-install.md"},
            ),
        ]
        result = enrich_metadata(chunks)
        meta = result[0].metadata

        assert meta["category"] == "installation"
        assert meta["platform"] == "windows"
        assert meta["doc_title"] != ""
        assert meta["section_header"] == "Install Docker"
        assert meta["doc_type"] == "guide"

    def test_preserves_frontmatter_title(self):
        """Si doc_title viene del frontmatter, no debe sobreescribirse."""
        chunks = [
            Document(
                page_content="## Content\n\nSome text here.",
                metadata={"source_file": "test.md", "doc_title": "Custom Title"},
            ),
        ]
        result = enrich_metadata(chunks)
        assert result[0].metadata["doc_title"] == "Custom Title"


# =============================================================================
# Tests — Integración (Pipeline completo)
# =============================================================================

from unittest.mock import patch
from app.ingestion.run import run_ingestion

class TestIntegration:
    """Tests End-to-End para el orquestador de ingesta."""

    @patch("app.retrieval.vector_store.index_documents")
    def test_run_ingestion_intercepts_chunks(self, mock_index_documents):
        """
        Prueba el flujo completo: lee del directorio REAL del corpus, limpia, 
        particiona, enriquece, y verifica cómo se envían los chunks al vector_store.
        """
        import os
        from app.ingestion.run import CORPUS_DIR
        
        # 1. Verificar que el corpus real exista, si no omitimos el test (skip)
        if not os.path.exists(CORPUS_DIR) or not os.listdir(CORPUS_DIR):
            pytest.skip("Corpus real no descargado. Ejecutá download_docs.py primero.")

        mock_index_documents.return_value = 9999  # Simular valor devuelto

        # 2. Correr pipeline completo con los datos reales
        chunks_devueltos = run_ingestion(force=True)

        # 3. Verificaciones de la ejecución en mock
        mock_index_documents.assert_called_once()
        
        # Obtener los chunks que intentó guardar
        chunks_para_guardar = mock_index_documents.call_args[0][0]
        force_flag = mock_index_documents.call_args[1].get('force')
        
        # Aserciones sobre la cantidad
        assert len(chunks_para_guardar) > 100  # Mínimo debería haber cientos
        assert len(chunks_devueltos) == len(chunks_para_guardar)
        assert force_flag is True
        
        # 4. Verificar contenido y enriquecimiento de un chunk real
        # Buscar un archivo que trate sobre Windows, así testeamos la detección
        chunk_windows = next((c for c in chunks_para_guardar if "windows" in c.metadata["source_file"].lower()), None)
        if chunk_windows:
            assert chunk_windows.metadata["platform"] == "windows"
            assert isinstance(chunk_windows.metadata["chunk_index"], int)
