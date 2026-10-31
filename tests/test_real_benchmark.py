import unittest
import pandas as pd
from scripts.benchmark_retail import prepare


class TestBenchmark(unittest.TestCase):
    def test_selecao_de_sku_nao_usa_volume_futuro(self):
        rows = []
        for day in pd.date_range("2025-01-01", periods=200):
            for sku, quantity in [("11111", 10), ("22222", 1)]:
                rows.append(
                    {
                        "InvoiceNo": "1",
                        "StockCode": sku,
                        "Quantity": quantity,
                        "UnitPrice": 1,
                        "InvoiceDate": day,
                    }
                )
        raw = pd.DataFrame(rows)
        first, meta = prepare(raw, products=1)
        raw.loc[
            (raw.InvoiceDate > pd.Timestamp(meta["corte_selecao_skus"]))
            & raw.StockCode.eq("22222"),
            "Quantity",
        ] = 100000
        second, changed = prepare(raw, products=1)
        self.assertEqual(meta["skus"], changed["skus"])
        self.assertEqual(meta["skus"], ["11111"])
        self.assertNotIn("preco", second.columns)
        self.assertNotIn("disponivel", second.columns)
        self.assertGreater(first.data.min(), raw.InvoiceDate.min())
        self.assertLess(first.data.max(), raw.InvoiceDate.max())
