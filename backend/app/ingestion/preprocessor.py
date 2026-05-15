"""
Preprocessor — Limpieza de texto de documentación Docker.

Responsabilidad:
- Extraer y separar YAML frontmatter como metadata
- Eliminar shortcodes Hugo ({{< >}}, {{% %}})
- Eliminar HTML no informativo (<div>, </div>, tags inline)
- Normalizar espacios, saltos de línea y separadores
- Preservar bloques de código intactos (```...```)
- Preservar alertas GitHub (> [!NOTE], > [!TIP], etc.)
- Limpiar referencias a imágenes locales (no son útiles para RAG de texto)

La documentación oficial de Docker (repo docker/docs) usa Hugo como
generador estático. El Markdown crudo contiene artefactos que deben
limpiarse antes de hacer chunking y embeddings.
"""

import re
import yaml

from langchain_core.documents import Document
from loguru import logger


# =============================================================================
# Regex patterns compilados (más eficientes que compilar en cada llamada)
# =============================================================================

# Shortcodes Hugo: {{< ... >}} y {{% ... %}} (incluyendo multilinea)
_RE_HUGO_SHORTCODE = re.compile(
    r"\{\{[<%][\s\S]*?[%>]\}\}", re.MULTILINE
)

# HTML tags completos (aperturas, cierres, y self-closing)
_RE_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")

# Imágenes Markdown con paths locales (no URLs completas)
# Ejemplo: ![alt text](../images/foo.png?border=true)
_RE_LOCAL_IMAGE = re.compile(
    r"!\[([^\]]*)\]\((?!https?://)([^)]+)\)"
)

# YAML frontmatter delimitado por ---
_RE_FRONTMATTER = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL
)

# Múltiples saltos de línea (más de 2 consecutivos)
_RE_MULTIPLE_NEWLINES = re.compile(r"\n{3,}")

# Líneas que solo tienen separadores (---, ===, ___)
_RE_SEPARATOR_LINES = re.compile(r"^\s*[-=_]{3,}\s*$", re.MULTILINE)

# Espacios en blanco al final de las líneas
_RE_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)


def preprocess_documents(documents: list[Document]) -> list[Document]:
    """
    Limpia y normaliza el contenido de todos los documentos.

    Para cada documento:
    1. Extrae YAML frontmatter → metadata
    2. Limpia el texto (shortcodes, HTML, etc.)
    3. Filtra documentos que quedan vacíos post-limpieza

    Args:
        documents: Lista de documentos crudos cargados por el loader.

    Returns:
        Lista de documentos limpios con metadata enriquecida del frontmatter.
    """
    logger.info(f"Preprocesando {len(documents)} documentos")

    cleaned: list[Document] = []
    filtered_count = 0

    for doc in documents:
        # 1. Extraer frontmatter YAML
        frontmatter, body = extract_frontmatter(doc.page_content)

        # 2. Limpiar el cuerpo del documento
        clean_body = clean_text(body)

        # 3. Filtrar documentos vacíos después de la limpieza
        if len(clean_body.strip()) < 30:
            filtered_count += 1
            logger.debug(
                f"Documento filtrado (contenido insuficiente post-limpieza): "
                f"{doc.metadata.get('source_file', 'unknown')}"
            )
            continue

        # 4. Merge metadata: original + frontmatter extraído
        enriched_metadata = {**doc.metadata, **frontmatter}

        cleaned.append(
            Document(
                page_content=clean_body,
                metadata=enriched_metadata,
            )
        )

    logger.info(
        f"Preprocesamiento completo: {len(cleaned)} documentos válidos, "
        f"{filtered_count} filtrados"
    )

    return cleaned


def clean_text(text: str) -> str:
    """
    Limpia el texto crudo de un documento Markdown de Docker docs.

    Estrategia: proteger bloques de código con placeholders, limpiar
    todo lo demás, y restaurar los bloques de código al final.
    Es importante preservar los code blocks porque contienen comandos
    y configuraciones que son fundamentales para soporte técnico.

    Args:
        text: Texto Markdown crudo (sin frontmatter).

    Returns:
        Texto limpio y normalizado.
    """
    # ─── Paso 1: Proteger bloques de código ───────────────────────
    # Los bloques ``` ... ``` se reemplazan por placeholders temporales
    # para evitar que las regex de limpieza los alteren.
    code_blocks: list[str] = []
    text = _protect_code_blocks(text, code_blocks)

    # ─── Paso 2: Eliminar shortcodes Hugo ─────────────────────────
    text = _RE_HUGO_SHORTCODE.sub("", text)

    # ─── Paso 3: Eliminar HTML tags ──────────────────────────────
    text = _RE_HTML_TAG.sub("", text)

    # ─── Paso 4: Reemplazar imágenes locales con descripción ──────
    # ![Docker Dashboard](../images/dashboard.png) → [Imagen: Docker Dashboard]
    text = _RE_LOCAL_IMAGE.sub(r"[Imagen: \1]", text)

    # ─── Paso 5: Limpiar separadores sueltos ──────────────────────
    text = _RE_SEPARATOR_LINES.sub("", text)

    # ─── Paso 6: Normalizar whitespace ────────────────────────────
    text = _RE_TRAILING_WHITESPACE.sub("", text)
    text = _RE_MULTIPLE_NEWLINES.sub("\n\n", text)

    # ─── Paso 7: Restaurar bloques de código ──────────────────────
    text = _restore_code_blocks(text, code_blocks)

    return text.strip()


def extract_frontmatter(text: str) -> tuple[dict, str]:
    """
    Extrae YAML frontmatter del inicio del documento.

    El frontmatter de Docker docs tiene campos útiles como:
    - title: Título del documento
    - description: Descripción breve
    - keywords: Palabras clave
    - tags: Tags como [Troubleshooting]

    Args:
        text: Contenido completo del documento (con frontmatter).

    Returns:
        Tupla de (metadata_dict, contenido_sin_frontmatter).
        Si no hay frontmatter, retorna ({}, text original).
    """
    match = _RE_FRONTMATTER.match(text)

    if not match:
        return {}, text

    yaml_content = match.group(1)
    body = text[match.end():]

    try:
        parsed = yaml.safe_load(yaml_content)

        if not isinstance(parsed, dict):
            return {}, body

        # Extraer solo los campos útiles para el RAG
        metadata = {}

        if "title" in parsed:
            metadata["doc_title"] = str(parsed["title"])

        if "description" in parsed:
            metadata["doc_description"] = str(parsed["description"])

        if "keywords" in parsed:
            raw_keywords = parsed["keywords"]
            if isinstance(raw_keywords, str):
                metadata["keywords"] = raw_keywords
            elif isinstance(raw_keywords, list):
                metadata["keywords"] = ", ".join(str(k) for k in raw_keywords)

        if "tags" in parsed and isinstance(parsed["tags"], list):
            metadata["tags"] = ", ".join(str(t) for t in parsed["tags"])

        return metadata, body

    except yaml.YAMLError as e:
        logger.warning(f"Error parseando frontmatter YAML: {e}")
        return {}, body


# =============================================================================
# Helpers internos
# =============================================================================

# Placeholder sin < ni > para evitar que la regex de HTML lo elimine
_CODE_PLACEHOLDER = "CODEBLOCK___{idx}___ENDBLOCK"


def _protect_code_blocks(text: str, storage: list[str]) -> str:
    """
    Reemplaza bloques de código con placeholders para protegerlos.

    Soporta bloques fenced (```) con o sin lenguaje especificado.

    Args:
        text: Texto original.
        storage: Lista donde se guardan los bloques extraídos.

    Returns:
        Texto con los bloques reemplazados por placeholders.
    """
    def _replacer(match: re.Match) -> str:
        idx = len(storage)
        storage.append(match.group(0))
        return _CODE_PLACEHOLDER.format(idx=idx)

    # Regex: ``` con opcional lenguaje, luego contenido hasta el cierre ```
    # - Soporta: ```python\n...\n```, ```\n...\n```, ``` console\n...\n```
    # - El [\s\S]*? es non-greedy para matchear el cierre más cercano
    return re.sub(r"```[^\n]*\n[\s\S]*?```", _replacer, text)


def _restore_code_blocks(text: str, storage: list[str]) -> str:
    """
    Restaura los bloques de código desde los placeholders.

    Args:
        text: Texto con placeholders.
        storage: Lista de bloques originales.

    Returns:
        Texto con los bloques de código restaurados.
    """
    for idx, block in enumerate(storage):
        placeholder = _CODE_PLACEHOLDER.format(idx=idx)
        text = text.replace(placeholder, block)
    return text
