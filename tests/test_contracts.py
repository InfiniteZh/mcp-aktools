import importlib.util
import pathlib
import unittest

import pandas as pd


def load_contracts_module():
    root = pathlib.Path(__file__).resolve().parents[1]
    path = root / "mcp_aktools" / "contracts.py"
    spec = importlib.util.spec_from_file_location("mcp_aktools.contracts", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ResponseContractTests(unittest.TestCase):
    def test_success_response_contains_expected_envelope_fields(self):
        contracts = load_contracts_module()
        response = contracts.ok_response("snapshot", {"now": "2026-04-14T12:00:00+08:00"})

        self.assertTrue(response["ok"])
        self.assertEqual(response["kind"], "snapshot")
        self.assertEqual(response["data"], {"now": "2026-04-14T12:00:00+08:00"})
        self.assertIsNone(response["error"])
        self.assertIn("generated_at", response["meta"])

    def test_dataframe_rows_are_normalized_to_python_values(self):
        contracts = load_contracts_module()
        frame = pd.DataFrame([{"name": "A", "value": 1.5, "missing": pd.NA}])

        rows = contracts.dataframe_rows(frame)

        self.assertEqual(rows, [{"name": "A", "value": 1.5, "missing": None}])

    def test_news_response_uses_news_list_shape(self):
        contracts = load_contracts_module()

        response = contracts.news_list_response(
            symbol="BTC",
            items=[{"title": "Headline", "content": "Body"}],
            source="eastmoney",
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["kind"], "news_list")
        self.assertEqual(response["data"]["symbol"], "BTC")
        self.assertEqual(response["data"]["items"][0]["title"], "Headline")
        self.assertEqual(response["meta"]["source"], "eastmoney")
        self.assertEqual(response["meta"]["count"], 1)

    def test_table_response_preserves_columns_and_count(self):
        contracts = load_contracts_module()
        frame = pd.DataFrame([{"代码": "600519", "名称": "贵州茅台"}])

        response = contracts.table_response(
            name="limit_up_pool",
            frame=frame,
            source="akshare",
        )

        self.assertEqual(response["kind"], "table")
        self.assertEqual(response["data"]["name"], "limit_up_pool")
        self.assertEqual(response["data"]["columns"], ["代码", "名称"])
        self.assertEqual(response["data"]["rows"], [{"代码": "600519", "名称": "贵州茅台"}])
        self.assertEqual(response["meta"]["count"], 1)

    def test_error_response_has_stable_shape(self):
        contracts = load_contracts_module()

        response = contracts.error_response(
            kind="search_result",
            code="NOT_FOUND",
            message="No match found",
            source="akshare",
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["kind"], "search_result")
        self.assertIsNone(response["data"])
        self.assertEqual(response["error"]["code"], "NOT_FOUND")
        self.assertEqual(response["meta"]["source"], "akshare")


if __name__ == "__main__":
    unittest.main()
