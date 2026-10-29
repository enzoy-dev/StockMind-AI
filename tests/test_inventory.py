"""Regras de estoque com datas de recebimento, limites de cobertura e lotes."""

import unittest

import pandas as pd

from stockmind.inventory import planejar_estoque


class TestPlanejamentoEstoque(unittest.TestCase):
    def setUp(self):
        self.origem = pd.Timestamp("2026-01-01")
        self.previsoes = pd.DataFrame(
            {
                "sku": ["A"] * 30,
                "data": pd.date_range("2026-01-02", periods=30),
                "previsao": [10.0] * 30,
                "status": ["avaliado"] * 30,
            }
        )
        self.produtos = pd.DataFrame(
            [["A", "Produto A", "F1", 10, 5, 1, 12]],
            columns=[
                "sku",
                "nome",
                "fornecedor_id",
                "estoque_atual",
                "estoque_seguranca",
                "pedido_minimo",
                "multiplo_compra",
            ],
        )
        self.fornecedores = pd.DataFrame(
            [["F1", "Fornecedor 1", 2]],
            columns=["fornecedor_id", "nome", "prazo_dias"],
        )
        self.pedidos = pd.DataFrame(
            columns=["pedido_id", "sku", "quantidade", "data_entrega"]
        )

    def executar(self, **opcoes):
        return planejar_estoque(
            self.previsoes,
            self.produtos,
            self.fornecedores,
            self.pedidos,
            **opcoes,
        )

    def pedido(self, quantidade, dias, identificador="P1"):
        self.pedidos.loc[len(self.pedidos)] = [
            identificador,
            "A",
            quantidade,
            self.origem + pd.Timedelta(days=dias),
        ]

    def test_alvo_desconta_pedidos_e_arredonda_lotes(self):
        self.pedido(20, 1)
        saldos, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(compra["estoque_alvo"], 95)
        self.assertEqual(compra["posicao_estoque"], 30)
        self.assertEqual(compra["compra_sugerida"], 72)
        self.assertEqual(saldos.iloc[0]["recebimentos"], 20)
        self.assertEqual(saldos.iloc[0]["saldo_estimado"], 20)
        self.assertEqual(compra["primeira_falta"], pd.Timestamp("2026-01-05"))

    def test_recebimento_atrasado_nao_apaga_falta_anterior(self):
        self.produtos.loc[0, "estoque_atual"] = 0
        self.fornecedores.loc[0, "prazo_dias"] = 4
        self.pedido(100, 3)
        saldos, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(compra["primeira_falta"], pd.Timestamp("2026-01-02"))
        self.assertTrue(compra["risco_antes_reposicao"])
        self.assertTrue(saldos.iloc[0]["risco_falta"])
        # Déficits anteriores continuam na projeção aritmética assinada.
        self.assertEqual(saldos.iloc[2]["saldo_estimado"], 70)

    def test_pedido_fora_da_janela_nao_reduz_compra(self):
        self.produtos.loc[
            0, ["estoque_atual", "estoque_seguranca", "multiplo_compra"]
        ] = [0, 0, 1]
        self.pedido(50, 10)
        _, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(compra["em_transito"], 0)
        self.assertEqual(compra["em_transito_total"], 50)
        self.assertEqual(compra["em_transito_apos_janela"], 50)
        self.assertEqual(compra["compra_sugerida"], 90)

    def test_pedido_no_ultimo_dia_da_janela_e_considerado(self):
        self.pedido(20, 9)
        _, compras = self.executar()
        self.assertEqual(compras.iloc[0]["em_transito"], 20)

    def test_minimo_de_compra_so_se_aplica_quando_precisa(self):
        self.produtos.loc[
            0, ["estoque_atual", "estoque_seguranca", "pedido_minimo"]
        ] = [89, 0, 25]
        _, compras = self.executar()
        self.assertEqual(compras.iloc[0]["compra_sugerida"], 36)
        self.produtos.loc[0, "estoque_atual"] = 1000
        _, compras = self.executar()
        self.assertEqual(compras.iloc[0]["compra_sugerida"], 0)

    def test_cobertura_insuficiente_nao_inventa_recomendacao(self):
        self.previsoes = self.previsoes.iloc[:7]
        self.fornecedores.loc[0, "prazo_dias"] = 10
        saldos, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(len(saldos), 7)
        self.assertEqual(compra["status"], "horizonte_insuficiente")
        self.assertEqual(compra["horizonte_necessario"], 17)
        self.assertTrue(pd.isna(compra["estoque_alvo"]))
        self.assertTrue(pd.isna(compra["compra_sugerida"]))
        self.assertTrue(pd.isna(compra["excesso"]))

    def test_produto_sem_historico_nao_vira_demanda_zero(self):
        novo = self.produtos.iloc[0].copy()
        novo["sku"] = "B"
        novo["nome"] = "Produto novo"
        self.produtos.loc[1] = novo
        saldos, compras = self.executar()
        compra = compras.set_index("sku").loc["B"]
        self.assertEqual(compra["status"], "sem_previsao")
        self.assertTrue(pd.isna(compra["compra_sugerida"]))
        self.assertTrue(pd.isna(compra["excesso"]))
        self.assertNotIn("B", set(saldos["sku"]))

    def test_prazo_zero_nao_cria_risco_anterior_a_reposicao(self):
        self.fornecedores.loc[0, "prazo_dias"] = 0
        self.produtos.loc[0, "estoque_atual"] = 0
        _, compras = self.executar()
        compra = compras.iloc[0]
        self.assertFalse(compra["risco_antes_reposicao"])
        self.assertEqual(
            compra["data_reposicao_estimada"], self.origem + pd.Timedelta(days=1)
        )
        self.assertEqual(compra["horizonte_necessario"], 7)

    def test_recebimento_ocorre_antes_da_venda_do_dia(self):
        self.produtos.loc[0, "estoque_atual"] = 0
        self.pedido(10, 1)
        saldos, compras = self.executar()
        self.assertEqual(saldos.iloc[0]["saldo_estimado"], 0)
        self.assertFalse(saldos.iloc[0]["risco_falta"])
        self.assertEqual(compras.iloc[0]["primeira_falta"], pd.Timestamp("2026-01-03"))

    def test_dia_de_chegada_nao_conta_como_antes_da_reposicao(self):
        self.produtos.loc[0, "estoque_atual"] = 10
        _, compras = self.executar()
        self.assertEqual(compras.iloc[0]["primeira_falta"], pd.Timestamp("2026-01-03"))
        self.assertFalse(compras.iloc[0]["risco_antes_reposicao"])

    def test_excesso_exige_trinta_dias_e_inclui_recebimentos(self):
        self.produtos.loc[0, "estoque_atual"] = 200
        self.pedido(200, 30)
        self.pedido(1000, 31, "P2")
        _, compras = self.executar()
        self.assertTrue(compras.iloc[0]["excesso"])
        self.assertEqual(compras.iloc[0]["unidades_acima_alvo_30dias"], 95)
        self.previsoes = self.previsoes.iloc[:29]
        _, compras = self.executar()
        self.assertTrue(pd.isna(compras.iloc[0]["excesso"]))

    def test_sem_excesso_quando_igual_ao_alvo_de_trinta_dias(self):
        self.produtos.loc[0, "estoque_atual"] = 305
        _, compras = self.executar()
        self.assertFalse(compras.iloc[0]["excesso"])

    def test_prazo_maximo_e_revisao_maxima_cabem_em_90_dias(self):
        self.previsoes = pd.concat([self.previsoes] * 3, ignore_index=True)
        self.previsoes["data"] = pd.date_range("2026-01-02", periods=90)
        self.fornecedores.loc[0, "prazo_dias"] = 60
        _, compras = self.executar(revisao_dias=30)
        self.assertEqual(compras.iloc[0]["horizonte_necessario"], 90)
        self.assertEqual(compras.iloc[0]["estoque_alvo"], 905)

    def test_valida_revisao_e_previsoes_invalidas(self):
        for revisao in (0, -1, 31, float("inf"), True, 1.5):
            with self.subTest(revisao=revisao), self.assertRaises(ValueError):
                self.executar(revisao_dias=revisao)
        original = self.previsoes.copy()
        for valor in (-1, float("nan"), float("inf")):
            self.previsoes = original.copy()
            self.previsoes.loc[0, "previsao"] = valor
            with self.subTest(previsao=valor), self.assertRaises(ValueError):
                self.executar()

    def test_lacuna_na_previsao_e_erro(self):
        self.previsoes = self.previsoes.drop(index=10)
        with self.assertRaisesRegex(ValueError, "consecutivas"):
            self.executar()

    def test_pedidos_anteriores_ao_fechamento_sao_invalidos(self):
        self.pedido(10, 0)
        with self.assertRaisesRegex(ValueError, "depois"):
            self.executar()

    def test_previsoes_embaralhadas_sao_ordenadas(self):
        self.previsoes = self.previsoes.iloc[::-1]
        saldos, _ = self.executar()
        self.assertTrue(saldos["data"].is_monotonic_increasing)

    def test_compra_sugerida_nao_e_recebida_na_projecao(self):
        saldos, compras = self.executar()
        self.assertGreater(compras.iloc[0]["compra_sugerida"], 0)
        self.assertEqual(saldos["recebimentos"].sum(), 0)
        self.assertEqual(saldos.iloc[-1]["saldo_estimado"], -290)

    def test_residuo_numerico_nao_cria_lote_desnecessario(self):
        self.previsoes["previsao"] = 10.0 + 1e-12
        self.produtos.loc[0, ["estoque_atual", "estoque_seguranca"]] = [90, 0]
        _, compras = self.executar()
        self.assertEqual(compras.iloc[0]["compra_sugerida"], 0)

    def test_programa_compra_futura_e_recalcula_quantidade(self):
        self.produtos.loc[
            0, ["estoque_atual", "estoque_seguranca", "multiplo_compra"]
        ] = [100, 0, 1]
        _, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(compra["compra_sugerida"], 0)
        self.assertEqual(
            compra["primeira_abaixo_seguranca"], self.origem + pd.Timedelta(days=11)
        )
        self.assertEqual(compra["dias_ate_seguranca"], 11)
        self.assertEqual(compra["dias_ate_falta"], 11)
        self.assertEqual(
            compra["data_limite_compra"], self.origem + pd.Timedelta(days=9)
        )
        self.assertEqual(
            compra["data_compra_sugerida"], self.origem + pd.Timedelta(days=9)
        )
        self.assertEqual(
            compra["data_entrega_compra_sugerida"], self.origem + pd.Timedelta(days=11)
        )
        # Estoque no fechamento do dia 9 = 10; demanda dos dias 10..18 = 90.
        self.assertEqual(compra["quantidade_compra_na_data"], 80)
        self.assertEqual(compra["horizonte_necessario_agendamento"], 18)
        self.assertEqual(compra["status_agendamento"], "compra_programada")
        self.assertFalse(compra["prazo_compra_vencido"])

    def test_compra_futura_nao_desconta_recebimento_passado_duas_vezes(self):
        self.produtos.loc[
            0, ["estoque_atual", "estoque_seguranca", "multiplo_compra"]
        ] = [100, 0, 1]
        self.pedido(20, 5)
        _, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(
            compra["data_compra_sugerida"], self.origem + pd.Timedelta(days=11)
        )
        # Já recebido antes da compra: estoque projetado no dia 11 é 10.
        self.assertEqual(compra["quantidade_compra_na_data"], 80)

    def test_compra_futura_cobre_ponte_antes_de_pedido_tardio(self):
        self.produtos.loc[
            0, ["estoque_atual", "estoque_seguranca", "multiplo_compra"]
        ] = [100, 0, 1]
        self.pedido(200, 12)
        _, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(compra["compra_sugerida"], 0)
        self.assertEqual(
            compra["data_compra_sugerida"], self.origem + pd.Timedelta(days=9)
        )
        # O pedido grande do dia 12 não cobre o déficit de 10 no dia 11.
        self.assertEqual(compra["quantidade_compra_na_data"], 10)

    def test_compra_agora_tambem_cobre_ponte_com_datas_exatas(self):
        self.produtos.loc[
            0, ["estoque_atual", "estoque_seguranca", "multiplo_compra"]
        ] = [0, 0, 1]
        self.pedido(100, 5)
        _, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(compra["estoque_alvo"], 90)
        self.assertEqual(compra["posicao_estoque"], 100)
        # O agregado sugere zero; o caminho até o pedido do dia 5 exige 40.
        self.assertEqual(compra["compra_sugerida"], 40)
        self.assertEqual(compra["quantidade_compra_na_data"], 40)
        self.assertEqual(compra["prioridade"], "critica")
        self.assertEqual(compra["prioridade_ordem"], 1)

    def test_pedido_grande_tardio_com_compra_zero_ainda_exige_urgencia(self):
        self.produtos.loc[
            0, ["estoque_atual", "estoque_seguranca", "multiplo_compra"]
        ] = [0, 0, 1]
        self.fornecedores.loc[0, "prazo_dias"] = 4
        self.pedido(200, 3)
        _, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(compra["compra_sugerida"], 0)
        self.assertEqual(compra["quantidade_compra_na_data"], 0)
        self.assertEqual(compra["status"], "revisar_entrega_urgente")
        self.assertEqual(compra["prioridade"], "critica")
        self.assertTrue(compra["falta_antes_entrega_compra"])
        self.assertEqual(compra["status_agendamento"], "sem_compra_adicional")
        self.assertTrue(pd.isna(compra["data_compra_sugerida"]))
        self.assertIn("antecipação", compra["motivos_alerta"])

    def test_prazo_vencido_de_seguranca_nao_implica_falta_impossivel(self):
        self.produtos.loc[
            0, ["estoque_atual", "estoque_seguranca", "multiplo_compra"]
        ] = [25, 20, 1]
        _, compras = self.executar()
        compra = compras.iloc[0]
        # Segurança cruza no dia 1; falta só no dia 3; entrega possível no dia 2.
        self.assertEqual(
            compra["data_limite_compra"], self.origem - pd.Timedelta(days=1)
        )
        self.assertEqual(compra["data_compra_sugerida"], self.origem)
        self.assertTrue(compra["prazo_compra_vencido"])
        self.assertFalse(compra["falta_antes_entrega_compra"])
        self.assertEqual(compra["prioridade"], "alta")
        self.assertEqual(compra["status_agendamento"], "prazo_vencido")

    def test_horizonte_curto_informa_prazo_mas_nao_inventa_quantidade_futura(self):
        self.produtos.loc[
            0, ["estoque_atual", "estoque_seguranca", "multiplo_compra"]
        ] = [100, 0, 1]
        self.previsoes = self.previsoes.iloc[:14]
        _, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(compra["compra_sugerida"], 0)
        self.assertEqual(
            compra["data_compra_sugerida"], self.origem + pd.Timedelta(days=9)
        )
        self.assertEqual(compra["horizonte_necessario_agendamento"], 18)
        self.assertTrue(pd.isna(compra["quantidade_compra_na_data"]))
        self.assertEqual(compra["status_agendamento"], "horizonte_insuficiente")

    def test_sem_cruzamento_no_horizonte_nao_promete_estoque_para_sempre(self):
        self.produtos.loc[0, "estoque_atual"] = 1000
        _, compras = self.executar()
        compra = compras.iloc[0]
        for coluna in (
            "data_limite_compra",
            "data_compra_sugerida",
            "quantidade_compra_na_data",
            "dias_ate_seguranca",
            "dias_ate_falta",
        ):
            self.assertTrue(pd.isna(compra[coluna]), coluna)
        self.assertEqual(compra["status_agendamento"], "sem_gatilho_no_horizonte")
        self.assertIn("desconhecida", compra["motivos_alerta"])

    def test_estoque_exatamente_na_seguranca_nao_e_abaixo(self):
        self.produtos.loc[0, ["estoque_atual", "estoque_seguranca"]] = [10, 10]
        self.previsoes["previsao"] = 0
        _, compras = self.executar()
        compra = compras.iloc[0]
        self.assertTrue(pd.isna(compra["primeira_abaixo_seguranca"]))
        self.assertEqual(compra["status_agendamento"], "sem_gatilho_no_horizonte")
        self.assertEqual(compra["compra_sugerida"], 0)

    def test_segurança_ja_violada_no_fechamento_tem_dia_zero(self):
        self.produtos.loc[0, ["estoque_atual", "estoque_seguranca"]] = [4, 5]
        _, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(compra["primeira_abaixo_seguranca"], self.origem)
        self.assertEqual(compra["dias_ate_seguranca"], 0)
        self.assertEqual(
            compra["data_limite_compra"], self.origem - pd.Timedelta(days=2)
        )

    def test_prazo_zero_compra_no_fechamento_anterior_a_venda(self):
        self.produtos.loc[
            0, ["estoque_atual", "estoque_seguranca", "multiplo_compra"]
        ] = [10, 0, 1]
        self.fornecedores.loc[0, "prazo_dias"] = 0
        _, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(
            compra["primeira_abaixo_seguranca"], self.origem + pd.Timedelta(days=2)
        )
        self.assertEqual(
            compra["data_compra_sugerida"], self.origem + pd.Timedelta(days=1)
        )
        self.assertEqual(
            compra["data_entrega_compra_sugerida"], self.origem + pd.Timedelta(days=2)
        )
        # Compra fecha no dia 1; janela de proteção termina no dia 8.
        self.assertEqual(compra["quantidade_compra_na_data"], 70)
        self.assertFalse(compra["risco_antes_reposicao"])

    def test_produto_sem_previsao_tem_alerta_indefinido(self):
        self.previsoes = self.previsoes.iloc[:0]
        _, compras = self.executar()
        compra = compras.iloc[0]
        self.assertEqual(compra["status_agendamento"], "sem_previsao")
        self.assertEqual(compra["prioridade"], "indefinida")
        self.assertEqual(compra["prioridade_ordem"], 5)
        self.assertTrue(pd.isna(compra["quantidade_compra_na_data"]))


if __name__ == "__main__":
    unittest.main()
