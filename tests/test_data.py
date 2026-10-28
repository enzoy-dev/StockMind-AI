"""Contratos de importação e qualidade dos dados."""

from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from stockmind.data import (
    DataError,
    carregar_vendas,
    inspecionar_vendas,
    ler_csv,
    validar_contexto_futuro,
    validar_planejamento,
    validar_vendas,
)


class TestSalesData(unittest.TestCase):
    def setUp(self):
        self.sales = pd.DataFrame(
            {
                "sku": ["001"] * 45,
                "data": pd.date_range("2026-01-01", periods=45),
                "vendas": [10] * 45,
            }
        )

    def test_legacy_csv_and_string_codes(self):
        legacy = carregar_vendas(StringIO("data,vendas\n2026-01-01,2\n"))
        self.assertEqual(legacy["sku"].tolist(), ["PRODUTO-001"])
        raw = ler_csv(StringIO("sku,data,vendas\n001,2026-01-01,2\nNA,2026-01-01,1\n"))
        self.assertEqual(raw["sku"].tolist(), ["001", "NA"])
        self.assertEqual(validar_vendas(raw)["sku"].tolist(), ["001", "NA"])

    def test_already_canonical_input_is_idempotent(self):
        canonical = validar_vendas(self.sales.iloc[::-1])
        pd.testing.assert_frame_equal(validar_vendas(canonical), canonical)
        self.assertTrue(canonical["data"].is_monotonic_increasing)

    def test_different_start_dates_allowed(self):
        second = self.sales.iloc[-3:].assign(sku="002")
        canonical = validar_vendas(pd.concat([self.sales, second]))
        self.assertEqual(len(canonical), 48)
        report = inspecionar_vendas(canonical)
        self.assertTrue(report["nivel"].eq("aviso").all())
        self.assertTrue(report["mensagem"].str.contains("apenas 3").any())

    def test_different_end_dates_rejected(self):
        second = self.sales.iloc[:-1].assign(sku="002")
        with self.assertRaisesRegex(DataError, "mesma data"):
            validar_vendas(pd.concat([self.sales, second]))

    def test_missing_days_not_filled(self):
        with self.assertRaises(DataError) as context:
            validar_vendas(self.sales.drop(index=10))
        self.assertTrue(
            context.exception.report["mensagem"].str.contains("faltam 1 dias").any()
        )

    def test_collects_errors_in_one_report(self):
        raw = pd.DataFrame(
            {
                "sku": ["A", "A", ""],
                "data": ["2026-01-01", "2026-01-01", "data inválida"],
                "vendas": [-1, 1.5, "texto"],
            }
        )
        report = inspecionar_vendas(raw)
        self.assertIn("sku", set(report["campo"]))
        self.assertIn("data", set(report["campo"]))
        self.assertIn("vendas", set(report["campo"]))
        self.assertIn("sku,data", set(report["campo"]))
        with self.assertRaises(DataError) as context:
            validar_vendas(raw)
        pd.testing.assert_frame_equal(context.exception.report, report)

    def test_finite_nonnegative_integer_units(self):
        for value in [-1, 1.5, float("inf"), float("nan"), "texto"]:
            sales = self.sales.astype({"vendas": object})
            sales.loc[0, "vendas"] = value
            with self.subTest(value=value), self.assertRaises(DataError):
                validar_vendas(sales)

    def test_invalid_dates_and_timezones_rejected(self):
        for value in [
            "2026-02-30",
            "01/01/2026",
            "2026-01-01 00:00:00",
            pd.Timestamp("2026-01-01", tz="UTC"),
            pd.Timestamp("2026-01-01 12:00"),
        ]:
            sales = self.sales.astype({"data": object})
            sales.loc[0, "data"] = value
            with self.subTest(value=value), self.assertRaises(DataError):
                validar_vendas(sales)

    def test_optional_context_partial_is_warning(self):
        sales = self.sales.assign(preco=10)
        actual = validar_vendas(sales)
        self.assertIn("preco", actual)
        report = inspecionar_vendas(sales)
        self.assertTrue(report["mensagem"].str.contains("Contexto parcial").any())
        self.assertFalse(report["nivel"].eq("erro").any())

    def test_context_fields_reject_invalid_values(self):
        for col, value in [
            ("preco", -1),
            ("preco", float("inf")),
            ("promocao", 2),
            ("feriado", 0.5),
        ]:
            with self.subTest(col=col, value=value), self.assertRaises(DataError):
                validar_vendas(self.sales.assign(**{col: value}))

    def test_numeric_booleans_are_rejected_without_coercion(self):
        for column in ["vendas", "preco", "promocao", "feriado"]:
            for value in [True, False]:
                with (
                    self.subTest(column=column, value=value),
                    self.assertRaises(DataError),
                ):
                    validar_vendas(self.sales.assign(**{column: value}))

    def test_integer_units_are_limited_to_exact_float_range(self):
        maximum = 2**53 - 1
        actual = validar_vendas(self.sales.assign(vendas=maximum))
        self.assertEqual(actual["vendas"].iloc[0], maximum)
        for value in [2**53, 2**53 + 1, 10**30]:
            with self.subTest(value=value), self.assertRaises(DataError):
                validar_vendas(self.sales.assign(vendas=value))

    def test_intermittent_and_zero_warnings(self):
        for values in [[0] * 45, [0] * 30 + [1] * 15]:
            report = inspecionar_vendas(self.sales.assign(vendas=values))
            self.assertTrue(report["nivel"].eq("aviso").all())
            self.assertFalse(report.empty)

    def test_unknown_columns_and_empty_csv_are_errors(self):
        with self.assertRaises(DataError):
            validar_vendas(self.sales.assign(revenue=999))
        with self.assertRaises(DataError):
            carregar_vendas(StringIO(""))
        with self.assertRaises(DataError):
            validar_vendas(pd.DataFrame(columns=["data", "vendas"]))

    def test_nested_json_values_are_reported_instead_of_crashing(self):
        for column, value in [("sku", ["001"]), ("data", {"dia": 1}), ("vendas", [2])]:
            raw = self.sales.astype({column: object})
            raw.at[0, column] = value
            with self.subTest(column=column), self.assertRaises(DataError):
                validar_vendas(raw)


class TestFutureContext(unittest.TestCase):
    def setUp(self):
        self.sales = validar_vendas(
            pd.DataFrame(
                {
                    "sku": ["001"] * 3,
                    "data": ["2026-01-01", "2026-01-02", "2026-01-03"],
                    "vendas": [1, 2, 3],
                }
            )
        )
        self.future = pd.DataFrame(
            {
                "sku": ["001"] * 7,
                "data": pd.date_range("2026-01-04", periods=7),
                "preco": [10] * 7,
                "promocao": [0] * 7,
                "feriado": [0] * 7,
            }
        )

    def test_exact_future_coverage_and_legacy_single_product(self):
        result = validar_contexto_futuro(self.future.drop(columns="sku"), self.sales, 7)
        self.assertEqual(result["sku"].unique().tolist(), ["001"])
        self.assertEqual(len(result), 7)

    def test_long_calendar_can_be_reused_for_shorter_horizon(self):
        future = pd.DataFrame(
            {
                "sku": ["001"] * 90,
                "data": pd.date_range("2026-01-04", periods=90),
                "preco": [10] * 90,
                "promocao": [0] * 90,
                "feriado": [0] * 90,
            }
        )
        result = validar_contexto_futuro(future, self.sales, 7)
        self.assertEqual(len(result), 7)
        self.assertEqual(result["data"].max(), pd.Timestamp("2026-01-10"))
        future.loc[89, "promocao"] = 2
        with self.assertRaises(DataError):
            validar_contexto_futuro(future, self.sales, 7)

    def test_gaps_and_historical_dates_rejected(self):
        for future in [
            self.future.iloc[:-1],
            self.future.assign(data=pd.date_range("2026-01-03", periods=7)),
            self.future.assign(sku="OUTRO"),
        ]:
            with self.subTest(rows=len(future)), self.assertRaises(DataError):
                validar_contexto_futuro(future, self.sales, 7)

    def test_all_context_fields_required_and_binary(self):
        for future in [
            self.future.drop(columns="promocao"),
            self.future.assign(feriado=2),
            pd.concat([self.future, self.future.iloc[:1]]),
        ]:
            with self.assertRaises(DataError):
                validar_contexto_futuro(future, self.sales, 7)


class TestPlanningData(unittest.TestCase):
    def setUp(self):
        self.products = pd.DataFrame(
            [
                {
                    "sku": "001",
                    "nome": "Café",
                    "fornecedor_id": "F01",
                    "estoque_atual": 20,
                    "estoque_seguranca": 5,
                    "pedido_minimo": 0,
                    "multiplo_compra": 6,
                }
            ]
        )
        self.suppliers = pd.DataFrame(
            [{"fornecedor_id": "F01", "nome": "Fornecedor", "prazo_dias": 3}]
        )
        self.orders = pd.DataFrame(
            [
                {
                    "pedido_id": "P01",
                    "sku": "001",
                    "quantidade": 12,
                    "data_entrega": "2026-01-04",
                }
            ]
        )
        self.origin = pd.Timestamp("2026-01-03")

    def validate(self, **kwargs):
        values = {
            "produtos": self.products,
            "fornecedores": self.suppliers,
            "pedidos": self.orders,
            "skus": ["001"],
            "origem": self.origin,
        }
        values.update(kwargs)
        return validar_planejamento(**values)

    def test_planning_optional_and_empty_orders(self):
        frames = validar_planejamento(None, None, None, ["001"], self.origin)
        self.assertTrue(all(frame.empty for frame in frames))
        products, suppliers, orders = self.validate(pedidos=None)
        self.assertEqual(len(products), 1)
        self.assertEqual(len(suppliers), 1)
        self.assertTrue(orders.empty)
        self.assertIn("data_entrega", orders)

    def test_accepts_canonical_timestamps_and_catalog_only_products(self):
        products, suppliers, orders = self.validate()
        extra = products.assign(sku="NOVO", nome="Novo produto")
        result = self.validate(
            produtos=pd.concat([products, extra]),
            fornecedores=suppliers,
            pedidos=orders,
        )
        self.assertEqual(len(result[0]), 2)

    def test_references_and_duplicate_identifiers(self):
        cases = [
            {"produtos": self.products.assign(fornecedor_id="DESCONHECIDO")},
            {"skus": ["001", "FALTANTE"]},
            {"pedidos": self.orders.assign(sku="OUTRO")},
            {"pedidos": pd.concat([self.orders, self.orders])},
            {"fornecedores": pd.concat([self.suppliers, self.suppliers])},
            {"produtos": pd.concat([self.products, self.products])},
        ]
        for updates in cases:
            with self.subTest(keys=list(updates)), self.assertRaises(DataError):
                self.validate(**updates)

    def test_orders_must_arrive_after_snapshot(self):
        for delivery in ["2026-01-03", "2026-01-02"]:
            with self.subTest(delivery=delivery), self.assertRaises(DataError):
                self.validate(pedidos=self.orders.assign(data_entrega=delivery))

    def test_supplier_limits_and_invalid_inventory(self):
        cases = [
            {"fornecedores": self.suppliers.assign(prazo_dias=61)},
            {"fornecedores": self.suppliers.assign(prazo_dias=1.5)},
            {"produtos": self.products.assign(multiplo_compra=0)},
            {"produtos": self.products.assign(estoque_atual=-1)},
            {"pedidos": self.orders.assign(quantidade=0)},
            {"produtos": self.products.assign(estoque_atual=True)},
            {"produtos": self.products.assign(multiplo_compra=False)},
            {"produtos": self.products.assign(estoque_seguranca=2**53)},
            {"pedidos": self.orders.assign(quantidade=2**53)},
        ]
        for updates in cases:
            with self.subTest(keys=list(updates)), self.assertRaises(DataError):
                self.validate(**updates)

    def test_planning_requires_suppliers_and_catalog(self):
        for updates in [{"produtos": None}, {"fornecedores": None}]:
            with self.assertRaises(DataError):
                self.validate(**updates)

    def test_api_rejects_boolean_sales_and_stock_with_422(self):
        from fastapi.testclient import TestClient
        from api import create_app

        sales = [{"sku": "001", "data": "2026-01-03", "vendas": True}]
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"STOCKMIND_API_KEY": ""}):
                with TestClient(
                    create_app(Path(directory) / "bools.sqlite3")
                ) as client:
                    response = client.post("/analises", json={"vendas": sales})
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertIn("booleanos", response.text)
                    sales[0]["vendas"] = 3
                    products = self.products.assign(estoque_atual=True).to_dict(
                        "records"
                    )
                    response = client.post(
                        "/analises",
                        json={
                            "vendas": sales,
                            "produtos": products,
                            "fornecedores": self.suppliers.to_dict("records"),
                        },
                    )
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertIn("estoque_atual", response.text)


if __name__ == "__main__":
    unittest.main()
