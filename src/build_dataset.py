"""Script principal: descarga, limpia, combina y exporta el dataset a CSV.

Uso:
    uv run python -m src.build_dataset --start 2019-01-01   # generación completa
    uv run python -m src.build_dataset --update             # actualización incremental
"""

import argparse
import logging
import sys

import holidays
import pandas as pd

from src import config
from src.http_utils import to_utc
from src.load_client import fetch_load
from src.validate import (
    clean_load,
    clean_weather,
    hourly_grid,
    quality_report,
    save_report,
    update_readme_summary,
)
from src.weather_client import fetch_weather

logger = logging.getLogger(__name__)


# --- Calendario -----------------------------------------------------------------

def add_calendar(df: pd.DataFrame) -> pd.DataFrame:
    """Añade `time_local`, `is_holiday` y `covid_flag` a un DataFrame con índice horario UTC."""
    df = df.copy()
    local = df.index.tz_convert(config.LOCAL_TZ)
    local_dates = local.normalize().tz_localize(None)
    years = range(local.year.min(), local.year.max() + 1)
    national = holidays.country_holidays(config.HOLIDAYS_COUNTRY, years=years)

    df["time_local"] = local
    df["is_holiday"] = pd.Index(local.date).map(lambda d: d in national).astype(int)
    covid = (local_dates >= pd.Timestamp(config.COVID_START)) & (local_dates <= pd.Timestamp(config.COVID_END))
    df["covid_flag"] = covid.astype(int)
    return df


# --- Combinación y exportación --------------------------------------------------

def combine(load_raw: pd.DataFrame, weather_raw: pd.DataFrame, grid_start: pd.Timestamp) -> pd.DataFrame:
    """Rejilla horaria → limpieza → left join demanda + meteo → columnas de calendario."""
    grid_end = load_raw["load_mw"].last_valid_index()
    if grid_end is None:
        raise RuntimeError("No hay datos de demanda descargados")
    grid = hourly_grid(grid_start, grid_end)
    load = clean_load(load_raw, grid)
    weather = clean_weather(weather_raw, grid)
    df = load.join(weather, how="left")
    return add_calendar(df)


def to_csv_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Columnas en el orden exacto del CSV y fechas en ISO 8601 con offset."""
    out = df.copy()
    out["time_utc"] = [t.isoformat() for t in out.index]
    out["time_local"] = [t.isoformat() for t in out["time_local"]]
    return out[config.CSV_COLUMNS].reset_index(drop=True)


def export(df: pd.DataFrame) -> None:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    to_csv_frame(df).to_csv(config.OUTPUT_CSV, index=False, encoding="utf-8", float_format=config.CSV_FLOAT_FORMAT)
    logger.info("CSV guardado en %s (%d filas)", config.OUTPUT_CSV, len(df))

    report = quality_report(df)
    save_report(report)
    update_readme_summary(report)
    if not report.get("load_missing_ok", False):
        logger.warning("Demanda sin datos: %.3f %% (límite %.1f %%)", report.get("load_missing_pct", 100), config.MAX_LOAD_MISSING_PCT)


def save_raw(load_raw: pd.DataFrame, weather_raw: pd.DataFrame) -> None:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    load_raw.to_parquet(config.RAW_LOAD_FILE)
    weather_raw.to_parquet(config.RAW_WEATHER_FILE)


# --- Modos de ejecución ---------------------------------------------------------

def default_end() -> pd.Timestamp:
    """Fin exclusivo por defecto: mañana a las 00:00 UTC (incluye todo lo disponible hoy)."""
    return pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=1)


def build_full(start: pd.Timestamp, end: pd.Timestamp, use_cache: bool = True) -> None:
    logger.info("Generación completa %s → %s", start.date(), end.date())
    load_raw = fetch_load(start, end, use_cache=use_cache)
    weather_raw = fetch_weather(start, end, use_cache=use_cache)
    save_raw(load_raw, weather_raw)
    export(combine(load_raw, weather_raw, start))


def replace_tail(existing: pd.DataFrame, new: pd.DataFrame, since: pd.Timestamp) -> pd.DataFrame:
    """Sustituye el tramo >= `since` de `existing` por `new`. Idempotente: nunca duplica horas."""
    merged = pd.concat([existing[existing.index < since], new[new.index >= since]])
    return merged[~merged.index.duplicated(keep="last")].sort_index()


def update() -> None:
    if not config.OUTPUT_CSV.exists():
        logger.warning("No existe %s: se hace la generación completa", config.OUTPUT_CSV)
        build_full(to_utc(config.START_DATE), default_end())
        return

    times = pd.read_csv(config.OUTPUT_CSV, usecols=["time_utc"])["time_utc"]
    first, last = to_utc(times.iloc[0]), to_utc(times.iloc[-1])
    if not (config.RAW_LOAD_FILE.exists() and config.RAW_WEATHER_FILE.exists()):
        logger.warning("Faltan las descargas en bruto en %s: se hace la generación completa (con caché)", config.RAW_DIR)
        build_full(first, default_end())
        return

    since = (last - pd.Timedelta(days=config.UPDATE_OVERLAP_DAYS)).normalize()
    end = default_end()
    logger.info("Actualización: se vuelve a descargar desde %s", since.date())
    new_load = fetch_load(since, end, use_cache=False)
    new_weather = fetch_weather(since, end, use_cache=False)

    load_raw = replace_tail(pd.read_parquet(config.RAW_LOAD_FILE), new_load, since)
    weather_raw = replace_tail(pd.read_parquet(config.RAW_WEATHER_FILE), new_weather, since)
    save_raw(load_raw, weather_raw)
    export(combine(load_raw, weather_raw, first))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--start", default=config.START_DATE, help="Fecha inicial (UTC) de la generación completa")
    mode.add_argument("--update", action="store_true", help="Actualiza el CSV existente desde su última fecha - 3 días")
    parser.add_argument("--end", help="Fecha final inclusiva (UTC); por defecto, hoy")
    parser.add_argument("--no-cache", action="store_true", help="Ignora la caché de data/raw y lo descarga todo")
    parser.add_argument("-v", "--verbose", action="store_true", help="Logging en nivel DEBUG")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # consolas de Windows
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format=config.LOG_FORMAT)
    if args.update:
        update()
    else:
        end = to_utc(args.end) + pd.Timedelta(days=1) if args.end else default_end()
        build_full(to_utc(args.start), end, use_cache=not args.no_cache)


if __name__ == "__main__":
    main()
