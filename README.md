# Aprobación Presidencial Chile

Dashboard web que reúne y visualiza las mediciones de aprobación presidencial en Chile, con bandas de confianza calculadas desde los n reales de cada encuesta.

## Estructura del proyecto

```
aprobacion-presidencial/
├── index.html                     # Dashboard principal
├── data/
│   └── aprobacion_presidencial.csv  # Base de datos maestra
└── README.md
```

## Base de datos (`data/aprobacion_presidencial.csv`)

Cada fila es una medición individual. Columnas:

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | int | Identificador único |
| `fecha_terreno` | date (YYYY-MM-DD) | Fecha de aplicación del instrumento |
| `presidente` | text | Presidente en ejercicio al momento de la medición |
| `encuestadora` | text | Empresa que realizó la encuesta |
| `producto` | text | Nombre del instrumento (ej. Plaza Pública) |
| `aprueba_pct` | float | % aprobación |
| `desaprueba_pct` | float | % desaprobación |
| `nr_pct` | float | % NS/NR o no responde |
| `n_muestra` | int | Tamaño muestral real |
| `se_aprueba` | float | Error estándar aprobación (pp) |
| `se_desaprueba` | float | Error estándar desaprobación (pp) |
| `ci95_aprueba` | float | IC 95% aprobación = 1.96 × SE (pp) |
| `ci95_desaprueba` | float | IC 95% desaprobación = 1.96 × SE (pp) |
| `neto` | int | Neto aprobación = aprueba − desaprueba |
| `modalidad` | text | online / telefónica / presencial / mixta |
| `n_informe` | text | Número del informe fuente |
| `url_fuente` | text | URL del informe original |

### Fórmulas

```
SE = sqrt( p × (1 − p) / n )     donde p = aprueba_pct / 100
IC95 = 1.96 × SE
neto = aprueba_pct − desaprueba_pct
```

## Cómo agregar nuevas mediciones

1. Abrir `data/aprobacion_presidencial.csv`
2. Agregar una fila al final con el próximo `id` correlativo
3. Completar todos los campos; `se_aprueba`, `se_desaprueba`, `ci95_aprueba`, `ci95_desaprueba` se pueden calcular con las fórmulas de arriba
4. Guardar el CSV — el dashboard se actualiza automáticamente

## Cómo correr el dashboard localmente

El dashboard lee el CSV con fetch, así que necesita un servidor local (no funciona abriendo el HTML directo desde el explorador de archivos por restricciones CORS).

**Con Python (recomendado):**
```bash
cd aprobacion-presidencial
python3 -m http.server 8000
# Abrir http://localhost:8000
```

**Con VS Code:**
Instalar la extensión Live Server (ritwickdey.LiveServer) → clic derecho en `index.html` → "Open with Live Server"

## Encuestadoras cubiertas

| Encuestadora | Producto | Frecuencia | Modalidad | Desde |
|---|---|---|---|---|
| Cadem | Plaza Pública | 2× semana | Online | Mar 2026 |

### Encuestadoras pendientes de incorporar

- CEP (trimestral, telefónica)
- Criteria (mensual)
- Pulso Ciudadano (mensual)
- Ipsos (ocasional)

## Notas metodológicas

- Desde el gobierno Kast (mar 2026), Cadem aplica **dos mediciones por semana**. Cada fila en la base corresponde a una medición individual, no al promedio semanal.
- El muestreo de Cadem es **no probabilístico con cuotas**; el IC calculado es orientativo, no estrictamente válido bajo teoría de muestreo clásico.
- Para comparaciones entre gobiernos, tener en cuenta que Cadem cambió de modalidad telefónica a online en 2026 — esto introduce un quiebre metodológico.
