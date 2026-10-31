"""Replay de políticas com demanda observada/conhecida e premissas explícitas.

Não reconstrói o estoque real passado. O catálogo fornece o estoque inicial e
parâmetros manuais de um cenário, iguais nas políticas. Vendas censuradas no
período impedem a avaliação: não são convertidas em demanda zero nem imputadas.
"""

from __future__ import annotations

import math
from numbers import Integral, Real

import pandas as pd

from stockmind.data import ORDER_COLUMNS, validar_planejamento, validar_vendas
from stockmind.forecasting import analisar_previsoes
from stockmind.inventory import planejar_estoque


POLITICAS = ("Sem reposição", "Média histórica", "Previsão selecionada")
MIN_HISTORICO = 28
SUMMARY_COLUMNS = [
    "sku",
    "politica",
    "status",
    "base_demanda",
    "estoque_inicial",
    "origem_estoque_inicial",
    "periodo_inicio",
    "periodo_fim",
    "dias_avaliados",
    "prazo_dias",
    "revisao_dias",
    "seguranca_manual",
    "demanda_total",
    "vendas_atendidas",
    "vendas_perdidas",
    "atendimento_pct",
    "estoque_medio",
    "estoque_final",
    "dias_com_falta",
    "pedidos_emitidos",
    "unidades_pedidas",
    "em_transito_final",
    "custo_falta_estimado",
    "custo_estoque_estimado",
    "custo_pedidos_estimado",
    "custo_total_estimado",
    "custo_falta_unitario",
    "custo_estoque_unitario_dia",
    "custo_pedido",
    "observacao",
]
DAILY_COLUMNS = [
    "sku",
    "politica",
    "data",
    "fase",
    "demanda",
    "recebimentos",
    "vendas_atendidas",
    "vendas_perdidas",
    "estoque_final",
    "quantidade_pedida",
    "data_entrega_pedido",
    "em_transito",
    "modelo",
    "custo_falta_estimado",
    "custo_estoque_estimado",
    "custo_pedido_estimado",
]


class ForecastUnavailable(ValueError):
    """Não há previsão utilizável para a decisão de um cenário."""


def _integer(value, name, *, choices=None, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{name} deve ser inteiro.")
    value = int(value)
    if (
        (choices is not None and value not in choices)
        or (minimum is not None and value < minimum)
        or (maximum is not None and value > maximum)
    ):
        raise ValueError(f"{name} fora do intervalo permitido.")
    return value


def _cost(value, name):
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} deve ser número finito não negativo.")
    return float(value)


def _available(frame):
    if "disponivel" not in frame:
        return frame
    return frame.loc[frame["disponivel"].eq(1)]


def _summary_template(sku, policy, product, lead, period, review, costs):
    first, last = period
    return {
        "sku": sku,
        "politica": policy,
        "status": None,
        "base_demanda": None,
        "estoque_inicial": int(product["estoque_atual"]),
        "origem_estoque_inicial": "cenario_catalogo",
        "periodo_inicio": first,
        "periodo_fim": last,
        "dias_avaliados": 0,
        "prazo_dias": lead,
        "revisao_dias": review,
        "seguranca_manual": int(product["estoque_seguranca"]),
        **{
            name: None
            for name in (
                "demanda_total",
                "vendas_atendidas",
                "vendas_perdidas",
                "atendimento_pct",
                "estoque_medio",
                "estoque_final",
                "dias_com_falta",
                "pedidos_emitidos",
                "unidades_pedidas",
                "em_transito_final",
                "custo_falta_estimado",
                "custo_estoque_estimado",
                "custo_pedidos_estimado",
                "custo_total_estimado",
            )
        },
        "custo_falta_unitario": costs[0],
        "custo_estoque_unitario_dia": costs[1],
        "custo_pedido": costs[2],
        "observacao": "",
    }


def _prediction(prefix, horizon, cache):
    # Prefixos crescentes são definidos somente pelo fechamento já observado.
    key = (str(prefix["sku"].iloc[0]), prefix["data"].iloc[-1], horizon)
    if key not in cache:
        forecasts, _ = analisar_previsoes(prefix, horizonte=horizon)
        if not {"sku", "data", "previsao", "modelo"}.issubset(forecasts.columns):
            raise ForecastUnavailable(
                "O modelo não retornou uma trajetória utilizável."
            )
        expected = pd.date_range(
            prefix["data"].iloc[-1] + pd.Timedelta(days=1), periods=horizon
        )
        forecasts = forecasts.loc[
            forecasts["sku"].eq(prefix["sku"].iloc[0])
        ].sort_values("data")
        values = pd.to_numeric(forecasts.get("previsao"), errors="coerce")
        if (
            len(forecasts) != horizon
            or not pd.DatetimeIndex(forecasts["data"]).equals(expected)
            or values.isna().any()
            or not values.map(math.isfinite).all()
            or values.lt(0).any()
        ):
            raise ForecastUnavailable(
                "Previsão indisponível para uma origem da simulação."
            )
        cache[key] = forecasts.copy()
    return cache[key].copy()


def _order(date, stock, pipeline, product, supplier, prefix, policy, review, cache):
    if policy == "Sem reposição":
        return 0, None, "Sem reposição"
    lead = int(supplier["prazo_dias"])
    protection = lead + review
    horizon = next(value for value in (7, 14, 30, 90) if value >= protection)
    if policy == "Média histórica":
        known = _available(prefix).tail(28)
        if known.empty:
            raise ForecastUnavailable(
                "Sem observações disponíveis para a média histórica."
            )
        forecast = pd.DataFrame(
            {
                "sku": product["sku"],
                "data": pd.date_range(date + pd.Timedelta(days=1), periods=horizon),
                "previsao": float(known["vendas"].mean()),
            }
        )
        model = "Média histórica (até 28 observações disponíveis)"
    else:
        forecast = _prediction(prefix, horizon, cache)
        model = str(forecast["modelo"].iloc[0])
    current_product = pd.DataFrame([{**product, "estoque_atual": int(stock)}])
    orders = pd.DataFrame(
        [
            {
                "pedido_id": f"SIM-{i}",
                "sku": product["sku"],
                "quantidade": quantity,
                "data_entrega": day,
            }
            for i, (day, quantity) in enumerate(pipeline)
            if day > date
        ],
        columns=ORDER_COLUMNS,
    )
    _, recommendations = planejar_estoque(
        forecast,
        current_product,
        pd.DataFrame([supplier]),
        orders,
        revisao_dias=review,
    )
    amount = recommendations.iloc[0]["compra_sugerida"]
    if pd.isna(amount) or not math.isfinite(float(amount)):
        raise ForecastUnavailable(
            "Não há cobertura para dimensionar a compra da simulação."
        )
    amount = int(amount)
    if not 0 <= amount <= 2**53 - 1:
        raise ForecastUnavailable(
            "Quantidade projetada fora da escala suportada pela simulação."
        )
    return amount, (date + pd.Timedelta(days=max(1, lead))) if amount else None, model


def _simulate(group, product, supplier, period, policy, review, costs, cache):
    first, last = period
    origin = first - pd.Timedelta(days=1)
    history = group.loc[group["data"].le(origin)].copy()
    demand = group.loc[group["data"].between(first, last)]
    stock = int(product["estoque_atual"])
    pipeline = []
    rows = []
    amount, delivery, model = _order(
        origin, stock, pipeline, product, supplier, history, policy, review, cache
    )
    if amount:
        pipeline.append((delivery, amount))
    rows.append(
        {
            "sku": product["sku"],
            "politica": policy,
            "data": origin,
            "fase": "inicial",
            "demanda": None,
            "recebimentos": 0,
            "vendas_atendidas": 0,
            "vendas_perdidas": 0,
            "estoque_final": stock,
            "quantidade_pedida": amount,
            "data_entrega_pedido": delivery,
            "em_transito": amount,
            "modelo": model,
            "custo_falta_estimado": 0.0,
            "custo_estoque_estimado": 0.0,
            "custo_pedido_estimado": costs[2] if amount else 0.0,
        }
    )
    for step, actual in enumerate(demand.itertuples(), start=1):
        day, units = actual.data, int(actual.vendas)
        receipts = sum(quantity for delivery, quantity in pipeline if delivery == day)
        pipeline = [
            (delivery, quantity) for delivery, quantity in pipeline if delivery > day
        ]
        stock += receipts
        served = min(stock, units)
        lost = units - served
        stock -= served
        amount, delivery = 0, None
        if step % review == 0:
            # A venda do dia só entra no treino depois de acontecer; nada além.
            prefix = group.loc[group["data"].le(day)]
            amount, delivery, model = _order(
                day, stock, pipeline, product, supplier, prefix, policy, review, cache
            )
            if amount:
                pipeline.append((delivery, amount))
        rows.append(
            {
                "sku": product["sku"],
                "politica": policy,
                "data": day,
                "fase": "simulacao",
                "demanda": units,
                "recebimentos": receipts,
                "vendas_atendidas": served,
                "vendas_perdidas": lost,
                "estoque_final": stock,
                "quantidade_pedida": amount,
                "data_entrega_pedido": delivery,
                "em_transito": sum(q for _, q in pipeline),
                "modelo": model,
                "custo_falta_estimado": lost * costs[0],
                "custo_estoque_estimado": stock * costs[1],
                "custo_pedido_estimado": costs[2] if amount else 0.0,
            }
        )
    return rows


def avaliar_politicas(
    vendas,
    produtos,
    fornecedores,
    periodo_dias=30,
    revisao_dias=7,
    assumir_vendas_como_demanda=False,
    custo_falta_unitario=1.0,
    custo_estoque_unitario_dia=0.01,
    custo_pedido=1.0,
):
    """Compara três políticas em um replay controlado, não em estoque real passado.

    O estoque inicial, segurança e prazo do catálogo são premissas fixas de cenário;
    não passe estimativas aprendidas com datas posteriores ao começo do período.
    Pedidos reais atuais não são reutilizados no passado. A demanda de cada dia é
    revelada ao controlador apenas no fechamento, mesmo quando houve perda na
    simulação (hipótese de replay com demanda conhecida).

    Revisa-se no fechamento anterior ao período e depois a cada ``revisao_dias``.
    Usa-se a compra para a referência de ``planejar_estoque``, não a data-limite
    futura. Recebimentos ocorrem antes da demanda do dia; prazo zero chega amanhã.
    Há uma linha inicial no diário, excluída do estoque médio e custo de manutenção.
    Custos e demanda proxy são premissas, não ROI observado. Pedidos que chegam
    após o fim do período permanecem em trânsito e seus custos de emissão contam.
    """
    period_days = _integer(periodo_dias, "periodo_dias", choices=(7, 14, 30))
    review = _integer(revisao_dias, "revisao_dias", minimum=1, maximum=30)
    if not isinstance(assumir_vendas_como_demanda, bool):
        raise ValueError("assumir_vendas_como_demanda deve ser booleano.")
    costs = (
        _cost(custo_falta_unitario, "custo_falta_unitario"),
        _cost(custo_estoque_unitario_dia, "custo_estoque_unitario_dia"),
        _cost(custo_pedido, "custo_pedido"),
    )
    sales = validar_vendas(vendas)
    end = sales["data"].max()
    start = end - pd.Timedelta(days=period_days - 1)
    products, suppliers, _ = validar_planejamento(
        produtos, fornecedores, None, sales["sku"].unique(), end
    )
    supplier_by_id = suppliers.set_index("fornecedor_id").to_dict("index")
    summaries, daily, cache = [], [], {}
    for product in products.to_dict("records"):
        sku = product["sku"]
        group = (
            sales.loc[sales["sku"].eq(sku)].sort_values("data").reset_index(drop=True)
        )
        supplier = {
            "fornecedor_id": product["fornecedor_id"],
            **supplier_by_id[product["fornecedor_id"]],
        }
        lead = int(supplier["prazo_dias"])
        test = group.loc[group["data"].between(start, end)]
        train = group.loc[group["data"].lt(start)]
        status, note, basis = "avaliado", "", None
        if group.empty:
            status, note = (
                "sem_historico",
                "Produto sem vendas; não é assumida demanda zero.",
            )
        elif len(test) != period_days or len(_available(train)) < MIN_HISTORICO:
            status, note = (
                "historico_insuficiente",
                "São necessários o período completo e 28 observações anteriores disponíveis.",
            )
        elif "disponivel" in test and test["disponivel"].eq(0).any():
            status, note = (
                "demanda_censurada",
                "Há indisponibilidade no período: vendas não identificam a demanda perdida.",
            )
        elif "disponivel" not in test and not assumir_vendas_como_demanda:
            status, note = (
                "disponibilidade_desconhecida",
                "Informe disponibilidade ou autorize explicitamente vendas como proxy de demanda.",
            )
        else:
            basis = (
                "vendas_como_proxy_assumida"
                if "disponivel" not in test
                else "vendas_com_disponibilidade_confirmada"
            )
        for policy in POLITICAS:
            summary = _summary_template(
                sku, policy, product, lead, (start, end), review, costs
            )
            summary.update(
                {"status": status, "base_demanda": basis, "observacao": note}
            )
            if status != "avaliado":
                summaries.append(summary)
                continue
            try:
                rows = _simulate(
                    group, product, supplier, (start, end), policy, review, costs, cache
                )
            except ForecastUnavailable as error:
                summary.update(
                    {"status": "previsao_indisponivel", "observacao": str(error)}
                )
                summaries.append(summary)
                continue
            observed = rows[1:]
            units = sum(r["demanda"] for r in observed)
            served = sum(r["vendas_atendidas"] for r in observed)
            lost = sum(r["vendas_perdidas"] for r in observed)
            cost_lost = sum(r["custo_falta_estimado"] for r in rows)
            cost_stock = sum(r["custo_estoque_estimado"] for r in rows)
            cost_orders = sum(r["custo_pedido_estimado"] for r in rows)
            total_cost = cost_lost + cost_stock + cost_orders
            if not math.isfinite(total_cost):
                raise ValueError(
                    "Custos estimados excedem a escala numérica suportada."
                )
            summary.update(
                {
                    "dias_avaliados": period_days,
                    "demanda_total": units,
                    "vendas_atendidas": served,
                    "vendas_perdidas": lost,
                    "atendimento_pct": served / units * 100 if units else None,
                    "estoque_medio": sum(r["estoque_final"] for r in observed)
                    / period_days,
                    "estoque_final": observed[-1]["estoque_final"],
                    "dias_com_falta": sum(r["vendas_perdidas"] > 0 for r in observed),
                    "pedidos_emitidos": sum(r["quantidade_pedida"] > 0 for r in rows),
                    "unidades_pedidas": sum(r["quantidade_pedida"] for r in rows),
                    "em_transito_final": observed[-1]["em_transito"],
                    "custo_falta_estimado": cost_lost,
                    "custo_estoque_estimado": cost_stock,
                    "custo_pedidos_estimado": cost_orders,
                    "custo_total_estimado": total_cost,
                    "observacao": "Replay com estoque inicial do cenário, demanda conhecida no fechamento e parâmetros manuais fixos; custos são premissas e pedidos podem chegar após a janela.",
                }
            )
            summaries.append(summary)
            daily.extend(rows)
    return pd.DataFrame(summaries, columns=SUMMARY_COLUMNS), pd.DataFrame(
        daily, columns=DAILY_COLUMNS
    )


def avaliar_multiperiodo(
    vendas, produtos, fornecedores, numero_periodos=3, periodo_dias=30, **kwargs
):
    """Repete cenários em blocos sem sobreposição, reiniciando o estoque manual.

    Não é uma simulação contínua nem estima estoque histórico real. Cada decisão
    conserva o corte temporal do replay original; períodos sem dados não são inventados.
    """
    count = _integer(numero_periodos, "numero_periodos", minimum=1, maximum=6)
    width = _integer(periodo_dias, "periodo_dias", choices=(7, 14, 30))
    sales = validar_vendas(vendas)
    final = sales["data"].max()
    summaries, days = [], []
    for index in range(count):
        end = final - pd.Timedelta(days=index * width)
        prefix = sales.loc[sales["data"].le(end)]
        if prefix.empty:
            break
        summary, daily = avaliar_politicas(
            prefix, produtos, fornecedores, periodo_dias=width, **kwargs
        )
        summaries.append(summary.assign(janela=index + 1))
        days.append(daily.assign(janela=index + 1))
    combined = pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()
    diary = pd.concat(days, ignore_index=True) if days else pd.DataFrame()
    stability = []
    if not combined.empty:
        for (sku, policy), group in combined.groupby(["sku", "politica"]):
            measured = group.dropna(subset=["custo_total_estimado"])
            stability.append(
                {
                    "sku": sku,
                    "politica": policy,
                    "periodos_com_dados": len(group),
                    "periodos_com_custos": len(measured),
                    "custo_medio_estimado": float(
                        measured["custo_total_estimado"].mean()
                    )
                    if len(measured)
                    else None,
                    "desvio_custo_estimado": float(
                        measured["custo_total_estimado"].std(ddof=0)
                    )
                    if len(measured)
                    else None,
                    "atendimento_medio_pct": float(measured["atendimento_pct"].mean())
                    if measured["atendimento_pct"].notna().any()
                    else None,
                }
            )
    return combined, diary, pd.DataFrame(stability)
