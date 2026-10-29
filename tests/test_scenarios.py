"""Sensibilidade preserva os contratos de estoque e não inventa probabilidades."""

import unittest

import pandas as pd

from stockmind.inventory import planejar_estoque
from stockmind.scenarios import simular_cenarios


class TestScenarios(unittest.TestCase):
    def setUp(self):
        self.origin = pd.Timestamp("2026-01-01")
        self.forecasts = pd.DataFrame(
            {
                "sku": ["A"] * 30,
                "data": pd.date_range("2026-01-02", periods=30),
                "previsao": [10.0] * 30,
                "limite_inferior": [4.0] * 30,
                "limite_superior": [18.0] * 30,
                "status": ["avaliado"] * 30,
            }
        )
        self.products = pd.DataFrame(
            [["A", "Produto A", "F1", 20, 5, 1, 12]],
            columns=[
                "sku",
                "nome",
                "fornecedor_id",
                "estoque_atual",
                "estoque_seguranca",
                "pedido_minimo",
                "multiplo_compra",
            ],
        )
        self.suppliers = pd.DataFrame(
            [["F1", "Fornecedor 1", 2]], columns=["fornecedor_id", "nome", "prazo_dias"]
        )
        self.orders = pd.DataFrame(
            columns=["pedido_id", "sku", "quantidade", "data_entrega"]
        )

    def simulate(self, **kwargs):
        return simular_cenarios(
            self.forecasts, self.products, self.suppliers, self.orders, **kwargs
        )

    def test_point_forecast_scenarios_and_fixed_now_purchase(self):
        summary, balances = self.simulate()
        result = summary.set_index("cenario")
        self.assertEqual(result.loc["Demanda menor", "compra_sugerida"], 60)
        self.assertEqual(result.loc["Cenário base", "compra_sugerida"], 84)
        self.assertEqual(result.loc["Demanda maior", "compra_sugerida"], 96)
        self.assertEqual(len(balances), 90)
        self.assertEqual(set(summary["tipo_analise"]), {"sensibilidade_deterministica"})
        self.assertEqual(set(summary["variacao_pct"]), {20.0})
        self.assertEqual(set(summary["fator_demanda"]), {0.8, 1.0, 1.2})
        for name, forecast in [
            ("Demanda menor", 8.0),
            ("Cenário base", 10.0),
            ("Demanda maior", 12.0),
        ]:
            self.assertTrue(
                balances.loc[balances["cenario"].eq(name), "previsao"]
                .eq(forecast)
                .all()
            )

    def test_high_demand_moves_shortage_earlier(self):
        self.products.loc[0, "estoque_atual"] = 55
        summary, balances = self.simulate()
        result = summary.set_index("cenario")
        self.assertEqual(
            result.loc["Demanda menor", "primeira_falta"], pd.Timestamp("2026-01-08")
        )
        self.assertEqual(
            result.loc["Cenário base", "primeira_falta"], pd.Timestamp("2026-01-07")
        )
        self.assertEqual(
            result.loc["Demanda maior", "primeira_falta"], pd.Timestamp("2026-01-06")
        )
        self.assertLessEqual(
            result.loc["Demanda menor", "compra_sugerida"],
            result.loc["Cenário base", "compra_sugerida"],
        )
        self.assertLessEqual(
            result.loc["Cenário base", "compra_sugerida"],
            result.loc["Demanda maior", "compra_sugerida"],
        )
        deficits = balances.groupby("cenario")["saldo_estimado"].min()
        self.assertLess(deficits["Demanda maior"], deficits["Cenário base"])

    def test_base_is_identical_to_existing_planning(self):
        expected_balances, expected_summary = planejar_estoque(
            self.forecasts, self.products, self.suppliers, self.orders
        )
        summary, balances = self.simulate()
        actual_summary = summary.loc[
            summary["cenario"].eq("Cenário base"), expected_summary.columns
        ].reset_index(drop=True)
        actual_balances = balances.loc[
            balances["cenario"].eq("Cenário base"), expected_balances.columns
        ].reset_index(drop=True)
        pd.testing.assert_frame_equal(actual_summary, expected_summary)
        pd.testing.assert_frame_equal(actual_balances, expected_balances)

    def test_existing_orders_keep_arrival_dates_and_lots(self):
        self.orders.loc[0] = ["P1", "A", 24, self.origin + pd.Timedelta(days=3)]
        summary, balances = self.simulate()
        self.assertTrue(summary["em_transito"].eq(24).all())
        self.assertTrue(summary["compra_sugerida"].mod(12).eq(0).all())
        self.assertTrue(
            balances.loc[
                balances["data"].eq(pd.Timestamp("2026-01-04")), "recebimentos"
            ]
            .eq(24)
            .all()
        )
        self.assertTrue(
            balances.loc[
                ~balances["data"].eq(pd.Timestamp("2026-01-04")), "recebimentos"
            ]
            .eq(0)
            .all()
        )
        self.assertEqual(balances["recebimentos"].sum(), 72)
        # Sugestões não são recebidas: apenas 24 unidades reais por cenário.
        for name, group in balances.groupby("cenario"):
            self.assertEqual(group["recebimentos"].sum(), 24, name)

    def test_minimum_applies_only_if_needed(self):
        self.products.loc[
            0, ["estoque_atual", "estoque_seguranca", "pedido_minimo"]
        ] = [89, 0, 25]
        summary, _ = self.simulate()
        result = summary.set_index("cenario")
        self.assertEqual(result.loc["Demanda menor", "compra_sugerida"], 0)
        self.assertEqual(result.loc["Cenário base", "compra_sugerida"], 36)
        self.assertEqual(result.loc["Demanda maior", "compra_sugerida"], 36)

    def test_zero_variation_keeps_three_identical_trajectories(self):
        summary, balances = self.simulate(variacao_pct=0)
        self.assertEqual(set(summary["fator_demanda"]), {1.0})
        self.assertEqual(len(summary), 3)
        self.assertEqual(summary["compra_sugerida"].nunique(), 1)
        self.assertTrue(balances["previsao"].eq(10).all())

    def test_zero_sales_does_not_invent_demand_or_minimum_purchase(self):
        self.forecasts["previsao"] = 0
        self.products.loc[0, "estoque_seguranca"] = 0
        summary, balances = self.simulate()
        self.assertTrue(summary["compra_sugerida"].eq(0).all())
        self.assertTrue(balances["saldo_estimado"].eq(20).all())
        self.assertFalse(balances["risco_falta"].any())

    def test_inputs_not_mutated_and_bands_do_not_define_scenarios(self):
        originals = [
            frame.copy(deep=True)
            for frame in (self.forecasts, self.products, self.suppliers, self.orders)
        ]
        first, _ = self.simulate()
        for actual, original in zip(
            (self.forecasts, self.products, self.suppliers, self.orders), originals
        ):
            pd.testing.assert_frame_equal(actual, original)
        self.forecasts["limite_inferior"] = 0
        self.forecasts["limite_superior"] = 9999
        second, balances = self.simulate()
        pd.testing.assert_frame_equal(first, second)
        self.assertNotIn("limite_inferior", balances)
        self.assertNotIn("limite_superior", balances)

    def test_insufficient_and_absent_forecast_remain_unknown(self):
        self.forecasts = self.forecasts.iloc[:7]
        self.suppliers.loc[0, "prazo_dias"] = 10
        new_product = self.products.iloc[0].copy()
        new_product["sku"] = "NOVO"
        self.products.loc[1] = new_product
        summary, balances = self.simulate()
        existing = summary.loc[summary["sku"].eq("A")]
        new = summary.loc[summary["sku"].eq("NOVO")]
        self.assertTrue(existing["status"].eq("horizonte_insuficiente").all())
        self.assertTrue(new["status"].eq("sem_previsao").all())
        self.assertTrue(summary["compra_sugerida"].isna().all())
        self.assertNotIn("NOVO", set(balances["sku"]))

    def test_empty_forecast_keeps_unknown_catalog_rows(self):
        self.forecasts = self.forecasts.iloc[:0]
        summary, balances = self.simulate()
        self.assertEqual(len(summary), 3)
        self.assertTrue(summary["compra_sugerida"].isna().all())
        self.assertTrue(summary["status"].eq("sem_previsao").all())
        self.assertTrue(balances.empty)
        self.assertIn("cenario", balances)

    def test_percent_range_and_invalid_values(self):
        for value in [
            -1,
            80.1,
            100,
            float("nan"),
            float("inf"),
            True,
            False,
            None,
            [],
            "inválido",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.simulate(variacao_pct=value)
        summary, _ = self.simulate(variacao_pct=80)
        self.assertAlmostEqual(summary["fator_demanda"].min(), 0.2)
        self.assertAlmostEqual(summary["fator_demanda"].max(), 1.8)

    def test_invalid_forecast_is_rejected(self):
        for value in [-1, float("nan"), float("inf")]:
            self.forecasts.loc[0, "previsao"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.simulate()


if __name__ == "__main__":
    unittest.main()
