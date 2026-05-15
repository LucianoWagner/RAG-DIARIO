include .env
export

.PHONY: up up-gpu down pull-models logs clean setup-venv run-backend ingest evaluate help

# ============================================
# Ayuda
# ============================================

help: ## Mostrar esta ayuda
	@echo.
	@echo  ========================================
	@echo  RAG Docker Support - Comandos
	@echo  ========================================
	@echo.
	@echo  --- Infraestructura (Docker) ---
	@echo  make up             Levantar Ollama + ChromaDB + OpenWebUI (CPU)
	@echo  make up-gpu         Idem con GPU NVIDIA
	@echo  make down           Detener servicios Docker
	@echo  make pull-models    Descargar modelos Ollama
	@echo  make logs           Ver logs de Docker
	@echo  make clean          Reset completo (borra volumenes)
	@echo.
	@echo  --- Backend local (venv) ---
	@echo  make setup-venv     Crear venv e instalar dependencias
	@echo  make run-backend    Correr el backend FastAPI local
	@echo  make ingest         Indexar corpus en ChromaDB
	@echo  make evaluate       Ejecutar evaluacion
	@echo.

# ============================================
# Docker — Servicios de infraestructura
# ============================================

up: ## Levantar Ollama + ChromaDB + OpenWebUI (modo CPU)
	docker compose up -d
	@echo.
	@echo Servicios Docker levantados (CPU).
	@echo Si es la primera vez, ejecuta: make pull-models
	@echo OpenWebUI: http://localhost:$(WEBUI_PORT)
	@echo.

up-gpu: ## Levantar con GPU NVIDIA (requiere nvidia-container-toolkit)
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
	@echo.
	@echo Servicios Docker levantados (GPU).
	@echo.

down: ## Detener servicios Docker
	docker compose down

pull-models: ## Descargar modelos de Ollama (solo primera vez)
	@echo Descargando $(LLM_MODEL)...
	docker exec rag-ollama ollama pull $(LLM_MODEL)
	@echo Descargando $(EMBEDDING_MODEL)...
	docker exec rag-ollama ollama pull $(EMBEDDING_MODEL)
	@echo Modelos descargados.

logs: ## Ver logs de los servicios Docker
	docker compose logs -f

clean: ## Reset completo - elimina volumenes Docker (CUIDADO: borra embeddings y modelos)
	docker compose down -v
	@echo Volumenes eliminados. Necesitas hacer pull-models e ingest de nuevo.

# ============================================
# Backend local (Python venv)
# ============================================

setup-venv: ## Crear entorno virtual e instalar dependencias
	python -m venv backend\venv
	backend\venv\Scripts\python.exe -m pip install --upgrade pip
	backend\venv\Scripts\pip.exe install -r backend\requirements.txt
	@echo.
	@echo venv creado en backend\venv
	@echo Activar con: backend\venv\Scripts\Activate.ps1
	@echo.

run-backend: ## Correr el backend FastAPI (requiere venv activado)
	cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port $(BACKEND_PORT) --reload

ingest: ## Indexar corpus en ChromaDB (requiere venv activado + Docker corriendo)
	cd backend && python -m app.ingestion.run

evaluate: ## Ejecutar evaluacion comparativa (requiere venv activado + Docker corriendo)
	cd backend && python -m evaluation.run_evaluation
