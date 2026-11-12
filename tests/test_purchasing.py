from copy import deepcopy
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import pandas as pd
from fastapi.testclient import TestClient
from api import create_app
from stockmind.purchasing import centavos, distribuir_orcamento, explicar_compras
from stockmind.inventory import planejar_estoque
from stockmind.service import executar_analise
from stockmind.stress import avaliar_estresse
from stockmind.evaluation import avaliar_politicas
from scripts.benchmark_retail import prepare


def fixtures():
    sales = pd.DataFrame(
        {
            "sku": ["A"] * 60,
            "data": pd.date_range("2026-01-01", periods=60),
            "vendas": [4] * 60,
            "disponivel": [1] * 60,
        }
    )
    products = pd.DataFrame(
        [
            {
                "sku": "A",
                "nome": "A",
                "fornecedor_id": "F",
                "estoque_atual": 10,
                "estoque_seguranca": 2,
                "pedido_minimo": 5,
                "multiplo_compra": 3,
            }
        ]
    )
    suppliers = pd.DataFrame([{"fornecedor_id": "F", "nome": "F", "prazo_dias": 2}])
    return sales, products, suppliers


class TestPurchasing(unittest.TestCase):
    def test_memoria_reconcilia_deficit_e_lote_sem_subtrair_pedido_duas_vezes(self):
        sales, products, suppliers = fixtures()
        dates = pd.date_range(sales.data.max() + pd.Timedelta(days=1), periods=14)
        forecasts = pd.DataFrame(
            {"sku": "A", "data": dates, "previsao": 4.0, "status": "avaliado"}
        )
        orders = pd.DataFrame(
            [{"pedido_id": "P", "sku": "A", "quantidade": 8, "data_entrega": dates[4]}]
        )
        balances, recs = planejar_estoque(forecasts, products, suppliers, orders, 3)
        memory, diag = explicar_compras(sales, forecasts, balances, recs, products, 3)
        now = memory.loc[memory.tipo_compra.eq("na_origem")].iloc[0]
        # D1=6 D2=2 D3=-2 D4=-6 D5=-2. Mínimo=-6 => déficit de segurança=8 => lote=9.
        self.assertEqual(now.menor_saldo_janela, -6)
        self.assertEqual(now.necessidade_antes_lote, 8)
        self.assertEqual(now.quantidade_sugerida, 9)
        self.assertEqual(now.recebimentos_ate_protecao, 8)
        self.assertEqual(diag.iloc[0].situacao_dados, "avaliada")

    def test_sem_historico_e_horizonte_insuficiente_nao_ganham_quantidade(self):
        sales, products, suppliers = fixtures()
        products = pd.concat([products, products.assign(sku="B")], ignore_index=True)
        result = executar_analise(
            sales, produtos=products, fornecedores=suppliers, horizonte=7
        )
        diag = {r["sku"]: r for r in result["diagnosticos_decisao"]}
        self.assertEqual(
            diag["A"]["situacao_dados"], "insuficiente"
        )  # prazo 2 + revisão 7 > 7
        self.assertEqual(diag["B"]["situacao_dados"], "insuficiente")
        self.assertTrue(
            all(
                r["quantidade_sugerida"] is None
                for r in result["memoria_compras"]
                if r["sku"] == "B"
            )
        )
        json.dumps(result, allow_nan=False)

    def test_disponibilidade_desconhecida_e_historico_curto_sao_provisorios(self):
        sales, products, suppliers = fixtures()
        for source in (sales.drop(columns="disponivel"), sales.tail(10)):
            result = executar_analise(
                source, horizonte=30, produtos=products, fornecedores=suppliers
            )
            self.assertEqual(
                result["diagnosticos_decisao"][0]["situacao_dados"], "provisoria"
            )

    def test_modelo_que_perdeu_no_teste_recebe_ressalva_sem_mudar_previsao(self):
        sales, products, suppliers = fixtures()
        forecasts = pd.DataFrame(
            {
                "sku": "A",
                "data": pd.date_range(
                    sales.data.max() + pd.Timedelta(days=1), periods=14
                ),
                "previsao": 4.0,
                "status": "avaliado",
            }
        )
        balances, recs = planejar_estoque(
            forecasts, products, suppliers, revisao_dias=3
        )
        metrics = pd.DataFrame(
            [
                {
                    "sku": "A",
                    "selecionado": True,
                    "ganho_mae_teste_pct": -10.0,
                    "mae_teste": 3.0,
                }
            ]
        )
        before = forecasts.copy(deep=True)
        _, diag = explicar_compras(
            sales, forecasts, balances, recs, products, 3, metricas=metrics
        )
        self.assertEqual(diag.iloc[0].situacao_dados, "provisoria")
        self.assertIn("perdeu", diag.iloc[0].motivos)
        pd.testing.assert_frame_equal(forecasts, before)

    def test_orcamento_respeita_prioridade_lotes_e_centavos(self):
        _, p, _ = fixtures()
        products = pd.concat(
            [p, p.assign(sku="B", pedido_minimo=1, multiplo_compra=1)],
            ignore_index=True,
        )
        recs = pd.DataFrame(
            [
                {
                    "sku": "B",
                    "prioridade_ordem": 2,
                    "prioridade": "media",
                    "dias_ate_falta": 3,
                    "quantidade_compra_na_data": 10,
                    "data_compra_sugerida": "2026-03-01",
                    "status_previsao": "avaliado",
                },
                {
                    "sku": "A",
                    "prioridade_ordem": 0,
                    "prioridade": "critica",
                    "dias_ate_falta": 1,
                    "quantidade_compra_na_data": 12,
                    "data_compra_sugerida": "2026-03-01",
                    "status_previsao": "avaliado",
                },
            ]
        )
        before = recs.copy(deep=True)
        rows, summary = distribuir_orcamento(
            recs, products, "1.00", {"A": ".10", "B": ".03"}
        )
        self.assertEqual([r["sku"] for r in rows], ["A", "B"])
        self.assertEqual([r["quantidade_reservada"] for r in rows], [9, 3])
        self.assertEqual(summary["reservado"], "0.99")
        self.assertEqual(summary["restante"], "0.01")
        pd.testing.assert_frame_equal(recs, before)
        reverse, _ = distribuir_orcamento(
            recs.iloc[::-1], products, "1.00", {"A": ".10", "B": ".03"}
        )
        self.assertEqual(rows, reverse)

    def test_sem_minimo_ou_custo_nao_reserva_e_produto_seguinte_pode_caber(self):
        _, p, _ = fixtures()
        recs = pd.DataFrame(
            [
                {
                    "sku": "A",
                    "prioridade_ordem": 1,
                    "prioridade": "alta",
                    "dias_ate_falta": 1,
                    "quantidade_compra_na_data": 12,
                    "data_compra_sugerida": "2026-03-01",
                    "status_previsao": "historico_curto",
                }
            ]
        )
        for costs, budget, status in [
            ({}, "10.00", "custo_ausente"),
            ({"A": "1"}, "5.00", "sem_orcamento"),
            ({"A": "1"}, "0", "sem_orcamento"),
        ]:
            rows, result = distribuir_orcamento(recs, p, budget, costs)
            self.assertEqual(rows[0]["status_orcamento"], status)
            self.assertEqual(rows[0]["quantidade_reservada"], 0)
            self.assertEqual(
                centavos(result["restante"], "saldo"), centavos(budget, "inicial")
            )

    def test_valores_invalidos_nao_sao_arredondados_ou_aceitos_como_zero(self):
        for value in [True, None, "-1", "NaN", "Infinity", "1.001", "1000000000000"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                centavos(value, "valor")
        with self.assertRaises(ValueError):
            centavos("0", "custo", positivo=True)

    def test_servico_com_orcamento_e_sku_sem_historico_retorna_json_padrao(self):
        sales, p, f = fixtures()
        p = pd.concat([p, p.assign(sku="B")], ignore_index=True)
        result = executar_analise(
            sales,
            horizonte=30,
            produtos=p,
            fornecedores=f,
            orcamento_compras="10.00",
            custos_unitarios={"A": ".10"},
        )
        json.dumps(result, allow_nan=False)
        unknown = next(row for row in result["plano_orcamento"] if row["sku"] == "B")
        self.assertIsNone(unknown["data_compra"])
        self.assertIsNone(unknown["quantidade_sugerida"])
        self.assertEqual(unknown["quantidade_reservada"], 0)

    def test_orcamento_invalido_sem_cadastro_e_sku_desconhecido(self):
        with self.assertRaises(ValueError):
            distribuir_orcamento(pd.DataFrame(), None, "10", {})
        _, products, _ = fixtures()
        with self.assertRaises(ValueError):
            distribuir_orcamento(pd.DataFrame(), products, "10", {"X": "1"})

    def test_api_preserva_entradas_resultados_e_rejeita_custo_invalido(self):
        sales, p, f = fixtures()
        body = {
            "vendas": sales.assign(data=sales.data.dt.strftime("%Y-%m-%d")).to_dict(
                "records"
            ),
            "produtos": p.to_dict("records"),
            "fornecedores": f.to_dict("records"),
            "horizonte": 30,
            "orcamento_compras": "10.01",
            "custos_unitarios": {"A": ".10"},
        }
        with (
            tempfile.TemporaryDirectory() as temp,
            TestClient(create_app(Path(temp) / "db.sqlite3")) as client,
        ):
            response = client.post("/analises", json=body)
            self.assertEqual(response.status_code, 201, response.text)
            snapshot = client.get("/analises/" + response.json()["id"]).json()
            self.assertEqual(
                snapshot["entrada"]["parametros"]["orcamento_compras"], "10.01"
            )
            self.assertEqual(
                snapshot["resultado"]["resumo_orcamento"]["orcamento"], "10.01"
            )
            for invalid in ["0", "-1", "0.001", "NaN"]:
                bad = deepcopy(body)
                bad["custos_unitarios"] = {"A": invalid}
                self.assertEqual(client.post("/analises", json=bad).status_code, 422)
            self.assertEqual(len(client.get("/analises").json()), 1)
            # Persistir outra análise não altera o snapshot anterior.
            body["orcamento_compras"] = "0"
            self.assertEqual(client.post("/analises", json=body).status_code, 201)
            self.assertEqual(
                client.get("/analises/" + response.json()["id"]).json(), snapshot
            )
            body.update(
                avaliar_estresse=True,
                periodo_simulacao=7,
                atraso_fornecedor_dias=2,
                choque_demanda_pct=30.0,
            )
            stressed = client.post("/analises", json=body)
            self.assertEqual(stressed.status_code, 201, stressed.text)
            stored = client.get("/analises/" + stressed.json()["id"]).json()
            self.assertIs(stored["entrada"]["parametros"]["avaliar_estresse"], True)
            self.assertEqual(len(stored["resultado"]["avaliacao_estresse"]), 15)
            self.assertEqual(stored["resultado"]["choque_demanda_pct"], 30.0)


class TestStress(unittest.TestCase):
    def test_base_igual_replay_e_cenario_nao_muda_entradas(self):
        sales, p, f = fixtures()
        original = sales.copy(deep=True)
        baseline, _ = avaliar_politicas(sales, p, f, periodo_dias=7)
        summary, daily = avaliar_estresse(
            sales, p, f, periodo_dias=7, atraso_dias=2, choque_pct=50.0
        )
        base = summary.loc[summary.cenario.eq("base")]
        self.assertEqual(
            base.custo_total_estimado.tolist(), baseline.custo_total_estimado.tolist()
        )
        high = daily.loc[daily.cenario.eq("demanda_maior") & daily.fase.eq("simulacao")]
        self.assertTrue(high.demanda.eq(6).all())
        low = daily.loc[daily.cenario.eq("demanda_menor") & daily.fase.eq("simulacao")]
        self.assertTrue(low.demanda.eq(2).all())
        self.assertEqual(
            set(summary.cenario),
            {"base", "atraso", "demanda_maior", "demanda_menor", "combinado"},
        )
        pd.testing.assert_frame_equal(sales, original)
        self.assertEqual(int(f.iloc[0].prazo_dias), 2)

    def test_cenarios_nulos_reproduzem_mesmos_custos_e_decisoes(self):
        sales, p, f = fixtures()
        result, daily = avaliar_estresse(
            sales, p, f, periodo_dias=7, atraso_dias=0, choque_pct=0.0
        )
        self.assertTrue(result.diferenca_custo_base.eq(0).all())
        for _, group in daily.groupby(["politica", "data"]):
            self.assertEqual(group.quantidade_pedida.nunique(), 1)
            self.assertEqual(group.demanda.nunique(dropna=False), 1)

    def test_choque_nao_altera_treino_anterior_ao_bloco(self):
        sales, p, f = fixtures()
        calls = []

        def capture(source, products, suppliers, **kwargs):
            calls.append(source.copy())
            return pd.DataFrame(
                [{"sku": "A", "politica": "P", "custo_total_estimado": None}]
            ), pd.DataFrame()

        with patch("stockmind.stress.avaliar_politicas", side_effect=capture):
            result, _ = avaliar_estresse(sales, p, f, periodo_dias=7, numero_periodos=2)
        for index, source in enumerate(calls):
            end = sales.data.max() - pd.Timedelta(days=(index // 5) * 7)
            start = end - pd.Timedelta(days=6)
            pd.testing.assert_frame_equal(
                source.loc[source.data.lt(start)], sales.loc[sales.data.lt(start)]
            )
            self.assertEqual(source.data.max(), end)
        self.assertTrue(result.diferenca_custo_base.isna().all())

    def test_censura_bloqueia_cenarios_e_prazo_invalido_nao_e_truncado(self):
        sales, p, f = fixtures()
        sales.loc[sales.index[-1], "disponivel"] = 0
        result, _ = avaliar_estresse(sales, p, f, periodo_dias=7)
        self.assertTrue(result.status.eq("demanda_censurada").all())
        with self.assertRaises(ValueError):
            avaliar_estresse(sales, p, f.assign(prazo_dias=60), atraso_dias=1)


class TestExpandedBenchmark(unittest.TestCase):
    def test_perfis_escolhidos_so_no_treino_sao_distintos(self):
        rows = []
        for index, day in enumerate(pd.date_range("2025-01-01", periods=240)):
            for sku in range(12):
                if index % (1 + sku % 3) == 0:
                    rows.append(
                        {
                            "InvoiceNo": "1",
                            "StockCode": str(10000 + sku),
                            "Quantity": 1 + sku + (index % 7) * (sku % 4),
                            "UnitPrice": 1,
                            "InvoiceDate": day,
                        }
                    )
        raw = pd.DataFrame(rows)
        _, first = prepare(raw, products=9, estratificado=True)
        raw.loc[
            raw.InvoiceDate.gt(pd.Timestamp(first["corte_selecao_skus"])), "Quantity"
        ] = 999999
        _, second = prepare(raw, products=9, estratificado=True)
        self.assertEqual(first["perfis_treino"], second["perfis_treino"])
        self.assertEqual(len(set(first["skus"])), 9)
        self.assertEqual(
            {x["perfil"] for x in first["perfis_treino"]},
            {"volume_alto", "intermitente", "variavel"},
        )
