# Aprobación Presidencial Chile

Dashboard web que reúne y visualiza las mediciones de aprobación presidencial en Chile. Combina un meta-análisis de efectos aleatorios (estimación retrospectiva del período seleccionado) con una tendencia LOESS (estimación prospectiva de la trayectoria reciente).

## Estructura del proyecto

```
aprobacion-presidencial/
├── index.html                        # Dashboard principal
├── wiki_sync.py                      # Sincronización automática desde Wikipedia
├── data/
│   ├── aprobacion_presidencial.csv   # Base de datos maestra
│   ├── encuestadoras.csv             # Catálogo de encuestadoras
│   └── .wiki_state.json              # Estado de sincronización (auto-generado)
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

**Encuestadoras no cubiertas por Wikipedia:** Black & White debe agregarse manualmente a Wikipedia antes de que el script la incorpore. AtlasIntel está marcada como `excluir = 1`.

**Falso positivo conocido:** la medición «después» del experimento pre-post de Panel Ciudadano (16 Abr 2026, 39%/49%, n=1030) siempre aparece como candidata; no debe incorporarse al CSV.

### Rutina diaria automatizada

Una rutina remota en Claude Code ejecuta `wiki_sync.py` cada día a las 12:00 UTC (~8am hora de Santiago en invierno) y, si hay filas nuevas, hace commit y push automáticamente.

- **ID de rutina:** `trig_014yGsqF2S8haYiapibxCPWh`
- **Gestión:** https://claude.ai/code/routines/trig_014yGsqF2S8haYiapibxCPWh
- **Requisito:** la GitHub App de Claude debe estar instalada en el repositorio para que la rutina pueda clonar y hacer push.

## Cómo agregar mediciones manualmente

Para encuestadoras no cubiertas por Wikipedia (actualmente solo Black & White):

1. Agregar primero la entrada a la tabla de Wikipedia (ver instrucciones de formato en el historial del repositorio).
2. Ejecutar `python wiki_sync.py` — la fila será incorporada automáticamente.
3. Completar `n_informe` y verificar `fecha_informe`.

Para incorporar mediciones directamente al CSV sin pasar por Wikipedia:

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
