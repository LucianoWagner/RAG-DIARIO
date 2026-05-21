# FASE 2: Clasificador de scope en cascada (heurístico → embeddings → LLM local)

## Objetivo de esta fase

Reemplazar la lógica actual de `scope_classifier.py` por una cascada de tres capas
que clasifique cada chunk con `country_scope` en `argentina`, `international` o `unknown`,
garantizando que los artículos vinculados a Argentina sean recuperados correctamente
independientemente de si el texto lo menciona de forma explícita.

**No se modifica ningún otro módulo fuera de los indicados en esta fase.**

---

## Contexto del proyecto

El proyecto es un RAG académico sobre prensa argentina histórica (1998-2016).
El pipeline de ingesta ya está implementado con los stages:

```
scrape -> parse -> chunk -> enrich -> index
```

El enrichment llama a `scope_classifier.py` por cada chunk. El clasificador actual
es puramente heurístico. Esta fase lo reemplaza por una cascada de tres capas.

Archivos relevantes para esta fase:

```
backend/app/ingestion/enrichers/scope_classifier.py   ← REEMPLAZAR
backend/app/ingestion/enrichers/ner.py                ← solo lectura
backend/app/ingestion/enrichers/gazetteer.py          ← solo lectura
backend/data/gazetteer/argentina.json                 ← solo lectura
backend/app/ingestion/metadata.py                     ← solo lectura
backend/tests/test_scope_classifier.py                ← CREAR o EXPANDIR
```

---

## Regla general de la cascada

```
Chunk enriquecido
      │
      ▼
  Capa 1: Heurístico
      │
      ├── "argentina"      ──────────────────────────► resultado final
      ├── "international"  ──────────────────────────► resultado final
      └── "unknown"
               │
               ▼
           Capa 2: Embeddings semánticos
               │
               ├── delta > umbral_alto  ────────────► "argentina"
               ├── delta < -umbral_alto ────────────► "international"
               └── zona gris (|delta| <= umbral_alto)
                           │
                           ▼
                       Capa 3: LLM local (solo zona gris)
                           │
                           ├── "argentina"
                           ├── "international"
                           └── "unknown"  ──────────► resultado final
```

---

## Capa 1: Heurístico (lógica actualizada)

### Secciones que clasifican directamente como `argentina`

Si la sección del chunk es alguna de las siguientes, clasificar `argentina` sin
necesidad de buscar señales en el texto:

```python
SECCIONES_ARGENTINA_DIRECTA = {
    "elpais", "economia", "sociedad", "universidad",
    "suplementos/cash", "suplementos/soy", "suplementos/no",
    "suplementos/m2", "suplementos/radar", "suplementos/turismo",
}
```

Estas secciones son estructuralmente argentinas en Página/12.
Si la sección matchea: `scope = "argentina"`, `signals = ["seccion:<nombre>"]`.

### Secciones que clasifican directamente como `international`

**Ninguna.** Este es el cambio clave respecto a la lógica anterior.

La sección `elmundo` ya **no** clasifica directamente como `international`.
Tampoco ninguna otra sección. Si la heurística no encuentra señales argentinas
positivas, el resultado es `"unknown"`, nunca `"international"` por sección sola.

### Secciones que requieren búsqueda de señales

Para cualquier sección que no esté en `SECCIONES_ARGENTINA_DIRECTA`
(incluyendo `elmundo`, `deportes`, `cultura`, `espectaculos`, `contratapa`,
suplementos no listados, sección vacía, etc.), la heurística busca señales
argentinas en el texto del chunk:

**Señales positivas de Argentina** (si encuentra al menos una → `argentina`):

1. Menciones del gazetteer nacional en `location_mentions` del chunk
   (provincias, ciudades, instituciones, partidos políticos, clubes).
2. Organizaciones detectadas por spaCy (`organizations`) que estén en una
   lista de orgs argentinas conocidas:
   ```python
   ORGS_ARGENTINA = {
       "UCR", "PJ", "CGT", "CTA", "Boca", "River", "Racing", "Independiente",
       "San Lorenzo", "Huracán", "Estudiantes", "Gimnasia", "Congreso",
       "Senado", "Diputados", "Banco Central", "BCRA", "INDEC", "AFIP",
       "ANSES", "Conicet", "UBA", "UNLP", "Cancillería", "Casa Rosada",
       "Madres de Plaza de Mayo", "Abuelas", "H.I.J.O.S.", "CONADEP",
   }
   ```
3. Términos o frases en el texto del chunk (case-insensitive):
   ```python
   TERMINOS_ARGENTINA = {
       "argentino", "argentina", "gobierno nacional", "gobierno argentino",
       "provincia", "municipio", "intendente", "gobernador", "diputados",
       "senadores", "paritarias", "corte de ruta", "cacerolazo", "piquete",
       "déficit fiscal", "paro nacional", "peso argentino", "deuda externa",
       "cancillería argentina", "ministerio de", "secretaría de",
   }
   ```

Si no encuentra ninguna señal positiva → `scope = "unknown"`, `signals = []`.
Si encuentra señales → `scope = "argentina"`, `signals = [lista de señales encontradas]`.

### Chunks muy cortos

Si `len(chunk.text.strip()) < 100`: clasificar directamente `unknown` sin buscar señales.
Son títulos o fragmentos sin contexto suficiente.

---

## Capa 2: Clasificación por embeddings semánticos

Solo se ejecuta si Capa 1 devolvió `"unknown"`.

### Frases ancla

Calcular embeddings de estas frases **una sola vez** al instanciar el clasificador
(no en cada llamada):

```python
ANCLAS_ARGENTINA = [
    "noticias de Argentina",
    "política argentina",
    "economía argentina",
    "sociedad argentina",
    "gobierno de Argentina",
    "Buenos Aires Argentina",
    "noticias argentinas",
]

ANCLAS_INTERNACIONAL = [
    "noticias internacionales",
    "política exterior mundial",
    "conflicto internacional",
    "elecciones en otro país",
    "economía mundial",
    "guerra en el exterior",
]
```

### Cálculo del score

```python
score_arg = max(cosine_similarity(chunk_emb, a) for a in ancla_embs_argentina)
score_int = max(cosine_similarity(chunk_emb, a) for a in ancla_embs_internacional)
delta = score_arg - score_int
```

### Umbrales

```python
UMBRAL_EMBEDDING = 0.15  # configurable desde config.py o .env
```

- `delta > UMBRAL_EMBEDDING`  → `"argentina"`, `signals = [f"emb_delta:{delta:.3f}"]`
- `delta < -UMBRAL_EMBEDDING` → `"international"`, `signals = [f"emb_delta:{delta:.3f}"]`
- `|delta| <= UMBRAL_EMBEDDING` → `"uncertain"` (pasa a Capa 3)

### Embedding del chunk

Usar el mismo modelo de embeddings que ya usa el proyecto
(`intfloat/multilingual-e5-large`). El clasificador recibe la instancia del
embedder como dependencia inyectada, no la instancia él solo.

**Importante:** aplicar prefijo `query: ` al texto del chunk antes de embeddear
para este propósito (es texto a comparar, no a indexar).

### Cache de embeddings de anclas

Calcularlos en `__init__` y guardarlos como atributo. No recalcular por chunk.

---

## Capa 3: LLM local (solo zona gris)

Solo se ejecuta si Capa 2 devolvió `"uncertain"`.

### Condiciones para saltar la Capa 3

Si se cumple alguna de las siguientes, devolver `"unknown"` directamente sin
llamar al LLM (ahorra tokens en casos irresolubles):

- El chunk tiene menos de 150 caracteres.
- El hash SHA-256 del texto del chunk está en el cache de resultados LLM.

### Modelo

Usar Ollama local con modelo configurable. Default: `qwen2.5:3b-instruct`.
Leer desde variable de entorno `SCOPE_LLM_MODEL` con fallback al default.

### Prompt

```python
PROMPT_TEMPLATE = """Sos un clasificador de noticias periodísticas argentinas. 
Respondé SOLO con una de estas tres palabras exactas: argentina / international / unknown

Pregunta: ¿Este fragmento de noticia está vinculado con Argentina?
Considerá "argentina" si trata sobre: política, economía, sociedad, deportes o cultura
de Argentina; argentinos en el exterior; o eventos internacionales donde Argentina
es parte activa (diplomacia, comercio, conflictos que involucren al país).
Considerá "international" si trata sobre eventos o temas de otros países sin
vínculo con Argentina.
Considerá "unknown" si no hay suficiente contexto para decidir.

Fragmento:
\"\"\"
{text}
\"\"\"

Respondé solo con una palabra:"""
```

Parámetros de la llamada:
- `max_tokens=5`
- `temperature=0`

### Parseo de la respuesta

Normalizar la respuesta: `strip().lower().split()[0]` y validar que sea
`"argentina"`, `"international"` o `"unknown"`. Si la respuesta no es válida,
devolver `"unknown"`.

### Cache

Guardar resultado en `dict` en memoria con clave `sha256(chunk.text)`.
No persistir a disco en esta fase (es un cache de sesión).

### Signals

`signals = ["llm_local:<modelo>"]`

---

## Interfaz pública del módulo

```python
# backend/app/ingestion/enrichers/scope_classifier.py

class ScopeClassifier:
    def __init__(self, embedder, llm_client=None):
        """
        embedder: instancia del modelo de embeddings ya cargado
        llm_client: cliente Ollama. Si es None, Capa 3 devuelve "unknown" directamente.
        """
        ...

    def classify(self, chunk_text: str, metadata: dict) -> tuple[str, list[str]]:
        """
        Retorna (country_scope, scope_signals).
        country_scope: "argentina" | "international" | "unknown"
        scope_signals: lista de strings que explican por qué se llegó a ese resultado
        """
        ...
```

`metadata` debe contener al menos:
- `section` (str | None)
- `location_mentions` (list[str])
- `organizations` (list[str])

---

## Cambios en `metadata.py`

El archivo `metadata.py` ya instancia el clasificador. Verificar que:

1. Pase la instancia del embedder al construir `ScopeClassifier`.
2. Pase el cliente LLM si está disponible (puede ser `None`, la capa 3 se
   desactiva silenciosamente).
3. El resultado de `classify()` se guarde en:
   - `chunk["country_scope"]`
   - `chunk["scope_signals"]`

No cambiar ninguna otra lógica de `metadata.py`.

---

## Configuración nueva en `.env.example`

Agregar estas variables:

```env
# Scope classifier
SCOPE_EMBEDDING_THRESHOLD=0.15
SCOPE_LLM_MODEL=qwen2.5:3b-instruct
SCOPE_LLM_ENABLED=true
```

Si `SCOPE_LLM_ENABLED=false`, la Capa 3 devuelve `"unknown"` directamente
sin llamar a Ollama. Útil para pruebas rápidas sin LLM.

---

## Logging obligatorio

```python
logger = logging.getLogger("enrichers.scope_classifier")
```

Mensajes a loguear:

- Al iniciar: `"ScopeClassifier inicializado. LLM capa 3: {'habilitado' if llm else 'deshabilitado'}"`
- Al precalcular anclas: `"Anclas de embeddings precalculadas ({n} argentina, {m} internacional)"`
- Por chunk clasificado en capa 1: `"[Capa1] scope={scope} signals={signals}"`  (level DEBUG)
- Por chunk clasificado en capa 2: `"[Capa2] delta={delta:.3f} scope={scope}"` (level DEBUG)
- Por chunk enviado a capa 3: `"[Capa3] enviando chunk ({len} chars) a LLM"` (level DEBUG)
- Por chunk clasificado en capa 3: `"[Capa3] LLM respondió: {respuesta_raw} → {scope}"` (level DEBUG)
- Estadísticas al final del stage enrich (opcional, level INFO):
  `"Scope stats: argentina={n}, international={m}, unknown={k}, total={t}"`

---

## Tests requeridos

Archivo: `backend/tests/test_scope_classifier.py`

Todos los tests deben mockear el embedder y el LLM. No hacer llamadas reales.

```python
def test_capa1_seccion_argentina_directa():
    # sección "elpais" → "argentina" sin llegar a capa 2 ni 3

def test_capa1_termino_en_texto():
    # sección "cultura", texto contiene "gobierno nacional" → "argentina"

def test_capa1_org_argentina():
    # sección "deportes", organizations=["River"] → "argentina"

def test_capa1_elmundo_sin_senales():
    # sección "elmundo", sin señales argentinas → "unknown" (NO "international")

def test_capa1_chunk_corto():
    # texto de 50 chars → "unknown" directo

def test_capa2_delta_positivo_alto():
    # embedder mockeado devuelve delta > 0.15 → "argentina"

def test_capa2_delta_negativo_alto():
    # embedder mockeado devuelve delta < -0.15 → "international"

def test_capa2_zona_gris_pasa_a_capa3():
    # delta dentro del umbral → llega a capa 3

def test_capa3_respuesta_valida_argentina():
    # LLM mockeado responde "argentina" → scope="argentina", signal="llm_local:..."

def test_capa3_respuesta_invalida():
    # LLM mockeado responde "quizás" → scope="unknown"

def test_capa3_deshabilitado_devuelve_unknown():
    # ScopeClassifier(embedder, llm_client=None) → capa 3 devuelve "unknown"

def test_cache_llm_no_repite_llamada():
    # mismo chunk enviado dos veces → LLM llamado solo una vez
```

---

## Restricciones

1. **No modificar** `ner.py`, `gazetteer.py`, `html_parser.py`, `pipeline.py`,
   `models.py`, `chunker.py` ni ningún scraper.
2. **No cambiar** la firma de `classify()` respecto a lo que `metadata.py`
   ya espera. Si hay diferencia, adaptar solo `scope_classifier.py`.
3. **No agregar dependencias nuevas** al `requirements.txt`. El embedder
   (`sentence-transformers`) y el cliente Ollama ya están presentes.
4. **No persistir el cache LLM** a disco en esta fase.
5. El módulo debe funcionar con `llm_client=None` sin lanzar excepciones.

---

## Criterio de aceptación

Ejecutar:

```powershell
python -m app.ingestion.run --stage preview --date 06-03-2005 --max-articles 3 --preview-limit 5
```

Y verificar que:

- El preview muestra `country_scope` y `scope_signals` por cada chunk.
- Ningún chunk de sección `elmundo` sin señales argentinas aparece como `international`.
- Los `scope_signals` indican claramente qué capa clasificó (`seccion:elpais`,
  `emb_delta:0.231`, `llm_local:qwen2.5:3b-instruct`, etc.).
- Los tests pasan: `pytest backend/tests/test_scope_classifier.py -q`

---

## Qué viene después (no implementar en esta fase)

Una vez validada la cascada con preview, la fase siguiente conecta el pipeline
completo con indexación en Qdrant usando `--stage all`, incluyendo los chunks
clasificados como `argentina` por cualquiera de las tres capas.