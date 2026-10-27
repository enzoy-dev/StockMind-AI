"""Verificações pequenas, usando unittest da biblioteca padrão."""

from io import StringIO
from pathlib import Path
import unittest

import pandas as pd

from app import carregar_vendas, prever_vendas


class TestStockMind(unittest.TestCase):
    def setUp(self):
        self.dados = pd.DataFrame(
            {"data": pd.date_range("2026-01-01", periods=40), "vendas": range(10, 50)}
        )

    def carregar(self, dados):
        return carregar_vendas(StringIO(dados.to_csv(index=False)))

    def test_exemplo_pode_ser_carregado(self):
        dados = carregar_vendas(Path(__file__).with_name("vendas_exemplo.csv"))
        self.assertEqual(len(dados), 60)

    def test_dias_futuros_e_tendencia_linear(self):
        previsao, erro, referencia = prever_vendas(self.carregar(self.dados))
        self.assertEqual(len(previsao), 7)
        self.assertEqual(
            previsao["data"].iloc[0], self.dados["data"].iloc[-1] + pd.Timedelta(days=1)
        )
        self.assertAlmostEqual(previsao["previsao"].iloc[0], 50)
        self.assertAlmostEqual(erro, 0)
        self.assertAlmostEqual(referencia, 4)

    def test_avaliacao_nao_treina_com_a_semana_de_teste(self):
        self.dados.loc[33:, "vendas"] += 100
        _, erro, _ = prever_vendas(self.carregar(self.dados))
        self.assertAlmostEqual(erro, 100)

    def test_previsao_nao_pode_ser_negativa(self):
        self.dados["vendas"] = list(range(40, 0, -1))
        previsao, _, _ = prever_vendas(self.carregar(self.dados))
        self.assertTrue(previsao["previsao"].ge(0).all())

    def test_ordena_historico(self):
        dados = self.carregar(self.dados.iloc[::-1])
        self.assertTrue(dados["data"].is_monotonic_increasing)

    def test_rejeita_historico_incompleto(self):
        for dados in [
            self.dados.iloc[:29],
            self.dados.drop(index=10),
            pd.concat([self.dados, self.dados.iloc[:1]]),
        ]:
            with self.subTest(linhas=len(dados)), self.assertRaises(ValueError):
                self.carregar(dados)

    def test_rejeita_vendas_invalidas(self):
        for valor in [-1, 1.5, float("inf"), float("nan"), "texto"]:
            dados = self.dados.astype({"vendas": object})
            dados.loc[0, "vendas"] = valor
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                self.carregar(dados)

    def test_rejeita_data_invalida_e_colunas_extras(self):
        dados = self.dados.copy()
        dados["data"] = dados["data"].astype(str)
        dados.loc[0, "data"] = "2026-02-30"
        with self.assertRaises(ValueError):
            self.carregar(dados)
        with self.assertRaises(ValueError):
            self.carregar(self.dados.assign(sku="produto"))


if __name__ == "__main__":
    unittest.main()
