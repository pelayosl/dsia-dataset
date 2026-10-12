"""Descarga de meteorología desde Open-Meteo y media nacional ponderada por población."""

import logging
from typing import Any

import pandas as pd

from src import config
from src.http_utils import get_json, read_cached, to_utc, write_cache

logger = logging.getLogger(__name__)


def parse_open_meteo(payload: dict[str, Any]) -> pd.DataFrame:
    """Convierte el bloque `hourly` de Open-Meteo (pedido con timezone=UTC) en un DataFrame con índice UTC."""
    hourly = payload.get("hourly", {})
    index = pd.DatetimeIndex(pd.to_datetime(hourly.get("time", [])).tz_localize("UTC"), name="time")
    data = {var: pd.to_numeric(pd.Series(hourly.get(var, [None] * len(index))), errors="coerce").to_numpy()
            for var in config.WEATHER_VARIABLES}
    return pd.DataFrame(data, index=index)


def weighted_mean(city_frames: dict[str, pd.DataFrame], weights: dict[str, float]) -> pd.DataFrame:
    """Media ponderada por ciudad. Si falta alguna ciudad en una hora, el resultado es NaN (no se oculta el hueco)."""
    total = sum(weights[city] for city in city_frames)
    combined = pd.concat(city_frames, axis=1)  # columnas (ciudad, variable)
    result = sum(combined[city] * (weights[city] / total) for city in city_frames)
    result.index.name = "time"
    return result


def _year_chunks(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    chunks = []
    for year in range(start.year, end.year + 1):
        chunk_start = max(start, pd.Timestamp(f"{year}-01-01", tz="UTC"))
        chunk_end = min(end, pd.Timestamp(f"{year + 1}-01-01", tz="UTC"))
        if chunk_start < chunk_end:
            chunks.append((chunk_start, chunk_end))
    return chunks


def _base_params(city: str) -> dict[str, Any]:
    coords = config.CITIES[city]
    return {
        "latitude": coords["lat"],
        "longitude": coords["lon"],
        "hourly": ",".join(config.WEATHER_VARIABLES),
        "timezone": config.OPEN_METEO_TIMEZONE,
    }


def _fetch_archive_chunk(city: str, chunk_start: pd.Timestamp, chunk_end: pd.Timestamp, use_cache: bool) -> pd.DataFrame:
    last_day = chunk_end - pd.Timedelta(hours=1)  # end_date es inclusivo
    name = f"weather_{city}_{chunk_start:%Y%m%d}_{last_day:%Y%m%d}.parquet"
    cache_path = config.RAW_WEATHER_CHUNKS_DIR / name
    cached = read_cached(cache_path, chunk_end, use_cache)
    if cached is not None:
        return cached

    logger.info("Descargando meteorología (archive) %s %s → %s", city, f"{chunk_start:%Y-%m-%d}", f"{last_day:%Y-%m-%d}")
    params = _base_params(city) | {
        "start_date": chunk_start.strftime("%Y-%m-%d"),
        "end_date": last_day.strftime("%Y-%m-%d"),
    }
    df = parse_open_meteo(get_json(config.OPEN_METEO_ARCHIVE_URL, params))
    write_cache(df, cache_path)
    return df


def _fetch_recent(city: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Últimos días desde el endpoint forecast (`past_days`) para cubrir el retraso del archive."""
    today = pd.Timestamp.now(tz="UTC").normalize()
    recent_start = max(start, today - pd.Timedelta(days=config.FORECAST_LOOKBACK_DAYS))
    if recent_start >= end:
        return pd.DataFrame(columns=config.WEATHER_VARIABLES, index=pd.DatetimeIndex([], tz="UTC", name="time"))
    past_days = min(config.FORECAST_MAX_PAST_DAYS, (today - recent_start.normalize()).days + 1)
    logger.info("Descargando meteorología (forecast, past_days=%d) %s", past_days, city)
    params = _base_params(city) | {"past_days": past_days, "forecast_days": 1}
    return parse_open_meteo(get_json(config.OPEN_METEO_FORECAST_URL, params))


def fetch_city(city: str, start: pd.Timestamp, end: pd.Timestamp, use_cache: bool = True) -> pd.DataFrame:
    """Meteorología horaria de una ciudad en [start, end): archive, con forecast rellenando lo que falte."""
    today = pd.Timestamp.now(tz="UTC").normalize()
    archive_end = min(end, today + pd.Timedelta(days=1))
    frames = [_fetch_archive_chunk(city, s, e, use_cache) for s, e in _year_chunks(start, archive_end)]
    archive = pd.concat(frames) if frames else parse_open_meteo({})
    recent = _fetch_recent(city, start, end)
    df = archive.combine_first(recent) if not recent.empty else archive  # el archive tiene prioridad
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df[(df.index >= start) & (df.index < end)]


def fetch_weather(start: str | pd.Timestamp, end: str | pd.Timestamp, use_cache: bool = True) -> pd.DataFrame:
    """Meteorología nacional horaria en [start, end): media ponderada de las ciudades de `config.CITIES`."""
    start, end = to_utc(start), to_utc(end)
    city_frames = {city: fetch_city(city, start, end, use_cache) for city in config.CITIES}
    weights = {city: c["weight"] for city, c in config.CITIES.items()}
    return weighted_mean(city_frames, weights)
