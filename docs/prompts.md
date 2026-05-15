# Prompts del Sistema RAG

## System Prompt Principal

El prompt principal está definido en `backend/app/generation/prompt_templates.py`.

### Características clave:
- Responde en el **idioma de la pregunta** (español/inglés)
- Citas obligatorias con formato `[Fuente N]`
- Prohibido inventar información fuera del contexto
- Estructura diferenciada por tipo de consulta:
  - **Instalación**: pasos numerados con comandos
  - **Troubleshooting**: diagnóstico → causa → solución
  - **Conceptos**: definición → explicación → ejemplo

## Variantes para Evaluación

| Variante | Archivo/Constante | Descripción |
|:---|:---|:---|
| Principal | `SYSTEM_PROMPT` | Balance entre precisión y utilidad |
| Restrictivo | `SYSTEM_PROMPT_RESTRICTIVE` | Prioriza abstención sobre alucinación |
| Permisivo | `SYSTEM_PROMPT_PERMISSIVE` | Permite inferencias razonables |

## Notas de Diseño

- La temperatura del LLM se configura baja (0.1) para respuestas más deterministas.
- El `num_ctx` de Ollama debe ser 8192+ para que el LLM vea todos los chunks.
- El prompt indica que el asistente es *especializado en Docker*, no un asistente genérico.
