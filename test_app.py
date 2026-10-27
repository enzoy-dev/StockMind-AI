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
        previsao, avaliacao = prever_vendas(self.carregar(self.dados))
        self.assertEqual(len(previsao), 7)
        self.assertEqual(
            previsao["data"].iloc[0], self.dados["data"].iloc[-1] + pd.Timedelta(days=1)
        )
        self.assertAlmostEqual(previsao["previsao"].iloc[0], 50)
        erros = avaliacao.set_index("modelo")
        self.assertAlmostEqual(erros.loc["Regressão linear", "mae_teste"], 0)
        self.assertAlmostEqual(erros.loc["Última venda", "mae_teste"], 4)
        self.assertAlmostEqual(erros.loc["Semana anterior", "mae_teste"], 7)
        self.assertTrue(erros.loc["Regressão linear", "selecionado"])
        self.assertEqual(avaliacao["selecionado"].sum(), 1)

    def test_avaliacao_nao_treina_com_a_semana_de_teste(self):
        self.dados.loc[33:, "vendas"] += 100
        _, avaliacao = prever_vendas(self.carregar(self.dados))
        erros = avaliacao.set_index("modelo")
        self.assertAlmostEqual(erros.loc["Regressão linear", "mae_teste"], 100)
        self.assertAlmostEqual(
            erros.loc["Regressão com dia da semana", "mae_teste"], 100
        )

    def test_semana_de_teste_nao_muda_a_escolha(self):
        _, original = prever_vendas(self.carregar(self.dados))
        self.dados.loc[33:, "vendas"] += 100
        _, alterada = prever_vendas(self.carregar(self.dados))
        pd.testing.assert_frame_equal(
            original[["modelo", "mae_validacao", "selecionado"]],
            alterada[["modelo", "mae_validacao", "selecionado"]],
        )
        self.assertFalse(original["mae_teste"].equals(alterada["mae_teste"]))

    def test_validacao_nao_treina_com_a_propria_semana(self):
        # A seleção usa dados até o índice 25; a validação é do índice 26 ao 32.
        self.dados.loc[26:32, "vendas"] += 100
        _, avaliacao = prever_vendas(self.carregar(self.dados))
        erros = avaliacao.set_index("modelo")
        self.assertAlmostEqual(erros.loc["Regressão linear", "mae_validacao"], 100)
        self.assertAlmostEqual(
            erros.loc["Regressão com dia da semana", "mae_validacao"], 100
        )

    def test_dia_da_semana_aprende_padrao_com_tendencia(self):
        datas = pd.date_range("2026-01-01", periods=70)
        efeitos = [0, 10, 3, 15, 8, 30, 25]
        dados = pd.DataFrame(
            {
                "data": datas,
                "vendas": [
                    10 + 2 * i + efeitos[data.dayofweek] for i, data in enumerate(datas)
                ],
            }
        )
        previsao, avaliacao = prever_vendas(self.carregar(dados))
        erros = avaliacao.set_index("modelo")
        nome = "Regressão com dia da semana"
        self.assertTrue(erros.loc[nome, "selecionado"])
        self.assertAlmostEqual(erros.loc[nome, "mae_validacao"], 0)
        self.assertAlmostEqual(erros.loc[nome, "mae_teste"], 0)
        self.assertGreater(erros.loc["Regressão linear", "mae_teste"], 1)
        for i, linha in enumerate(previsao.itertuples(), start=70):
            esperado = 10 + 2 * i + efeitos[linha.data.dayofweek]
            self.assertAlmostEqual(linha.previsao, esperado)

    def test_semana_anterior_preserva_o_dia_da_semana(self):
        datas = pd.date_range("2026-01-01", periods=45)
        padrao = [3, 5, 7, 9, 10, 30, 25]
        dados = pd.DataFrame(
            {"data": datas, "vendas": [padrao[data.dayofweek] for data in datas]}
        )
        previsao, avaliacao = prever_vendas(self.carregar(dados))
        escolhido = avaliacao.loc[avaliacao["selecionado"], "modelo"].iloc[0]
        self.assertEqual(escolhido, "Semana anterior")
        self.assertEqual(
            previsao["previsao"].tolist(),
            [padrao[data.dayofweek] for data in previsao["data"]],
        )

    def test_empate_prefere_referencia_mais_simples(self):
        for vendas in (0, 10):
            with self.subTest(vendas=vendas):
                self.dados["vendas"] = vendas
                previsao, avaliacao = prever_vendas(self.carregar(self.dados))
                escolhido = avaliacao.loc[avaliacao["selecionado"], "modelo"].iloc[0]
                self.assertEqual(escolhido, "Última venda")
                self.assertEqual(previsao["previsao"].tolist(), [vendas] * 7)

    def test_aceita_o_minimo_de_30_dias(self):
        dados = self.carregar(self.dados.iloc[:30])
        previsao, avaliacao = prever_vendas(dados)
        self.assertEqual(len(previsao), 7)
        self.assertEqual(len(avaliacao), 4)
        self.assertTrue(avaliacao[["mae_validacao", "mae_teste"]].notna().all().all())

    def test_previsao_nao_pode_ser_negativa(self):
        self.dados["vendas"] = list(range(40, 0, -1))
        previsao, _ = prever_vendas(self.carregar(self.dados))
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

    def test_interface_mostra_comparacao_e_aguarda_upload(self):
        from streamlit.testing.v1 import AppTest

        interface = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run(
            timeout=30
        )
        self.assertFalse(interface.exception)
        self.assertEqual(len(interface.dataframe), 2)
        comparacao = interface.dataframe[1].value
        self.assertEqual(len(comparacao), 4)
        self.assertEqual(comparacao["Usado na previsão"].sum(), 1)
        self.assertTrue(
            any("Método usado na previsão:" in aviso.value for aviso in interface.info)
        )
        interface.radio[0].set_value("Enviar CSV").run(timeout=30)
        self.assertFalse(interface.exception)
        self.assertEqual(len(interface.dataframe), 0)


if __name__ == "__main__":
    unittest.main()
