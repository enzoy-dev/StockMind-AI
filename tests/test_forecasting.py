"""Cenários de previsão, separação temporal e faixas sem dados futuros."""

import unittest
import warnings
from unittest.mock import patch

import numpy as np
import pandas as pd

from stockmind.forecasting import (
    MODELO_ATRASOS,
    MODELO_CONTEXTO,
    MODELO_INICIAL,
    analisar_previsoes,
    comparar_horizontes,
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

    def test_atrasos_so_entram_se_todas_as_origens_tem_treino_suficiente(self):
        _, curta = analisar_previsoes(historico(80))
        _, suficiente = analisar_previsoes(historico(84))
        self.assertNotIn(MODELO_ATRASOS, curta["modelo"].tolist())
        self.assertIn(MODELO_ATRASOS, suficiente["modelo"].tolist())
        with self.assertRaises(ValueError):
            prever_com_modelo(historico(41), MODELO_ATRASOS)

    def test_atrasos_usam_apenas_passado_em_cada_alvo_e_recursao_no_futuro(self):
        dados = historico(70)
        ajustes, atributos_previstos = [], []

        class ModeloInstrumentado:
            def fit(self, atributos, alvo):
                ajustes.append((atributos.copy(deep=True), np.array(alvo)))
                return self

            def predict(self, atributos):
                atributos_previstos.append(atributos.copy(deep=True))
                return np.array([atributos["atraso_1"].iloc[0] + 2])

        contexto = pd.DataFrame({"vendas": [-999999] * 30})
        with patch(
            "stockmind.forecasting.make_pipeline", return_value=ModeloInstrumentado()
        ):
            resultado = prever_com_modelo(dados, MODELO_ATRASOS, 30, contexto)
        valores = dados["vendas"].to_numpy()
        np.testing.assert_array_equal(resultado, valores[-1] + 2 * np.arange(1, 31))
        treino, alvos = ajustes[0]
        np.testing.assert_array_equal(alvos, valores[14:])
        self.assertEqual(treino["atraso_1"].iloc[0], valores[13])
        self.assertEqual(treino["atraso_7"].iloc[0], valores[7])
        self.assertEqual(treino["atraso_14"].iloc[0], valores[0])
        self.assertAlmostEqual(treino["media_7"].iloc[0], valores[7:14].mean())
        self.assertAlmostEqual(treino["media_14"].iloc[0], valores[:14].mean())
        self.assertEqual(atributos_previstos[1]["atraso_1"].iloc[0], resultado[0])
        self.assertEqual(atributos_previstos[7]["atraso_7"].iloc[0], resultado[0])
        self.assertEqual(atributos_previstos[14]["atraso_14"].iloc[0], resultado[0])
        esperado = np.r_[valores[-6:], resultado[0]].mean()
        self.assertAlmostEqual(atributos_previstos[1]["media_7"].iloc[0], esperado)
        self.assertAlmostEqual(
            atributos_previstos[14]["media_14"].iloc[0], resultado[:14].mean()
        )

    def test_atrasos_aprendem_autocorrelacao_em_serie_sintetica(self):
        dados = historico(280)
        dias = np.arange(len(dados))
        dados["vendas"] = np.round(
            100 + 20 * np.sin(2 * np.pi * dias / 30) + 5 * np.sin(2 * np.pi * dias / 7)
        )
        _, metricas = analisar_previsoes(dados)
        erros = metricas.set_index("modelo")
        self.assertLess(
            erros.loc[MODELO_ATRASOS, "mae_teste"],
            erros.loc["Semana anterior", "mae_teste"],
        )

    def test_atrasos_nao_usam_alvos_do_bloco_de_teste(self):
        dados = historico()
        _, original = analisar_previsoes(dados)
        dados.loc[len(dados) - 7 :, "vendas"] += 1000
        _, alterada = analisar_previsoes(dados)
        a = original.set_index("modelo").loc[MODELO_ATRASOS]
        b = alterada.set_index("modelo").loc[MODELO_ATRASOS]
        self.assertEqual(a["mae_validacao"], b["mae_validacao"])
        self.assertGreater(b["mae_teste"] - a["mae_teste"], 990)

    def test_comparacao_tem_uma_linha_por_produto_e_horizonte(self):
        dados = pd.concat([historico(150, "A"), historico(150, "B")], ignore_index=True)
        resumo = comparar_horizontes(dados)
        self.assertEqual(len(resumo), 6)
        self.assertFalse(resumo.duplicated(["sku", "horizonte"]).any())
        self.assertTrue(resumo["selecionado"].all())
        self.assertEqual(set(resumo["horizonte"]), {7, 14, 30})
        duracao = (resumo["teste_fim"] - resumo["teste_inicio"]).dt.days + 1
        self.assertTrue(duracao.eq(resumo["horizonte"]).all())
        self.assertTrue(
            resumo["comparacao_observacao"]
            .str.contains("durações de teste distintas")
            .all()
        )

    def test_comparacao_nao_troca_escolha_por_resultado_do_teste(self):
        dados = historico()
        dados.loc[len(dados) - 7 :, "vendas"] = dados["vendas"].iloc[-8]
        resumo = comparar_horizontes(dados, horizontes=(7,))
        linha = resumo.iloc[0]
        self.assertEqual(linha["modelo"], "Regressão linear")
        self.assertAlmostEqual(linha["mae_validacao"], 0)
        self.assertGreater(linha["mae_teste"], linha["mae_teste_semana_anterior"])
        self.assertAlmostEqual(linha["ganho_mae_teste_pct"], -100 / 3)

    def test_ganho_e_indefinido_quando_referencia_tem_erro_zero_ou_ausente(self):
        dados = historico()
        dados["vendas"] = 0
        resumo = comparar_horizontes(dados)
        self.assertTrue(resumo["ganho_mae_teste_pct"].isna().all())
        self.assertTrue(resumo["mae_teste_semana_anterior"].eq(0).all())
        self.assertTrue(resumo["wape_teste"].isna().all())
        curto = comparar_horizontes(historico(5))
        self.assertEqual(len(curto), 3)
        self.assertTrue(curto["status"].eq("historico_curto").all())
        self.assertTrue(
            curto[
                [
                    "mae_teste",
                    "mae_teste_semana_anterior",
                    "ganho_mae_teste_pct",
                    "wape_teste",
                ]
            ]
            .isna()
            .all()
            .all()
        )

    def test_calendario_futuro_pode_ser_reutilizado_em_varios_horizontes(self):
        dados, curto = self.contextual()
        plano = pd.DataFrame(
            {
                "sku": "A",
                "data": pd.date_range(curto["data"].iloc[0], periods=30),
                "preco": 12,
                "promocao": 0,
                "feriado": 0,
            }
        )
        resumo = comparar_horizontes(dados, plano)
        self.assertTrue(resumo["modelo"].eq(MODELO_CONTEXTO).all())
        self.assertTrue(resumo["contexto_utilizado"].all())
        previsto_curto, metrica_curta = analisar_previsoes(dados, contexto_futuro=curto)
        previsto_longo, metrica_longa = analisar_previsoes(dados, contexto_futuro=plano)
        pd.testing.assert_frame_equal(previsto_curto, previsto_longo)
        pd.testing.assert_frame_equal(metrica_curta, metrica_longa)

    def test_comparacao_rejeita_horizontes_duplicados_ou_vazios(self):
        for horizontes in ((), (7, 7), (8,)):
            with self.subTest(horizontes=horizontes), self.assertRaises(ValueError):
                comparar_horizontes(historico(), horizontes=horizontes)

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
