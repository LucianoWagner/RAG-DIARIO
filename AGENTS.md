# 🐳 Asistente RAG — Soporte Técnico Documental de Docker

Asistente conversacional especializado en soporte técnico de Docker, basado en documentación oficial. Utiliza Retrieval-Augmented Generation (RAG) con búsqueda híbrida, reranking, verificación de evidencia y citas trazables.

## 📋 Tabla de Contenidos

- [Descripción](#descripción)
- [Arquitectura](#arquitectura)
- [Stack Tecnológico](#stack-tecnológico)
- [Requisitos Previos](#requisitos-previos)
- [Instalación y Setup](#instalación-y-setup)
- [Uso](#uso)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Notas para el Equipo](#notas-para-el-equipo)

---

## Descripción

Este sistema responde preguntas sobre Docker (instalación, uso inicial, troubleshooting) fundamentando sus respuestas **exclusivamente en documentación oficial**, con citas verificables y un detector de evidencia insuficiente para evitar alucinaciones.

**No es un RAG genérico.** El corpus, los prompts, la metadata y la evaluación están diseñados específicamente para soporte técnico documental de Docker.

---

## Arquitectura

El proyecto separa **infraestructura** (Docker) y **lógica de negocio** (Python local):

```
┌─────────────────────────────────────────────────────────────┐
│                     EN DOCKER                               │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Ollama      │  │  ChromaDB    │  │  OpenWebUI   │      │
│  │  LLM + Embed  │  │  Vectores    │  │  Frontend    │      │
│  │  :11434       │  │  :8000       │  │  :3000       │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                  │              │
└─────────┼─────────────────┼──────────────────┼──────────────┘
          │                 │                  │
          │    localhost     │    localhost      │  host.docker.internal
          │                 │                  │
┌─────────┼─────────────────┼──────────────────┼──────────────┐
│         │                 │                  │              │
│  ┌──────▼─────────────────▼──────────────────▼───────────┐  │
│  │           Backend RAG (FastAPI + LangChain)            │  │
│  │              Python local en venv — :8080              │  │
│  │                                                       │  │
│  │  Ingesta │ Retrieval Híbrido │ Reranking │ Generación  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│                     LOCAL (venv Python)                      │
└─────────────────────────────────────────────────────────────┘
```

**¿Por qué el backend corre local y no en Docker?**
- Más fácil de debuggear y desarrollar
- Recarga automática con `--reload`
- No hay que hacer rebuild de imagen para cada cambio
- Los servicios pesados (LLM, base vectorial, frontend) sí van en Docker

---

## Stack Tecnológico

| Componente | Tecnología | Corre en |
|:---|:---|:---|
| Frontend | OpenWebUI | Docker |
| LLM | Ollama (llama3.1:8b) | Docker |
| Embeddings | Ollama (nomic-embed-text) | Docker |
| Base Vectorial | ChromaDB | Docker |
| Backend RAG | FastAPI + LangChain | **Local (venv)** |
| Generación | Groq API (llama-3.3-70b / 3.1-8b) | Cloud |
| Traducción (Detección) | langdetect | Local (venv) - 0 tokens |
| Traducción (ES→EN) | deep-translator (Google) | Local (venv) - 0 tokens |
| Traducción (EN→ES) | Groq API (preserva código) | Cloud |
| Búsqueda Léxica | BM25 (rank-bm25) | Local (venv) |
| Reranking | FlashRank | Local (venv) |
| Evaluación | RAGAS + Groq (venv-eval, Python 3.11) | Local + Cloud |

---

## Requisitos Previos

### Para TODOS los miembros del equipo

- **Docker Desktop** instalado y funcionando
  - Windows: [Descargar Docker Desktop](https://docs.docker.com/desktop/install/windows-install/)
  - Requiere WSL 2 habilitado en Windows
- **Git** instalado
- **Python 3.11+** instalado (compatible con Python 3.14)
- **Make** (opcional)
  - Windows: `choco install make` o `winget install GnuWin32.Make`
  - Si no lo tenés, podés usar los comandos directamente (ver sección "Sin Make")

### Solo si tenés GPU NVIDIA (opcional, mejora rendimiento)

- GPU NVIDIA con al menos 6 GB de VRAM (ej: RTX 2060)
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) instalado
- Drivers NVIDIA actualizados

> **Sin GPU funciona igual.** Solo tarda más cada respuesta (~15-30s en CPU vs ~2-5s con GPU).

---

## Instalación y Setup

### Paso 1 — Clonar el repositorio

```bash
git clone <URL_DEL_REPO>
cd ProyectoRagSoporteTecnico
```

### Paso 2 — Configuración de entorno

```bash
copy .env.example .env
```

Revisá `.env` y ajustá puertos si hay conflictos (ej: si ya usás el 3000).

### Paso 3 — Crear el entorno virtual de Python

```powershell
# Crear venv
python -m venv backend\venv

# Activar (PowerShell)
backend\venv\Scripts\Activate.ps1

# Upgrade pip
python -m pip install --upgrade pip

# Instalar dependencias
pip install -r backend\requirements.txt
```

### Paso 3b — Crear entorno de evaluación RAGAS (opcional)

> ⚠️ RAGAS no es compatible con Python 3.14. Se necesita un venv separado con Python 3.11.

```powershell
# Crear venv de evaluación con Python 3.11
py -3.11 -m venv backend\venv-eval

# Activar (PowerShell)
backend\venv-eval\Scripts\Activate.ps1

# Instalar dependencias de evaluación
pip install -r backend\requirements-eval.txt
```

### Paso 4 — Levantar servicios Docker (Ollama + ChromaDB + OpenWebUI)

**Sin GPU (la mayoría del equipo):**
```bash
docker compose up -d
```

**Con GPU NVIDIA:**
```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

### Paso 5 — Descargar modelos de Ollama (solo la primera vez)

```bash
docker exec rag-ollama ollama pull llama3.1:8b
docker exec rag-ollama ollama pull nomic-embed-text
```

> ⏳ Puede tardar varios minutos. Los modelos se guardan en un volumen Docker persistente (se descargan una sola vez).

### Paso 6 — Correr el backend local

Con el venv activado:

```powershell
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

### Paso 7 — Ingestar el corpus (solo la primera vez)

Asegurate de tener los archivos `.md` en `corpus/processed/`, luego con el venv activado:

```powershell
cd backend
python -m app.ingestion.run
```

> Los embeddings se guardan en ChromaDB (volumen Docker). **No se re-indexan cada vez que levantás el proyecto.** Solo hace falta si actualizás el corpus.

### Paso 8 — Usar el asistente

Abrí en tu navegador:

```
http://localhost:3000
```

---

## Uso

### Comandos principales (con Make)

| Comando | Descripción |
|:---|:---|
| `make up` | Levantar Docker (CPU) |
| `make up-gpu` | Levantar Docker (GPU NVIDIA) |
| `make down` | Detener Docker |
| `make pull-models` | Descargar modelos Ollama |
| `make setup-venv` | Crear venv + instalar dependencias |
| `make run-backend` | Correr backend FastAPI local |
| `make ingest` | Indexar corpus en ChromaDB |
| `make evaluate` | Ejecutar evaluación RAGAS (requiere venv-eval) |
| `make evaluate-8b` | Evaluar con modelo llama-3.1-8b-instant |
| `make logs` | Ver logs de Docker |
| `make clean` | Reset completo (¡borra todo!) |

### Sin Make (comandos directos)

```powershell
# --- Docker (infraestructura) ---
docker compose up -d                                    # Levantar (CPU)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d  # Con GPU
docker compose down                                     # Detener
docker exec rag-ollama ollama pull llama3.1:8b          # Descargar LLM
docker exec rag-ollama ollama pull nomic-embed-text     # Descargar embeddings

# --- Backend local (con venv activado) ---
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload   # Correr backend
python -m app.ingestion.run                                  # Ingestar corpus

# --- Evaluación RAGAS (con venv-eval activado) ---
backend\venv-eval\Scripts\Activate.ps1                       # Activar venv-eval
cd backend
python -m tests.test_evaluation --model llama-3.3-70b-versatile  # Evaluar 70b
python -m tests.test_evaluation --model llama-3.1-8b-instant     # Evaluar 8b
python -m tests.test_evaluation --model llama-3.3-70b-versatile --delay 10  # Con delay
```

### Endpoints del Backend

| Endpoint | Método | Descripción |
|:---|:---|:---|
| `/health` | GET | Health check |
| `/docs` | GET | Documentación Swagger |
| `/query` | POST | Consulta al pipeline RAG |
| `/ingest` | POST | Re-indexar corpus |
| `/v1/models` | GET | Modelos (OpenAI-compatible) |
| `/v1/chat/completions` | POST | Chat (OpenAI-compatible) |

---

## Estructura del Proyecto

```
ProyectoRagSoporteTecnico/
├── docker-compose.yml           # Ollama + ChromaDB + OpenWebUI
├── docker-compose.gpu.yml       # Override GPU NVIDIA
├── .env / .env.example          # Variables de entorno
├── Makefile                     # Comandos simplificados
├── README.md
│
├── backend/                     # 🔧 Backend RAG (corre LOCAL en venv)
│   ├── requirements.txt         # Dependencias Python (producción)
│   ├── requirements-eval.txt    # Dependencias evaluación (Python 3.11)
│   ├── venv/                    # Entorno virtual producción (Python 3.14)
│   ├── venv-eval/               # Entorno virtual evaluación (Python 3.11)
│   ├── app/
│   │   ├── main.py              # FastAPI endpoints
│   │   ├── config.py            # Configuración centralizada
│   │   ├── models.py            # Modelos Pydantic
│   │   ├── pipeline.py          # Orquestador del pipeline RAG
│   │   │
│   │   ├── ingestion/           # Carga y procesamiento del corpus
│   │   │   ├── loader.py        # Carga archivos Markdown
│   │   │   ├── preprocessor.py  # Limpieza de texto
│   │   │   ├── chunker.py       # División en chunks
│   │   │   ├── metadata.py      # Enriquecimiento de metadata
│   │   │   └── run.py           # Script de ingesta completo
│   │   │
│   │   ├── retrieval/           # Búsqueda y recuperación
│   │   │   ├── vector_store.py  # ChromaDB (semántico)
│   │   │   ├── bm25_retriever.py# BM25 (léxico)
│   │   │   ├── hybrid.py        # Retriever híbrido (RRF)
│   │   │   └── reranker.py      # FlashRank reranking
│   │   │
│   │   └── generation/          # Generación de respuestas
│   │       ├── evidence_checker.py # Detector de evidencia
│   │       ├── prompt_templates.py # Prompts especializados
│   │       ├── translator.py    # Traducción automática ES↔EN
│   │       └── generator.py     # Invocación LLM + citas
│   │
│   └── tests/                   # 📊 Tests y Evaluación RAGAS
│       ├── eval_dataset.json    # Dataset de evaluación (20 preguntas)
│       ├── test_evaluation.py   # Script RAGAS nativo
│       ├── test_ingestion.py    # Tests de ingesta
│       └── test_vector_store.py # Tests de vector store
│
├── corpus/                      # 📄 Documentación Docker
│   ├── raw/                     # Markdown crudo (gitignored)
│   ├── processed/               # Markdown limpio (input de ingesta)
│   └── scripts/
│       ├── download_docs.py     # Descarga docs de GitHub
│       └── prepare_corpus.py    # Preprocesamiento
│
└── docs/                        # 📖 Documentación del proyecto
    ├── architecture.md          # Diagrama de arquitectura
    └── prompts.md               # Documentación de prompts
```

---

## Notas para el Equipo

### Persistencia de datos

| Dato | ¿Persiste? | ¿Dónde? | ¿Cuándo se pierde? |
|:---|:---|:---|:---|
| Modelos Ollama | ✅ Sí | Volumen Docker `rag_ollama_data` | Solo con `docker compose down -v` |
| Embeddings (ChromaDB) | ✅ Sí | Volumen Docker `rag_chroma_data` | Solo con `docker compose down -v` |
| Config OpenWebUI | ✅ Sí | Volumen Docker `rag_openwebui_data` | Solo con `docker compose down -v` |
| Código Python | 📁 Local | `backend/` en tu repo | No se pierde |
| venv | 📁 Local | `backend/venv/` (gitignored) | Si borrás la carpeta |
| venv-eval | 📁 Local | `backend/venv-eval/` (gitignored) | Si borrás la carpeta |

> **Los embeddings NO se recalculan** cada vez que levantás el proyecto. Solo ejecutar `python -m app.ingestion.run` la primera vez o si cambia el corpus.

### Arquitectura de Traducción Híbrida (Multilingüe)

El sistema soporta preguntas en español, pero internamente opera todo el Pipeline RAG (Retrieval, Reranking, Prompts) en **inglés** porque la documentación técnica oficial de Docker es mucho más precisa en ese idioma. Se utiliza una estrategia híbrida optimizada para no gastar tokens:

1. **Detección de Idioma**: Se usa `langdetect` (0 tokens, muy rápido).
2. **Traducción Inicial (Usuario → Sistema)**: Se usa `deep-translator` (Google Translate gratis, 0 tokens) ya que las consultas de los usuarios son texto plano.
3. **Traducción Final (Sistema → Usuario)**: Se usa el LLM de Groq. Esto garantiza que comandos como `docker run -d nginx` o términos de infraestructura (volumes, containers) no sean destrozados por traductores genéricos.

### Enrutamiento Semántico y Clasificación de Intenciones

El pipeline integra un componente `router.py` encargado de clasificar la intención de la consulta *antes* de realizar operaciones costosas en la base de datos vectorial. 

**Estrategia en Cascada (Zero a Low-Cost):**
1. **Heurísticas Locales:** Se ejecutan expresiones regulares (Regex) para identificar saludos (`Hola`, `Gracias`) y keywords técnicas (`docker`, `compose`). Es instantáneo y no consume tokens.
2. **Evaluación LLM (Fallback):** Si la consulta es trivial o ambigua, un modelo LLM evalúa la pregunta usando Few-Shot prompting para definir estrictamente si es `RAG` o `CHITCHAT`.
3. **Respuesta Directa:** Si la intención es `CHITCHAT`, se elabora dinámicamente un mensaje conversacional amigable saltándose por completo Retriever (ChromaDB), Reranker (FlashRank) y Evidence Checker. Esto provee una respuesta instantánea y ahorra costos computacionales.

### OpenWebUI y Modelos Disponibles

OpenWebUI cree que está hablando con la API oficial de OpenAI. Tu backend expone el modelo **`docker-rag-assistant`**.
Para evitar que los usuarios bypasseen el RAG y le hablen directo al LLM crudo, se deshabilitó el auto-descubrimiento en el `docker-compose.yml` (`ENABLE_OLLAMA_API=false`). 
1. Siempre elegir **`docker-rag-assistant`** en la ventana de chat.
2. Si no aparece, asegúrate de que el servidor FastAPI esté corriendo en el puerto 8080 antes de abrir localhost:3000.

### Con GPU vs Sin GPU

- **Con GPU (ej: RTX 2060):** ~2-5 segundos por respuesta. Usar `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`
- **Sin GPU (CPU):** ~15-30 segundos por respuesta. Usar `docker compose up -d`
- El modelo `llama3.1:8b` usa ~5 GB de VRAM (GPU) o RAM (CPU)

### Flujo de trabajo diario

```powershell
git pull                              # 1. Traer cambios
docker compose up -d                  # 2. Levantar infra (si no está corriendo)
backend\venv\Scripts\Activate.ps1     # 3. Activar venv
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload  # 4. Correr backend
# ... desarrollar ...
# Ctrl+C para detener el backend
docker compose down                   # 5. Al terminar (opcional)
```

### Troubleshooting

**"Cannot connect to Docker daemon"**
→ Asegurate de que Docker Desktop esté corriendo.

**"Port 3000 already in use"**
→ Cambiá `WEBUI_PORT=3001` en tu `.env`.

**Ollama tarda mucho en responder**
→ Normal en CPU. La primera consulta carga el modelo en memoria, las siguientes son más rápidas.

**`make` no se reconoce como comando**
→ `choco install make` o usá los comandos directamente (ver "Sin Make").

**OpenWebUI no se conecta al backend**
→ Verificá que el backend esté corriendo en el puerto 8080. OpenWebUI lo busca en `host.docker.internal:8080`.

**Error al instalar dependencias Python**
→ Asegurate de tener el venv activado. Si ves errores de compilación, puede faltar [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/).

**Error al instalar RAGAS (`scikit-network` falla)**
→ RAGAS no es compatible con Python 3.14. Usá el `venv-eval` con Python 3.11:
```powershell
py -3.11 -m venv backend\venv-eval
backend\venv-eval\Scripts\Activate.ps1
pip install -r backend\requirements-eval.txt
```
