# MCP Response Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the MCP tools to return a unified response envelope with stable `kind`-based payload shapes for AI consumers.

**Architecture:** Add a dedicated response-contract module for envelope construction and pandas normalization, then migrate each public tool to that module without changing tool inputs. Verify behavior with standard-library unit tests around the response layer and targeted integration checks on tool functions where possible.

**Tech Stack:** Python, pandas, FastMCP, standard-library `unittest`

---

### Task 1: Add response contract helpers

**Files:**
- Create: `mcp_aktools/contracts.py`
- Test: `tests/test_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_success_response_contains_expected_envelope_fields(self):
    response = contracts.ok_response("snapshot", {"now": "2026-04-14T12:00:00+08:00"})
    self.assertTrue(response["ok"])
    self.assertEqual(response["kind"], "snapshot")
    self.assertIsNone(response["error"])
    self.assertIn("generated_at", response["meta"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_contracts.ResponseContractTests.test_success_response_contains_expected_envelope_fields -v`
Expected: FAIL because `mcp_aktools.contracts` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def ok_response(kind, data, meta=None):
    return {
        "ok": True,
        "kind": kind,
        "data": data,
        "error": None,
        "meta": {"generated_at": now_iso(), **(meta or {})},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_contracts.ResponseContractTests.test_success_response_contains_expected_envelope_fields -v`
Expected: PASS

### Task 2: Add pandas normalization helpers

**Files:**
- Modify: `mcp_aktools/contracts.py`
- Test: `tests/test_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_dataframe_rows_are_normalized_to_python_values(self):
    frame = pd.DataFrame([{"name": "A", "value": 1.5, "missing": pd.NA}])
    rows = contracts.dataframe_rows(frame)
    self.assertEqual(rows, [{"name": "A", "value": 1.5, "missing": None}])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_contracts.ResponseContractTests.test_dataframe_rows_are_normalized_to_python_values -v`
Expected: FAIL because `dataframe_rows` is not implemented.

- [ ] **Step 3: Write minimal implementation**

```python
def dataframe_rows(frame):
    return [{key: normalize_value(value) for key, value in row.items()} for row in frame.to_dict(orient="records")]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_contracts.ResponseContractTests.test_dataframe_rows_are_normalized_to_python_values -v`
Expected: PASS

### Task 3: Migrate public tools to the contract helpers

**Files:**
- Modify: `mcp_aktools/__init__.py`
- Modify: `mcp_aktools/contracts.py`
- Test: `tests/test_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_news_response_uses_news_list_shape(self):
    response = contracts.news_list_response(
        symbol="BTC",
        items=[{"title": "Headline", "content": "Body"}],
        source="eastmoney",
    )
    self.assertEqual(response["kind"], "news_list")
    self.assertEqual(response["data"]["symbol"], "BTC")
    self.assertEqual(response["meta"]["count"], 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_contracts.ResponseContractTests.test_news_response_uses_news_list_shape -v`
Expected: FAIL because `news_list_response` is not implemented.

- [ ] **Step 3: Write minimal implementation**

```python
def news_list_response(symbol, items, source, meta=None):
    data = {"symbol": symbol, "items": items}
    merged = {"source": source, "count": len(items), **(meta or {})}
    return ok_response("news_list", data, merged)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_contracts.ResponseContractTests.test_news_response_uses_news_list_shape -v`
Expected: PASS

- [ ] **Step 5: Refactor tool functions**

Update each `@mcp.tool` function to return one of the contract helpers instead of text, CSV, or ad-hoc dicts.

- [ ] **Step 6: Run targeted verification**

Run: `python3 -m unittest tests.test_contracts -v`
Expected: PASS

### Task 4: Document the breaking change

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add response contract section**

Document the unified envelope, the supported `kind` values, and the fact that text/CSV outputs were replaced by structured JSON responses.

- [ ] **Step 2: Verify docs update**

Run: `rg -n "Response Contract|kind|ok" README.md`
Expected: output shows the new contract section.
