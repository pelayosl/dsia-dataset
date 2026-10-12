"""Descarga real de 2 días de ambas APIs. Ejecutar con: uv run pytest -m integration"""

import pandas as pd
import pytest

from src import config
from src.load_client import fetch_load
from src.weather_client import fetch_weather

pytestmark = pytest.mark.integration

START, END = "2024-06-01", "2024-06-03"


def test_fetch_load_real():
    df = fetch_load(START, END, use_cache=False)
    assert list(df.columns) == ["load_mw"]
    assert len(df) == 48
    assert str(df.index.tz) == "UTC"
    assert df["load_mw"].between(15000, 50000).all()


def test_fetch_weather_real():
    df = fetch_weather(START, END, use_cache=False)
    assert list(df.columns) == config.WEATHER_VARIABLES
    assert len(df) == 48
    assert df.index[0] == pd.Timestamp(START, tz="UTC")
    assert df["temperature_2m"].between(-20, 50).all()
    assert df["relative_humidity_2m"].between(0, 100).all()
    assert (df[["wind_speed_10m", "shortwave_radiation", "precipitation"]] >= 0).all().all()
