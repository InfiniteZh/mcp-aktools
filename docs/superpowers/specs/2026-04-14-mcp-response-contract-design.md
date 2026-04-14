# MCP Response Contract Design

**Date:** 2026-04-14

**Scope:** Refactor all public MCP tools in `mcp_aktools` to return a unified AI-friendly response envelope instead of mixed plain-text, CSV, and ad-hoc dict payloads.

## Goals

- Make every MCP tool response structurally consistent for AI consumers.
- Distinguish success, empty results, and failures with stable semantics.
- Keep the contract simple enough for prompt-driven agents to learn quickly.
- Avoid over-modeling each tool as an independent API product.

## Non-Goals

- Preserve backwards compatibility with existing text/CSV responses.
- Rebuild every upstream dataset into a bespoke domain model.
- Change tool inputs in a significant way.

## Contract

All MCP tools return the same envelope:

```json
{
  "ok": true,
  "kind": "timeseries",
  "data": {},
  "error": null,
  "meta": {
    "source": "akshare",
    "generated_at": "2026-04-14T12:00:00+08:00"
  }
}
```

Failure responses use:

```json
{
  "ok": false,
  "kind": "timeseries",
  "data": null,
  "error": {
    "code": "NOT_FOUND",
    "message": "No data found for symbol 600519 in market sh"
  },
  "meta": {
    "source": "akshare",
    "generated_at": "2026-04-14T12:00:00+08:00"
  }
}
```

## Kinds

The server supports a small set of data shapes:

- `search_result`
- `entity_profile`
- `timeseries`
- `table`
- `news_list`
- `snapshot`
- `advice`

## Tool Mapping

- `search` -> `search_result`
- `stock_info` -> `entity_profile`
- `stock_prices` -> `timeseries`
- `stock_news` -> `news_list`
- `stock_indicators_a` -> `table`
- `stock_indicators_hk` -> `table`
- `stock_indicators_us` -> `table`
- `get_current_time` -> `snapshot`
- `stock_zt_pool_em` -> `table`
- `stock_zt_pool_strong_em` -> `table`
- `stock_lhb_ggtj_sina` -> `table`
- `stock_sector_fund_flow_rank` -> `table`
- `stock_news_global` -> `news_list`
- `okx_prices` -> `timeseries`
- `okx_loan_ratios` -> `timeseries`
- `okx_taker_volume` -> `timeseries`
- `binance_ai_report` -> `advice`
- `trading_suggest` -> `advice`

## Data Shape Rules

### `search_result`

`data` contains:

- `query`
- `market`
- `match`

`match` is either `null` or an object with normalized symbol/name fields.

### `entity_profile`

`data` contains:

- `symbol`
- `market`
- `profile`

`profile` is a normalized key-value object.

### `timeseries`

`data` contains:

- `symbol`
- `market`
- `interval`
- `items`

`items` is a list of objects. Core fields are stable: `time`, plus domain-specific numeric fields such as `open`, `high`, `low`, `close`, `volume`.

### `table`

`data` contains:

- `name`
- `columns`
- `rows`

`rows` is a list of row objects keyed by normalized column names.

### `news_list`

`data` contains:

- `symbol`
- `items`

Each item should preserve as much structure as possible: `title`, `content`, `source`, `published_at`, `url`.

### `snapshot`

`data` contains a small object representing the current state, such as current time and recent trade dates.

### `advice`

`data` contains opinionated analysis fields such as:

- `symbol`
- `action`
- `score`
- `reason`

## Error Semantics

- Empty but valid results return `ok: true` with empty collections and `meta.count: 0`.
- Lookup misses return `ok: false` with `error.code: "NOT_FOUND"`.
- Upstream fetch errors return `ok: false` with `error.code: "UPSTREAM_ERROR"`.
- Invalid inputs return `ok: false` with `error.code: "INVALID_ARGUMENT"`.

## Implementation Notes

- Extract envelope builders and normalization helpers into focused modules.
- Keep public tool functions thin: fetch, normalize, wrap.
- Replace string/CSV formatting with normalized dict payloads.
- Normalize pandas output with null-safe conversion to plain Python values.
- Preserve source and count metadata for downstream agent use.

## Testing Strategy

- Add unit tests for response envelope builders and normalization helpers.
- Add focused tests for the main kind builders: `table`, `timeseries`, `news_list`, `snapshot`, `advice`.
- Prefer tests that verify semantic shape over raw textual formatting.
