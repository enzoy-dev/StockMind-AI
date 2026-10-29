from datetime import date, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import create_app


def fixture_analysis(sales, **_kwargs):
    horizon = _kwargs.get("horizonte", 7)
    start = sales["data"].max().date() + timedelta(days=1)
    forecasts = [
        {
            "sku": str(sku),
            "data": (start + timedelta(days=i)).isoformat(),
            "previsao": 5.0,
            "limite_inferior": None,
            "limite_superior": None,
            "modelo": "Última venda",
            "status": "historico_curto",
        }
        for sku in sales["sku"].unique()
        for i in range(horizon)
    ]
    return {
        "previsoes": forecasts,
        "metricas": [],
        "saldos": [],
        "recomendacoes": [],
        "qualidade": [],
        "comparacao_horizontes": [],
        "cenarios": [],
        "saldos_cenarios": [],
        "comparar_horizontes": _kwargs.get("comparar_horizontes", False),
        "variacao_cenario_pct": _kwargs.get("variacao_cenario_pct", 20.0),
    }


class TestAPI(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"STOCKMIND_API_KEY": ""})
        self.environment.start()
        self.client = TestClient(create_app(Path(self.directory.name) / "api.sqlite3"))
        self.client.__enter__()
        self.sales = [
            {"sku": "001", "data": "2026-01-01", "vendas": 3},
            {"sku": "001", "data": "2026-01-02", "vendas": 5},
        ]

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.environment.stop()
        self.directory.cleanup()

    @patch("api.executar_analise", side_effect=fixture_analysis)
    def test_analysis_history_and_sparse_actuals(self, _analyse):
        response = self.client.post("/analises", json={"vendas": self.sales})
        self.assertEqual(response.status_code, 201, response.text)
        run_id = response.json()["id"]
        self.assertEqual(len(self.client.get("/analises").json()), 1)
        snapshot = self.client.get(f"/analises/{run_id}").json()
        result = self.client.get(f"/analises/{run_id}/comparacao").json()
        self.assertEqual(result["resumo"][0]["periodos_observados"], 0)
        # Apenas um dia chega. Os demais continuam desconhecidos, não zero.
        response = self.client.post(
            "/vendas",
            json={
                "vendas": [
                    {"sku": "001", "data": "2026-01-05", "vendas": 0},
                ]
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = self.client.get(f"/analises/{run_id}/comparacao").json()
        self.assertEqual(result["resumo"][0]["periodos_observados"], 1)
        self.assertEqual(result["resumo"][0]["mae"], 5)
        self.assertEqual(self.client.get(f"/analises/{run_id}").json(), snapshot)

    def test_validation_report_and_failed_analysis_have_no_history(self):
        duplicate = self.sales + [self.sales[0]]
        response = self.client.post("/analises", json={"vendas": duplicate})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertTrue(response.json()["detail"]["relatorio"])
        self.assertEqual(self.client.get("/analises").json(), [])

    def test_request_contract_rejects_unknown_fields_and_bad_horizon(self):
        for extra in ({"horizonte": 8}, {"revisao_dias": 0}, {"campo_inventado": True}):
            with self.subTest(extra=extra):
                response = self.client.post(
                    "/analises", json={"vendas": self.sales, **extra}
                )
                self.assertEqual(response.status_code, 422)

    @patch("api.executar_analise", side_effect=fixture_analysis)
    def test_new_parameters_keep_existing_request_defaults(self, analyse):
        response = self.client.post("/analises", json={"vendas": self.sales})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIs(analyse.call_args.kwargs["comparar_horizontes"], False)
        self.assertEqual(analyse.call_args.kwargs["variacao_cenario_pct"], 20.0)
        snapshot = self.client.get(f"/analises/{response.json()['id']}").json()
        self.assertEqual(
            snapshot["entrada"]["parametros"],
            {
                "horizonte": 7,
                "revisao_dias": 7,
                "comparar_horizontes": False,
                "variacao_cenario_pct": 20.0,
            },
        )
        self.assertEqual(len(snapshot["resultado"]["previsoes"]), 7)

    def test_scenario_results_and_parameters_are_in_the_immutable_snapshot(self):
        def analysis_with_scenarios(sales, **kwargs):
            result = fixture_analysis(sales, **kwargs)
            result["comparacao_horizontes"] = [{"sku": "001", "horizonte": 30}]
            result["cenarios"] = [
                {"sku": "001", "cenario": "demanda_alta", "compra_sugerida": 12}
            ]
            result["saldos_cenarios"] = [
                {
                    "sku": "001",
                    "cenario": "demanda_alta",
                    "data": "2026-01-03",
                    "saldo_estimado": 3,
                }
            ]
            return result

        with patch(
            "api.executar_analise", side_effect=analysis_with_scenarios
        ) as analyse:
            response = self.client.post(
                "/analises",
                json={
                    "vendas": self.sales,
                    "comparar_horizontes": True,
                    "variacao_cenario_pct": 35,
                },
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIs(analyse.call_args.kwargs["comparar_horizontes"], True)
        self.assertEqual(analyse.call_args.kwargs["variacao_cenario_pct"], 35.0)
        run_id = response.json()["id"]
        snapshot = self.client.get(f"/analises/{run_id}").json()
        self.assertEqual(snapshot["resultado"], response.json()["resultado"])
        self.assertEqual(
            snapshot["entrada"]["parametros"]["variacao_cenario_pct"], 35.0
        )
        self.assertTrue(snapshot["entrada"]["parametros"]["comparar_horizontes"])
        self.client.post(
            "/vendas",
            json={"vendas": [{"sku": "001", "data": "2026-01-03", "vendas": 4}]},
        )
        self.assertEqual(self.client.get(f"/analises/{run_id}").json(), snapshot)

    @patch("api.executar_analise", side_effect=fixture_analysis)
    def test_future_context_covers_comparison_horizons_without_truncating_to_primary(
        self, analyse
    ):
        context = [
            {
                "sku": "001",
                "data": (date(2026, 1, 3) + timedelta(days=i)).isoformat(),
                "preco": 10.0,
                "promocao": 0,
                "feriado": 0,
            }
            for i in range(90)
        ]
        for horizon, compare, expected in [
            (7, False, 7),
            (7, True, 30),
            (90, True, 90),
        ]:
            with self.subTest(horizon=horizon, compare=compare):
                response = self.client.post(
                    "/analises",
                    json={
                        "vendas": self.sales,
                        "horizonte": horizon,
                        "comparar_horizontes": compare,
                        "contexto_futuro": context,
                    },
                )
                self.assertEqual(response.status_code, 201, response.text)
                forwarded = analyse.call_args.kwargs["contexto_futuro"]
                self.assertEqual(len(forwarded), expected)
                snapshot = self.client.get(f"/analises/{response.json()['id']}").json()
                self.assertEqual(len(snapshot["entrada"]["contexto_futuro"]), expected)
        before = len(self.client.get("/analises").json())
        response = self.client.post(
            "/analises",
            json={
                "vendas": self.sales,
                "comparar_horizontes": True,
                "contexto_futuro": context[:7],
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("30", response.json()["detail"]["mensagem"])
        self.assertEqual(len(self.client.get("/analises").json()), before)

    @patch("api.executar_analise", side_effect=fixture_analysis)
    def test_invalid_scenario_parameters_rejected_before_any_analysis_or_write(
        self, analyse
    ):
        invalid = [
            {"variacao_cenario_pct": value}
            for value in (
                -1,
                80.1,
                True,
                False,
                "20",
                None,
                {},
                float("nan"),
                float("inf"),
                -float("inf"),
            )
        ] + [{"comparar_horizontes": value} for value in (1, 0, "true", None)]
        for extra in invalid:
            with self.subTest(extra=extra):
                response = self.client.post(
                    "/analises",
                    content=json.dumps({"vendas": self.sales, **extra}),
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(response.status_code, 422, response.text)
        analyse.assert_not_called()
        self.assertEqual(self.client.get("/analises").json(), [])

    @patch("api.executar_analise", side_effect=fixture_analysis)
    def test_scenario_percentage_accepts_both_inclusive_limits(self, analyse):
        for percentage in (0, 80):
            with self.subTest(percentage=percentage):
                response = self.client.post(
                    "/analises",
                    json={
                        "vendas": self.sales,
                        "variacao_cenario_pct": percentage,
                    },
                )
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual(
                    analyse.call_args.kwargs["variacao_cenario_pct"], float(percentage)
                )

    def test_missing_history_returns_404(self):
        self.assertEqual(self.client.get("/analises/inexistente").status_code, 404)
        self.assertEqual(
            self.client.get("/analises/inexistente/comparacao").status_code, 404
        )

    @patch("api.executar_analise", side_effect=fixture_analysis)
    def test_api_key_required_when_configured(self, _analyse):
        with patch.dict(os.environ, {"STOCKMIND_API_KEY": "chave-de-teste"}):
            application = create_app(Path(self.directory.name) / "protected.sqlite3")
        with TestClient(application) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertTrue(client.get("/health").json()["autenticacao_configurada"])
            self.assertEqual(client.get("/analises").status_code, 401)
            self.assertEqual(
                client.post("/analises", json={"vendas": self.sales}).status_code, 401
            )
            self.assertEqual(
                client.get(
                    "/planejamento", headers={"X-API-Key": "errada"}
                ).status_code,
                401,
            )
            response = client.post(
                "/analises",
                json={"vendas": self.sales},
                headers={"X-API-Key": "chave-de-teste"},
            )
            self.assertEqual(response.status_code, 201, response.text)

    def test_invalid_actuals_do_not_partially_write(self):
        response = self.client.post(
            "/vendas",
            json={
                "vendas": [
                    {"sku": "001", "data": "2026-01-03", "vendas": 1},
                    {"sku": "001", "data": "2026-01-04", "vendas": -1},
                ]
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        with patch("api.executar_analise", side_effect=fixture_analysis):
            run_id = self.client.post("/analises", json={"vendas": self.sales}).json()[
                "id"
            ]
        summary = self.client.get(f"/analises/{run_id}/comparacao").json()["resumo"][0]
        self.assertEqual(summary["periodos_observados"], 0)

    @patch("api.executar_analise", side_effect=fixture_analysis)
    def test_planning_saved_and_stale_stock_rejected(self, _analyse):
        planning = {
            "origem": "2026-01-02",
            "fornecedores": [
                {"fornecedor_id": "F1", "nome": "Fornecedor", "prazo_dias": 2}
            ],
            "produtos": [
                {
                    "sku": "001",
                    "nome": "Produto",
                    "fornecedor_id": "F1",
                    "estoque_atual": 10,
                    "estoque_seguranca": 2,
                    "pedido_minimo": 3,
                    "multiplo_compra": 3,
                }
            ],
            "pedidos": [],
        }
        response = self.client.put("/planejamento", json=planning)
        self.assertEqual(response.status_code, 200, response.text)
        saved = self.client.get("/planejamento").json()
        self.assertEqual(saved["origem"], "2026-01-02")
        self.assertEqual(saved["produtos"][0]["sku"], "001")
        direct = {key: value for key, value in planning.items() if key != "origem"}
        response = self.client.post("/analises", json={"vendas": self.sales, **direct})
        self.assertEqual(response.status_code, 201, response.text)
        response = self.client.post(
            "/analises", json={"vendas": self.sales, "usar_planejamento_salvo": True}
        )
        self.assertEqual(response.status_code, 201, response.text)
        later = [{"sku": "001", "data": "2026-01-03", "vendas": 4}]
        response = self.client.post(
            "/analises", json={"vendas": later, "usar_planejamento_salvo": True}
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("data do estoque", response.json()["detail"]["mensagem"])

    def test_real_service_integration(self):
        # Usa o serviço real, além dos testes HTTP determinísticos com fixture.
        sales = [
            {
                "sku": "001",
                "data": (date(2026, 1, 1) + timedelta(days=i)).isoformat(),
                "vendas": 5,
            }
            for i in range(60)
        ]
        response = self.client.post("/analises", json={"vendas": sales})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(len(response.json()["resultado"]["previsoes"]), 7)
        self.assertTrue(response.json()["resultado"]["metricas"])


if __name__ == "__main__":
    unittest.main()
