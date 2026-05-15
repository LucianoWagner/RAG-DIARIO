"""Script para inspeccionar los chunks generados por el pipeline de ingesta."""

from app.ingestion.run import run_ingestion

chunks = run_ingestion()

print("\n" + "=" * 70)
print(f"  DETALLE DE LOS {len(chunks)} CHUNKS GENERADOS")
print("=" * 70)

for i, c in enumerate(chunks):
    print(f"\n{'─' * 70}")
    print(f"  CHUNK {i}  ({len(c.page_content)} chars)")
    print(f"  Archivo:    {c.metadata.get('source_file', '?')}")
    print(f"  Categoría:  {c.metadata.get('category', '?')}")
    print(f"  Plataforma: {c.metadata.get('platform', '?')}")
    print(f"  Sección:    {c.metadata.get('section_header', '?')}")
    print(f"  Índice:     {c.metadata.get('chunk_index', '?')}/{c.metadata.get('total_chunks', '?')}")
    print(f"{'─' * 70}")
    # Mostrar las primeras 5 líneas del contenido
    lines = c.page_content.strip().split("\n")
    for line in lines[:5]:
        print(f"  | {line}")
    if len(lines) > 5:
        print(f"  | ... ({len(lines) - 5} líneas más)")
