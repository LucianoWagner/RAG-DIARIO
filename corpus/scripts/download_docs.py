"""
Download Docker Docs — Descarga la documentación oficial de Docker.

Descarga un ZIP del repo docker/docs desde GitHub y extrae solo
las secciones relevantes de archivos Markdown.

Secciones descargadas:
- get-started/                  → Conceptos básicos, primeros pasos
- manuals/desktop/              → Docker Desktop (instalación, config, troubleshoot)
- manuals/engine/install/       → Docker Engine (instalación por OS)
- manuals/compose/              → Docker Compose
- reference/cli/docker/         → CLI reference (docker run, build, etc.)

Uso (desde la raíz del proyecto):
    python corpus/scripts/download_docs.py
    python corpus/scripts/download_docs.py --force   (re-descarga)
"""

import io
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# =============================================================================
# Configuración
# =============================================================================

ZIP_URL = "https://github.com/docker/docs/archive/refs/heads/main.zip"

CORPUS_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = CORPUS_DIR / "raw"

# Secciones a extraer: (prefijo dentro del zip, nombre en raw/)
# El ZIP de GitHub tiene un directorio raíz "docs-main/"
ZIP_PREFIX = "docs-main/content/"

SECTIONS_TO_EXTRACT = [
    ("get-started", "get-started"),
    ("manuals/desktop", "desktop"),
    ("manuals/engine/install", "engine-install"),
    ("manuals/compose", "compose"),
]

# La referencia CLI está en un path diferente dentro del ZIP (vendor)
CLI_VENDOR_PREFIX = "docs-main/_vendor/github.com/docker/cli/docs/reference/"
CLI_DEST_NAME = "cli-reference"


def download_docs(force: bool = False) -> None:
    """
    Descarga la documentación de Docker desde GitHub (ZIP).

    1. Descarga el ZIP del branch main (~30MB)
    2. Extrae solo los .md de las secciones relevantes
    3. Guarda en corpus/raw/ con estructura limpia
    """
    print("=" * 60)
    print("  DESCARGA DE DOCUMENTACIÓN DOCKER")
    print("=" * 60)
    print(f"  URL:     {ZIP_URL}")
    print(f"  Destino: {RAW_DIR}")
    print(f"  Forzar:  {force}")
    print("=" * 60)

    # Verificar si ya existe
    existing_md = list(RAW_DIR.rglob("*.md")) if RAW_DIR.exists() else []
    if existing_md and not force:
        print(f"\n⚠️  Ya existen {len(existing_md)} archivos .md en corpus/raw/")
        print("   Usá --force para re-descargar.")
        print("   O pasá directo a: python corpus/scripts/prepare_corpus.py")
        return

    # Limpiar directorio raw
    if RAW_DIR.exists():
        print(f"\n🗑️  Limpiando {RAW_DIR}...")
        shutil.rmtree(RAW_DIR)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # ─── Paso 1: Descargar ZIP ────────────────────────────────────
    print(f"\n📥 Descargando ZIP del repo docker/docs (~30MB)...")
    print("   Esto puede tardar 1-2 minutos...")

    try:
        req = Request(ZIP_URL, headers={"User-Agent": "Mozilla/5.0"})
        response = urlopen(req, timeout=120)
        zip_data = response.read()
        print(f"   Descargado: {len(zip_data) / (1024*1024):.1f} MB")
    except URLError as e:
        print(f"❌ Error de red: {e}")
        print("   Verificá tu conexión a internet.")
        sys.exit(1)
    except TimeoutError:
        print("❌ Timeout. El servidor tardó demasiado.")
        sys.exit(1)

    # ─── Paso 2: Extraer archivos .md ─────────────────────────────
    print("\n📄 Extrayendo archivos Markdown...")

    total_files = 0
    total_bytes = 0

    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        all_names = zf.namelist()

        for section_path, dest_name in SECTIONS_TO_EXTRACT:
            # El path dentro del ZIP es: docs-main/content/{section_path}/
            prefix = f"{ZIP_PREFIX}{section_path}/"
            matching = [n for n in all_names if n.startswith(prefix) and n.endswith(".md")]

            copied = 0
            for zip_entry in matching:
                # Calcular path relativo dentro de la sección
                relative = zip_entry[len(prefix):]
                if not relative:
                    continue

                dest_file = RAW_DIR / dest_name / relative
                dest_file.parent.mkdir(parents=True, exist_ok=True)

                data = zf.read(zip_entry)
                dest_file.write_bytes(data)

                total_bytes += len(data)
                copied += 1

            total_files += copied
            print(f"   ✅ {dest_name}: {copied} archivos")

        # CLI reference (está en un path vendor diferente)
        cli_matching = [n for n in all_names if n.startswith(CLI_VENDOR_PREFIX) and n.endswith(".md")]
        cli_copied = 0
        for zip_entry in cli_matching:
            relative = zip_entry[len(CLI_VENDOR_PREFIX):]
            if not relative:
                continue
            dest_file = RAW_DIR / CLI_DEST_NAME / relative
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            data = zf.read(zip_entry)
            dest_file.write_bytes(data)
            total_bytes += len(data)
            cli_copied += 1

        total_files += cli_copied
        print(f"   ✅ {CLI_DEST_NAME}: {cli_copied} archivos")

    # ─── Resumen ──────────────────────────────────────────────────
    size_mb = total_bytes / (1024 * 1024)
    print(f"\n{'=' * 60}")
    print(f"  ✅ DESCARGA COMPLETADA")
    print(f"  Archivos:  {total_files} archivos .md")
    print(f"  Tamaño:    {size_mb:.1f} MB")
    print(f"  Destino:   {RAW_DIR}")
    print(f"\n  Siguiente paso:")
    print(f"  python corpus/scripts/prepare_corpus.py")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    force_flag = "--force" in sys.argv
    download_docs(force=force_flag)
