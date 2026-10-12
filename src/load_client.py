"""Descarga de la demanda eléctrica de España desde Energy-Charts (Fraunhofer ISE, datos ENTSO-E)."""

import logging
from typing import Any

import numpy as np
import pandas as pd

from src import config
from src.http_utils import get_json, read_cached, to_utc, write_cache

logger = logging.getLogger(__name__)


def parse_load_response(payload: dict[str, Any]) -> pd.DataFrame:
    """Extrae la serie `Load` (MW) de una respuesta de /public_power, sin remuestrear.

    Devuelve un DataFrame con la columna `load_mw` e índice `time` en UTC; los `null` pasan a NaN.
    """
    series = next(
        (p for p in payload.get("production_types", []) if p.get("name") == config.LOAD_SERIES_NAME),
        None,
    )
    index = pd.to_datetime(payload.get("unix_seconds", []), unit="s", utc=True)
    if series is None:
        logger.warning("La respuesta no contiene la serie %r", config.LOAD_SERIES_NAME)
        values = np.full(len(index), np.nan)
    else:
        values = np.array([np.nan if v is None else v for v in series["data"]], dtype=float)
    return pd.DataFrame({"load_mw": values}, index=pd.DatetimeIndex(index, name="time"))


def to_hourly(raw: pd.DataFrame) -> pd.DataFrame:
    """Elimina duplicados, ordena y remuestrea a 1 h con la media (sirve para datos de 15 min y horarios)."""
    raw = raw[~raw.index.duplicated(keep="last")].sort_index()
    hourly = raw.resample(config.FREQ).mean()
    hourly.index.name = "time"
    return hourly


def _month_starts(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    first = start.tz_convert("UTC").tz_localize(None).to_period("M").to_timestamp().tz_localize("UTC")
    return list(pd.date_range(first, end, freq="MS", inclusive="left")) or [first]


def _fetch_month(month_start: pd.Timestamp, use_cache: bool) -> pd.DataFrame:
    month_end = month_start + pd.offsets.MonthBegin(1)
    cache_path = config.RAW_LOAD_CHUNKS_DIR / f"load_{month_start:%Y-%m}.parquet"
    cached = read_cached(cache_path, month_end, use_cache)
    if cached is not None:
        return cached

    logger.info("Descargando demanda %s", f"{month_start:%Y-%m}")
    # Energy-Charts interpreta las fechas en hora local: se pide un día de margen a cada lado
    # y luego se recorta en UTC.
    params = {
        "country": config.COUNTRY,
        "start": (month_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        "end": month_end.strftime("%Y-%m-%d"),
    }
    raw = parse_load_response(get_json(config.ENERGY_CHARTS_URL, params))
    raw = raw[(raw.index >= month_start) & (raw.index < month_end)]
    write_cache(raw, cache_path)
    return raw


def fetch_load(start: str | pd.Timestamp, end: str | pd.Timestamp, use_cache: bool = True) -> pd.DataFrame:
    """Demanda horaria en [start, end) con columna `load_mw` e índice `time` (UTC)."""
    start, end = to_utc(start), to_utc(end)
    chunks = [_fetch_month(m, use_cache) for m in _month_starts(start, end)]
    raw = pd.concat(chunks)
    raw = raw[(raw.index >= start) & (raw.index < end)]
    return to_hourly(raw)
