# Implementación de Traducción Automática en el RAG

A continuación se detallan los cambios estructurales que se aplicaron en el backend para lograr que el sistema detecte si una pregunta está en español, la traduzca al inglés para su procesamiento, y luego vuelva a traducir la respuesta técnica generada al español.

## 1. Creación del módulo `translator.py`
Se creó un nuevo archivo para aislar la lógica de traducción y detección de idioma.

**Archivo:** `backend/app/generation/translator.py`
**Funciones añadidas:**
- `detect_spanish(llm, text)`: Usa un `SystemMessage` con el LLM para responder con un simple "YES" o "NO" dependiendo de si detecta que la entrada del usuario está en español.
- `translate_to_english(llm, text)`: Toma la pregunta detectada en español y la traduce al inglés usando el LLM (esencial ya que los chunks vectorizados y el `BM25` funcionan mejor con los términos en inglés nativos de la documentación técnica).
- `translate_to_spanish(llm, text)`: Traduce la respuesta generada desde el inglés al español técnico, asegurándose de no alterar comandos vitales de docker (e.g. *containers*, *volumes*, *docker compose*).

## 2. Soporte en Modelos de Metadatos
Para evitar conflictos de Tipado (Typos) y de variables no soportadas debido al cambio a objetos Pydantic, se añadieron los campos necesarios al metadato del pipeline.

**Archivo:** `backend/app/models.py`
**Cambios:**
Se añadieron los siguientes atributos nuevos a la clase `RetrievalMetadata`:
```python
class RetrievalMetadata(BaseModel):
    # ...
    original_question: str | None = Field(default=None, description="Pregunta antes de traducir (si aplica)")
    translated_question: str | None = Field(default=None, description="Pregunta traducida utilizada (si aplica)")
    status: str | None = Field(default=None, description="Estado del retrieval (e.g., abstained)")
    # ...
```

## 3. Integración en el Pipeline Principal
Se incrustó completamente la capacidad de traducción dentro del orquestador.

**Archivo:** `backend/app/pipeline.py`
**Cambios en el método `RAGPipeline.run()`:**

1. **Detección Previa:** Al inicio del flujo, se detecta el lenguaje usando `detect_spanish()`.
2. **Traducción Inicial (Forward):** Si resulta verdadero (el usuario preguntó en español), la pregunta se reasigna a su versión en inglés pasando por `translate_to_english()`. Esta versión en inglés es la que transcurre a lo largo del Retrieval Híbrido y el Reranking.
3. **Manejo de Casos en Blanco (Abstenciones):** Si la evidencia es insuficiente y se utiliza una abstención pre-programada, esta abstención también es pasada por el traductor al español antes de ser devuelta.
4. **Traducción Final (Backward):** Justo antes del `return response`, se re-evalúa si la pregunta original era en español. Si es afirmativo, se toma la `response.answer` generada y se le aplica `translate_to_spanish()` para devolverle al usuario un resultado en el mismo lenguaje del input.
5. **Registro de Trazabilidad:** Se actualizan formalmente los valores `response.retrieval_metadata.original_question` y `response.retrieval_metadata.translated_question` usando notación de puntos (Object Attributes) para el registro de auditoría.

---

# Implementación de Semantic Router (Clasificador de Intenciones)

Se implementó una capa temprana de enrutamiento en el backend para evitar malgastar recursos computacionales y tokens en la base de datos vectorial (ChromaDB) cuando el usuario realiza interacciones puramente conversacionales que no requieren documentación.

## 1. Módulo Enrutador `router.py`
Se creó el archivo encargado de clasificar la intención con un acercamiento de doble barrera (heurísticas locales + LLM fallback).

**Archivo:** `backend/app/generation/router.py`
**Funcionalidades:**
- **Evaluación Heurística 0-Costo (`_heuristic_classify`):** Revisa con Expresiones Regulares si la consulta encaja en patrones de saludos (`Hola!`), agradecimientos (`Gracias`), u otras frases triviales. Adicionalmente, verifica si existen *Keywords* técnicas (`docker`, `install`, `compose`). Si las heurísticas definen un caso claro de la intención, ahorran la llamada a la red.
- **Clasificador LLM Fallback (`_llm_classify`):** Si las heurísticas no están seguras, se emplea un LLM localmente con un potente pero corto Prompt *Few-Shot*. El clasificador responde estrictamente con `RAG` o `CHITCHAT`.
- **Generador de Conversación (`get_chitchat_response`):** Responde de manera amigable a cuestiones triviales recordando al usuario sobre qué trata el bot sin hacer retrieval.

## 2. Orquestación del Router
El pipeline general se divide estratégicamente nada más detectar el lenguaje.

**Archivo:** `backend/app/pipeline.py`
**Cambios:**
1. Inmediatamente luego de la detección de traducción, se invoca `route_query()`.
2. Si la intención calculada arroja `CHITCHAT`, el sistema elabora la respuesta amigable, empaqueta un metadata vacío (simulando evidencia `SUFFICIENT` con score `1.0` y estado `chit-chat`), y **aborta todo el resto del flujo**.
3. Si el clasificador dicta `RAG` (o si falla e incurre a la opción por defecto), se prosigue a lanzar la búsqueda a Base Vectorial (BM25 y ChromaDB) seguido de la reubicación con FlashRank.
