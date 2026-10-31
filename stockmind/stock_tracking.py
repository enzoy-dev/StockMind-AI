"""Snapshots observados de estoque: comparação, sem criar um livro de movimentos."""

import pandas as pd
from stockmind.data import DataError, _dates, _ids, _numbers, _duplicate, _fail


def validar_estoques_reais(raw):
    columns = ["sku", "data", "estoque_real"]
    if (
        not isinstance(raw, pd.DataFrame)
        or set(raw.columns) != set(columns)
        or raw.empty
    ):
        raise DataError("Informe sku,data,estoque_real, com pelo menos uma linha.")
    frame = raw.copy().reset_index(drop=True)
    issues = []
    _ids(frame, "sku", issues)
    _dates(frame, "data", issues)
    _numbers(frame, "estoque_real", issues, integer=True)
    _duplicate(frame, ["sku", "data"], issues, "estoques_reais")
    _fail(issues)
    return frame.sort_values(["sku", "data"])


def comparar_estoque(snapshot, actuals):
    rows = []
    lookup = {(r["sku"], r["data"]): r["estoque_real"] for r in actuals}
    for point in snapshot["resultado"].get("saldos", []):
        observed = lookup.get((point["sku"], point["data"]))
        physical = max(0, float(point["saldo_estimado"]))
        rows.append(
            {
                "sku": point["sku"],
                "data": point["data"],
                "saldo_aritmetico": point["saldo_estimado"],
                "estoque_fisico_projetado": physical,
                "estoque_real": observed,
                "diferenca": None if observed is None else physical - observed,
            }
        )
    summary = []
    for sku in sorted({r["sku"] for r in rows}):
        known = [r for r in rows if r["sku"] == sku and r["estoque_real"] is not None]
        summary.append(
            {
                "sku": sku,
                "dias_comparados": len(known),
                "mae_saldo": sum(abs(r["diferenca"]) for r in known) / len(known)
                if known
                else None,
                "vies_saldo": sum(r["diferenca"] for r in known) / len(known)
                if known
                else None,
            }
        )
    return {
        "id": snapshot["id"],
        "resumo": summary,
        "comparacoes": rows,
        "premissa": "Saldo físico projetado=max(0,saldo aritmético). Divergência não atribui causa; não reconcilia movimentos, perdas ou reservas.",
    }
