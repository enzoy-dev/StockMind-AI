from pathlib import Path
import tempfile
import unittest
from stockmind.storage import Store
from stockmind.data import DataError


class TestStockTracking(unittest.TestCase):
    def test_snapshot_comparacao_e_correcao_sem_mudar_projecao(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "db.sqlite3")
            result = {
                "previsoes": [{"sku": "A", "data": "2026-01-02", "previsao": 5}],
                "saldos": [{"sku": "A", "data": "2026-01-02", "saldo_estimado": -5}],
            }
            run = store.save_run(
                result, [{"sku": "A", "data": "2026-01-01", "vendas": 1}]
            )
            self.assertIsNone(store.compare_stock_run(run)["resumo"][0]["mae_saldo"])
            store.save_stock_actuals(
                [{"sku": "A", "data": "2026-01-02", "estoque_real": 3}]
            )
            comparison = store.compare_stock_run(run)
            self.assertEqual(
                comparison["comparacoes"][0]["estoque_fisico_projetado"], 0
            )
            self.assertEqual(comparison["resumo"][0]["mae_saldo"], 3)
            store.save_stock_actuals(
                [{"sku": "A", "data": "2026-01-02", "estoque_real": 1}]
            )
            self.assertEqual(
                store.compare_stock_run(run)["resumo"][0]["dias_comparados"], 1
            )
            self.assertEqual(store.get_run(run)["resultado"], result)
            with self.assertRaises(DataError):
                store.save_stock_actuals(
                    [
                        {"sku": "A", "data": "2026-01-03", "estoque_real": 2},
                        {"sku": "B", "data": "2026-01-03", "estoque_real": -1},
                    ]
                )
            with store._connection() as conn:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM stock_actuals").fetchone()[0], 1
                )
            store.close()
