import numpy as np
import pandas as pd

from src import config
from src.weather_client import parse_open_meteo, weighted_mean


def city_frame(value: float, hours: int = 3) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=hours, freq="h", tz="UTC", name="time")
    return pd.DataFrame({v: np.full(hours, value) for v in config.WEATHER_VARIABLES}, index=index)


def test_weighted_mean_uses_population_weights():
    weights = {c: v["weight"] for c, v in config.CITIES.items()}
    frames = {city: city_frame(float(i)) for i, city in enumerate(config.CITIES)}
    expected = sum(i * weights[c] for i, c in enumerate(config.CITIES))
    result = weighted_mean(frames, weights)
    assert list(result.columns) == config.WEATHER_VARIABLES
    assert np.allclose(result.to_numpy(), expected)


def test_weights_sum_to_one():
    assert np.isclose(sum(c["weight"] for c in config.CITIES.values()), 1.0)


def test_weighted_mean_is_nan_when_a_city_is_missing():
    weights = {"a": 0.5, "b": 0.5}
    b = city_frame(2.0)
    b.iloc[1] = np.nan
    result = weighted_mean({"a": city_frame(1.0), "b": b}, weights)
    assert result.iloc[1].isna().all()
    assert np.allclose(result.iloc[[0, 2]].to_numpy(), 1.5)


def test_parse_open_meteo_utc_index():
    payload = {"hourly": {"time": ["2024-01-01T00:00", "2024-01-01T01:00"],
                          **{v: [1.0, None] for v in config.WEATHER_VARIABLES}}}
    df = parse_open_meteo(payload)
    assert str(df.index.tz) == "UTC"
    assert df.index[0] == pd.Timestamp("2024-01-01T00:00", tz="UTC")
    assert df.iloc[1].isna().all()
