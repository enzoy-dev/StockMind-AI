"""Cenários de previsão, separação temporal e faixas sem dados futuros."""

import unittest
import warnings

import numpy as np
import pandas as pd

from stockmind.forecasting import (
    MODELO_CONTEXTO,
    MODELO_INICIAL,
    analisar_previsoes,
    prever_com_modelo,
)


def historico(n=140, sku="A"):
    return pd.DataFrame(
        {
            "sku": sku,
            "data": pd.date_range("2025-01-01", periods=n),
            "vendas": np.arange(n) + 20,
        }
    )


class TestForecasting(unittest.TestCase):
    def test_previsao_por_produto_sem_misturar_series(self):
        a = historico(140, "001")
        b = historico(140, "002")
        b["vendas"] = 500
        dados = pd.concat([a, b], ignore_index=True)
        original = dados.copy(deep=True)
        previsao, metricas = analisar_previsoes(dados)
        self.assertEqual(len(previsao), 14)
        self.assertEqual(
            metricas.groupby("sku")["selecionado"].sum().to_dict(), {"001": 1, "002": 1}
        )
        valores_a = previsao.loc[previsao["sku"].eq("001"), "previsao"].to_numpy()
        np.testing.assert_allclose(valores_a, np.arange(160, 167))
        self.assertTrue(
            previsao.loc[previsao["sku"].eq("002"), "previsao"].eq(500).all()
        )
        self.assertGreater(previsao["data"].min(), dados["data"].max())
        pd.testing.assert_frame_equal(dados, original)

    def test_teste_final_nao_escolhe_modelo_nem_calibra_faixas(self):
        dados = historico()
        previsao, original = analisar_previsoes(dados)
        dados.loc[len(dados) - 7 :, "vendas"] += 500
        alterada, metricas = analisar_previsoes(dados)
        pd.testing.assert_frame_equal(
            original[["modelo", "mae_validacao", "selecionado", "amostras_calibracao"]],
            metricas[["modelo", "mae_validacao", "selecionado", "amostras_calibracao"]],
        )
        largura_original = previsao["limite_superior"] - previsao["previsao"]
        largura_alterada = alterada["limite_superior"] - alterada["previsao"]
        np.testing.assert_allclose(largura_original, largura_alterada, atol=1e-9)
        erros = metricas.set_index("modelo")
        self.assertAlmostEqual(erros.loc["Regressão linear", "mae_teste"], 500)
        self.assertAlmostEqual(
            erros.loc["Regressão com dia da semana", "mae_teste"], 500
        )
        self.assertLess(erros.loc["Regressão linear", "vies_teste"], -499)

    def test_calibracao_nao_influencia_escolha(self):
        dados = historico()
        _, antes = analisar_previsoes(dados)
        dados.loc[len(dados) - 21 : len(dados) - 8, "vendas"] += 100
        previsao, depois = analisar_previsoes(dados)
        pd.testing.assert_frame_equal(
            antes[["modelo", "mae_validacao", "selecionado"]],
            depois[["modelo", "mae_validacao", "selecionado"]],
        )
        self.assertTrue(
            (previsao["limite_superior"] - previsao["previsao"]).gt(90).all()
        )

    def test_origens_multiplas_e_blocos_independentes(self):
        _, metricas = analisar_previsoes(historico())
        self.assertTrue(metricas["janelas_validacao"].eq(3).all())
        self.assertTrue(metricas["amostras_calibracao"].eq(14).all())
        self.assertTrue(
            (metricas["validacao_fim"] < metricas["calibracao_inicio"]).all()
        )
        self.assertTrue((metricas["calibracao_fim"] < metricas["teste_inicio"]).all())
        self.assertTrue(metricas["teste_fim"].eq(historico()["data"].iloc[-1]).all())

    def test_padrao_semanal_com_tendencia(self):
        dados = historico()
        efeitos = [0, 15, 3, 20, 6, 40, 30]
        dados["vendas"] = [
            20 + i + efeitos[d.dayofweek] for i, d in enumerate(dados["data"])
        ]
        previsao, metricas = analisar_previsoes(dados)
        escolhido = metricas.loc[metricas["selecionado"], "modelo"].iloc[0]
        self.assertEqual(escolhido, "Regressão com dia da semana")
        esperado = [
            20 + i + efeitos[d.dayofweek]
            for i, d in enumerate(previsao["data"], start=len(dados))
        ]
        np.testing.assert_allclose(previsao["previsao"], esperado)

    def test_referencia_semanal_preserva_calendario_em_mais_de_uma_semana(self):
        dados = historico()
        padrao = [5, 7, 9, 11, 20, 40, 15]
        dados["vendas"] = [padrao[d.dayofweek] for d in dados["data"]]
        previsao, metricas = analisar_previsoes(dados, 14)
        escolhido = metricas.loc[metricas["selecionado"], "modelo"].iloc[0]
        self.assertEqual(escolhido, "Semana anterior")
        self.assertEqual(
            previsao["previsao"].tolist(),
            [padrao[d.dayofweek] for d in previsao["data"]],
        )

    def test_empate_e_zeros_nao_fabricam_wape(self):
        dados = historico()
        dados["vendas"] = 0
        previsao, metricas = analisar_previsoes(dados)
        self.assertEqual(
            metricas.loc[metricas["selecionado"], "modelo"].iloc[0], "Última venda"
        )
        self.assertTrue(metricas["wape_teste"].isna().all())
        self.assertTrue(previsao["previsao"].eq(0).all())
        self.assertTrue(previsao["limite_inferior"].eq(0).all())
        self.assertTrue(previsao["limite_superior"].eq(0).all())
        self.assertTrue(metricas["cobertura_teste"].eq(100).all())

    def test_serie_curta_tem_estimativa_sem_erros_ou_faixas(self):
        for n in (1, 5, 27):
            with self.subTest(dias=n):
                dados = historico(n)
                previsao, metricas = analisar_previsoes(dados)
                self.assertEqual(len(previsao), 7)
                self.assertEqual(metricas["modelo"].iloc[0], MODELO_INICIAL)
                self.assertEqual(metricas["janelas_validacao"].iloc[0], 0)
                self.assertTrue(
                    metricas[["mae_validacao", "mae_teste", "cobertura_teste"]]
                    .isna()
                    .all()
                    .all()
                )
                self.assertTrue(
                    previsao[["limite_inferior", "limite_superior"]].isna().all().all()
                )
                self.assertTrue(previsao["status"].eq("historico_curto").all())
                self.assertAlmostEqual(
                    previsao["previsao"].iloc[0], dados["vendas"].tail(14).mean()
                )

    def test_catalogo_misto_preserva_ausencias_sem_avisos_de_concatenacao(self):
        longo = historico()
        novo = historico(1, "NOVO")
        novo["data"] = longo["data"].iloc[-1]
        with warnings.catch_warnings(record=True) as avisos:
            warnings.simplefilter("always")
            _, metricas = analisar_previsoes(pd.concat([longo, novo]))
        self.assertFalse(avisos)
        erros_novo = metricas.loc[metricas["sku"].eq("NOVO"), "mae_teste"]
        self.assertTrue(erros_novo.isna().all())

    def test_30_dias_preservam_avaliacao_sem_inventar_faixa(self):
        previsao, metricas = analisar_previsoes(historico(30))
        self.assertTrue(metricas["janelas_validacao"].eq(1).all())
        self.assertTrue(metricas["mae_teste"].notna().all())
        self.assertTrue(metricas["amostras_calibracao"].eq(0).all())
        self.assertTrue(previsao["limite_inferior"].isna().all())

    def test_horizontes_sao_avaliados_na_propria_duracao(self):
        dados = historico(400)
        for horizonte in (7, 14, 30, 90):
            with self.subTest(horizonte=horizonte):
                previsao, metricas = analisar_previsoes(dados, horizonte)
                self.assertEqual(len(previsao), horizonte)
                dias = (metricas["teste_fim"] - metricas["teste_inicio"]).dt.days + 1
                self.assertTrue(dias.eq(horizonte).all())
                self.assertTrue(metricas["amostras_calibracao"].eq(2 * horizonte).all())

    def test_horizonte_longo_sem_historico_suficiente_e_explicito(self):
        previsao, metricas = analisar_previsoes(historico(180), 90)
        self.assertEqual(len(previsao), 90)
        self.assertTrue(previsao["status"].eq("historico_curto").all())
        self.assertTrue(metricas["mae_teste"].isna().all())

    def test_previsao_e_limite_inferior_nao_negativos(self):
        dados = historico()
        dados["vendas"] = np.arange(140, 0, -1)
        previsao, _ = analisar_previsoes(dados)
        self.assertTrue(previsao["previsao"].ge(0).all())
        self.assertTrue(previsao["limite_inferior"].ge(0).all())
        self.assertTrue(
            previsao["limite_superior"].ge(previsao["limite_inferior"]).all()
        )

    def test_croston_sba_lida_com_vendas_esparsas(self):
        dados = historico()
        dados["vendas"] = 0
        dados.loc[::11, "vendas"] = 10
        previsao = prever_com_modelo(dados, "Croston-SBA", 30)
        self.assertTrue(np.isfinite(previsao).all())
        self.assertTrue((previsao > 0).all())
        self.assertLess(previsao.mean(), 2)
        _, metricas = analisar_previsoes(dados)
        self.assertIn("Croston-SBA", metricas["modelo"].tolist())

    def test_contexto_completo_pode_ser_selecionado_e_responde_ao_plano(self):
        dados, plano = self.contextual()
        previsao, metricas = analisar_previsoes(dados, contexto_futuro=plano)
        escolhido = metricas.loc[metricas["selecionado"], "modelo"].iloc[0]
        self.assertEqual(escolhido, MODELO_CONTEXTO)
        self.assertTrue(previsao["contexto_utilizado"].all())
        plano_caro = plano.copy()
        plano_caro["preco"] = 30
        cara, nova_avaliacao = analisar_previsoes(dados, contexto_futuro=plano_caro)
        self.assertLess(cara["previsao"].mean(), previsao["previsao"].mean() - 20)
        pd.testing.assert_frame_equal(metricas, nova_avaliacao)

    def test_sem_plano_futuro_nao_imputa_covariaveis(self):
        dados, plano = self.contextual()
        for futuro in (None, plano.iloc[:-1], plano.drop(columns="preco")):
            with self.subTest(plano_incompleto=futuro is not None):
                previsao, metricas = analisar_previsoes(dados, contexto_futuro=futuro)
                self.assertNotIn(MODELO_CONTEXTO, metricas["modelo"].tolist())
                self.assertFalse(previsao["contexto_utilizado"].any())
                self.assertTrue(
                    previsao["observacao"].str.contains("Contexto ignorado").all()
                )

    def test_plano_futuro_sem_contexto_historico_tem_aviso(self):
        dados, plano = self.contextual()
        previsao, metricas = analisar_previsoes(
            dados.drop(columns=["preco", "promocao", "feriado"]), contexto_futuro=plano
        )
        self.assertNotIn(MODELO_CONTEXTO, metricas["modelo"].tolist())
        self.assertTrue(previsao["observacao"].str.contains("Contexto ignorado").all())

    def test_vendas_futuras_nao_entram_no_modelo_contextual(self):
        dados, plano = self.contextual()
        previsao, original = analisar_previsoes(dados, contexto_futuro=plano)
        dados.loc[len(dados) - 7 :, "vendas"] += 1000
        alterada, metricas = analisar_previsoes(dados, contexto_futuro=plano)
        pd.testing.assert_frame_equal(
            original[["modelo", "mae_validacao", "selecionado"]],
            metricas[["modelo", "mae_validacao", "selecionado"]],
        )
        np.testing.assert_allclose(
            previsao["limite_superior"] - previsao["previsao"],
            alterada["limite_superior"] - alterada["previsao"],
            atol=1e-9,
        )

    def test_horizonte_invalido(self):
        for horizonte in (0, 8, 100, True, 7.0, None):
            with self.subTest(horizonte=horizonte), self.assertRaises(ValueError):
                analisar_previsoes(historico(), horizonte)

    @staticmethod
    def contextual():
        dados = historico(260)
        rng = np.random.default_rng(7)
        dados["preco"] = rng.integers(8, 19, len(dados))
        dados["promocao"] = rng.integers(0, 2, len(dados))
        dados["feriado"] = rng.integers(0, 2, len(dados))
        dados["vendas"] = (
            100
            + np.arange(len(dados))
            - 3 * dados["preco"]
            + 15 * dados["promocao"]
            + 20 * dados["feriado"]
        )
        plano = pd.DataFrame(
            {
                "sku": "A",
                "data": pd.date_range(
                    dados["data"].iloc[-1] + pd.Timedelta(days=1), periods=7
                ),
                "preco": 12,
                "promocao": 0,
                "feriado": 0,
            }
        )
        return dados, plano


if __name__ == "__main__":
    unittest.main()
