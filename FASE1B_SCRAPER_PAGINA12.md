# FASE 1-B: Scraper de URLs — Página 12 filtrado por "La Plata"

## Objetivo de esta fase

Implementar un script reanudable que, dado **un día concreto** (configurable vía argumento),
descubra y guarde todas las URLs de notas de Página 12 que mencionen "La Plata" publicadas
en esa fecha. El resultado es un archivo JSON de URLs listo para ser consumido por el
pipeline de ingesta (parseo → enriquecimiento → indexación) definido en el plan general.

**No se parsea el contenido de las notas en esta fase. Solo se descubren y persisten las URLs.**

---

## Contexto del proyecto

El proyecto es un RAG académico sobre noticias históricas de La Plata, Argentina.
La estructura de carpetas relevante para esta fase es:

```
backend/
└── app/
    └── ingestion/
        └── scrapers/
            ├── __init__.py
            └── pagina12.py        ← archivo a crear en esta fase
data/
└── raw/
    └── pagina12/
        └── YYYY/
            └── MM/
                └── urls_DD-MM-YYYY.json   ← output de esta fase
```

El archivo `__init__.py` de scrapers ya existe (puede estar vacío). Si no existe,
crearlo vacío.

---

## Por qué Página 12

Página 12 tiene archivo web desde el año 2000 con estructura de URL predecible
y un buscador que soporta filtrado por frase exacta. Esto permite descubrir
exactamente las notas que mencionan "La Plata" sin tener que bajar el diario completo.

---

## Estrategia de descubrimiento de URLs

Página 12 expone dos mecanismos aprovechables:

### Mecanismo 1: Buscador con filtro por fecha (PREFERIDO)

URL base del buscador:
```
https://www.pagina12.com.ar/buscador/index.php
```

Parámetros GET relevantes (a verificar inspeccionando el buscador real):
```
q        = "La Plata"     (frase exacta entre comillas)
fecha    = DD-MM-YYYY     (o el formato que use el sitio)
```

**Instrucción importante:** antes de asumir los parámetros exactos, hacer un
`httpx.get` al buscador con una query de prueba y loguear la URL final + el HTML
resultante para inferir la estructura real. No hardcodear parámetros a ciegas.

### Mecanismo 2: Edición del día (FALLBACK)

Si el buscador no permite filtrar por fecha con precisión, la alternativa es:

1. Fetchear la edición completa del día:
   ```
   https://www.pagina12.com.ar/YYYY/MM-YYYY/dia/DD-MM-YYYY.html
   ```
   Ejemplo para el 15 de marzo de 2005:
   ```
   https://www.pagina12.com.ar/2005/03-2005/dia/15-03-2005.html
   ```

2. Extraer todos los links de artículos de esa página (los `<a href>` que apunten
   a notas, típicamente con patrón `/diario/YYYY/MM/dia/subnotas/...` o similar).

3. Filtrar solo los artículos cuyo **título o bajada** contenga "La Plata"
   (case-insensitive, con variantes: "la plata", "La Plata", "LA PLATA").

**Usar el Mecanismo 1 si funciona. Implementar el Mecanismo 2 como fallback.**
El código debe intentar Mecanismo 1, y si falla (status != 200, HTML vacío,
o no devuelve resultados), caer automáticamente al Mecanismo 2.

---

## Especificación del script

### Archivo: `backend/app/ingestion/scrapers/pagina12.py`

#### Interfaz de línea de comandos

```bash
python -m backend.app.ingestion.scrapers.pagina12 --date 15-03-2005
```

Argumento:
- `--date`: fecha en formato `DD-MM-YYYY`. Requerido.

#### Comportamiento esperado

1. Parsear el argumento `--date` y validar que sea una fecha válida.
2. Determinar el path de output: `data/raw/pagina12/YYYY/MM/urls_DD-MM-YYYY.json`.
3. **Verificar si el archivo de output ya existe.** Si existe, loguear
   "URLs ya descubiertas para esta fecha, salteando." y terminar sin hacer requests.
   Esto garantiza reanudabilidad.
4. Intentar Mecanismo 1 (buscador). Si falla, intentar Mecanismo 2 (edición del día).
5. Guardar las URLs descubiertas en el archivo JSON de output.
6. Loguear un resumen: cuántas URLs se encontraron, qué mecanismo se usó, path del output.

#### Rate limiting

- Esperar **2 segundos entre requests** usando `time.sleep(2)`.
- User-Agent: `HemerotecaLaPlataAcademic/1.0 (proyecto-universitario)`
- Timeout por request: 30 segundos.
- Si un request falla (timeout, status 4xx/5xx), reintentar hasta 3 veces con
  backoff exponencial (2s, 4s, 8s) usando `tenacity`.

#### Formato del archivo JSON de output

```json
{
  "date": "15-03-2005",
  "source": "pagina12",
  "mechanism_used": "buscador" | "edicion_del_dia",
  "total_urls": 12,
  "scraped_at": "2026-05-15T10:30:00",
  "urls": [
    {
      "url": "https://www.pagina12.com.ar/...",
      "title": "Título de la nota si está disponible, null si no",
      "snippet": "Fragmento del bajada si está disponible, null si no"
    }
  ]
}
```

Si `title` y `snippet` no están disponibles en el mecanismo usado, guardarlos como `null`.
No es bloqueante: la URL sola es suficiente para esta fase.

---

## Librerías a usar

Todas ya están en `requirements.txt` del proyecto o son parte de stdlib:

```python
import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
```

**No usar `requests`**. El proyecto usa `httpx`.
**No usar `selenium` ni `playwright`**. Solo requests HTTP estáticos.

---

## Logging

Usar el módulo `logging` de stdlib, NO `print`.

Configuración mínima:
```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger("scrapers.pagina12")
```

Mensajes obligatorios:
- Al iniciar: `"Iniciando descubrimiento de URLs para fecha: {date}"`
- Si el archivo ya existe: `"Ya existe {path}, salteando."`
- Al intentar mecanismo: `"Intentando mecanismo: {mecanismo}"`
- Al encontrar URLs: `"Se encontraron {n} URLs con mención de 'La Plata'"`
- Al guardar: `"Output guardado en {path}"`
- En caso de error irrecuperable: `"Error al descubrir URLs: {error}"` (level ERROR)

---

## Script de prueba

Crear también `backend/tests/test_pagina12_scraper.py` con los siguientes tests:

```python
# Tests que NO hacen requests reales (todo mockeado con httpx mock o unittest.mock)

def test_output_path_generado_correctamente():
    # Dado "15-03-2005", el path debe ser data/raw/pagina12/2005/03/urls_15-03-2005.json
    ...

def test_skip_si_archivo_existe(tmp_path):
    # Si el archivo JSON ya existe, el scraper no hace ningún request
    ...

def test_parseo_fecha_invalida():
    # Si se pasa "32-13-2005", debe lanzar ValueError
    ...

def test_formato_json_output():
    # El JSON guardado debe tener las claves: date, source, mechanism_used,
    # total_urls, scraped_at, urls
    ...
```

---

## Restricciones importantes

1. **No modificar** `pipeline.py`, `models.py`, ni ningún módulo fuera de
   `backend/app/ingestion/scrapers/` y `backend/tests/`.
2. **No indexar nada en Qdrant** en esta fase. Solo descubrir y guardar URLs en disco.
3. **Respetar robots.txt**: antes de hacer el primer request, verificar
   `https://www.pagina12.com.ar/robots.txt` y loguear si hay restricciones
   relevantes para las rutas que se van a acceder. Si robots.txt prohíbe
   explícitamente el buscador o las ediciones del día, detener y notificar.
4. El script debe poder interrumpirse (Ctrl+C) sin corromper el archivo de output.
   Usar escritura atómica: escribir a un archivo `.tmp` y renombrarlo al final.
5. Crear los directorios de output con `Path.mkdir(parents=True, exist_ok=True)`.

---

## Criterio de aceptación de esta fase

Ejecutar:
```bash
python -m backend.app.ingestion.scrapers.pagina12 --date 15-03-2005
```

Y obtener:
- Un archivo `data/raw/pagina12/2005/03/urls_15-03-2005.json` con al menos 1 URL.
- El archivo JSON válido con todas las claves especificadas.
- Logs claros en stdout indicando qué mecanismo se usó y cuántas URLs se encontraron.
- Segunda ejecución con la misma fecha: el script termina inmediatamente sin hacer requests.

---

## Qué viene después (no implementar en esta fase)

Una vez validado que el JSON de URLs se genera correctamente, la siguiente fase
usará esas URLs como input para:
1. Fetchear el HTML completo de cada nota.
2. Parsear con `trafilatura`.
3. Extraer metadata (título, fecha, autor, sección).
4. Enriquecer con NER (spaCy) y gazetteer de La Plata.
5. Chunkear e indexar en Qdrant.

El contrato entre esta fase y la siguiente es exactamente el JSON descrito arriba.
