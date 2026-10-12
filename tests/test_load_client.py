import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.load_client import parse_load_response, to_hourly

FIXTURE = Path(__file__).parent / "fixtures" / "energy_charts_es_sample.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_extracts_load_with_nan_and_utc_index():
    raw = parse_load_response(load_fixture())
    assert list(raw.columns) == ["load_mw"]
    assert str(raw.index.tz) == "UTC"
    assert raw.index[0] == pd.Timestamp("2024-03-29T23:00", tz="UTC")
    assert raw["load_mw"].isna().sum() == 5  # los null del JSON pasan a NaN


def test_to_hourly_resamples_15min_to_mean():
    hourly = to_hourly(parse_load_response(load_fixture()))
    assert len(hourly) == 3
    assert (hourly.index.to_series().diff().dropna() == pd.Timedelta(hours=1)).all()
    assert hourly["load_mw"].iloc[0] == np.mean([22456.0, 22376.0, 22116.0, 21596.0])
    assert np.isclose(hourly["load_mw"].iloc[1], np.mean([21280.0, 20636.0, 20228.0]))  # ignora el null
    assert np.isnan(hourly["load_mw"].iloc[2])  # hora entera sin datos → NaN


def test_to_hourly_drops_duplicates_and_sorts():
    raw = parse_load_response(load_fixture())
    shuffled = pd.concat([raw.iloc[4:], raw.iloc[:4], raw.iloc[:2]])
    pd.testing.assert_frame_equal(to_hourly(shuffled), to_hourly(raw))


def test_missing_load_series_gives_nan():
    payload = load_fixture()
    payload["production_types"] = [p for p in payload["production_types"] if p["name"] != "Load"]
    assert parse_load_response(payload)["load_mw"].isna().all()
