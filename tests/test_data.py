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
    validar_entregas,
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
        for column in ["vendas", "preco", "promocao", "feriado", "disponivel"]:
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

    def test_legacy_availability_unknown_is_not_assumed_available(self):
        result = validar_vendas(self.sales)
        self.assertNotIn("disponivel", result)
        report = inspecionar_vendas(self.sales)
        warning = report.loc[report["campo"].eq("disponivel")]
        self.assertEqual(len(warning), 1)
        self.assertEqual(warning.iloc[0]["nivel"], "aviso")
        self.assertIn("não informada", warning.iloc[0]["mensagem"])

    def test_censored_sales_and_true_zero_sales_are_preserved(self):
        sales = self.sales.assign(disponivel=1)
        sales.loc[0, ["vendas", "disponivel"]] = [0, 0]
        sales.loc[1, ["vendas", "disponivel"]] = [5, 0]
        sales.loc[2, "vendas"] = 0
        actual = validar_vendas(sales)
        self.assertEqual(len(actual), 45)
        self.assertEqual(actual["vendas"].tolist(), sales["vendas"].tolist())
        self.assertEqual(actual["disponivel"].tolist(), sales["disponivel"].tolist())
        warning = inspecionar_vendas(sales).query("campo == 'disponivel'")
        self.assertEqual(len(warning), 1)
        self.assertIn("2 dias", warning.iloc[0]["mensagem"])
        self.assertIn("censuradas", warning.iloc[0]["mensagem"])

    def test_availability_must_be_complete_finite_and_binary(self):
        for value in [None, "", -1, 2, 0.5, float("inf"), float("nan")]:
            sales = self.sales.assign(disponivel=pd.Series([1] * 45, dtype=object))
            sales.at[0, "disponivel"] = value
            with self.subTest(value=value), self.assertRaises(DataError) as context:
                validar_vendas(sales)
            self.assertIn("disponivel", set(context.exception.report["campo"]))

    def test_censored_counts_are_reported_per_product(self):
        first = self.sales.assign(disponivel=1)
        first.loc[:1, "disponivel"] = 0
        second = self.sales.assign(sku="002", disponivel=1)
        second.loc[0, "disponivel"] = 0
        report = inspecionar_vendas(pd.concat([first, second]))
        warnings = report.loc[report["campo"].eq("disponivel")].set_index("sku")
        self.assertIn("2 dias", warnings.loc["001", "mensagem"])
        self.assertIn("1 dias", warnings.loc["002", "mensagem"])

    def test_censored_zero_days_do_not_claim_intermittent_demand(self):
        sales = self.sales.assign(disponivel=0, vendas=0)
        sales.loc[44, ["disponivel", "vendas"]] = [1, 10]
        report = inspecionar_vendas(sales)
        self.assertTrue(report["campo"].eq("disponivel").all())
        self.assertEqual(len(validar_vendas(sales)), 45)


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

    def test_future_availability_is_unknown_and_not_accepted_as_context(self):
        for value in [0, 1]:
            with self.subTest(value=value), self.assertRaises(DataError) as context:
                validar_contexto_futuro(
                    self.future.assign(disponivel=value), self.sales, 7
                )
            self.assertIn("disponivel", set(context.exception.report["campo"]))


class TestHistoricalReceipts(unittest.TestCase):
    def setUp(self):
        self.receipts = pd.DataFrame(
            [
                {
                    "entrega_id": "001",
                    "fornecedor_id": "F1",
                    "data_pedido": "2026-01-01",
                    "data_prevista": "2026-01-05",
                    "data_recebida": "2026-01-06",
                },
                {
                    "entrega_id": "002",
                    "fornecedor_id": "F1",
                    "data_pedido": "2026-01-07",
                    "data_prevista": "2026-01-12",
                    "data_recebida": "2026-01-10",
                },
            ]
        )
        self.origin = pd.Timestamp("2026-01-10")
        self.suppliers = pd.DataFrame(
            [{"fornecedor_id": "F1", "nome": "Fornecedor", "prazo_dias": 5}]
        )

    def test_early_and_late_receipts_are_valid_and_idempotent(self):
        result = validar_entregas(self.receipts, self.origin, self.suppliers)
        self.assertEqual(result["entrega_id"].tolist(), ["001", "002"])
        self.assertLess(result.loc[1, "data_recebida"], result.loc[1, "data_prevista"])
        pd.testing.assert_frame_equal(
            validar_entregas(result, self.origin, self.suppliers), result
        )

    def test_csv_preserves_receipt_identifiers_and_supplier_codes(self):
        raw = ler_csv(
            StringIO(
                "entrega_id,fornecedor_id,data_pedido,data_prevista,data_recebida\n001,002,2026-01-01,2026-01-05,2026-01-04\n"
            )
        )
        result = validar_entregas(raw, self.origin)
        self.assertEqual(result.iloc[0]["entrega_id"], "001")
        self.assertEqual(result.iloc[0]["fornecedor_id"], "002")

    def test_none_and_empty_receipts_return_empty_canonical_tables(self):
        for raw in [None, pd.DataFrame(), self.receipts.iloc[:0]]:
            with self.subTest(raw_type=type(raw).__name__):
                result = validar_entregas(raw, self.origin)
                self.assertTrue(result.empty)
                self.assertEqual(
                    result.columns.tolist(), self.receipts.columns.tolist()
                )

    def test_no_future_received_information_allowed(self):
        # The second receipt is known on Jan10, not Jan9.
        with self.assertRaisesRegex(DataError, "referência"):
            validar_entregas(self.receipts, "2026-01-09")
        self.assertEqual(len(validar_entregas(self.receipts, "2026-01-10")), 2)

    def test_promised_future_date_is_allowed_if_delivery_already_arrived(self):
        raw = self.receipts.iloc[[1]].assign(data_prevista="2026-02-01")
        result = validar_entregas(raw, self.origin)
        self.assertEqual(result.iloc[0]["data_prevista"], pd.Timestamp("2026-02-01"))

    def test_order_must_not_follow_promised_or_received_date(self):
        for column in ["data_prevista", "data_recebida"]:
            with self.subTest(column=column), self.assertRaises(DataError) as context:
                validar_entregas(
                    self.receipts.assign(**{column: "2025-12-31"}), self.origin
                )
            self.assertIn(column, set(context.exception.report["campo"]))

    def test_historical_lead_times_are_bounded_to_365_days(self):
        raw = self.receipts.iloc[:1].assign(
            data_prevista="2027-01-01", data_recebida="2027-01-01"
        )
        self.assertEqual(len(validar_entregas(raw, "2027-01-01")), 1)
        for column in ["data_prevista", "data_recebida"]:
            with self.subTest(column=column), self.assertRaisesRegex(DataError, "365"):
                validar_entregas(raw.assign(**{column: "2027-01-02"}), "2027-01-02")

    def test_supplier_reference_validation_is_optional(self):
        self.assertEqual(len(validar_entregas(self.receipts, self.origin)), 2)
        with self.assertRaisesRegex(DataError, "não cadastrado"):
            validar_entregas(
                self.receipts, self.origin, self.suppliers.assign(fornecedor_id="OUTRO")
            )

    def test_duplicate_empty_ids_dates_and_unknown_fields_are_reported(self):
        raw = self.receipts.copy()
        raw.loc[1, "entrega_id"] = "001"
        raw.loc[0, "fornecedor_id"] = ""
        raw.loc[1, "data_recebida"] = "data inválida"
        raw["quantidade"] = 10
        with self.assertRaises(DataError) as context:
            validar_entregas(raw, self.origin)
        fields = set(context.exception.report["campo"])
        self.assertTrue(
            {"entrega_id", "fornecedor_id", "data_recebida", "quantidade"}.issubset(
                fields
            )
        )

    def test_same_day_receipts_allowed_but_date_times_rejected(self):
        raw = self.receipts.iloc[:1].assign(
            data_pedido="2026-01-01",
            data_prevista="2026-01-01",
            data_recebida="2026-01-01",
        )
        self.assertEqual(len(validar_entregas(raw, self.origin)), 1)
        with self.assertRaises(DataError):
            validar_entregas(
                raw.assign(data_recebida="2026-01-01 12:00:00"), self.origin
            )

    def test_different_receipts_same_supplier_and_day_are_not_duplicates(self):
        raw = pd.concat(
            [self.receipts.iloc[:1], self.receipts.iloc[:1].assign(entrega_id="OUTRA")]
        )
        self.assertEqual(len(validar_entregas(raw, self.origin)), 2)


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
