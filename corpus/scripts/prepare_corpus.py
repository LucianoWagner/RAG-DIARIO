"""
Prepare Corpus — Copia los docs descargados a corpus/processed/.

Toma los archivos .md de corpus/raw/ y los copia a corpus/processed/
manteniendo la estructura de directorios. La limpieza fina (eliminar
shortcodes Hugo, HTML, etc.) la hace el preprocessor del backend
durante la ingesta, así que acá solo hacemos filtrado básico.

Filtros aplicados:
- Omitir archivos _index.md que son solo navegación de Hugo
- Omitir archivos muy cortos (< 100 bytes, probablemente redirects)
- Omitir archivos que son solo frontmatter sin contenido

Uso (desde la raíz del proyecto):
    python corpus/scripts/prepare_corpus.py
    python corpus/scripts/prepare_corpus.py --force   (sobreescribe)
"""

import shutil
import sys
from pathlib import Path


# =============================================================================
# Configuración
# =============================================================================

CORPUS_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = CORPUS_DIR / "raw"
PROCESSED_DIR = CORPUS_DIR / "processed"

# Tamaño mínimo en bytes para considerar un archivo útil
MIN_FILE_SIZE = 200

# Archivos a omitir (patrones de nombre)
SKIP_PATTERNS = {
    "_index.md",      # Archivos índice de Hugo (solo navegación)
    "_category_.md",  # Archivos de categoría de Hugo
}


def prepare_corpus(force: bool = False) -> None:
    """
    Procesa los archivos crudos y genera el corpus limpio.

    1. Recorre corpus/raw/ recursivamente
    2. Filtra archivos irrelevantes
    3. Copia los archivos válidos a corpus/processed/

    Args:
        force: Si True, borra corpus/processed/ existente.
    """
    print("=" * 60)
    print("  PREPARACIÓN DEL CORPUS")
    print("=" * 60)
    print(f"  Origen:   {RAW_DIR}")
    print(f"  Destino:  {PROCESSED_DIR}")
    print("=" * 60)

    if not RAW_DIR.exists():
        print(f"\n❌ No existe {RAW_DIR}")
        print("   Primero ejecutá: python corpus/scripts/download_docs.py")
        sys.exit(1)

    raw_files = list(RAW_DIR.rglob("*.md"))
    if not raw_files:
        print(f"\n❌ No hay archivos .md en {RAW_DIR}")
        sys.exit(1)

    print(f"\n📂 Encontrados {len(raw_files)} archivos .md en raw/")

    # Verificar si ya existe
    existing = list(PROCESSED_DIR.rglob("*.md")) if PROCESSED_DIR.exists() else []
    if existing and not force:
        print(f"\n⚠️  Ya existen {len(existing)} archivos en processed/")
        print("   Usá --force para regenerar.")
        return

    # Limpiar processed/ (eliminar archivos .md pero mantener .gitkeep)
    if PROCESSED_DIR.exists():
        for f in PROCESSED_DIR.rglob("*.md"):
            f.unlink()
        # Eliminar subdirectorios vacíos
        for d in sorted(PROCESSED_DIR.rglob("*"), reverse=True):
            if d.is_dir() and not list(d.iterdir()):
                d.rmdir()

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # ─── Filtrar y copiar ─────────────────────────────────────────
    copied = 0
    skipped_small = 0
    skipped_pattern = 0
    skipped_empty_body = 0
    total_bytes = 0

    for raw_file in sorted(raw_files):
        # Filtro 1: Patrones de nombre
        if raw_file.name in SKIP_PATTERNS:
            skipped_pattern += 1
            continue

        # Filtro 2: Tamaño mínimo
        file_size = raw_file.stat().st_size
        if file_size < MIN_FILE_SIZE:
            skipped_small += 1
            continue

        # Filtro 3: Verificar que tiene contenido más allá del frontmatter
        content = raw_file.read_text(encoding="utf-8-sig", errors="replace")
        body = _strip_frontmatter(content)
        if len(body.strip()) < 50:
            skipped_empty_body += 1
            continue

        # Copiar manteniendo la estructura relativa
        relative = raw_file.relative_to(RAW_DIR)
        dest_file = PROCESSED_DIR / relative
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(raw_file, dest_file)

        copied += 1
        total_bytes += file_size

    # ─── Resumen ──────────────────────────────────────────────────
    size_mb = total_bytes / (1024 * 1024)

    print(f"\n{'─' * 40}")
    print(f"  Copiados:                {copied}")
    print(f"  Omitidos (muy chicos):   {skipped_small}")
    print(f"  Omitidos (index/nav):    {skipped_pattern}")
    print(f"  Omitidos (sin cuerpo):   {skipped_empty_body}")
    print(f"  Tamaño total:            {size_mb:.1f} MB")
    print(f"{'─' * 40}")

    print(f"\n✅ Corpus preparado en {PROCESSED_DIR}")
    print(f"\n  Siguiente paso (con venv activado):")
    print(f"  cd backend")
    print(f"  python -m app.ingestion.run")
    print("=" * 60)


def _strip_frontmatter(text: str) -> str:
    """Remueve el frontmatter YAML del inicio del texto."""
    if not text.startswith("---"):
        return text

    # Buscar el cierre del frontmatter
    end = text.find("---", 3)
    if end == -1:
        return text

    return text[end + 3:]


if __name__ == "__main__":
    force_flag = "--force" in sys.argv
    prepare_corpus(force=force_flag)
