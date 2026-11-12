"""Explicação auditável e reserva de orçamento; nenhuma compra é executada."""

from decimal import Decimal, InvalidOperation
import math
import pandas as pd


def centavos(value, name, *, positivo=False):
    if isinstance(value, bool):
        raise ValueError(f"{name}: informe valor monetário.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name}: valor monetário inválido.") from None
    if (
        not number.is_finite()
        or number < 0
        or number > Decimal("999999999999.99")
        or number != number.quantize(Decimal("0.01"))
        or (positivo and number == 0)
    ):
        raise ValueError(
            f"{name}: valor não negativo com até duas casas; custo deve ser positivo."
        )
    return int(number * 100)


def dinheiro(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def explicar_compras(
    vendas, previsoes, saldos, recomendacoes, produtos, revisao, metricas=None
):
    """Uma memória por SKU, para a compra na origem e a compra agendada.

    A quantidade é a mesma do planejador; o déficit bruto permite revisar o
    arredondamento. Ausência de trajetória ou cobertura é desconhecida, não zero.
    """
    rows, diagnostics = [], []
    if produtos is None or recomendacoes.empty:
        return pd.DataFrame(), pd.DataFrame()
    catalog = produtos.set_index("sku").to_dict("index")
    origin = vendas.data.max()
    for r in recomendacoes.to_dict("records"):
        sku = r["sku"]
        history = vendas.loc[vendas.sku.eq(sku)]
        points = previsoes.loc[previsoes.sku.eq(sku)]
        reasons = []
        blocked = points.empty
        if blocked:
            reasons.append("Sem trajetória utilizável; não dimensionar compra.")
        if r["status_previsao"] != "avaliado":
            reasons.append(f"Status da previsão: {r['status_previsao']}.")
        if "disponivel" not in history:
            reasons.append(
                "Disponibilidade desconhecida: vendas observadas não comprovam demanda."
            )
        elif history.disponivel.eq(0).any():
            reasons.append("Há dias censurados: demanda perdida não foi estimada.")
        if (
            r["status_agendamento"] == "horizonte_insuficiente"
            or r["status"] == "horizonte_insuficiente"
        ):
            blocked = True
            reasons.append("Previsão não cobre toda a janela necessária da compra.")
        if metricas is not None and not metricas.empty:
            selected = metricas.loc[
                metricas.sku.eq(sku) & metricas.selecionado.eq(True)
            ]
            if not selected.empty:
                measured = selected.iloc[0]
                gain = measured.get("ganho_mae_teste_pct")
                if pd.notna(gain) and gain < 0:
                    reasons.append(
                        "Método escolhido perdeu para a referência semanal no teste; investigar desempenho."
                    )
                if pd.isna(measured.get("mae_teste")):
                    reasons.append(
                        "Sem erro de teste mensurável para o método escolhido."
                    )
            if (
                "limite_inferior" in points
                and not points.empty
                and points.limite_inferior.isna().all()
            ):
                reasons.append("Sem faixa empírica calibrada para esta previsão.")
        state = "insuficiente" if blocked else "provisoria" if reasons else "avaliada"
        diagnostics.append(
            {
                "sku": sku,
                "situacao_dados": state,
                "dias_historico": len(history),
                "dias_previstos": len(points),
                "motivos": " ".join(reasons)
                or "Histórico avaliado e disponibilidade declarada; revisar premissas comerciais.",
                "garantia": "Diagnóstico de dados, não probabilidade de acerto ou aprovação de compra.",
            }
        )
        path = (
            saldos.loc[saldos.sku.eq(sku)].sort_values("data")
            if not saldos.empty
            else pd.DataFrame()
        )
        p = catalog[sku]
        for kind, date, quantity in [
            ("na_origem", origin, r["compra_sugerida"]),
            ("agendada", r["data_compra_sugerida"], r["quantidade_compra_na_data"]),
        ]:
            date = pd.Timestamp(date) if pd.notna(date) else None
            lead = int(r["prazo_dias"])
            arrival = (
                date + pd.Timedelta(days=max(1, lead)) if date is not None else None
            )
            end = date + pd.Timedelta(days=lead + revisao) if date is not None else None
            covered = bool(
                end is not None and not path.empty and end <= path.data.max()
            )
            window = (
                path.loc[path.data.between(arrival, end)] if covered else pd.DataFrame()
            )
            lowest = float(window.saldo_estimado.min()) if not window.empty else None
            raw = (
                max(0.0, float(p["estoque_seguranca"]) - lowest)
                if lowest is not None
                else None
            )
            rows.append(
                {
                    "sku": sku,
                    "tipo_compra": kind,
                    "data_compra": date,
                    "origem": origin,
                    "estoque_inicial": p["estoque_atual"],
                    "estoque_seguranca": p["estoque_seguranca"],
                    "prazo_dias": lead,
                    "revisao_dias": revisao,
                    "chegada": arrival,
                    "fim_protecao": end,
                    "cobertura_completa": covered,
                    "menor_saldo_janela": lowest,
                    "data_menor_saldo": window.loc[
                        window.saldo_estimado.idxmin(), "data"
                    ]
                    if not window.empty
                    else None,
                    "necessidade_antes_lote": raw,
                    "pedido_minimo": p["pedido_minimo"],
                    "multiplo_compra": p["multiplo_compra"],
                    "quantidade_sugerida": quantity if pd.notna(quantity) else None,
                    "recebimentos_ate_protecao": float(
                        path.loc[path.data.le(end), "recebimentos"].sum()
                    )
                    if covered
                    else None,
                    "consumo_previsto_ate_protecao": float(
                        path.loc[path.data.le(end), "previsao"].sum()
                    )
                    if covered
                    else None,
                    "falta_antes_entrega": bool(
                        pd.notna(r["primeira_falta"])
                        and arrival is not None
                        and pd.Timestamp(r["primeira_falta"]) < arrival
                    ),
                    "situacao_dados": state,
                    "regra": "max(0, segurança - menor saldo após chegada); se positivo, aplicar mínimo e arredondar para lote. Pedidos já estão no saldo.",
                }
            )
    memory = pd.DataFrame(rows)
    for col in ("data_compra", "origem", "chegada", "fim_protecao", "data_menor_saldo"):
        memory[col] = pd.to_datetime(memory[col])
    return memory, pd.DataFrame(diagnostics)


def distribuir_orcamento(recomendacoes, produtos, orcamento, custos):
    """Heurística gulosa determinística; reserva de compras agendadas no horizonte.

    Prioridade, falta mais próxima e SKU definem a ordem. Não otimiza lucro/serviço,
    não altera recomendações nem considera frete, tributos ou descontos.
    """
    if orcamento is None:
        if custos:
            raise ValueError("Informe orçamento para utilizar custos unitários.")
        return [], None
    budget = centavos(orcamento, "orcamento_compras")
    if produtos is None:
        raise ValueError("Orçamento exige produtos e fornecedores.")
    if custos is not None and not isinstance(custos, dict):
        raise ValueError("custos_unitarios deve ser um mapa SKU/valor.")
    costs = {
        sku: centavos(value, "custo_unitario", positivo=True)
        for sku, value in (custos or {}).items()
    }
    catalog = produtos.set_index("sku").to_dict("index")
    if set(costs) - set(catalog):
        raise ValueError("Custo informado para SKU fora do catálogo.")
    ordered = recomendacoes.sort_values(
        ["prioridade_ordem", "dias_ate_falta", "sku"], na_position="last"
    )
    remaining, rows = budget, []
    for r in ordered.to_dict("records"):
        sku = r["sku"]
        qty = r["quantidade_compra_na_data"]
        p = catalog[sku]
        unit = costs.get(sku)
        funded = 0
        if pd.isna(qty):
            state = "quantidade_indefinida"
        elif qty <= 0:
            state = "sem_compra"
        elif unit is None:
            state = "custo_ausente"
        else:
            qty = int(qty)
            lot = int(p["multiplo_compra"])
            minimum = int(p["pedido_minimo"])
            funded = min(qty, (remaining // unit // lot) * lot)
            if funded < max(lot, math.ceil(minimum / lot) * lot):
                funded = 0
            state = (
                "integral"
                if funded == qty
                else "parcial"
                if funded
                else "sem_orcamento"
            )
        spent = funded * (unit or 0)
        remaining -= spent
        rows.append(
            {
                "sku": sku,
                "prioridade": r["prioridade"],
                "data_compra": pd.Timestamp(r["data_compra_sugerida"]).strftime(
                    "%Y-%m-%d"
                )
                if pd.notna(r["data_compra_sugerida"])
                else None,
                "quantidade_sugerida": int(qty) if pd.notna(qty) else None,
                "quantidade_reservada": funded,
                "quantidade_nao_coberta": int(qty) - funded if pd.notna(qty) else None,
                "custo_unitario": dinheiro(unit) if unit is not None else None,
                "custo_reservado": dinheiro(spent),
                "saldo_orcamento": dinheiro(remaining),
                "status_orcamento": state,
                "status_previsao": r["status_previsao"],
                "observacao": "Reserva de orçamento exige revisão; quantidade parcial pode manter risco de falta. Sem frete/tributos.",
            }
        )
    return rows, {
        "orcamento": dinheiro(budget),
        "reservado": dinheiro(budget - remaining),
        "restante": dinheiro(remaining),
        "metodo": "Prioridade, dias até falta e SKU; guloso com mínimos/lotes, sem garantia de ótimo.",
        "escopo": "Todas as compras agendadas sugeridas no horizonte; não é fluxo de caixa por data nem pedido enviado.",
    }
