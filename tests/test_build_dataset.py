import pandas as pd

from src import config
from src.build_dataset import add_calendar, replace_tail, to_csv_frame


def frame(start: str, end: str) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="h", tz="UTC", name="time")
    return pd.DataFrame(index=index)


def test_time_local_on_23_hour_day():
    df = add_calendar(frame("2024-03-30T23:00", "2024-03-31T21:00"))  # 31-mar local completo
    local = df["time_local"]
    assert (local.dt.date == pd.Timestamp("2024-03-31").date()).sum() == 23
    assert local.iloc[1].isoformat() == "2024-03-31T01:00:00+01:00"
    assert local.iloc[2].isoformat() == "2024-03-31T03:00:00+02:00"  # salta las 02:00


def test_time_local_on_25_hour_day():
    df = add_calendar(frame("2024-10-26T22:00", "2024-10-27T22:00"))  # 27-oct local completo
    local = df["time_local"]
    assert (local.dt.date == pd.Timestamp("2024-10-27").date()).sum() == 25
    assert local.iloc[2].isoformat() == "2024-10-27T02:00:00+02:00"
    assert local.iloc[3].isoformat() == "2024-10-27T02:00:00+01:00"  # las 02:00 se repiten


def test_holiday_and_covid_flags_use_local_date():
    df = add_calendar(frame("2019-12-31T22:00", "2020-01-01T00:00"))
    # 22:00 UTC del 31-dic = 23:00 local (no festivo); 23:00 UTC = 00:00 local del 1-ene (festivo)
    assert df["is_holiday"].tolist() == [0, 1, 1]
    covid = add_calendar(frame("2020-03-13T22:00", "2020-03-13T23:00"))
    assert covid["covid_flag"].tolist() == [0, 1]


def test_csv_frame_columns_and_iso_format():
    df = add_calendar(frame("2024-01-01T00:00", "2024-01-01T01:00"))
    for col in config.CSV_COLUMNS:
        if col not in df:
            df[col] = 0
    out = to_csv_frame(df)
    assert list(out.columns) == config.CSV_COLUMNS
    assert out["time_utc"].iloc[0] == "2024-01-01T00:00:00+00:00"


def test_replace_tail_is_idempotent():
    existing = frame("2024-01-01", "2024-01-05").assign(load_mw=1.0)
    new = frame("2024-01-04", "2024-01-06").assign(load_mw=2.0)
    since = pd.Timestamp("2024-01-04", tz="UTC")
    once = replace_tail(existing, new, since)
    twice = replace_tail(once, new, since)
    pd.testing.assert_frame_equal(once, twice)
    assert once.index.is_unique
    assert (once.loc[once.index >= since, "load_mw"] == 2.0).all()
