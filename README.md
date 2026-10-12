# Dataset de demanda eléctrica + meteorología (España)

Repositorio que **descarga, limpia y combina** la demanda eléctrica horaria de España con meteorología, y lo exporta a un CSV.
El CSV se usa después en otro proyecto (forecasting de demanda a 24 h). El modelado no forma parte de este repositorio.

```
Energy-Charts (demanda) ─┐
                         ├─→ limpieza + validación → combinación → CSV
Open-Meteo (meteo) ──────┘
```

## Contenido del CSV

`data/output/energy_weather_es_hourly.csv`

- **Periodo:** desde `2019-01-01T00:00:00+00:00` hasta la última hora con demanda disponible.
- **Resolución:** horaria, una fila por hora, ordenada por `time_utc`, sin huecos en la rejilla.
- **Formato:** UTF-8, separador `,`, decimal `.`, sin columna de índice. Fechas ISO 8601 con offset.

| Columna | Tipo | Descripción |
|---|---|---|
| `time_utc` | datetime | Inicio de la hora, en UTC |
| `time_local` | datetime | Inicio de la hora, en `Europe/Madrid` (los días de cambio de hora tienen 23 o 25 filas) |
| `load_mw` | float | Demanda media horaria (MW) |
| `temperature_2m` | float | °C, media ponderada |
| `relative_humidity_2m` | float | %, media ponderada |
| `wind_speed_10m` | float | km/h, media ponderada |
| `shortwave_radiation` | float | W/m², media ponderada |
| `precipitation` | float | mm, media ponderada |
| `is_holiday` | int (0/1) | Festivo nacional en España (librería `holidays`, fecha local) |
| `covid_flag` | int (0/1) | Estado de alarma: del 2020-03-14 al 2020-06-21 (fecha local) |
| `load_interpolated` | int (0/1) | Demanda interpolada |
| `weather_interpolated` | int (0/1) | Alguna variable meteorológica interpolada |

```python
import pandas as pd
df = pd.read_csv("energy_weather_es_hourly.csv", parse_dates=["time_utc"])
```

> `time_local` tiene offsets mixtos (+01:00 y +02:00). Para tratarla como fecha usa
> `pd.to_datetime(df["time_local"], utc=True).dt.tz_convert("Europe/Madrid")`.

La meteorología nacional es la media ponderada por población de 5 ciudades:

| Ciudad | lat | lon | peso |
|---|---|---|---|
| Madrid | 40.42 | -3.70 | 0.30 |
| Barcelona | 41.39 | 2.17 | 0.25 |
| Valencia | 39.47 | -0.38 | 0.15 |
| Sevilla | 37.39 | -5.98 | 0.15 |
| Bilbao | 43.26 | -2.93 | 0.15 |

## Fuentes de datos y licencias

- **Demanda:** [Energy-Charts](https://energy-charts.info) (Fraunhofer ISE), endpoint `public_power`, serie `Load`, con datos de la
  [ENTSO-E Transparency Platform](https://transparency.entsoe.eu). Energy-Charts publica sus datos bajo
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); los datos de origen ENTSO-E están sujetos a sus
  [condiciones de uso](https://transparency.entsoe.eu/content/static_content/Static%20content/terms%20and%20conditions/terms%20and%20conditions.html).
  Cita: *Energy-Charts.info, Fraunhofer ISE, datos de ENTSO-E*.
  La resolución es horaria hasta aproximadamente 2022 y de 15 minutos después; todo se remuestrea a 1 h con la media.
- **Meteorología:** [Open-Meteo](https://open-meteo.com) (endpoints historical `archive` y `forecast` con `past_days` para los últimos días).
  Datos bajo [CC BY 4.0](https://open-meteo.com/en/license); la API gratuita es solo para uso no comercial.
  Cita: *Weather data by Open-Meteo.com*.

## Cómo generar o actualizar el dataset

Requisito: [uv](https://docs.astral.sh/uv/). uv instala Python 3.11 y las dependencias automáticamente.

```bash
uv sync                                           # crea .venv con Python 3.11 y las dependencias
uv run python -m src.build_dataset --start 2019-01-01   # generación completa
uv run python -m src.build_dataset --update             # actualización incremental
```

Opciones: `--end YYYY-MM-DD` (fecha final inclusiva, por defecto hoy), `--no-cache` (lo vuelve a descargar todo) y `-v` (logging DEBUG).

- **Generación completa:** descarga la demanda mes a mes y la meteorología por bloques anuales y por ciudad.
  Cada bloque se guarda en `data/raw/` y los bloques ya definitivos (de hace más de 7 días) se reutilizan,
  así que si algo falla basta con volver a lanzar el comando. Energy-Charts limita la frecuencia de peticiones
  (HTTP 429): el cliente respeta `Retry-After`, y la primera generación completa tarda unos 20-40 minutos.
- **`--update`:** lee la última fecha del CSV, vuelve a descargar desde esa fecha **menos 3 días** (los datos recientes
  se revisan), sustituye ese tramo en `data/raw/*_hourly.parquet` y regenera el CSV, el informe de calidad y el resumen de este README.
  Es idempotente: ejecutarlo dos veces seguidas no duplica filas. Si no existe `data/raw/` (por ejemplo, en un clon nuevo),
  hace una generación completa.

Tests:

```bash
uv run pytest                  # tests unitarios (sin red)
uv run pytest -m integration   # descarga real de 2 días de ambas APIs
```

## Decisiones de limpieza

- Todo se procesa en **UTC**; `time_local` solo se añade al exportar.
- Se reindexa a una **rejilla horaria continua**, así que los huecos aparecen como NaN.
- Los huecos **interiores de 3 horas o menos** se interpolan linealmente y se marcan con `load_interpolated` / `weather_interpolated`.
- Los huecos mayores se dejan como **NaN** y se listan en el informe de calidad.
- Si falta alguna de las 5 ciudades en una hora, la media nacional de esa hora queda como NaN, en lugar de renormalizar los pesos.
- **No se elimina nada:** ni el periodo COVID ni los valores fuera de rango. Se marcan con columnas indicadoras o se reportan
  en `data/output/quality_report.json` (rangos esperados: demanda 15.000-50.000 MW, temperatura -20 a 50 °C, humedad 0-100 %,
  viento, radiación y precipitación ≥ 0).
- No se calculan lags ni medias móviles: dependen del proyecto que consume el CSV.

## Estructura

```
src/
├── config.py           # todas las constantes (país, fechas, ciudades, pesos, rutas, URLs, umbrales)
├── http_utils.py       # peticiones con reintentos (tenacity) + caché de bloques en parquet
├── load_client.py      # demanda (Energy-Charts)
├── weather_client.py   # meteorología (Open-Meteo)
├── validate.py         # rejilla, interpolación, informe de calidad
└── build_dataset.py    # CLI principal → CSV
data/raw/               # descargas en bruto (parquet, ignoradas por git)
data/output/            # CSV final + quality_report.json
tests/                  # pytest (+ fixtures/)
```

## Último informe de calidad

<!-- QUALITY:START -->
_Generado: 2026-10-11T21:33:26+00:00_

| Métrica | Valor |
|---|---|
| Periodo | 2019-01-01T00:00:00+00:00 → 2026-10-11T19:00:00+00:00 |
| Filas | 68,180 |
| Horas esperadas / presentes | 68,180 / 68,180 |
| Índice único y creciente | True |
| Horas sin demanda | 35 (0.0513 %) |
| Huecos de demanda > 3 h | 1 |
| Huecos de meteorología > 3 h | 0 |
| Valores interpolados (demanda / meteo) | 0 / 0 |
| Valores fuera de rango | {'load_mw': 2} |
<!-- QUALITY:END -->
