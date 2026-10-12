"""Utilidades compartidas: peticiones HTTP con reintentos y caché de bloques en parquet."""

import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src import config

logger = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    """Reintenta errores de red, 429 y 5xx; no los 4xx (son errores de la petición)."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        return status == 429 or status >= 500
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))


_exponential = wait_exponential(min=config.HTTP_BACKOFF_MIN, max=config.HTTP_BACKOFF_MAX)


def _wait(retry_state: RetryCallState) -> float:
    """Respeta la cabecera `Retry-After` de un 429; si no la hay, backoff exponencial."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        retry_after = exc.response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after) + 1, config.HTTP_BACKOFF_MAX)
    return _exponential(retry_state)


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(config.HTTP_MAX_ATTEMPTS),
    wait=_wait,
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def get_json(url: str, params: dict[str, Any]) -> Any:
    """GET con timeout y reintentos con backoff exponencial."""
    response = requests.get(url, params=params, timeout=config.HTTP_TIMEOUT)
    response.raise_for_status()
    time.sleep(config.REQUEST_PAUSE_SECONDS)
    return response.json()


def to_utc(value: str | pd.Timestamp) -> pd.Timestamp:
    """Convierte una fecha a Timestamp UTC (las fechas sin zona se interpretan como UTC)."""
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def is_stable(chunk_end: pd.Timestamp) -> bool:
    """Un bloque es definitivo si termina antes de hoy - STABLE_DAYS (sus datos ya no se revisan)."""
    cutoff = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=config.STABLE_DAYS)
    return chunk_end <= cutoff


def read_cached(path: Path, chunk_end: pd.Timestamp, use_cache: bool) -> pd.DataFrame | None:
    """Devuelve el bloque cacheado si existe, se permite la caché y el bloque es definitivo."""
    if use_cache and path.exists() and is_stable(chunk_end):
        logger.debug("Usando caché %s", path)
        return pd.read_parquet(path)
    return None


def write_cache(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
