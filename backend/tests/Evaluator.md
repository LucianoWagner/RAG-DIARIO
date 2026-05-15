# 📊 Evaluación Científica del RAG (RAGAS)

Esta carpeta contiene la suite de evaluación E2E (End-to-End) para medir de forma determinística y estadística la calidad y veracidad del sistema RAG. 

Utiliza el framework **RAGAS (Retrieval Augmented Generation Assessment)**, que es un estándar de la industria para aplicar el paradigma de **"LLM-as-a-Judge"** (un modelo más potente evaluando las salidas del RAG local).

## ⚠️ Requisitos Previos: El Entorno `venv-eval`

**RAGAS no es compatible con Python 3.14** (lanza errores compilando la dependencia recursiva `scikit-network`). Debido a que el backend de producción corre en 3.14, la evaluación **debe** ejecutarse en un entorno aislado con Python 3.11.

```powershell
# 1. Crear el entorno virtual con Python 3.11 (desde la raíz del proyecto)
py -3.11 -m venv backend\venv-eval

# 2. Activar el entorno
backend\venv-eval\Scripts\Activate.ps1

# 3. Instalar dependencias estrictas de evaluación
pip install -r backend\requirements-eval.txt
```

---

## 📂 Archivos Clave

- **`eval_dataset.json`**: Dataset dorado (Ground Truth) con 20 preguntas seleccionadas manualmente desde la documentación de Docker y equilibradas por categoría (Installation, Troubleshooting, CLI, Getting Started, Config). Incluye las respuestas oficiales e indica `expected_keywords` (palabras obligatorias que el Retriever debería encontrar).
- **`test_evaluation.py`**: Motor pesado de evaluación. Orquesta tu pipeline, extrae las fuentes y ejecuta la suite de RAGAS para calificar numéricamente del 0 al 1 cada aspecto.
- **`ragas_report_xxx.csv`**: Resultados exportados post-evaluación.

---

## 🧪 Las 4 Métricas de RAGAS que Medimos

1. **Faithfulness (Fidelidad de Generación)**: Penaliza las alucinaciones. Extrae sentencias del texto del LLM y verifica si existen textualmente dentro de los *Chunks Recuperados* de ChromaDB.
2. **Answer Relevancy (Relevancia Generativa)**: Verifica si la respuesta final que da el sistema ataca la pregunta original del usuario, omitiendo preámbulos innecesarios o desvíos.
3. **Context Precision (Precisión Lexico/Semántica)**: Mide el Retriever. Revisa si los manuales recuperados fueron útiles para el LLM y qué tan bien ordenados vinieron. Si el chunk ganador quedó en puesto 10 (Reranker débil), penaliza el score.
4. **Context Recall (Filtro de Recuperación)**: Contrasta el `Ground Truth` perfecto del dataset contra el contexto que rescató tu BD. Si Docker manda usar `Rosetta 2` y tus manuales recuperados no mencionaron nunca a Rosetta 2, el Recall baja.

---

## 🚀 Uso Rápido y Casos Frecuentes

Desde la carpeta `backend/` con tu `venv-eval` activado:

**Evaluar con modelo estelar de Groq (Llama 70b):**
```powershell
python -m tests.test_evaluation --model llama-3.3-70b-versatile
```

**Evaluar con modelo rápido para comparar Scores (Llama 8b):**
```powershell
python -m tests.test_evaluation --model llama-3.1-8b-instant
```

**Testing exploratorio o límite de Tokens saturado:**
```powershell
python -m tests.test_evaluation --model llama-3.1-8b-instant --quick
```
> `--quick` reduce la corrida a solo 2 preguntas por categoría (10 en total) para no drenar tu cuenta ni gastar todo el límite diario de Groq en pruebas exploratorias.

---

## 🧱 Entendiendo la Lucha contra el "Rate-Limit (Error 429)"

La API Gratuita de Groq tiene **límites de Tokens Por Día (TPD)** que rondan los 100,000 en el tier libre.

RAGAS es **muy agresivo con los tokens**. Para evaluar 1 pregunta con 4 métricas, RAGAS dispara 4 llamadas masivas al LLM pidiéndole que extraiga JSONs por separado. En un set de 20 preguntas, eso es ~80 invocaciones, saturando la cuota en ~1 hora. Las pausas entre preguntas con tiempo (delay) no evitan este problema, porque tu billetera de tokens del día se extingue velozmente.

**¿Cómo funciona nuestro script para defenderse?**
1. **Serialización Forzada**: Ragas está programado para tirar hilos paralelos por defecto (`max_workers=16`). Tuve que programarle un `RunConfig(max_workers=1)` para asegurarnos de que la API reciba de a UN mensaje al LLM, espere que devuelva los tokens calculando, y proceda.
2. **Generador de Espera Inteligente**: `max_retries=15` combinado con `max_wait=120`. Si de casualidad tu proveedor de LLM revienta en un request porque pasaste los Token por Minuto, Ragas detiene tu Test, tira a dormir hasta 2 minutos y lo reintenta. Así no perdés el reporte completo.
3. **Pausas RAG (`--delay 15`)**: Le indica al programa local que espere en la extracción de vectores antes de enviar todo el pliego de Contextos (que cuestan 8 mil tokens de entrada cada vez) nuevamente al modelo padre.
