from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from api import create_app


class TestMaturityAPI(unittest.TestCase):
    def test_rotas_estoque_preservam_snapshot_e_validam_dados(self):
        import pandas as pd

        with (
            tempfile.TemporaryDirectory() as temp,
            TestClient(create_app(Path(temp) / "db.sqlite3")) as client,
        ):
            sales = [
                {
                    "sku": "A",
                    "data": day.strftime("%Y-%m-%d"),
                    "vendas": 2,
                    "disponivel": 1,
                }
                for day in pd.date_range("2026-01-01", periods=45)
            ]
            body = {
                "vendas": sales,
                "produtos": [
                    {
                        "sku": "A",
                        "nome": "A",
                        "fornecedor_id": "F",
                        "estoque_atual": 50,
                        "estoque_seguranca": 5,
                        "pedido_minimo": 1,
                        "multiplo_compra": 1,
                    }
                ],
                "fornecedores": [{"fornecedor_id": "F", "nome": "F", "prazo_dias": 2}],
                "janela_classificacao": 30,
            }
            response = client.post("/analises", json=body)
            self.assertEqual(response.status_code, 201, response.text)
            result = response.json()
            identifier = result["id"]
            first = result["resultado"]["saldos"][0]
            actual = {
                "sku": "A",
                "data": first["data"],
                "estoque_real": first["saldo_estimado"] - 1,
            }
            self.assertEqual(
                client.post("/estoques-reais", json={"estoques": [actual]}).status_code,
                200,
            )
            compared = client.get(f"/analises/{identifier}/estoque-real")
            self.assertEqual(compared.status_code, 200)
            self.assertAlmostEqual(compared.json()["resumo"][0]["mae_saldo"], 1)
            self.assertEqual(
                client.get(f"/analises/{identifier}").json()["resultado"],
                result["resultado"],
            )
            self.assertEqual(
                client.get("/analises/ausente/estoque-real").status_code, 404
            )
            self.assertEqual(
                client.post(
                    "/estoques-reais",
                    json={"estoques": [{**actual, "estoque_real": True}]},
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(
                    "/analises", json={**body, "janela_classificacao": True}
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(
                    "/analises", json={**body, "numero_periodos_simulacao": 7}
                ).status_code,
                422,
            )
