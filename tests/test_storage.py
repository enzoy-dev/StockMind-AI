from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest

import pandas as pd

from stockmind.storage import Store


class TestStore(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "stockmind.sqlite3")
        self.sales = pd.DataFrame(
            [
                {"sku": "001", "data": pd.Timestamp("2026-01-01"), "vendas": 2},
                {"sku": "001", "data": pd.Timestamp("2026-01-02"), "vendas": 3},
            ]
        )
        self.result = {
            "previsoes": [
                {
                    "sku": "001",
                    "data": "2026-01-03",
                    "previsao": 10,
                    "limite_inferior": 8,
                    "limite_superior": 12,
                    "modelo": "referencia",
                },
                {
                    "sku": "001",
                    "data": "2026-01-04",
                    "previsao": 20,
                    "limite_inferior": 18,
                    "limite_superior": 22,
                    "modelo": "referencia",
                },
            ],
            "metricas": [],
            "saldos": [],
            "recomendacoes": [],
            "qualidade": [],
        }
        self.suppliers = pd.DataFrame(
            [{"fornecedor_id": "F1", "nome": "Fornecedor", "prazo_dias": 2}]
        )
        self.products = pd.DataFrame(
            [
                {
                    "sku": "001",
                    "nome": "Produto",
                    "fornecedor_id": "F1",
                    "estoque_atual": 10,
                    "estoque_seguranca": 5,
                    "pedido_minimo": 6,
                    "multiplo_compra": 3,
                }
            ]
        )

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_snapshot_is_immutable_while_actuals_can_be_corrected(self):
        run_id = self.store.save_run(
            self.result, self.sales, parametros={"horizonte": 2}
        )
        snapshot = deepcopy(self.store.get_run(run_id))
        before = self.store.compare_run(run_id)
        self.assertEqual(before["resumo"][0]["periodos_observados"], 0)
        self.assertIsNone(before["resumo"][0]["mae"])
        self.assertTrue(
            all(row["vendas_reais"] is None for row in before["comparacoes"])
        )

        self.store.save_actuals([{"sku": "001", "data": "2026-01-03", "vendas": 8}])
        partial = self.store.compare_run(run_id)
        self.assertEqual(partial["resumo"][0]["mae"], 2)
        self.assertEqual(partial["resumo"][0]["status"], "parcial")
        self.assertIsNone(partial["comparacoes"][1]["vendas_reais"])

        self.store.save_actuals(
            [
                {"sku": "001", "data": "2026-01-03", "vendas": 10},
                {"sku": "001", "data": "2026-01-04", "vendas": 0},
            ]
        )
        complete = self.store.compare_run(run_id)["resumo"][0]
        self.assertEqual(complete["periodos_observados"], 2)
        self.assertEqual(complete["mae"], 10)
        self.assertEqual(complete["vies"], 10)
        self.assertEqual(complete["wape"], 200)
        self.assertEqual(complete["cobertura_faixa"], 50)
        self.assertEqual(complete["status"], "completo")
        self.assertEqual(self.store.get_run(run_id), snapshot)

    def test_catalog_replacement_rolls_back_on_invalid_reference(self):
        self.store.save_planning(self.products, self.suppliers, origem="2026-01-02")
        saved = self.store.get_planning()
        invalid = self.products.assign(fornecedor_id="INEXISTENTE")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_planning(invalid, self.suppliers)
        self.assertEqual(self.store.get_planning(), saved)

    def test_run_failure_rolls_back_actuals_catalog_and_history_together(self):
        run_id = self.store.save_run(self.result, self.sales)
        invalid = self.products.assign(fornecedor_id="INEXISTENTE")
        future_actuals = pd.DataFrame(
            [{"sku": "001", "data": "2026-01-03", "vendas": 10}]
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_run(
                self.result,
                future_actuals,
                produtos=invalid,
                fornecedores=self.suppliers,
            )
        self.assertEqual(len(self.store.list_runs()), 1)
        self.assertEqual(
            self.store.compare_run(run_id)["resumo"][0]["periodos_observados"], 0
        )

    def test_invalid_second_actual_does_not_write_first(self):
        run_id = self.store.save_run(self.result, self.sales)
        with self.assertRaises(ValueError):
            self.store.save_actuals(
                [
                    {"sku": "001", "data": "2026-01-03", "vendas": 1},
                    {"sku": "001", "data": "2026-01-04", "vendas": -1},
                ]
            )
        self.assertEqual(
            self.store.compare_run(run_id)["resumo"][0]["periodos_observados"], 0
        )

    def test_sql_metacharacters_are_identifiers_not_executable_sql(self):
        run_id = self.store.save_run(self.result, self.sales)
        self.assertIsNone(self.store.get_run("' OR 1=1 --"))
        self.assertIsNone(self.store.compare_run("' OR 1=1 --"))
        self.store.save_actuals(
            [{"sku": "'; DROP TABLE sales; --", "data": "2026-01-03", "vendas": 1}]
        )
        self.assertEqual(len(self.store.list_runs()), 1)
        self.assertIsNotNone(self.store.get_run(run_id))

    def test_in_memory_store_shares_connections_and_preserves_leading_zero(self):
        store = Store(":memory:")
        try:
            run_id = store.save_run(self.result, self.sales)
            self.assertEqual(
                store.get_run(run_id)["entrada"]["vendas"][0]["sku"], "001"
            )
            self.assertEqual(store.list_runs()[0]["quantidade_previsoes"], 2)
        finally:
            store.close()

    def test_zero_sales_are_observed_and_wape_is_undefined(self):
        run_id = self.store.save_run(self.result, self.sales)
        self.store.save_actuals(
            [
                {"sku": "001", "data": day, "vendas": 0}
                for day in ("2026-01-03", "2026-01-04")
            ]
        )
        summary = self.store.compare_run(run_id)["resumo"][0]
        self.assertEqual(summary["periodos_observados"], 2)
        self.assertEqual(summary["mae"], 15)
        self.assertIsNone(summary["wape"])

    def test_planning_origin_and_orders_round_trip(self):
        orders = pd.DataFrame(
            [
                {
                    "pedido_id": "P001",
                    "sku": "001",
                    "quantidade": 6,
                    "data_entrega": pd.Timestamp("2026-01-04"),
                }
            ]
        )
        self.store.save_run(
            self.result,
            self.sales,
            produtos=self.products,
            fornecedores=self.suppliers,
            pedidos=orders,
        )
        planning = self.store.get_planning()
        self.assertEqual(planning["origem"], "2026-01-02")
        self.assertEqual(planning["pedidos"][0]["data_entrega"], "2026-01-04")
        self.assertEqual(planning["produtos"][0]["sku"], "001")


if __name__ == "__main__":
    unittest.main()
