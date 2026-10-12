"""Constantes del proyecto: país, fechas, ciudades, pesos, rutas, URLs y umbrales."""

from pathlib import Path

# --- Zona y periodo ---------------------------------------------------------
COUNTRY = "es"
START_DATE = "2019-01-01"
LOCAL_TZ = "Europe/Madrid"
FREQ = "1h"

# --- Rutas ------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_LOAD_CHUNKS_DIR = RAW_DIR / "load"
RAW_WEATHER_CHUNKS_DIR = RAW_DIR / "weather"
RAW_LOAD_FILE = RAW_DIR / "load_hourly.parquet"
RAW_WEATHER_FILE = RAW_DIR / "weather_hourly.parquet"
OUTPUT_DIR = DATA_DIR / "output"
OUTPUT_CSV = OUTPUT_DIR / "energy_weather_es_hourly.csv"
QUALITY_REPORT_FILE = OUTPUT_DIR / "quality_report.json"
README_FILE = ROOT_DIR / "README.md"
README_QUALITY_MARKERS = ("<!-- QUALITY:START -->", "<!-- QUALITY:END -->")

# --- Energy-Charts (demanda) ------------------------------------------------
ENERGY_CHARTS_URL = "https://api.energy-charts.info/public_power"
LOAD_SERIES_NAME = "Load"

# --- Open-Meteo (meteorología) ----------------------------------------------
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_TIMEZONE = "UTC"
# Días recientes que se piden también al endpoint forecast para cubrir el retraso del archive.
FORECAST_LOOKBACK_DAYS = 14
FORECAST_MAX_PAST_DAYS = 92

WEATHER_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "shortwave_radiation",
    "precipitation",
]

CITIES = {
    "madrid": {"lat": 40.42, "lon": -3.70, "weight": 0.30},
    "barcelona": {"lat": 41.39, "lon": 2.17, "weight": 0.25},
    "valencia": {"lat": 39.47, "lon": -0.38, "weight": 0.15},
    "sevilla": {"lat": 37.39, "lon": -5.98, "weight": 0.15},
    "bilbao": {"lat": 43.26, "lon": -2.93, "weight": 0.15},
}

# --- HTTP ---------------------------------------------------------------------
HTTP_TIMEOUT = 60  # segundos
# Energy-Charts limita mucho la frecuencia (429 + Retry-After): hacen falta bastantes reintentos.
HTTP_MAX_ATTEMPTS = 10
HTTP_BACKOFF_MIN = 2  # segundos
HTTP_BACKOFF_MAX = 120  # segundos
# Pausa entre peticiones, por cortesía con las APIs públicas.
REQUEST_PAUSE_SECONDS = 0.5

# --- Caché de descargas en bruto ---------------------------------------------
# Los bloques que terminan antes de hoy - STABLE_DAYS se consideran definitivos y se reutilizan.
STABLE_DAYS = 7

# --- Limpieza -----------------------------------------------------------------
MAX_INTERPOLATION_GAP_HOURS = 3
UPDATE_OVERLAP_DAYS = 3

VALUE_RANGES: dict[str, tuple[float | None, float | None]] = {
    "load_mw": (15000, 50000),
    "temperature_2m": (-20, 50),
    "relative_humidity_2m": (0, 100),
    "wind_speed_10m": (0, None),
    "shortwave_radiation": (0, None),
    "precipitation": (0, None),
}
OUT_OF_RANGE_EXAMPLES = 10
MAX_LOAD_MISSING_PCT = 0.5

# --- Calendario ---------------------------------------------------------------
COVID_START = "2020-03-14"
COVID_END = "2020-06-21"
HOLIDAYS_COUNTRY = "ES"

# --- CSV ----------------------------------------------------------------------
CSV_COLUMNS = [
    "time_utc",
    "time_local",
    "load_mw",
    *WEATHER_VARIABLES,
    "is_holiday",
    "covid_flag",
    "load_interpolated",
    "weather_interpolated",
]
CSV_FLOAT_FORMAT = "%.3f"

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
