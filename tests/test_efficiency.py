import unittest
from unittest.mock import patch
import pandas as pd
from stockmind.cache import AnalysisCache, CACHE
from stockmind.service import executar_analise
from stockmind.analytics import classificar_produtos
from stockmind.evaluation import avaliar_multiperiodo
from stockmind.forecasting import analisar_previsoes


class TestEfficiency(unittest.TestCase):
    def test_cache_copia_resultados_e_expira(self):
        cache = AnalysisCache(max_entries=1, ttl=10)
        calls = []

        def compute():
            calls.append(1)
            return pd.DataFrame({"a": [1]})

        with patch("stockmind.cache.monotonic", return_value=0):
            first = cache.obtain("a", (1,), compute)
            first.loc[0, "a"] = 99
            self.assertEqual(cache.obtain("a", (1,), compute).iloc[0]["a"], 1)
        with patch("stockmind.cache.monotonic", return_value=11):
            cache.obtain("a", (1,), compute)
        self.assertEqual(len(calls), 2)
        cache.obtain("b", (2,), compute)
        self.assertEqual(len(cache.entries), 1)

    def test_mudar_estoque_cenario_e_custo_reutiliza_modelos(self):
        CACHE.clear()
        self.addCleanup(CACHE.clear)
        sales = pd.DataFrame(
            {
                "sku": ["A"] * 90,
                "data": pd.date_range("2026-01-01", periods=90),
                "vendas": [10] * 90,
                "disponivel": [1] * 90,
            }
        )
        products = pd.DataFrame(
            [
                {
                    "sku": "A",
                    "nome": "A",
                    "fornecedor_id": "F",
                    "estoque_atual": 20,
                    "estoque_seguranca": 5,
                    "pedido_minimo": 1,
                    "multiplo_compra": 1,
                }
            ]
        )
        suppliers = pd.DataFrame([{"fornecedor_id": "F", "nome": "F", "prazo_dias": 2}])
        with patch(
            "stockmind.forecasting.analisar_previsoes", wraps=analisar_previsoes
        ) as spy:
            a = executar_analise(
                sales,
                produtos=products,
                fornecedores=suppliers,
                comparar_horizontes=True,
            )
            fits = spy.call_count
            products.loc[0, "estoque_atual"] = 300
            b = executar_analise(
                sales,
                produtos=products,
                fornecedores=suppliers,
                variacao_cenario_pct=40,
                custo_pedido=20,
                comparar_horizontes=True,
            )
            self.assertEqual(spy.call_count, fits)
            self.assertEqual(a["previsoes"], b["previsoes"])
            self.assertNotEqual(a["recomendacoes"], b["recomendacoes"])
            sales.loc[0, "vendas"] = 12
            executar_analise(sales)
            self.assertGreater(spy.call_count, fits)

    def test_abc_mesma_janela_e_produto_novo_provisorio(self):
        rows = []
        for sku, n in [("LONGO", 120), ("CURTO", 30), ("NOVO", 10)]:
            for day in pd.date_range(end="2026-10-20", periods=n):
                rows.append({"sku": sku, "data": day, "vendas": 10, "disponivel": 1})
        result = classificar_produtos(pd.DataFrame(rows), janela_dias=30).set_index(
            "sku"
        )
        self.assertEqual(
            result.loc["LONGO", "valor_base"], result.loc["CURTO", "valor_base"]
        )
        self.assertEqual(
            result.loc["LONGO", "classe_abc"], result.loc["CURTO", "classe_abc"]
        )
        self.assertEqual(result.loc["NOVO", "classe_abc"], "provisoria")
        self.assertTrue(pd.isna(result.loc["NOVO", "participacao_pct"]))
        self.assertEqual(result.loc["LONGO", "participacao_pct"], 50)

    def test_estabilidade_usa_somente_validacao(self):
        data = pd.DataFrame(
            {
                "sku": ["A"] * 90,
                "data": pd.date_range("2026-01-01", periods=90),
                "vendas": range(10, 100),
            }
        )
        _, first = analisar_previsoes(data)
        data.loc[83:, "vendas"] += 1000
        _, changed = analisar_previsoes(data)
        fields = [
            "modelo",
            "mae_validacao_desvio",
            "janelas_vencidas",
            "vitorias_validacao_pct",
        ]
        pd.testing.assert_frame_equal(first[fields], changed[fields])
        self.assertTrue(first.janelas_vencidas.le(first.janelas_validacao).all())
        self.assertAlmostEqual(
            first.set_index("modelo").loc["Regressão linear", "vitorias_validacao_pct"],
            100,
        )

    def test_multiperiodo_recorta_sem_usar_futuro(self):
        data = pd.DataFrame(
            {
                "sku": ["A"] * 60,
                "data": pd.date_range("2026-01-01", periods=60),
                "vendas": [1] * 60,
            }
        )
        ends = []

        def evaluate(prefix, *args, **kwargs):
            end = prefix.data.max()
            ends.append(end)
            return pd.DataFrame(
                [
                    {
                        "sku": "A",
                        "politica": "P",
                        "custo_total_estimado": 1,
                        "atendimento_pct": 100,
                    }
                ]
            ), pd.DataFrame([{"sku": "A", "data": end}])

        with patch("stockmind.evaluation.avaliar_politicas", side_effect=evaluate):
            summary, daily, stability = avaliar_multiperiodo(
                data, pd.DataFrame(), pd.DataFrame(), numero_periodos=3, periodo_dias=7
            )
        self.assertEqual(
            ends, [data.data.max() - pd.Timedelta(days=i * 7) for i in range(3)]
        )
        self.assertEqual(len(summary), 3)
        self.assertEqual(stability.iloc[0].periodos_com_custos, 3)
