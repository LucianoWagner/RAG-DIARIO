"""
Loader — Carga de documentos Markdown del corpus Docker.

Responsabilidad:
- Recorrer el directorio de corpus procesado de forma recursiva
- Cargar cada archivo .md como un Document de LangChain
- Asignar metadata básica (ruta relativa, nombre de archivo)
- Manejar errores de encoding (UTF-8 / UTF-8 BOM)
"""

from pathlib import Path

from langchain_core.documents import Document
from loguru import logger


def load_markdown_files(corpus_dir: str) -> list[Document]:
    """
    Carga todos los archivos .md de un directorio (recursivo).

    Args:
        corpus_dir: Ruta al directorio con los Markdown procesados.

    Returns:
        Lista de Document con page_content y metadata básica.

    Raises:
        FileNotFoundError: Si el directorio no existe.
        ValueError: Si no se encuentran archivos .md.
    """
    corpus_path = Path(corpus_dir).resolve()

    if not corpus_path.exists():
        raise FileNotFoundError(f"Directorio de corpus no encontrado: {corpus_path}")

    if not corpus_path.is_dir():
        raise ValueError(f"La ruta no es un directorio: {corpus_path}")

    md_files = sorted(corpus_path.rglob("*.md"))

    if not md_files:
        raise ValueError(
            f"No se encontraron archivos .md en {corpus_path}. "
            "Asegurate de que el corpus esté en corpus/processed/"
        )

    logger.info(f"Encontrados {len(md_files)} archivos .md en {corpus_path}")

    documents: list[Document] = []

    for file_path in md_files:
        content = _read_file_safe(file_path)

        if content is None:
            continue

        # Ruta relativa al directorio del corpus (para metadata)
        relative_path = file_path.relative_to(corpus_path).as_posix()

        doc = Document(
            page_content=content,
            metadata={
                "source_file": relative_path,
                "file_name": file_path.name,
                "absolute_path": str(file_path),
            },
        )
        documents.append(doc)

    logger.info(f"Cargados {len(documents)} documentos correctamente")

    if len(documents) < len(md_files):
        skipped = len(md_files) - len(documents)
        logger.warning(f"{skipped} archivos fueron omitidos por errores de lectura")

    return documents


def _read_file_safe(file_path: Path) -> str | None:
    """
    Lee un archivo de texto manejando distintas codificaciones.

    Intenta UTF-8 primero (con y sin BOM), luego latin-1 como fallback.

    Args:
        file_path: Ruta absoluta al archivo.

    Returns:
        Contenido del archivo como string, o None si falla la lectura.
    """
    encodings_to_try = ["utf-8-sig", "utf-8", "latin-1"]

    for encoding in encodings_to_try:
        try:
            content = file_path.read_text(encoding=encoding)

            # Descartar archivos vacíos o demasiado cortos
            stripped = content.strip()
            if len(stripped) < 10:
                logger.debug(f"Archivo demasiado corto, omitido: {file_path.name}")
                return None

            return content

        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as e:
            logger.error(f"Error de I/O al leer {file_path.name}: {e}")
            return None

    logger.warning(f"No se pudo decodificar: {file_path.name}")
    return None
