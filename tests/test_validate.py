import numpy as np
import pandas as pd

from src.validate import interpolate_short_gaps, quality_report


def hourly(values, start="2024-01-01") -> pd.Series:
    index = pd.date_range(start, periods=len(values), freq="h", tz="UTC", name="time")
    return pd.Series(values, index=index, dtype=float)


def test_interpolates_only_gaps_up_to_3_hours():
    nan = np.nan
    s = hourly([1, nan, nan, nan, 5, 6, nan, nan, nan, nan, 11])
    filled, mask = interpolate_short_gaps(s, max_gap=3)
    assert filled.iloc[1:4].tolist() == [2, 3, 4]
    assert mask.iloc[1:4].all()
    assert filled.iloc[6:10].isna().all()  # hueco de 4 h: se deja NaN
    assert not mask.iloc[6:10].any()
    assert mask.sum() == 3


def test_does_not_extrapolate_edges():
    s = hourly([np.nan, 2, 3, np.nan])
    filled, mask = interpolate_short_gaps(s)
    assert np.isnan(filled.iloc[0]) and np.isnan(filled.iloc[-1])
    assert not mask.any()


def test_quality_report_detects_gaps_and_duplicates():
    s = hourly(np.full(10, 30000.0))
    s.iloc[3:5] = np.nan
    df = s.to_frame("load_mw")
    df = df.drop(df.index[7])                 # timestamp ausente
    df = pd.concat([df, df.iloc[[0]]])        # timestamp duplicado
    report = quality_report(df)

    assert report["duplicated_timestamps"] == 1
    assert report["index_unique"] is False
    assert report["index_monotonic_increasing"] is False
    assert report["expected_hours"] == 10
    assert report["present_hours"] == 9
    assert report["missing_timestamps"] == [
        {"start": "2024-01-01T07:00:00+00:00", "end": "2024-01-01T07:00:00+00:00", "hours": 1}
    ]
    assert [g["hours"] for g in report["gaps"]["load_mw"]] == [2, 1]


def test_quality_report_out_of_range():
    df = hourly([30000, 10000, 60000]).to_frame("load_mw")
    report = quality_report(df)
    assert report["out_of_range"]["load_mw"]["count"] == 2
