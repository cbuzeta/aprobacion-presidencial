# Aprobación Presidencial Chile

Dashboard web que reúne y visualiza las mediciones de aprobación presidencial en Chile. Combina un meta-análisis de efectos aleatorios (estimación retrospectiva del período seleccionado) con una tendencia LOESS (estimación prospectiva de la trayectoria reciente).

## Estructura del proyecto

```
aprobacion-presidencial/
├── index.html                        # Dashboard principal
├── wiki_sync.py                      # Sincronización automática desde Wikipedia
├── blackwhite_sync.py                # Sincronización automática desde blackwhite.global
├── data/
│   ├── aprobacion_presidencial.csv   # Base de datos maestra
│   ├── encuestadoras.csv             # Catálogo de encuestadoras
│   └── .wiki_state.json              # Estado de sincronización de Wikipedia (auto-generado)
├── .github/
│   └── workflows/
│       ├── wiki_sync.yml             # Acción diaria de sincronización (Wikipedia)
│       └── blackwhite_sync.yml       # Acción diaria de sincronización (Black & White)
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
| AtlasIntel | Latam Pulse Chile | Mensual | Online (excluida) |

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

**Seguimiento manual tras cada sincronización:** el script deja en blanco `n_informe` y usa la fecha fin de campo como proxy de `fecha_informe`; ambos campos pueden requerir corrección manual.

**Encuestadoras no cubiertas por Wikipedia:** Black & White casi nunca aparece en la tabla de Wikipedia (la última vez fue una medición publicada el 1 de mayo de 2026); se sincroniza aparte con `blackwhite_sync.py` (ver abajo). AtlasIntel está marcada como `excluir = 1`.

**Falso positivo conocido:** la medición «después» del experimento pre-post de Panel Ciudadano (16 Abr 2026, 39%/49%, n=1030) siempre aparece como candidata; no debe incorporarse al CSV.

### `blackwhite_sync.py`

Recorre el listado de informes en https://www.blackwhite.global/s-projects-side-by-side y agrega al CSV los que falten. Los PDF de Black & White tienen capa de texto para el título, la fecha, el tamaño muestral y el % de aprobación (mencionado en el texto de la lámina "Aprobación del gobierno"), pero el % de desaprobación y de "no aprueba ni desaprueba" solo existen como gráfico — esos dos se leen con OCR (`tesseract`) y se descartan automáticamente si no cuadran (checksum ≠ 100 o el valor de aprobación del OCR no coincide con el del texto), quedando pendientes de carga manual.

```bash
python blackwhite_sync.py            # verificar y sincronizar informes nuevos
python blackwhite_sync.py --dry-run  # previsualizar sin escribir nada
```

Requiere los binarios `tesseract` y `pdftotext`/`pdftoppm` (poppler) en el PATH; no tiene dependencias de Python fuera de la biblioteca estándar.

### Rutina diaria automatizada

Dos workflows de GitHub Actions ejecutan cada sincronizador una vez al día y, si hay filas nuevas, hacen commit y push automáticamente:

- `wiki_sync.yml` — 12:00 UTC (~8am Santiago en invierno)
- `blackwhite_sync.yml` — 13:00 UTC

- **Ver ejecuciones:** https://github.com/cbuzeta/aprobacion-presidencial/actions
- **Disparar manualmente:** GitHub → Actions → (Wiki Sync | Black & White Sync) → Run workflow (o `gh workflow run wiki_sync.yml` / `gh workflow run blackwhite_sync.yml`)

## Cómo agregar mediciones manualmente

Para filas que ninguno de los dos sincronizadores pudo verificar automáticamente (por ejemplo, un informe de Black & White marcado "OCR mismatch" o "checksum failed" en el log de la Action):

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
