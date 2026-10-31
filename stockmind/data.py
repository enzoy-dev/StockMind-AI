"""Contratos de importação com diagnóstico explícito, sem preencher vendas ausentes."""

from datetime import date, datetime
import math
import re

import pandas as pd


REPORT_COLUMNS = ["nivel", "sku", "campo", "mensagem", "linha"]
SALES_COLUMNS = ["sku", "data", "vendas"]
CONTEXT_COLUMNS = ["preco", "promocao", "feriado"]
PRODUCT_COLUMNS = [
    "sku",
    "nome",
    "fornecedor_id",
    "estoque_atual",
    "estoque_seguranca",
    "pedido_minimo",
    "multiplo_compra",
]
SUPPLIER_COLUMNS = ["fornecedor_id", "nome", "prazo_dias"]
ORDER_COLUMNS = ["pedido_id", "sku", "quantidade", "data_entrega"]
RECEIPT_COLUMNS = [
    "entrega_id",
    "fornecedor_id",
    "data_pedido",
    "data_prevista",
    "data_recebida",
]
MAX_RECEIPT_LEAD_DAYS = 365
MAX_SAFE_INTEGER = 2**53 - 1


class DataError(ValueError):
    """Erro de contrato acompanhado pelo relatório completo de qualidade."""

    def __init__(self, message, report=None):
        self.report = (
            report
            if report is not None
            else pd.DataFrame(
                [
                    {
                        "nivel": "erro",
                        "sku": None,
                        "campo": "arquivo",
                        "mensagem": str(message),
                        "linha": None,
                    }
                ],
                columns=REPORT_COLUMNS,
            )
        )
        super().__init__(message)


def _issue(issues, campo, mensagem, sku=None, linha=None, nivel="erro"):
    issues.append(
        {
            "nivel": nivel,
            "sku": sku,
            "campo": campo,
            "mensagem": mensagem,
            "linha": linha,
        }
    )


def _report(issues):
    return pd.DataFrame(issues, columns=REPORT_COLUMNS)


def _fail(issues):
    report = _report(issues)
    errors = [item["mensagem"] for item in issues if item["nivel"] == "erro"]
    if errors:
        raise DataError(" ".join(errors[:3]), report)
    return report


def ler_csv(arquivo):
    """Lê CSV UTF-8 e preserva códigos como 001 e NA como identificadores."""
    try:
        return pd.read_csv(
            arquivo,
            dtype={
                "sku": str,
                "fornecedor_id": str,
                "pedido_id": str,
                "entrega_id": str,
            },
            keep_default_na=False,
        )
    except (ValueError, UnicodeError, OSError) as exc:
        raise DataError(f"Não foi possível ler o CSV: {exc}") from exc


def _frame(raw, required, issues, label):
    if raw is None:
        return pd.DataFrame(columns=required)
    if not isinstance(raw, pd.DataFrame):
        _issue(issues, label, f"{label}: entrada deve ser uma tabela.")
        return pd.DataFrame(columns=required)
    frame = raw.copy().reset_index(drop=True)
    if frame.columns.duplicated().any():
        _issue(issues, label, f"{label}: há nomes de colunas duplicados.")
        frame = frame.loc[:, ~frame.columns.duplicated()].copy()
    for column in required:
        if column not in frame.columns:
            _issue(issues, column, f"{label}: coluna obrigatória ausente: {column}.")
            frame[column] = pd.NA
    unknown = set(frame.columns) - set(required)
    for column in sorted(unknown, key=str):
        _issue(issues, column, f"{label}: coluna desconhecida: {column}.")
    return frame


def _ids(frame, column, issues):
    values = []
    for i, value in enumerate(frame[column]):
        missing = (
            not pd.api.types.is_scalar(value)
            or pd.isna(value)
            or str(value).strip() == ""
        )
        normal = "" if missing else str(value).strip()
        if missing:
            _issue(issues, column, f"{column} não pode estar vazio.", linha=i + 2)
        values.append(normal)
    frame[column] = values


def _date_value(value):
    if not pd.api.types.is_scalar(value) or pd.isna(value):
        return pd.NaT
    try:
        if isinstance(value, (pd.Timestamp, date, datetime)):
            result = pd.Timestamp(value)
            if result.tzinfo is not None or result != result.normalize():
                return pd.NaT
            # Restrict to the nanosecond range used in the rest of pandas.
            return pd.to_datetime(result, errors="coerce")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
            return pd.NaT
        return pd.to_datetime(str(value), format="%Y-%m-%d", errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


def _dates(frame, column, issues):
    parsed = []
    for i, value in enumerate(frame[column]):
        result = _date_value(value)
        if pd.isna(result):
            sku = frame["sku"].iloc[i] if "sku" in frame else None
            _issue(
                issues,
                column,
                f"{column} inválida: use YYYY-MM-DD, sem horário ou fuso.",
                sku,
                i + 2,
            )
        parsed.append(result)
    frame[column] = pd.to_datetime(parsed)


def _numbers(frame, column, issues, integer=False, minimum=0, maximum=None):
    if integer:
        maximum = (
            min(maximum, MAX_SAFE_INTEGER) if maximum is not None else MAX_SAFE_INTEGER
        )

    def numeric_value(value):
        if not pd.api.types.is_scalar(value) or pd.api.types.is_bool(value):
            return math.nan
        try:
            return float(value)
        except (ValueError, TypeError, OverflowError):
            return math.nan

    parsed = frame[column].map(numeric_value)
    for i, value in enumerate(parsed):
        invalid = pd.isna(value)
        if not invalid:
            numeric = float(value)
            invalid = not math.isfinite(numeric) or numeric < minimum
            invalid = invalid or (integer and numeric != math.floor(numeric))
            invalid = invalid or (maximum is not None and numeric > maximum)
        if invalid:
            sku = frame["sku"].iloc[i] if "sku" in frame else None
            description = "inteiro" if integer else "número"
            bounds = (
                f"entre {minimum} e {maximum}"
                if maximum is not None
                else f"maior ou igual a {minimum}"
            )
            _issue(
                issues,
                column,
                f"{column} deve ser {description} finito {bounds}; booleanos não são aceitos.",
                sku,
                i + 2,
            )
    frame[column] = parsed


def _duplicate(frame, columns, issues, label):
    for i in frame.index[frame.duplicated(columns, keep=False)]:
        sku = frame.loc[i, "sku"] if "sku" in frame else None
        _issue(
            issues,
            ",".join(columns),
            f"{label}: identificador duplicado ({', '.join(columns)}).",
            sku,
            int(i) + 2,
        )


def _normalize_sales(raw):
    issues = []
    if isinstance(raw, pd.DataFrame):
        raw = raw.copy()
        if "sku" not in raw.columns:
            raw["sku"] = "PRODUTO-001"
        supplied_context = [col for col in CONTEXT_COLUMNS if col in raw.columns]
        supplied_availability = "disponivel" in raw.columns
    else:
        supplied_context = []
        supplied_availability = False
    required = (
        SALES_COLUMNS
        + supplied_context
        + (["disponivel"] if supplied_availability else [])
    )
    frame = _frame(raw, required, issues, "vendas")
    if frame.empty:
        _issue(issues, "vendas", "O histórico de vendas está vazio.")
        return frame, issues
    _ids(frame, "sku", issues)
    _dates(frame, "data", issues)
    _numbers(frame, "vendas", issues, integer=True)
    if supplied_availability:
        _numbers(frame, "disponivel", issues, integer=True, maximum=1)
    for col in supplied_context:
        _numbers(
            frame,
            col,
            issues,
            integer=col != "preco",
            maximum=1 if col != "preco" else None,
        )
    _duplicate(frame, ["sku", "data"], issues, "vendas")
    if supplied_context and len(supplied_context) != len(CONTEXT_COLUMNS):
        _issue(
            issues,
            "contexto",
            "Contexto parcial: o modelo contextual exige preco, promocao e feriado no histórico e no plano futuro.",
            nivel="aviso",
        )
    ends = []
    for sku, group in frame.groupby("sku", sort=False):
        valid_dates = group["data"].dropna().drop_duplicates()
        if valid_dates.empty:
            continue
        begin, end = valid_dates.min(), valid_dates.max()
        ends.append(end)
        expected = (end - begin).days + 1
        if len(valid_dates) != expected:
            _issue(
                issues,
                "data",
                f"{sku}: faltam {expected - len(valid_dates)} dias no histórico. Não são convertidos automaticamente em zero.",
                sku,
            )
        if len(group) < 30:
            _issue(
                issues,
                "historico",
                f"{sku}: apenas {len(group)} dias; métodos de referência podem ser usados sem avaliação suficiente.",
                sku,
                nivel="aviso",
            )
        if supplied_availability:
            censored = int(group["disponivel"].eq(0).sum())
            if censored:
                _issue(
                    issues,
                    "disponivel",
                    f"{sku}: {censored} dias com disponibilidade parcial ou ausente; vendas censuradas não medem a demanda perdida.",
                    sku,
                    nivel="aviso",
                )
            # Zeros em dias censurados não identificam demanda intermitente.
            units = group.loc[group["disponivel"].eq(1), "vendas"].dropna()
        else:
            _issue(
                issues,
                "disponivel",
                f"{sku}: disponibilidade histórica não informada; não é possível distinguir vendas baixas de vendas limitadas por falta de estoque.",
                sku,
                nivel="aviso",
            )
            units = group["vendas"].dropna()
        if len(units) and units.eq(0).all():
            _issue(
                issues,
                "vendas",
                f"{sku}: todas as vendas registradas são zero; isso não confirma ausência de demanda.",
                sku,
                nivel="aviso",
            )
        elif len(units) and units.eq(0).mean() >= 0.5:
            _issue(
                issues,
                "vendas",
                f"{sku}: vendas intermitentes, com pelo menos metade dos dias zerados.",
                sku,
                nivel="aviso",
            )
    if len(set(ends)) > 1:
        _issue(
            issues,
            "data",
            "Todos os produtos devem terminar na mesma data de referência.",
        )
    return frame.sort_values(["sku", "data"]).reset_index(drop=True), issues


def inspecionar_vendas(raw):
    """Retorna todos os erros/avisos encontrados, sem interromper no primeiro."""
    _, issues = _normalize_sales(raw)
    return _report(issues)


def validar_vendas(raw):
    frame, issues = _normalize_sales(raw)
    _fail(issues)
    return frame


def carregar_vendas(arquivo):
    return validar_vendas(ler_csv(arquivo))


def validar_contexto_futuro(raw, vendas, horizonte):
    issues = []
    if (
        not isinstance(horizonte, int)
        or isinstance(horizonte, bool)
        or not 1 <= horizonte <= 90
    ):
        raise DataError("Horizonte do contexto deve ser inteiro entre 1 e 90 dias.")
    if (
        isinstance(raw, pd.DataFrame)
        and "sku" not in raw
        and vendas["sku"].nunique() == 1
    ):
        raw = raw.assign(sku=vendas["sku"].iloc[0])
    frame = _frame(raw, ["sku", "data", *CONTEXT_COLUMNS], issues, "contexto futuro")
    _ids(frame, "sku", issues)
    _dates(frame, "data", issues)
    for col in CONTEXT_COLUMNS:
        _numbers(
            frame,
            col,
            issues,
            integer=col != "preco",
            maximum=1 if col != "preco" else None,
        )
    _duplicate(frame, ["sku", "data"], issues, "contexto futuro")
    known = set(vendas["sku"])
    if set(frame["sku"]) - known:
        _issue(
            issues,
            "sku",
            "O contexto futuro contém produtos sem histórico correspondente.",
        )
    required_rows = pd.Series(False, index=frame.index)
    for sku in sorted(known):
        end = vendas.loc[vendas["sku"].eq(sku), "data"].max()
        expected = set(pd.date_range(end + pd.Timedelta(days=1), periods=horizonte))
        actual = set(frame.loc[frame["sku"].eq(sku), "data"].dropna())
        if any(day <= end for day in actual):
            _issue(
                issues,
                "data",
                f"{sku}: o plano futuro não pode incluir datas do histórico.",
                sku,
            )
        if not expected.issubset(actual):
            _issue(
                issues,
                "data",
                f"{sku}: o plano futuro deve cobrir todos os {horizonte} dias após o histórico.",
                sku,
            )
        required_rows |= frame["sku"].eq(sku) & frame["data"].isin(expected)
    _fail(issues)
    return frame.loc[required_rows].sort_values(["sku", "data"]).reset_index(drop=True)


def validar_planejamento(produtos, fornecedores, pedidos, skus, origem):
    """Valida catálogo, fornecedores e pedidos em aberto como uma unidade."""
    if produtos is None and fornecedores is None and pedidos is None:
        return (
            pd.DataFrame(columns=PRODUCT_COLUMNS),
            pd.DataFrame(columns=SUPPLIER_COLUMNS),
            pd.DataFrame(columns=ORDER_COLUMNS),
        )
    issues = []
    products = _frame(produtos, PRODUCT_COLUMNS, issues, "produtos")
    suppliers = _frame(fornecedores, SUPPLIER_COLUMNS, issues, "fornecedores")
    orders = _frame(pedidos, ORDER_COLUMNS, issues, "pedidos")
    if products.empty:
        _issue(issues, "produtos", "O planejamento exige um catálogo de produtos.")
    if suppliers.empty:
        _issue(issues, "fornecedores", "O planejamento exige fornecedores cadastrados.")
    for column in ["sku", "nome", "fornecedor_id"]:
        _ids(products, column, issues)
    for column in ["fornecedor_id", "nome"]:
        _ids(suppliers, column, issues)
    for column in ["pedido_id", "sku"]:
        _ids(orders, column, issues)
    for column in [
        "estoque_atual",
        "estoque_seguranca",
        "pedido_minimo",
        "multiplo_compra",
    ]:
        _numbers(
            products,
            column,
            issues,
            integer=True,
            minimum=1 if column == "multiplo_compra" else 0,
        )
    _numbers(suppliers, "prazo_dias", issues, integer=True, maximum=60)
    _numbers(orders, "quantidade", issues, integer=True, minimum=1)
    _dates(orders, "data_entrega", issues)
    _duplicate(products, ["sku"], issues, "produtos")
    _duplicate(suppliers, ["fornecedor_id"], issues, "fornecedores")
    _duplicate(orders, ["pedido_id"], issues, "pedidos")
    known_skus = {str(sku) for sku in skus}
    product_skus = set(products["sku"])
    for sku in sorted(known_skus - product_skus):
        _issue(issues, "sku", f"{sku}: produto das vendas ausente no catálogo.", sku)
    for sku in sorted(product_skus - known_skus):
        _issue(
            issues,
            "sku",
            f"{sku}: produto cadastrado sem histórico; não será assumida demanda zero.",
            sku,
            nivel="aviso",
        )
    supplier_ids = set(suppliers["fornecedor_id"])
    for row in products.itertuples():
        if row.fornecedor_id not in supplier_ids:
            _issue(
                issues,
                "fornecedor_id",
                f"{row.sku}: fornecedor inexistente: {row.fornecedor_id}.",
                row.sku,
            )
    origin = _date_value(origem)
    if pd.isna(origin):
        _issue(issues, "origem", "Data de referência inválida para o planejamento.")
    for row in orders.itertuples():
        if row.sku not in product_skus:
            _issue(
                issues,
                "sku",
                f"Pedido {row.pedido_id}: SKU não cadastrado: {row.sku}.",
                row.sku,
            )
        if (
            pd.notna(row.data_entrega)
            and pd.notna(origin)
            and row.data_entrega <= origin
        ):
            _issue(
                issues,
                "data_entrega",
                f"Pedido {row.pedido_id}: entrega deve ser após a data de referência do estoque.",
                row.sku,
            )
    _fail(issues)
    return (
        products.sort_values("sku").reset_index(drop=True),
        suppliers.sort_values("fornecedor_id").reset_index(drop=True),
        orders.sort_values(["data_entrega", "pedido_id"]).reset_index(drop=True),
    )


def validar_entregas(raw, origem, fornecedores=None):
    """Valida recebimentos históricos conhecidos na data de referência.

    Uma linha representa uma entrega identificada. Prazos prometidos e realizados
    são limitados a 365 dias corridos a partir do pedido. Chegar antes do prometido
    é válido. Uma entrega recebida após ``origem`` é rejeitada, sem aproveitar
    informação que ainda não estava disponível naquela data.
    """
    issues = []
    if raw is None:
        return pd.DataFrame(columns=RECEIPT_COLUMNS)
    if isinstance(raw, pd.DataFrame) and raw.empty and not len(raw.columns):
        return pd.DataFrame(columns=RECEIPT_COLUMNS)
    frame = _frame(raw, RECEIPT_COLUMNS, issues, "entregas históricas")
    if frame.empty:
        _fail(issues)
        return frame[RECEIPT_COLUMNS].copy()

    _ids(frame, "entrega_id", issues)
    _ids(frame, "fornecedor_id", issues)
    _duplicate(frame, ["entrega_id"], issues, "entregas históricas")
    for column in ["data_pedido", "data_prevista", "data_recebida"]:
        _dates(frame, column, issues)

    origin = _date_value(origem)
    if pd.isna(origin):
        _issue(
            issues, "origem", "Data de referência inválida para as entregas históricas."
        )

    known_suppliers = None
    if fornecedores is not None:
        if (
            not isinstance(fornecedores, pd.DataFrame)
            or "fornecedor_id" not in fornecedores
        ):
            _issue(
                issues,
                "fornecedor_id",
                "Fornecedores devem informar a coluna fornecedor_id.",
            )
        else:
            suppliers = fornecedores[["fornecedor_id"]].copy().reset_index(drop=True)
            _ids(suppliers, "fornecedor_id", issues)
            known_suppliers = set(suppliers["fornecedor_id"])

    for i, row in enumerate(frame.itertuples(index=False), start=2):
        label = f"Entrega {row.entrega_id}"
        if known_suppliers is not None and row.fornecedor_id not in known_suppliers:
            _issue(
                issues,
                "fornecedor_id",
                f"{label}: fornecedor não cadastrado: {row.fornecedor_id}.",
                linha=i,
            )
        if pd.notna(row.data_pedido):
            for column in ["data_prevista", "data_recebida"]:
                value = getattr(row, column)
                if pd.isna(value):
                    continue
                lead = (value - row.data_pedido).days
                if lead < 0 or lead > MAX_RECEIPT_LEAD_DAYS:
                    _issue(
                        issues,
                        column,
                        f"{label}: {column} deve ficar entre 0 e {MAX_RECEIPT_LEAD_DAYS} dias após o pedido.",
                        linha=i,
                    )
        if (
            pd.notna(row.data_recebida)
            and pd.notna(origin)
            and row.data_recebida > origin
        ):
            _issue(
                issues,
                "data_recebida",
                f"{label}: recebimento após a data de referência não pode ser usado como histórico conhecido.",
                linha=i,
            )
    _fail(issues)
    return (
        frame[RECEIPT_COLUMNS]
        .sort_values(["fornecedor_id", "data_recebida", "entrega_id"])
        .reset_index(drop=True)
    )
