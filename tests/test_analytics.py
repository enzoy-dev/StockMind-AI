"""Classificação descritiva e políticas sugeridas sem alterar entradas."""

import math
import unittest

import pandas as pd

from stockmind.analytics import (
    analisar_prazos,
    classificar_produtos,
    sugerir_seguranca,
)


def historico(valores, dias=28):
    return pd.DataFrame(
        [
            {"sku": sku, "data": data, "vendas": vendas, "disponivel": 1}
            for sku, vendas in valores.items()
            for data in pd.date_range("2026-01-01", periods=dias)
        ]
    )


class TestClassificacao(unittest.TestCase):
    def test_limites_abc_usam_acumulado_anterior(self):
        resultado = classificar_produtos(historico({"A": 80, "B": 15, "C": 5}))
        self.assertEqual(resultado["classe_abc"].tolist(), ["A", "B", "C"])
        self.assertEqual(resultado["acumulado_pct"].tolist(), [80, 95, 100])
        self.assertTrue(resultado["base_abc"].eq("unidades_vendidas").all())

    def test_item_que_cruza_limite_continua_na_classe_anterior(self):
        resultado = classificar_produtos(historico({"A": 96, "B": 3, "C": 1}))
        self.assertEqual(resultado.iloc[0]["classe_abc"], "A")
        self.assertEqual(resultado.iloc[1]["classe_abc"], "C")

    def test_empates_ficam_juntos_e_nao_dependem_da_ordem(self):
        vendas = historico({"B": 40, "A": 40, "C": 15, "D": 5})
        antes = vendas.copy(deep=True)
        resultado = classificar_produtos(vendas)
        reverso = classificar_produtos(vendas.iloc[::-1])
        pd.testing.assert_frame_equal(resultado, reverso)
        pd.testing.assert_frame_equal(vendas, antes)
        self.assertEqual(
            resultado.set_index("sku").loc[["A", "B"], "classe_abc"].tolist(),
            ["A", "A"],
        )

    def test_abc_usa_receita_somente_com_precos_completos(self):
        vendas = historico({"A": 1, "B": 20})
        vendas["preco"] = vendas["sku"].map({"A": 100, "B": 1})
        resultado = classificar_produtos(vendas)
        self.assertEqual(resultado.iloc[0]["sku"], "A")
        self.assertTrue(resultado["base_abc"].eq("faturamento_registrado").all())
        self.assertEqual(resultado.iloc[0]["valor_base"], 2800)
        vendas.loc[vendas["sku"].eq("B"), "preco"] = math.nan
        resultado = classificar_produtos(vendas)
        self.assertEqual(resultado.iloc[0]["sku"], "B")
        self.assertTrue(resultado["base_abc"].eq("unidades_vendidas").all())
        self.assertEqual(resultado.set_index("sku").loc["A", "valor_base"], 28)
        self.assertTrue(
            resultado["observacoes"].str.contains("todos os produtos").all()
        )

    def test_precos_vazios_fazem_fallback_global(self):
        vendas = historico({"A": 10})
        vendas["preco"] = ""
        resultado = classificar_produtos(vendas)
        self.assertEqual(resultado.iloc[0]["base_abc"], "unidades_vendidas")

    def test_xyz_exclui_dias_censurados_mas_abc_mantem_vendas(self):
        vendas = historico({"A": 10}, dias=30)
        vendas.loc[:1, "disponivel"] = 0
        vendas.loc[:1, "vendas"] = 0
        resultado = classificar_produtos(vendas).iloc[0]
        self.assertEqual(resultado["classe_xyz"], "X")
        self.assertEqual(resultado["cv"], 0)
        self.assertEqual(resultado["valor_base"], 280)
        self.assertIn("2 dias", resultado["observacoes"])
        vendas.loc[2, "disponivel"] = 0
        resultado = classificar_produtos(vendas).iloc[0]
        self.assertEqual(resultado["classe_xyz"], "indefinida")
        self.assertTrue(pd.isna(resultado["cv"]))

    def test_xyz_curto_e_zero_sao_indefinidos(self):
        for vendas in (historico({"A": 10}, dias=27), historico({"A": 0})):
            resultado = classificar_produtos(vendas).iloc[0]
            self.assertEqual(resultado["classe_xyz"], "indefinida")
            self.assertTrue(pd.isna(resultado["cv"]))
        resultado = classificar_produtos(historico({"A": 0, "B": 0}))
        self.assertTrue(resultado["classe_abc"].eq("indefinida").all())
        self.assertTrue(resultado["participacao_pct"].eq(0).all())

    def test_xyz_distingue_variabilidade_media_e_alta(self):
        vendas = historico({"A": 0, "B": 0})
        vendas.loc[vendas["sku"].eq("A"), "vendas"] = [5, 15] * 14
        vendas.loc[vendas["sku"].eq("B"), "vendas"] = [0] * 27 + [100]
        resultado = classificar_produtos(vendas).set_index("sku")
        self.assertEqual(resultado.loc["A", "classe_xyz"], "Y")
        self.assertEqual(resultado.loc["B", "classe_xyz"], "Z")
        self.assertAlmostEqual(
            resultado.loc["A", "cv"], pd.Series([5, 15] * 14).std(ddof=1) / 10
        )

    def test_zero_com_base_total_positiva_e_classe_c(self):
        resultado = classificar_produtos(historico({"A": 10, "B": 0})).set_index("sku")
        self.assertEqual(resultado.loc["B", "classe_abc"], "C")

    def test_disponibilidade_desconhecida_nao_vira_demanda_confirmada(self):
        vendas = historico({"A": 10}).drop(columns="disponivel")
        resultado = classificar_produtos(vendas).iloc[0]
        self.assertEqual(resultado["classe_abc"], "A")
        self.assertEqual(resultado["classe_xyz"], "indefinida")
        self.assertTrue(pd.isna(resultado["cv"]))
        self.assertIn("não informada", resultado["observacoes"])

    def test_rejeita_numeros_datas_e_disponibilidade_invalidos(self):
        for campo, valor in [
            ("vendas", -1),
            ("vendas", 1.5),
            ("preco", -2),
            ("preco", math.inf),
            ("disponivel", 2),
            ("data", "2026-02-30"),
        ]:
            vendas = historico({"A": 1}).astype(object)
            if campo == "preco":
                vendas["preco"] = 1.0
            vendas.loc[0, campo] = valor
            with self.subTest(campo=campo, valor=valor), self.assertRaises(ValueError):
                classificar_produtos(vendas)
        vendas = historico({"A": 1})
        with self.assertRaises(ValueError):
            classificar_produtos(pd.concat([vendas, vendas.iloc[:1]]))


class TestPrazos(unittest.TestCase):
    def setUp(self):
        self.fornecedores = pd.DataFrame(
            [
                {"fornecedor_id": "F1", "nome": "Fornecedor 1", "prazo_dias": 4},
                {"fornecedor_id": "F2", "nome": "Fornecedor 2", "prazo_dias": 2},
            ]
        )
        self.origem = pd.Timestamp("2026-06-01")
        self.entregas = self.criar_entregas([2, 4, 6, 8, 10])

    def criar_entregas(self, prazos):
        return pd.DataFrame(
            [
                {
                    "entrega_id": f"E{i}",
                    "fornecedor_id": "F1",
                    "data_pedido": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i),
                    "data_prevista": pd.Timestamp("2026-01-05") + pd.Timedelta(days=i),
                    "data_recebida": pd.Timestamp("2026-01-01")
                    + pd.Timedelta(days=i + prazo),
                }
                for i, prazo in enumerate(prazos)
            ]
        )

    def test_estatisticas_e_sugestao_nao_alteram_prazo_manual(self):
        antes = self.fornecedores.copy(deep=True)
        resultado = analisar_prazos(
            self.entregas, self.fornecedores, self.origem
        ).set_index("fornecedor_id")
        f1 = resultado.loc["F1"]
        self.assertEqual(f1["prazo_manual"], 4)
        self.assertEqual(f1["prazo_medio"], 6)
        self.assertAlmostEqual(
            f1["prazo_desvio"], pd.Series([2, 4, 6, 8, 10]).std(ddof=1)
        )
        self.assertEqual(f1["prazo_p90"], 10)
        self.assertEqual(f1["prazo_sugerido"], 10)
        self.assertEqual(f1["amostras"], 5)
        self.assertEqual(f1["atrasos_pct"], 60)
        self.assertEqual(f1["status"], "sugerido")
        self.assertEqual(resultado.loc["F2", "status"], "sem_entregas")
        pd.testing.assert_frame_equal(antes, self.fornecedores)

    def test_recebimentos_depois_da_referencia_nao_vazam_para_estatisticas(self):
        futuras = self.entregas.copy()
        futuras["entrega_id"] = futuras["entrega_id"] + "F"
        for coluna in ["data_pedido", "data_prevista", "data_recebida"]:
            futuras[coluna] += pd.Timedelta(days=365)
        resultado = analisar_prazos(
            pd.concat([self.entregas, futuras]), self.fornecedores, self.origem
        )
        linha = resultado.iloc[0]
        self.assertEqual(linha["amostras"], 5)
        self.assertEqual(linha["prazo_medio"], 6)
        self.assertIn("5 recebimentos", linha["observacoes"])

    def test_menos_de_cinco_nao_sugere_prazo(self):
        resultado = analisar_prazos(
            self.entregas.iloc[:4], self.fornecedores, self.origem
        ).iloc[0]
        self.assertEqual(resultado["status"], "amostra_insuficiente")
        self.assertTrue(pd.isna(resultado["prazo_sugerido"]))
        resultado = analisar_prazos(
            self.entregas.iloc[:1], self.fornecedores, self.origem
        ).iloc[0]
        self.assertTrue(pd.isna(resultado["prazo_desvio"]))

    def test_prazo_acima_de_sessenta_nao_e_truncado(self):
        entregas = self.criar_entregas([90] * 5)
        resultado = analisar_prazos(entregas, self.fornecedores, self.origem).iloc[0]
        self.assertEqual(resultado["prazo_p90"], 90)
        self.assertTrue(pd.isna(resultado["prazo_sugerido"]))
        self.assertEqual(resultado["prazo_manual"], 4)
        self.assertEqual(resultado["status"], "fora_limite_planejamento")

    def test_entregas_no_mesmo_dia_podem_sugerir_zero(self):
        resultado = analisar_prazos(
            self.criar_entregas([0] * 5), self.fornecedores, self.origem
        ).iloc[0]
        self.assertEqual(resultado["prazo_sugerido"], 0)
        self.assertEqual(resultado["atrasos_pct"], 0)

    def test_rejeita_fornecedor_desconhecido_duplicatas_e_datas_impossiveis(self):
        for entregas in [
            self.entregas.assign(fornecedor_id="DESCONHECIDO"),
            pd.concat([self.entregas, self.entregas.iloc[:1]]),
            self.entregas.assign(data_recebida="2025-01-01"),
            self.entregas.assign(data_recebida=None),
        ]:
            with self.subTest(), self.assertRaises(ValueError):
                analisar_prazos(entregas, self.fornecedores, self.origem)


class TestSeguranca(unittest.TestCase):
    def setUp(self):
        self.produtos = pd.DataFrame(
            [
                {"sku": "A", "estoque_seguranca": 12},
                {"sku": "B", "estoque_seguranca": 5},
            ]
        )
        self.erros = self.criar_erros([1, 2, 3, 4, 10])

    def criar_erros(self, valores, prazo=2):
        return pd.DataFrame(
            [
                {
                    "sku": "A",
                    "origem": pd.Timestamp("2026-01-01") + pd.Timedelta(days=prazo * i),
                    "prazo_dias": prazo,
                    "erro_acumulado": erro,
                    "modelo": "Regressão linear",
                }
                for i, erro in enumerate(valores)
            ]
        )

    def test_quantil_acumulado_e_arredondado_para_cima_sem_alterar_catalogo(self):
        antes = self.produtos.copy(deep=True)
        resultado = sugerir_seguranca(self.produtos, self.erros).set_index("sku")
        self.assertEqual(resultado.loc["A", "amostras"], 5)
        self.assertEqual(resultado.loc["A", "seguranca_sugerida"], 8)
        self.assertEqual(resultado.loc["A", "seguranca_manual"], 12)
        self.assertEqual(resultado.loc["A", "status"], "sugerida")
        self.assertTrue(pd.isna(resultado.loc["B", "seguranca_sugerida"]))
        pd.testing.assert_frame_equal(antes, self.produtos)

    def test_erros_negativos_suficientes_podem_sugerir_zero(self):
        resultado = sugerir_seguranca(
            self.produtos, self.criar_erros([-10, -5, -3, -2, -1])
        ).iloc[0]
        self.assertEqual(resultado["seguranca_sugerida"], 0)

    def test_menos_de_cinco_nao_vira_seguranca_zero(self):
        resultado = sugerir_seguranca(self.produtos, self.erros.iloc[:4]).iloc[0]
        self.assertEqual(resultado["status"], "amostra_insuficiente")
        self.assertTrue(pd.isna(resultado["seguranca_sugerida"]))
        self.assertEqual(resultado["seguranca_manual"], 12)

    def test_sobreposicoes_nao_inflam_tamanho_da_amostra(self):
        erros = self.criar_erros([1, 2, 3, 4, 5, 6, 7])
        erros["origem"] = pd.date_range("2026-01-01", periods=7)
        resultado = sugerir_seguranca(self.produtos, erros).iloc[0]
        self.assertEqual(resultado["amostras"], 4)
        self.assertTrue(pd.isna(resultado["seguranca_sugerida"]))
        self.assertIn("3 blocos", resultado["observacoes"])

    def test_blocos_adjacentes_nao_sao_sobrepostos_e_ordem_nao_importa(self):
        normal = sugerir_seguranca(self.produtos, self.erros)
        invertido = sugerir_seguranca(self.produtos, self.erros.iloc[::-1])
        pd.testing.assert_frame_equal(normal, invertido)
        self.assertEqual(normal.iloc[0]["amostras"], 5)

    def test_janelas_duplicadas_nao_inflam_amostras_e_conflitos_sao_rejeitados(self):
        duplicados = pd.concat([self.erros, self.erros.iloc[:1]], ignore_index=True)
        resultado = sugerir_seguranca(self.produtos, duplicados).iloc[0]
        self.assertEqual(resultado["amostras"], 5)
        self.assertEqual(resultado["seguranca_sugerida"], 8)
        duplicados.loc[5, "erro_acumulado"] = 100
        with self.assertRaisesRegex(ValueError, "conflitantes"):
            sugerir_seguranca(self.produtos, duplicados)

    def test_prazo_zero_nao_fabrica_amostras_independentes(self):
        resultado = sugerir_seguranca(
            self.produtos, self.criar_erros([1] * 10, prazo=0)
        ).iloc[0]
        self.assertEqual(resultado["amostras"], 0)
        self.assertTrue(pd.isna(resultado["seguranca_sugerida"]))

    def test_erros_proxy_nao_entram_na_seguranca_automatica(self):
        erros = self.criar_erros([100] * 10)
        erros["proxy"] = True
        resultado = sugerir_seguranca(self.produtos, erros).iloc[0]
        self.assertEqual(resultado["amostras"], 0)
        self.assertTrue(pd.isna(resultado["seguranca_sugerida"]))
        self.assertIn("10 blocos proxy", resultado["observacoes"])
        erros = self.erros.assign(proxy=False)
        self.assertEqual(sugerir_seguranca(self.produtos, erros).iloc[0]["amostras"], 5)

    def test_validacao_de_nivel_minimo_produto_e_erro(self):
        for argumentos in [
            {"nivel": 0},
            {"nivel": 1},
            {"nivel": math.nan},
            {"nivel": True},
            {"min_amostras": 4},
            {"min_amostras": 5.5},
        ]:
            with self.subTest(argumentos=argumentos), self.assertRaises(ValueError):
                sugerir_seguranca(self.produtos, self.erros, **argumentos)
        for erros in [
            self.erros.assign(sku="DESCONHECIDO"),
            self.erros.assign(erro_acumulado=math.inf),
            self.erros.assign(prazo_dias=-1),
        ]:
            with self.subTest(), self.assertRaises(ValueError):
                sugerir_seguranca(self.produtos, erros)

    def test_nao_mistura_erros_de_modelos_ou_prazos_diferentes(self):
        for campo, valor in [("modelo", "Outro modelo"), ("prazo_dias", 3)]:
            erros = self.erros.copy()
            erros.loc[0, campo] = valor
            with self.subTest(campo=campo), self.assertRaises(ValueError):
                sugerir_seguranca(self.produtos, erros)

    def test_erros_ausentes_preservam_manual(self):
        resultado = sugerir_seguranca(self.produtos, None)
        self.assertTrue(resultado["seguranca_sugerida"].isna().all())
        self.assertEqual(resultado["seguranca_manual"].tolist(), [12, 5])


if __name__ == "__main__":
    unittest.main()
