"""Replay de estoque: conservação física, cronologia, premissas e censura."""

from unittest.mock import patch
import unittest

import pandas as pd

from stockmind.evaluation import avaliar_politicas, POLITICAS


def observed_mean_forecast(prefix, horizonte=7):
    """Previsor externo determinístico para isolar o controlador nas verificações."""
    visible = (
        prefix.loc[prefix["disponivel"].eq(1)] if "disponivel" in prefix else prefix
    )
    points = pd.DataFrame(
        {
            "sku": prefix["sku"].iloc[0],
            "data": pd.date_range(
                prefix["data"].iloc[-1] + pd.Timedelta(days=1), periods=horizonte
            ),
            "previsao": float(visible["vendas"].tail(28).mean()),
            "modelo": "Previsor de teste com prefixo observado",
        }
    )
    return points, pd.DataFrame()


class TestPolicyEvaluation(unittest.TestCase):
    def setUp(self):
        self.sales = pd.DataFrame(
            {
                "sku": ["A"] * 50,
                "data": pd.date_range("2026-01-01", periods=50),
                "vendas": [2] * 50,
                "disponivel": [1] * 50,
            }
        )
        self.products = pd.DataFrame(
            [
                {
                    "sku": "A",
                    "nome": "Produto A",
                    "fornecedor_id": "F1",
                    "estoque_atual": 0,
                    "estoque_seguranca": 0,
                    "pedido_minimo": 1,
                    "multiplo_compra": 1,
                }
            ]
        )
        self.suppliers = pd.DataFrame(
            [{"fornecedor_id": "F1", "nome": "Fornecedor A", "prazo_dias": 0}]
        )

    def run_scenario(self, **options):
        return avaliar_politicas(
            self.sales,
            self.products,
            self.suppliers,
            periodo_dias=7,
            revisao_dias=3,
            **options,
        )

    def test_real_forecaster_and_three_policies(self):
        summary, diary = self.run_scenario()
        self.assertEqual(set(summary["politica"]), set(POLITICAS))
        self.assertTrue(summary["status"].eq("avaliado").all())
        self.assertTrue(
            summary["base_demanda"].eq("vendas_com_disponibilidade_confirmada").all()
        )
        self.assertTrue(summary["origem_estoque_inicial"].eq("cenario_catalogo").all())
        self.assertEqual(len(diary), 3 * 8)
        self.assertTrue(diary["estoque_final"].ge(0).all())
        model = summary.set_index("politica").loc["Previsão selecionada"]
        self.assertEqual(model["vendas_perdidas"], 0)
        self.assertEqual(model["atendimento_pct"], 100)

    @patch(
        "stockmind.evaluation.analisar_previsoes", side_effect=observed_mean_forecast
    )
    def test_zero_lead_arrives_next_morning_and_not_before_order(self, _forecast):
        _, diary = self.run_scenario()
        selected = diary.loc[diary["politica"].eq("Previsão selecionada")].reset_index(
            drop=True
        )
        initial, day1 = selected.iloc[0], selected.iloc[1]
        self.assertEqual(initial["fase"], "inicial")
        self.assertTrue(pd.isna(initial["demanda"]))
        self.assertEqual(initial["recebimentos"], 0)
        self.assertGreater(initial["quantidade_pedida"], 0)
        self.assertEqual(initial["data_entrega_pedido"], day1["data"])
        self.assertEqual(day1["recebimentos"], initial["quantidade_pedida"])
        self.assertEqual(day1["vendas_perdidas"], 0)

    @patch(
        "stockmind.evaluation.analisar_previsoes", side_effect=observed_mean_forecast
    )
    def test_future_actuals_do_not_change_earlier_orders(self, _forecast):
        _, original = self.run_scenario()
        changed_at = self.sales["data"].iloc[-3]
        self.sales.loc[self.sales["data"].ge(changed_at), "vendas"] = 200
        _, modified = self.run_scenario()
        pd.testing.assert_frame_equal(
            original.loc[original["data"].lt(changed_at)].reset_index(drop=True),
            modified.loc[modified["data"].lt(changed_at)].reset_index(drop=True),
        )
        self.assertFalse(original["demanda"].equals(modified["demanda"]))

    @patch(
        "stockmind.evaluation.analisar_previsoes", side_effect=observed_mean_forecast
    )
    def test_censored_period_is_never_assumed_zero_even_with_opt_in(self, forecast):
        self.sales.loc[self.sales.index[-2], ["disponivel", "vendas"]] = [0, 0]
        summary, diary = self.run_scenario(assumir_vendas_como_demanda=True)
        self.assertTrue(summary["status"].eq("demanda_censurada").all())
        self.assertTrue(summary["custo_total_estimado"].isna().all())
        self.assertTrue(summary["atendimento_pct"].isna().all())
        self.assertTrue(diary.empty)
        forecast.assert_not_called()

    def test_missing_availability_requires_explicit_assumption(self):
        self.sales = self.sales.drop(columns="disponivel")
        summary, diary = self.run_scenario()
        self.assertTrue(summary["status"].eq("disponibilidade_desconhecida").all())
        self.assertTrue(diary.empty)
        with patch(
            "stockmind.evaluation.analisar_previsoes",
            side_effect=observed_mean_forecast,
        ):
            summary, diary = self.run_scenario(assumir_vendas_como_demanda=True)
        self.assertTrue(summary["status"].eq("avaliado").all())
        self.assertTrue(summary["base_demanda"].eq("vendas_como_proxy_assumida").all())
        self.assertFalse(diary.empty)

    @patch(
        "stockmind.evaluation.analisar_previsoes", side_effect=observed_mean_forecast
    )
    def test_lost_demand_and_stock_conservation(self, _forecast):
        self.products.loc[0, "estoque_atual"] = 3
        self.suppliers.loc[0, "prazo_dias"] = 4
        _, diary = self.run_scenario()
        for _, group in diary.groupby("politica"):
            inventory = 3
            for row in group.itertuples():
                if row.fase == "inicial":
                    continue
                inventory += row.recebimentos
                self.assertEqual(
                    row.vendas_atendidas + row.vendas_perdidas, row.demanda
                )
                self.assertEqual(row.vendas_atendidas, min(inventory, row.demanda))
                inventory -= row.vendas_atendidas
                self.assertEqual(row.estoque_final, inventory)
                self.assertGreaterEqual(inventory, 0)

    @patch(
        "stockmind.evaluation.analisar_previsoes", side_effect=observed_mean_forecast
    )
    def test_costs_are_explicit_and_initial_row_has_no_holding_cost(self, _forecast):
        self.products.loc[0, "estoque_atual"] = 3
        summary, diary = self.run_scenario(
            custo_falta_unitario=3, custo_estoque_unitario_dia=0.5, custo_pedido=4
        )
        no_order = summary.set_index("politica").loc["Sem reposição"]
        self.assertEqual(no_order["demanda_total"], 14)
        self.assertEqual(no_order["vendas_atendidas"], 3)
        self.assertEqual(no_order["vendas_perdidas"], 11)
        self.assertEqual(no_order["custo_falta_estimado"], 33)
        self.assertEqual(no_order["custo_estoque_estimado"], 0.5)
        self.assertEqual(no_order["custo_pedidos_estimado"], 0)
        self.assertEqual(no_order["custo_total_estimado"], 33.5)
        self.assertTrue(
            diary.loc[diary["fase"].eq("inicial"), "custo_estoque_estimado"].eq(0).all()
        )
        self.assertTrue(summary["estoque_inicial"].eq(3).all())

    @patch(
        "stockmind.evaluation.analisar_previsoes", side_effect=observed_mean_forecast
    )
    def test_orders_after_period_remain_in_pipeline_and_cost_is_counted(
        self, _forecast
    ):
        self.suppliers.loc[0, "prazo_dias"] = 10
        summary, diary = self.run_scenario()
        selected = summary.set_index("politica").loc["Previsão selecionada"]
        self.assertGreater(selected["em_transito_final"], 0)
        self.assertEqual(selected["estoque_final"], 0)
        self.assertEqual(
            selected["custo_pedidos_estimado"], selected["pedidos_emitidos"]
        )
        rows = diary.loc[diary["politica"].eq("Previsão selecionada")]
        self.assertTrue(rows["recebimentos"].eq(0).all())

    @patch(
        "stockmind.evaluation.analisar_previsoes", side_effect=observed_mean_forecast
    )
    def test_zero_demand_has_no_invented_service_percentage(self, _forecast):
        self.sales["vendas"] = 0
        summary, _ = self.run_scenario()
        self.assertTrue(summary["status"].eq("avaliado").all())
        self.assertTrue(summary["atendimento_pct"].isna().all())
        self.assertTrue(summary["pedidos_emitidos"].eq(0).all())
        self.assertTrue(summary["vendas_perdidas"].eq(0).all())

    def test_short_history_and_catalog_only_product_are_unknown(self):
        self.sales = self.sales.iloc[-10:].copy()
        extra = self.products.iloc[0].copy()
        extra["sku"] = "B"
        self.products.loc[1] = extra
        summary, diary = self.run_scenario()
        self.assertTrue(
            summary.loc[summary["sku"].eq("A"), "status"]
            .eq("historico_insuficiente")
            .all()
        )
        self.assertTrue(
            summary.loc[summary["sku"].eq("B"), "status"].eq("sem_historico").all()
        )
        self.assertTrue(summary["custo_total_estimado"].isna().all())
        self.assertTrue(diary.empty)

    @patch(
        "stockmind.evaluation.analisar_previsoes", side_effect=observed_mean_forecast
    )
    def test_inputs_unchanged_and_order_lots_respected(self, _forecast):
        originals = [
            df.copy(deep=True) for df in (self.sales, self.products, self.suppliers)
        ]
        self.products.loc[0, ["pedido_minimo", "multiplo_compra"]] = [7, 6]
        originals[1] = self.products.copy(deep=True)
        _, diary = self.run_scenario()
        orders = diary.loc[diary["quantidade_pedida"].gt(0), "quantidade_pedida"]
        self.assertTrue(orders.mod(6).eq(0).all())
        self.assertTrue(orders.ge(7).all())
        for before, after in zip(
            originals, (self.sales, self.products, self.suppliers)
        ):
            pd.testing.assert_frame_equal(before, after)

    def test_invalid_parameters_fail_explicitly(self):
        cases = [
            {"periodo_dias": 1},
            {"periodo_dias": True},
            {"periodo_dias": 7.0},
            {"revisao_dias": 0},
            {"revisao_dias": 31},
            {"revisao_dias": True},
            {"assumir_vendas_como_demanda": 1},
            {"custo_falta_unitario": -1},
            {"custo_falta_unitario": True},
            {"custo_estoque_unitario_dia": float("nan")},
            {"custo_pedido": float("inf")},
            {"custo_pedido": "2"},
        ]
        for options in cases:
            defaults = {"periodo_dias": 7, "revisao_dias": 3, **options}
            with self.subTest(options=options), self.assertRaises(ValueError):
                avaliar_politicas(self.sales, self.products, self.suppliers, **defaults)

    @patch("stockmind.evaluation.analisar_previsoes")
    def test_unavailable_model_does_not_become_zero_cost_or_demand(self, forecast):
        forecast.return_value = (
            pd.DataFrame(columns=["sku", "data", "previsao", "modelo"]),
            pd.DataFrame(),
        )
        summary, diary = self.run_scenario()
        selected = summary.set_index("politica").loc["Previsão selecionada"]
        self.assertEqual(selected["status"], "previsao_indisponivel")
        self.assertTrue(pd.isna(selected["custo_total_estimado"]))
        self.assertFalse(diary["politica"].eq("Previsão selecionada").any())
        self.assertEqual(summary["status"].eq("avaliado").sum(), 2)


if __name__ == "__main__":
    unittest.main()
