from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return normalize_mapping(value)
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_value(item) for item in value]
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item"):
        try:
            return normalize_value(value.item())
        except Exception:
            pass
    return value


def normalize_mapping(item: dict[str, Any]) -> dict[str, Any]:
    return {str(key): normalize_value(value) for key, value in item.items()}


def dataframe_rows(frame: pd.DataFrame, *, limit: int | None = None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    data = frame
    if limit is not None:
        data = data.head(int(limit))
    return [normalize_mapping(row) for row in data.to_dict(orient="records")]


def frame_columns(frame: pd.DataFrame) -> list[str]:
    if frame is None or frame.empty:
        return list(frame.columns) if frame is not None else []
    return [str(column) for column in frame.columns]


def ok_response(kind: str, data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "kind": kind,
        "data": data,
        "error": None,
        "meta": {"generated_at": now_iso(), **normalize_mapping(meta or {})},
    }


def error_response(
    kind: str,
    code: str,
    message: str,
    source: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_meta = dict(meta or {})
    if source:
        merged_meta.setdefault("source", source)
    return {
        "ok": False,
        "kind": kind,
        "data": None,
        "error": {
            "code": code,
            "message": message,
        },
        "meta": {"generated_at": now_iso(), **normalize_mapping(merged_meta)},
    }


def search_result_response(
    query: str,
    market: str | None,
    match: dict[str, Any] | None,
    *,
    source: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "query": query,
        "market": market,
        "match": normalize_mapping(match or {}) if match else None,
    }
    merged_meta = {"source": source, "count": 1 if match else 0, **(meta or {})}
    return ok_response("search_result", payload, merged_meta)


def entity_profile_response(
    symbol: str,
    market: str | None,
    profile: dict[str, Any],
    *,
    source: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "symbol": symbol,
        "market": market,
        "profile": normalize_mapping(profile),
    }
    merged_meta = {"source": source, "count": len(payload["profile"]), **(meta or {})}
    return ok_response("entity_profile", payload, merged_meta)


def timeseries_response(
    symbol: str,
    items: list[dict[str, Any]],
    *,
    source: str,
    market: str | None = None,
    interval: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "symbol": symbol,
        "market": market,
        "interval": interval,
        "items": [normalize_mapping(item) for item in items],
    }
    merged_meta = {"source": source, "count": len(items), **(meta or {})}
    return ok_response("timeseries", payload, merged_meta)


def table_response(
    name: str,
    frame: pd.DataFrame,
    *,
    source: str,
    meta: dict[str, Any] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    rows = dataframe_rows(frame, limit=limit)
    payload = {
        "name": name,
        "columns": frame_columns(frame),
        "rows": rows,
    }
    merged_meta = {"source": source, "count": len(rows), **(meta or {})}
    return ok_response("table", payload, merged_meta)


def news_list_response(
    symbol: str | None,
    items: list[dict[str, Any]],
    *,
    source: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "symbol": symbol,
        "items": [normalize_mapping(item) for item in items],
    }
    merged_meta = {"source": source, "count": len(items), **(meta or {})}
    return ok_response("news_list", payload, merged_meta)


def snapshot_response(
    name: str,
    snapshot: dict[str, Any],
    *,
    source: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "snapshot": normalize_mapping(snapshot),
    }
    merged_meta = {"source": source, **(meta or {})}
    return ok_response("snapshot", payload, merged_meta)


def advice_response(
    advice: dict[str, Any],
    *,
    source: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_meta = {"source": source, **(meta or {})}
    return ok_response("advice", normalize_mapping(advice), merged_meta)


def profile_from_frame(frame: pd.DataFrame) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {}
    columns = list(frame.columns)
    if len(columns) == 2:
        key_column, value_column = columns
        return {
            str(row[key_column]): normalize_value(row[value_column])
            for _, row in frame.iterrows()
        }
    if len(frame) == 1:
        return normalize_mapping(frame.iloc[0].to_dict())
    return {"rows": dataframe_rows(frame)}
