from pathlib import Path
import json
import unittest

import pandas as pd

from stockmind.data import DataError, ler_csv
from stockmind.service import executar_analise

ROOT = Path(__file__).resolve().parents[1]


class TestService(unittest.TestCase):
    def test_fluxo_completo_json_e_produto_sem_historico(self):
        sample = lambda name: ler_csv(ROOT / "data" / name)
        result = executar_analise(
            sample("vendas_multiplos_exemplo.csv"),
            30,
            sample("contexto_futuro_exemplo.csv"),
            sample("produtos_exemplo.csv"),
            sample("fornecedores_exemplo.csv"),
            sample("pedidos_exemplo.csv"),
        )
        json.dumps(result, allow_nan=False)
        self.assertEqual(len(result["previsoes"]), 120)
        self.assertEqual(len(result["recomendacoes"]), 5)
        cold = next(p for p in result["recomendacoes"] if p["sku"] == "SEM-005")
        self.assertIsNone(cold["compra_sugerida"])
        self.assertTrue(any(row["sku"] == "SEM-005" for row in result["qualidade"]))
        recent = next(p for p in result["metricas"] if p["sku"] == "NOV-004")
        self.assertIsNone(recent["mae_teste"])
        self.assertIsNone(recent["cobertura_teste"])
        self.assertEqual(len(result["cenarios"]), 15)
        self.assertEqual(len(result["saldos_cenarios"]), 360)
        self.assertEqual(result["comparacao_horizontes"], [])

    def test_compara_tres_horizontes_e_preserva_contexto(self):
        sample = lambda name: ler_csv(ROOT / "data" / name)
        result = executar_analise(
            sample("vendas_multiplos_exemplo.csv"),
            7,
            sample("contexto_futuro_exemplo.csv"),
            comparar_horizontes=True,
        )
        self.assertEqual(len(result["previsoes"]), 28)
        self.assertEqual(len(result["comparacao_horizontes"]), 12)
        self.assertEqual(
            {r["horizonte"] for r in result["comparacao_horizontes"]}, {7, 14, 30}
        )
        self.assertTrue(
            any(row["modelo"] == "Regressão com contexto" for row in result["metricas"])
        )
        json.dumps(result, allow_nan=False)

    def test_parametros_de_cenario_e_comparacao_invalidos(self):
        data = ler_csv(ROOT / "vendas_exemplo.csv")
        for params in [
            {"comparar_horizontes": 1},
            {"comparar_horizontes": "false"},
            {"variacao_cenario_pct": True},
            {"variacao_cenario_pct": float("nan")},
            {"variacao_cenario_pct": float("inf")},
            {"variacao_cenario_pct": -1},
            {"variacao_cenario_pct": 81},
            {"variacao_cenario_pct": "20"},
        ]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                executar_analise(data, **params)

    def test_formato_legado_e_sem_planejamento(self):
        result = executar_analise(ler_csv(ROOT / "vendas_exemplo.csv"))
        self.assertEqual(len(result["previsoes"]), 7)
        self.assertEqual(result["recomendacoes"], [])
        self.assertEqual(result["saldos"], [])

    def test_relatorio_de_erro_nao_vira_previsao(self):
        data = pd.DataFrame({"data": ["2026-01-01", "2026-01-03"], "vendas": [10, 20]})
        with self.assertRaises(DataError) as error:
            executar_analise(data)
        self.assertTrue(error.exception.report["nivel"].eq("erro").any())

    def test_parametros_invalidos(self):
        data = ler_csv(ROOT / "vendas_exemplo.csv")
        for horizonte, revisao in [(0, 7), (True, 7), (7, 0), (7, 31), (7, True)]:
            with (
                self.subTest(horizonte=horizonte, revisao=revisao),
                self.assertRaises(ValueError),
            ):
                executar_analise(data, horizonte, revisao_dias=revisao)


if __name__ == "__main__":
    unittest.main()
