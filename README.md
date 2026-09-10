# Aprobación Presidencial Chile

Dashboard web que reúne y visualiza las mediciones de aprobación presidencial en Chile. Combina un meta-análisis de efectos aleatorios (estimación retrospectiva del período seleccionado) con una tendencia LOESS (estimación prospectiva de la trayectoria reciente).

## Estructura del proyecto

```
aprobacion-presidencial/
├── index.html                        # Dashboard principal
├── wiki_sync.py                      # Sincronización automática desde Wikipedia
├── blackwhite_sync.py                # Sincronización automática desde blackwhite.global
├── atlasintel_sync.py                # Sincronización automática desde atlasintel.org
├── data/
│   ├── aprobacion_presidencial.csv   # Base de datos maestra
│   ├── encuestadoras.csv             # Catálogo de encuestadoras
│   └── .wiki_state.json              # Estado de sincronización de Wikipedia (auto-generado)
├── .github/
│   └── workflows/
│       ├── wiki_sync.yml             # Acción diaria de sincronización (Wikipedia)
│       ├── blackwhite_sync.yml       # Acción diaria de sincronización (Black & White)
│       └── atlasintel_sync.yml       # Acción mensual de sincronización (AtlasIntel)
├── logo.svg
├── logotype.svg
└── README.md
```

## Base de datos (`data/aprobacion_presidencial.csv`)

Cada fila es una medición individual. Columnas:

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | int | Identificador único correlativo |
| `fecha_informe` | date (DD-MM-YYYY) | Fecha de publicación del informe |
| `fecha_inicio_campo` | date (DD-MM-YYYY) | Inicio del trabajo de campo |
| `fecha_fin_campo` | date (DD-MM-YYYY) | Fin del trabajo de campo |
| `presidente` | text | Presidente en ejercicio |
| `encuestadora` | text | Empresa que realizó la encuesta |
| `producto` | text | Nombre del instrumento (ej. Plaza Pública) |
| `aprueba_pct` | float | % aprobación presidencial |
| `desaprueba_pct` | float | % desaprobación presidencial |
| `nr_pct` | float | % NS/NR / ninguna |
| `n_muestra` | int | Tamaño muestral nominal |
| `aprueba_gob_pct` | float | % aprobación del gobierno (cuando disponible) |
| `desaprueba_gob_pct` | float | % desaprobación del gobierno (cuando disponible) |
| `nr_gob_pct` | float | % NS/NR gobierno (cuando disponible) |
| `neto_gob` | int | Neto gobierno = aprueba_gob − desaprueba_gob |
| `modalidad` | text | online / telefónica / presencial / mixta |
| `n_informe` | text | Número o nombre del informe fuente |
| `excluir` | int | 1 = excluir de la visualización; 0 = incluir |
| `url_fuente` | text | URL del informe original |

## Encuestadoras cubiertas

| Encuestadora | Producto | Frecuencia aprox. | Modalidad |
|---|---|---|---|
| Cadem | Plaza Pública | 2× semana | Online |
| Criteria | Agenda Criteria | Semanal | Online |
| Black & White | Black & White | Semanal | Online |
| Panel Ciudadano-UDD | Panel Ciudadano | Semanal | Online |
| Activa Research | Pulso Ciudadano | Quincenal | Online |
| TuInfluyes.com | DataInfluye | Mensual | Online |
| AtlasIntel | Latam Pulse Chile | Mensual | Online |

## Sincronización automática

La principal fuente para mantener el CSV actualizado es la tabla de Wikipedia:
[Encuestas de aprobación del gobierno de José Antonio Kast](https://es.wikipedia.org/wiki/Anexo:Encuestas_de_aprobaci%C3%B3n_del_gobierno_de_Jos%C3%A9_Antonio_Kast)

### `wiki_sync.py`

Detecta cambios en la página de Wikipedia y agrega las filas nuevas al CSV.

```bash
python wiki_sync.py            # verificar y sincronizar si hubo cambios
python wiki_sync.py --force    # sincronizar sin importar la revisión
python wiki_sync.py --dry-run  # previsualizar sin escribir nada
```

El script requiere solo la biblioteca estándar de Python (sin dependencias externas).

**`n_informe` y `fecha_informe` se derivan automáticamente** a partir de la propia cita de Wikipedia (número de seguimiento de Cadem, fecha de publicación de Criteria/CEP/Activa, código de mes de TuInfluyes, etc.), con un resguardo ante fechas de citación inverosímiles (anteriores al fin del trabajo de campo, o más de 30 días después) por si la cita en Wikipedia tiene un error de tipeo. Cuando una fila no queda respaldada por el informe propio de la encuestadora (por ejemplo, una encuesta mencionada solo en un artículo periodístico), se usa un `n_informe` del tipo «Citado en \<sitio\> (\<fecha\>)» en vez de dejarlo en blanco. Si de todas formas algún `n_informe` queda vacío (una encuestadora o formato de cita nuevo que el script no reconoce), la Action termina en rojo para que no pase inadvertido.

**Encuestadoras no cubiertas por Wikipedia:** Black & White casi nunca aparece en la tabla (la última vez fue una medición publicada el 1 de mayo de 2026) y AtlasIntel no tiene ninguna fila en la tabla actualmente; ambas se sincronizan aparte con `blackwhite_sync.py` y `atlasintel_sync.py` (ver abajo).

**Falso positivo conocido:** la medición «después» del experimento pre-post de Panel Ciudadano (16 Abr 2026, 39%/49%, n=1030) siempre aparece como candidata; no debe incorporarse al CSV.

**Enlaces de Cadem:** Cadem elimina de `cadem.cl/wp-content/uploads` los PDF de más de ~1 mes (confirmado: todo lo anterior a agosto 2026 daba 404). El script reescribe automáticamente cualquier URL de `cadem.cl` a su equivalente en `insight-chile.cl` — plataforma hermana del propio Cadem (`insightchile@cadem.cl`), no un mirror de terceros — que replica la misma ruta de forma permanente.

### `blackwhite_sync.py`

Recorre el listado de informes en https://www.blackwhite.global/s-projects-side-by-side y agrega al CSV los que falten. Los PDF de Black & White tienen capa de texto para el título, la fecha, el tamaño muestral y el % de aprobación (mencionado en el texto de la lámina "Aprobación del gobierno"), pero el % de desaprobación y de "no aprueba ni desaprueba" solo existen como gráfico — esos dos se leen con OCR (`tesseract`) y se descartan automáticamente si no cuadran (checksum ≠ 100 o el valor de aprobación del OCR no coincide con el del texto), quedando pendientes de carga manual.

```bash
python blackwhite_sync.py            # verificar y sincronizar informes nuevos
python blackwhite_sync.py --dry-run  # previsualizar sin escribir nada
```

Requiere los binarios `tesseract` y `pdftotext`/`pdftoppm` (poppler) en el PATH; no tiene dependencias de Python fuera de la biblioteca estándar.

### `atlasintel_sync.py`

Recorre el listado de informes en https://atlasintel.org/polls/latam-pulse y agrega al CSV los "Latam Pulse: Chile" que falten (AtlasIntel publica uno al mes, típicamente dentro de los primeros ~8 días del mes siguiente). La página de metodología del PDF tiene capa de texto (tamaño muestral, fechas de campo), pero el gráfico de barras de aprobación/desaprobación/no sabe es una imagen sin capa de texto — esos tres valores se leen con OCR (`tesseract`), ubicando primero cada etiqueta ("Apruebo"/"Desapruebo"/"No sé") y luego recortando ajustadamente los píxeles casi negros debajo de cada una (para no confundir el propio color de la barra con texto). Se prueban varias combinaciones de escala/umbral/PSM hasta que los tres valores sumen 100% ±1pp; si ninguna cuadra, el informe queda pendiente de carga manual.

```bash
python atlasintel_sync.py            # verificar y sincronizar informes nuevos
python atlasintel_sync.py --dry-run  # previsualizar sin escribir nada
```

Requiere los binarios `tesseract` y `pdftotext`/`pdftoppm` (poppler), además del paquete Python `Pillow` (para el recorte/umbralado a nivel de píxel que la biblioteca estándar no puede hacer).

### Rutina automatizada

Tres workflows de GitHub Actions ejecutan cada sincronizador y, si hay filas nuevas, hacen commit y push automáticamente. Los tres terminan en rojo (sin dejar de hacer commit de lo que sí se pudo verificar) si algún informe encontrado no pudo verificarse automáticamente, para que una falla silenciosa no pase semanas sin notarse:

- `wiki_sync.yml` — diario, 12:00 UTC (~8am Santiago en invierno)
- `blackwhite_sync.yml` — diario, 13:00 UTC
- `atlasintel_sync.yml` — mensual, día 10 (segunda semana) a las 14:00 UTC

- **Ver ejecuciones:** https://github.com/cbuzeta/aprobacion-presidencial/actions
- **Disparar manualmente:** GitHub → Actions → (Wiki Sync | Black & White Sync | AtlasIntel Sync) → Run workflow (o `gh workflow run wiki_sync.yml` / `gh workflow run blackwhite_sync.yml` / `gh workflow run atlasintel_sync.yml`)

## Cómo agregar mediciones manualmente

Para filas que ningún sincronizador pudo verificar automáticamente (por ejemplo, un informe marcado "OCR mismatch" o "checksum failed" en el log de la Action):

1. Revisar el PDF del informe (el log imprime la URL).
2. Completar la fila a mano siguiendo el procedimiento de abajo.

Para incorporar mediciones directamente al CSV sin pasar por los sincronizadores:

1. Abrir `data/aprobacion_presidencial.csv`.
2. Agregar una fila al final con el próximo `id` correlativo.
3. Completar todos los campos obligatorios; dejar en blanco los que no apliquen.

## Cómo correr el dashboard localmente

El dashboard carga el CSV con `fetch`, por lo que necesita un servidor local (no funciona abriendo el HTML directamente desde el explorador de archivos por restricciones CORS).

**Con Python:**
```bash
python -m http.server 8000
# Abrir http://localhost:8000
```

**Con VS Code:**
Instalar la extensión Live Server → clic derecho en `index.html` → «Open with Live Server».

## Notas metodológicas

- **Paneles no probabilísticos:** la mayoría de las encuestadoras utiliza paneles en línea. Los tamaños de muestra reportados no necesariamente reflejan observaciones independientes; los intervalos de confianza deben interpretarse como orientativos.
- **Meta-análisis:** las estimaciones retrospectivas usan meta-análisis de efectos aleatorios (DerSimonian-Laird, escala de Fisher arcsin√p). La heterogeneidad entre encuestadoras queda absorbida en τ² y no se modela explícitamente como efecto de casa.
- **Tendencia LOESS:** regresión local lineal ponderada (grado 1, kernel tri-cúbico, bw = 35%); el n por medición entra como peso. No existe un «n efectivo» único que caracterice la tendencia.
- **Escala temporal:** el eje x usa la fecha fin de campo como fecha de referencia de cada medición.

## Agradecimientos

Este proyecto se ha beneficiado de los comentarios y la retroalimentación de:

- **Rodrigo Uribe** (Universidad de Chile)
- **Paulina Valenzuela** (Datavoz)
- **Alejandra Ojeda** (IPSOS)

## Historial de versiones

El número de versión se muestra junto al logo en el dashboard y corresponde a un [tag de git](https://github.com/cbuzeta/aprobacion-presidencial/tags) sobre el commit correspondiente.

| Versión | Descripción |
|---|---|
| v1.0 | Versión inicial del dashboard. |
| v1.1 | Filtros dinámicos por encuestadora y rango de fechas. |
| v1.2 | Mejora de los estimadores LOESS y meta-análisis; URLs de fuente clickeables y tabla de fuentes colapsable. |
| v1.3 | Serie NS/NR, filtro de series y dropdown de encuestadora; columnas de aprobación de gobierno. |
| v1.4 | Branding Metaseñal y limpieza del header. |
| v1.5 | Secciones colapsables (Nota metodológica, Fuentes de datos); tarjetas de estadísticas reencuadradas como retrospectivas/prospectivas. |
| v1.6 | `wiki_sync.py`: primera sincronización automática de datos desde Wikipedia. |
| v1.7 | Rebrand a MetaAprobación; sincronización diaria movida a GitHub Actions. |
| v1.8 | Corrección del intervalo de confianza al 95% y exportación a PNG. |
| v1.9 | Corrección de bugs de pérdida de datos en `wiki_sync.py`; nuevo `blackwhite_sync.py` (sincronización por OCR desde blackwhite.global); auditoría completa del CSV (id duplicado, fila de CEP mal parseada, `n_informe` incompletos, orden cronológico); corrección de redondeo en el tooltip «Neto». |
| v1.10 | Sección de Agradecimientos; nuevo `atlasintel_sync.py` (tercera fuente automatizada, mensual, por OCR) e inclusión de AtlasIntel en el dashboard; derivación automática de `n_informe`/`fecha_informe` y alerta ruidosa ante reportes no verificables en las tres sincronizaciones; corrección de regresión de fechas y backfill de 7 semanas en `blackwhite_sync.py`; recuperación de 39 enlaces caídos de Cadem vía `insight-chile.cl` (espejo permanente propio de Cadem) y reescritura automática de esas URLs en `wiki_sync.py` para que no vuelvan a caerse; auditoría de salud de enlaces en las 82 fuentes restantes (sin hallazgos). |
