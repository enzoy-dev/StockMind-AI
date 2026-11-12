"""Sensibilidade histórica: cenários contrafactuais, sem estimativa de ROI."""

import math
import pandas as pd
from stockmind.evaluation import avaliar_politicas, _integer


def avaliar_estresse(
    vendas,
    produtos,
    fornecedores,
    periodo_dias=30,
    numero_periodos=1,
    atraso_dias=3,
    choque_pct=20.0,
    **kwargs,
):
    count = _integer(numero_periodos, "numero_periodos", minimum=1, maximum=6)
    width = _integer(periodo_dias, "periodo_dias", choices=(7, 14, 30))
    delay = _integer(atraso_dias, "atraso_dias", minimum=0, maximum=30)
    if (
        isinstance(choque_pct, bool)
        or not isinstance(choque_pct, (int, float))
        or not math.isfinite(choque_pct)
        or not 0 <= choque_pct <= 80
    ):
        raise ValueError("choque_pct deve estar entre 0 e 80.")
    if fornecedores.prazo_dias.add(delay).gt(60).any():
        raise ValueError(
            "Prazo com atraso excede 60 dias; reduza o cenário, sem truncar o prazo."
        )
    scenarios = [
        ("base", 0, 0.0),
        ("atraso", delay, 0.0),
        ("demanda_maior", 0, choque_pct),
        ("demanda_menor", 0, -choque_pct),
        ("combinado", delay, choque_pct),
    ]
    summaries, diaries = [], []
    final = vendas.data.max()
    for window in range(count):
        end = final - pd.Timedelta(days=window * width)
        start = end - pd.Timedelta(days=width - 1)
        prefix = vendas.loc[vendas.data.le(end)]
        if prefix.empty:
            break
        for name, extra, change in scenarios:
            counterfactual = prefix.copy()
            mask = counterfactual.data.ge(start)
            # Só a realização do bloco é alterada; o treino anterior fica intacto.
            counterfactual.loc[mask, "vendas"] = counterfactual.loc[mask, "vendas"].map(
                lambda n: math.ceil(int(n) * (1 + change / 100))
            )
            suppliers = fornecedores.copy()
            suppliers["prazo_dias"] += extra
            summary, daily = avaliar_politicas(
                counterfactual, produtos, suppliers, periodo_dias=width, **kwargs
            )
            tags = dict(
                cenario=name,
                janela=window + 1,
                atraso_assumido_dias=extra,
                choque_demanda_pct=float(change),
            )
            summaries.append(summary.assign(**tags))
            diaries.append(daily.assign(**tags))
    combined = pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()
    diary = pd.concat(diaries, ignore_index=True) if diaries else pd.DataFrame()
    if not combined.empty:
        baseline = combined.loc[
            combined.cenario.eq("base"),
            ["sku", "politica", "janela", "custo_total_estimado"],
        ].rename(columns={"custo_total_estimado": "custo_cenario_base"})
        combined = combined.merge(
            baseline, on=["sku", "politica", "janela"], validate="many_to_one"
        )
        combined["diferenca_custo_base"] = (
            combined.custo_total_estimado - combined.custo_cenario_base
        )
        combined["premissa_estresse"] = (
            "Prazo ampliado conhecido pelas políticas desde o início; demanda alterada só no bloco, revelada a cada fechamento. Estoque reinicia por janela; não é atraso surpresa nem ROI."
        )
    return combined, diary
