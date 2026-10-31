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
        self.assertTrue(
            all(
                c["classe_xyz"] == "indefinida"
                for c in result["classificacao_produtos"]
            )
        )

    def test_estimativas_aplicam_copias_e_replay_usa_parametros_manuais(self):
        read = lambda name: ler_csv(ROOT / "data" / name)
        products, suppliers = (
            read("produtos_exemplo.csv"),
            read("fornecedores_exemplo.csv"),
        )
        before_p, before_f = products.copy(deep=True), suppliers.copy(deep=True)
        result = executar_analise(
            read("vendas_multiplos_exemplo.csv"),
            30,
            read("contexto_futuro_exemplo.csv"),
            products,
            suppliers,
            read("pedidos_exemplo.csv"),
            entregas=read("entregas_exemplo.csv"),
            seguranca_automatica=True,
            ajustar_prazos=True,
            avaliar_reposicao=True,
        )
        pd.testing.assert_frame_equal(products, before_p)
        pd.testing.assert_frame_equal(suppliers, before_f)
        self.assertTrue(any(r["aplicado"] for r in result["seguranca_estoque"]))
        self.assertTrue(all(r["aplicado"] for r in result["prazos_fornecedores"]))
        caf = [r for r in result["avaliacao_reposicao"] if r["sku"] == "CAF-001"]
        self.assertTrue(
            all(r["seguranca_manual"] == 20 and r["prazo_dias"] == 5 for r in caf)
        )
        censored = [r for r in result["avaliacao_reposicao"] if r["sku"] == "CAC-003"]
        self.assertTrue(
            all(
                r["status"] == "demanda_censurada" and r["custo_total_estimado"] is None
                for r in censored
            )
        )
        json.dumps(result, allow_nan=False)

    def test_sem_demanda_observavel_nao_fabrica_zero(self):
        vendas = pd.DataFrame(
            {
                "sku": ["A"] * 30,
                "data": pd.date_range("2026-01-01", periods=30),
                "vendas": [10] * 30,
                "disponivel": [0] * 30,
            }
        )
        result = executar_analise(vendas)
        self.assertEqual(result["previsoes"], [])
        self.assertTrue(
            all(
                m["status"] == "demanda_indisponivel" and m["mae_teste"] is None
                for m in result["metricas"]
            )
        )

    def test_novos_parametros_invalidos_e_estoque_obrigatorio(self):
        data = ler_csv(ROOT / "vendas_exemplo.csv")
        params = [
            {"seguranca_automatica": 1},
            {"ajustar_prazos": "true"},
            {"avaliar_reposicao": 1},
            {"assumir_vendas_como_demanda": "false"},
            {"periodo_simulacao": True},
            {"periodo_simulacao": 90},
            {"custo_falta_unitario": -1},
            {"custo_estoque_unitario_dia": float("nan")},
            {"custo_pedido": True},
            {"seguranca_automatica": True},
            {"ajustar_prazos": True},
            {"avaliar_reposicao": True},
        ]
        for parameter in params:
            with self.subTest(parameter=parameter), self.assertRaises(ValueError):
                executar_analise(data, **parameter)

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
