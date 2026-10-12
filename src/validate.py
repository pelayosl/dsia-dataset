"""Limpieza (rejilla horaria + interpolación de huecos cortos) y comprobaciones de calidad.

Nunca se elimina ningún dato: los problemas se marcan con columnas indicadoras o se reportan.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src import config

logger = logging.getLogger(__name__)


def hourly_grid(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """Rejilla horaria continua en UTC, ambos extremos incluidos."""
    return pd.date_range(start, end, freq=config.FREQ, tz="UTC", name="time")


def to_grid(df: pd.DataFrame, grid: pd.DatetimeIndex) -> pd.DataFrame:
    """Reindexa a la rejilla para que los huecos aparezcan explícitamente como NaN."""
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.reindex(grid)


def nan_runs(mask: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    """Tramos consecutivos donde `mask` es True: (inicio, fin, número de horas)."""
    if not mask.any():
        return []
    run_id = (mask != mask.shift()).cumsum()
    runs = []
    for _, block in mask[mask].groupby(run_id[mask]):
        runs.append((block.index[0], block.index[-1], len(block)))
    return runs


def interpolate_short_gaps(series: pd.Series, max_gap: int = config.MAX_INTERPOLATION_GAP_HOURS) -> tuple[pd.Series, pd.Series]:
    """Interpola linealmente solo los huecos interiores de `max_gap` horas o menos.

    Devuelve la serie rellenada y una máscara booleana con los valores interpolados.
    Los huecos más largos, y los de los extremos de la serie, se dejan como NaN.
    """
    isna = series.isna()
    fillable = pd.Series(False, index=series.index)
    for start, end, length in nan_runs(isna):
        interior = start != series.index[0] and end != series.index[-1]
        if length <= max_gap and interior:
            fillable.loc[start:end] = True
    interpolated = series.interpolate(method="time", limit_area="inside")
    filled = series.where(~fillable, interpolated)
    return filled, fillable & filled.notna()


def clean_load(load: pd.DataFrame, grid: pd.DatetimeIndex) -> pd.DataFrame:
    df = to_grid(load[["load_mw"]], grid)
    df["load_mw"], mask = interpolate_short_gaps(df["load_mw"])
    df["load_interpolated"] = mask.astype(int)
    return df


def clean_weather(weather: pd.DataFrame, grid: pd.DatetimeIndex) -> pd.DataFrame:
    df = to_grid(weather[config.WEATHER_VARIABLES], grid)
    any_interpolated = pd.Series(False, index=df.index)
    for column in config.WEATHER_VARIABLES:
        df[column], mask = interpolate_short_gaps(df[column])
        any_interpolated |= mask
    df["weather_interpolated"] = any_interpolated.astype(int)
    return df


def out_of_range(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Valores fuera de los rangos de `config.VALUE_RANGES` (se reportan, no se borran)."""
    report: dict[str, dict[str, Any]] = {}
    for column, (low, high) in config.VALUE_RANGES.items():
        if column not in df:
            continue
        values = df[column]
        bad = pd.Series(False, index=df.index)
        if low is not None:
            bad |= values < low
        if high is not None:
            bad |= values > high
        examples = values[bad].head(config.OUT_OF_RANGE_EXAMPLES)
        report[column] = {
            "range": [low, high],
            "count": int(bad.sum()),
            "examples": [{"time": _iso(t), "value": float(v)} for t, v in examples.items()],
        }
    return report


def _iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).isoformat()


def _gaps(mask: pd.Series) -> list[dict[str, Any]]:
    return [{"start": _iso(s), "end": _iso(e), "hours": n} for s, e, n in nan_runs(mask)]


def quality_report(df: pd.DataFrame) -> dict[str, Any]:
    """Informe de calidad de un DataFrame con índice horario UTC."""
    index = df.index
    duplicated = int(index.duplicated().sum())
    unique = df[~index.duplicated(keep="last")].sort_index()
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": int(len(df)),
        "start": _iso(unique.index.min()) if len(unique) else None,
        "end": _iso(unique.index.max()) if len(unique) else None,
        "index_unique": duplicated == 0,
        "index_monotonic_increasing": bool(index.is_monotonic_increasing),
        "duplicated_timestamps": duplicated,
    }
    if not len(unique):
        return report

    grid = hourly_grid(unique.index.min(), unique.index.max())
    full = unique.reindex(grid)
    missing_index = ~grid.isin(unique.index)
    report["expected_hours"] = int(len(grid))
    report["present_hours"] = int(len(grid) - missing_index.sum())
    report["missing_timestamps"] = _gaps(pd.Series(missing_index, index=grid))

    gaps: dict[str, list[dict[str, Any]]] = {}
    if "load_mw" in full:
        gaps["load_mw"] = _gaps(full["load_mw"].isna())
    weather_cols = [c for c in config.WEATHER_VARIABLES if c in full]
    if weather_cols:
        gaps["weather"] = _gaps(full[weather_cols].isna().any(axis=1))
    report["gaps"] = gaps

    report["nulls"] = {c: int(n) for c, n in full.isna().sum().items()}
    report["interpolated"] = {c: int(full[c].fillna(0).sum()) for c in ("load_interpolated", "weather_interpolated") if c in full}
    report["out_of_range"] = out_of_range(full)
    if "load_mw" in full:
        missing_pct = 100 * full["load_mw"].isna().mean()
        report["load_missing_pct"] = round(float(missing_pct), 4)
        report["load_missing_ok"] = bool(missing_pct < config.MAX_LOAD_MISSING_PCT)
    return report


def save_report(report: dict[str, Any], path: Path = config.QUALITY_REPORT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Informe de calidad guardado en %s", path)


def report_summary_markdown(report: dict[str, Any]) -> str:
    """Resumen breve del informe en Markdown, para el README."""
    gaps = report.get("gaps", {})
    out_of_range = {c: v["count"] for c, v in report.get("out_of_range", {}).items() if v["count"]}
    interpolated = report.get("interpolated", {})
    lines = [
        f"_Generado: {report['generated_at']}_",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Periodo | {report['start']} → {report['end']} |",
        f"| Filas | {report['rows']:,} |",
        f"| Horas esperadas / presentes | {report.get('expected_hours', 0):,} / {report.get('present_hours', 0):,} |",
        f"| Índice único y creciente | {report['index_unique'] and report['index_monotonic_increasing']} |",
        f"| Horas sin demanda | {report.get('nulls', {}).get('load_mw', 0)} ({report.get('load_missing_pct', 0)} %) |",
        f"| Huecos de demanda > {config.MAX_INTERPOLATION_GAP_HOURS} h | {len(gaps.get('load_mw', []))} |",
        f"| Huecos de meteorología > {config.MAX_INTERPOLATION_GAP_HOURS} h | {len(gaps.get('weather', []))} |",
        f"| Valores interpolados (demanda / meteo) | {interpolated.get('load_interpolated', 0)} / {interpolated.get('weather_interpolated', 0)} |",
        f"| Valores fuera de rango | {out_of_range or 'ninguno'} |",
    ]
    return "\n".join(lines)


def update_readme_summary(report: dict[str, Any], path: Path = config.README_FILE) -> None:
    """Sustituye el bloque entre los marcadores de calidad del README por el resumen del informe."""
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    start, end = config.README_QUALITY_MARKERS
    if start not in text or end not in text:
        logger.warning("El README no tiene los marcadores de calidad; no se actualiza")
        return
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    path.write_text(f"{head}{start}\n{report_summary_markdown(report)}\n{end}{tail}", encoding="utf-8")
    logger.info("Resumen de calidad actualizado en %s", path)
