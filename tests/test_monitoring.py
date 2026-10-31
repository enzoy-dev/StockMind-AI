from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from stockmind.monitoring import monitorar_desempenho
from stockmind.storage import Store


class TestMonitoring(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "monitor.sqlite3")

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def add_run(
        self,
        origin,
        prediction=11,
        *,
        horizon=7,
        created=None,
        sku="001",
        censored_reference=None,
    ):
        history = [
            {
                "sku": sku,
                "data": (origin - timedelta(days=13 - i)).isoformat(),
                "vendas": 10,
                "disponivel": 0
                if origin - timedelta(days=13 - i) == censored_reference
                else 1,
            }
            for i in range(14)
        ]
        forecasts = [
            {
                "sku": sku,
                "data": (origin + timedelta(days=i + 1)).isoformat(),
                "previsao": prediction,
                "modelo": "teste",
            }
            for i in range(horizon)
        ]
        run_id = self.store.save_run({"previsoes": forecasts, "metricas": []}, history)
        with self.store._connection() as connection:
            connection.execute(
                "UPDATE runs SET criado_em=? WHERE id=?",
                (
                    created or f"{origin.isoformat()}T12:00:00+00:00",
                    run_id,
                ),
            )
        return run_id

    def scenario(self, *, base_prediction=11, recent_prediction=14):
        origins = [date(2026, 1, 7) + timedelta(days=7 * i) for i in range(4)]
        runs = [
            self.add_run(origin, recent_prediction if i == 3 else base_prediction)
            for i, origin in enumerate(origins)
        ]
        actuals = [
            {
                "sku": "001",
                "data": (date(2026, 1, 8) + timedelta(days=i)).isoformat(),
                "vendas": 10,
                "disponivel": 1,
            }
            for i in range(28)
        ]
        self.store.save_actuals(actuals)
        return runs

    def test_supported_deterioration_is_readonly_and_baseline_uses_snapshot(self):
        runs = self.scenario()
        before = self.store.get_run(runs[0])
        result = monitorar_desempenho(self.store)
        row = result.iloc[0]
        self.assertEqual(row["amostras_recente"], 7)
        self.assertEqual(row["amostras_base"], 21)
        self.assertEqual(row["mae_recente"], 4)
        self.assertEqual(row["vies_recente"], 4)
        self.assertEqual(row["mae_base"], 1)
        self.assertEqual(row["aumento_pct"], 300)
        self.assertEqual(row["mae_referencia_recente"], 0)
        self.assertEqual(row["amostras_referencia"], 7)
        self.assertTrue(row["alerta"])
        self.assertEqual(row["status"], "aumento_erro")
        self.assertTrue(row["perde_referencia_semanal"])
        self.assertEqual(row["direcao_vies"], "superestimacao")
        self.assertEqual(
            row["motivos_monitoramento"], "aumento_erro;abaixo_referencia_semanal"
        )
        pd.testing.assert_frame_equal(result, monitorar_desempenho(self.store))
        self.assertEqual(self.store.get_run(runs[0]), before)
        self.assertEqual(len(self.store.list_runs()), 4)

    def test_overlap_keeps_freshest_origin_and_creation_without_counting_twice(self):
        self.scenario()
        self.add_run(date(2026, 1, 29), 16, created="2026-01-29T12:00:00+00:00")
        self.add_run(date(2026, 1, 29), 17, created="2026-01-29T18:00:00+00:00")
        # A reexecução posterior ao resultado não substitui a previsão prospectiva.
        self.add_run(date(2026, 1, 29), 100, created="2026-02-10T12:00:00+00:00")
        row = monitorar_desempenho(self.store).iloc[0]
        self.assertEqual(row["amostras_recente"], 7)
        self.assertAlmostEqual(row["mae_recente"], 46 / 7)
        self.assertEqual(row["periodos_retrospectivos"], 7)

    def test_censored_days_excluded_and_small_support_prevents_alert(self):
        self.scenario()
        self.store.save_actuals(
            [
                {"sku": "001", "data": "2026-02-04", "vendas": 0, "disponivel": 0},
            ]
        )
        row = monitorar_desempenho(self.store).iloc[0]
        self.assertEqual(row["periodos_censurados"], 1)
        self.assertEqual(row["amostras_recente"], 6)
        self.assertEqual(row["mae_recente"], 4)
        self.assertFalse(row["alerta"])
        self.assertEqual(row["status"], "amostra_insuficiente")
        self.assertTrue(pd.isna(row["perde_referencia_semanal"]))

    def test_missing_availability_stays_observed_sales_not_demand(self):
        self.scenario()
        # Simula registro legado cujo sinal não existia no banco anterior.
        with self.store._connection() as connection:
            connection.execute(
                "UPDATE sales SET disponivel=NULL WHERE data='2026-02-04'"
            )
        row = monitorar_desempenho(self.store).iloc[0]
        self.assertEqual(row["amostras_recente"], 7)
        self.assertEqual(row["disponibilidade_desconhecida"], 1)
        self.assertIn("disponibilidade_desconhecida", row["base_avaliacao"])

    def test_zero_base_guards_both_stable_zero_and_new_errors(self):
        self.scenario(base_prediction=10, recent_prediction=10)
        stable = monitorar_desempenho(self.store).iloc[0]
        self.assertEqual(stable["aumento_pct"], 0)
        self.assertFalse(stable["alerta"])
        self.assertEqual(stable["direcao_vies"], "equilibrado")
        self.assertFalse(stable["perde_referencia_semanal"])
        self.assertEqual(stable["motivos_monitoramento"], "")
        self.add_run(date(2026, 1, 28), 14, created="2026-01-28T18:00:00+00:00")
        worsening = monitorar_desempenho(self.store).iloc[0]
        self.assertEqual(worsening["mae_base"], 0)
        self.assertTrue(pd.isna(worsening["aumento_pct"]))
        self.assertTrue(worsening["alerta"])
        self.assertEqual(worsening["status"], "erro_apos_base_zero")
        self.assertEqual(
            worsening["motivos_monitoramento"],
            "erro_apos_base_zero;abaixo_referencia_semanal",
        )

    def test_stable_error_still_signals_loss_to_weekly_reference(self):
        self.scenario(base_prediction=11, recent_prediction=11)
        row = monitorar_desempenho(self.store).iloc[0]
        self.assertEqual(row["mae_recente"], 1)
        self.assertEqual(row["mae_base"], 1)
        self.assertEqual(row["aumento_pct"], 0)
        self.assertEqual(row["mae_referencia_recente"], 0)
        self.assertTrue(row["perde_referencia_semanal"])
        self.assertTrue(row["alerta"])
        self.assertEqual(row["status"], "abaixo_referencia_semanal")
        self.assertEqual(row["motivos_monitoramento"], "abaixo_referencia_semanal")

    def test_incomplete_reference_is_not_compared_with_a_different_target_set(self):
        self.scenario(base_prediction=11, recent_prediction=11)
        self.add_run(
            date(2026, 1, 28),
            11,
            created="2026-01-28T18:00:00+00:00",
            censored_reference=date(2026, 1, 22),
        )
        row = monitorar_desempenho(self.store).iloc[0]
        self.assertEqual(row["amostras_recente"], 7)
        self.assertEqual(row["amostras_base"], 20)
        self.assertEqual(row["amostras_referencia"], 6)
        self.assertTrue(pd.isna(row["perde_referencia_semanal"]))
        self.assertFalse(row["alerta"])
        self.assertEqual(row["motivos_monitoramento"], "")

    def test_negative_bias_is_labeled_as_underestimation(self):
        self.scenario(base_prediction=9, recent_prediction=9)
        row = monitorar_desempenho(self.store).iloc[0]
        self.assertEqual(row["vies_recente"], -1)
        self.assertEqual(row["direcao_vies"], "subestimacao")

    def test_utc_creation_is_converted_to_sao_paulo_and_same_day_is_retrospective(self):
        self.add_run(date(2026, 1, 2), 11, created="2026-01-03T01:00:00+00:00")
        self.add_run(date(2026, 1, 2), 100, created="2026-01-03T04:00:00+00:00")
        self.store.save_actuals(
            [{"sku": "001", "data": "2026-01-03", "vendas": 10, "disponivel": 1}]
        )
        row = monitorar_desempenho(self.store).iloc[0]
        self.assertEqual(row["amostras_recente"], 1)
        self.assertEqual(row["mae_recente"], 1)
        self.assertEqual(row["periodos_retrospectivos"], 1)
        self.assertFalse(row["alerta"])

    def test_future_actuals_are_not_evidence_and_horizons_do_not_mix(self):
        origin = date(2030, 1, 1)
        self.add_run(origin, 20, horizon=7)
        self.add_run(date(2026, 1, 1), 100, horizon=14, sku="OUTRO")
        self.store.save_actuals(
            [{"sku": "001", "data": "2030-01-02", "vendas": 10, "disponivel": 1}]
        )

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2030, 1, 1, 18, tzinfo=timezone.utc).astimezone(tz)

        with patch("stockmind.monitoring.datetime", FixedDatetime):
            result = monitorar_desempenho(self.store, horizonte=7)
        self.assertEqual(result["sku"].tolist(), ["001"])
        row = result.iloc[0]
        self.assertEqual(row["periodos_futuros"], 7)
        self.assertEqual(row["amostras_recente"], 0)
        self.assertFalse(row["alerta"])

    def test_reference_never_reads_future_realizations_outside_snapshot(self):
        origin = date(2026, 1, 1)
        self.add_run(origin, 11, horizon=14)
        self.store.save_actuals(
            [
                {
                    "sku": "001",
                    "data": (origin + timedelta(days=i)).isoformat(),
                    "vendas": 100,
                    "disponivel": 1,
                }
                for i in range(1, 15)
            ]
        )
        row = monitorar_desempenho(self.store, horizonte=14).iloc[0]
        self.assertEqual(row["mae_referencia_recente"], 90)
        self.assertEqual(row["amostras_referencia"], 7)
        self.assertFalse(row["alerta"])

    def test_raw_snapshot_censored_reference_is_not_a_weekly_baseline(self):
        origin = date(2026, 1, 1)
        history = [
            {
                "sku": "001",
                "data": (origin - timedelta(days=6 - i)).isoformat(),
                "vendas": "10",
                "disponivel": "0",
            }
            for i in range(7)
        ]
        forecasts = [
            {
                "sku": "001",
                "data": (origin + timedelta(days=i)).isoformat(),
                "previsao": 11,
            }
            for i in range(1, 8)
        ]
        run_id = self.store.save_run({"previsoes": forecasts}, history)
        with self.store._connection() as connection:
            connection.execute(
                "UPDATE runs SET criado_em='2026-01-01T12:00:00+00:00' WHERE id=?",
                (run_id,),
            )
        self.store.save_actuals(
            [{"sku": "001", "data": "2026-01-02", "vendas": 10, "disponivel": 1}]
        )
        row = monitorar_desempenho(self.store).iloc[0]
        self.assertEqual(row["amostras_recente"], 1)
        self.assertEqual(row["amostras_referencia"], 0)
        self.assertTrue(pd.isna(row["mae_referencia_recente"]))

    def test_monitoring_validates_parameters_and_empty_history(self):
        self.assertTrue(monitorar_desempenho(self.store).empty)
        for kwargs in [
            {"horizonte": 8},
            {"horizonte": True},
            {"janela_recente": 0},
            {"janela_base": 366},
            {"janela_base": True},
            {"janela_recente": 1.5},
            {"limiar_aumento_pct": -1},
            {"limiar_aumento_pct": float("inf")},
            {"limiar_aumento_pct": True},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                monitorar_desempenho(self.store, **kwargs)


if __name__ == "__main__":
    unittest.main()
