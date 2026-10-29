"""Sensibilidade de estoque a três trajetórias determinísticas de vendas.

A variação é escolhida pela pessoa usuária e aplicada à previsão pontual. Não
representa nível de confiança, intervalo de previsão ou probabilidade de demanda.
Faixas empíricas do modelo não são convertidas em cenários de estoque.
"""

from __future__ import annotations

import math

import pandas as pd

from stockmind.inventory import planejar_estoque


TIPO_ANALISE = "sensibilidade_deterministica"


def simular_cenarios(
    previsoes,
    produtos,
    fornecedores,
    pedidos=None,
    revisao_dias=7,
    variacao_pct=20.0,
):
    """Retorna recomendações e saldos para demanda menor, base e maior.

    Os estoques iniciais, pedidos já abertos, prazos e regras de lote permanecem
    iguais. Apenas as vendas previstas mudam. Cada trajetória reutiliza as mesmas
    regras de reposição do planejamento base, inclusive cobertura insuficiente e
    produtos sem previsão. Compras sugeridas não viram recebimentos na projeção.
    As entradas são preservadas.
    """
    if not pd.api.types.is_scalar(variacao_pct) or pd.api.types.is_bool(variacao_pct):
        raise ValueError("variacao_pct deve ser um número finito entre 0 e 80.")
    try:
        variacao = float(variacao_pct)
    except (TypeError, ValueError, OverflowError) as erro:
        raise ValueError(
            "variacao_pct deve ser um número finito entre 0 e 80."
        ) from erro
    if not math.isfinite(variacao) or not 0 <= variacao <= 80:
        raise ValueError("variacao_pct deve ser um número finito entre 0 e 80.")
    if not isinstance(previsoes, pd.DataFrame) or "previsao" not in previsoes:
        raise ValueError("Previsões devem ser uma tabela com a coluna previsao.")

    # As faixas pontuais de erro do modelo têm outro significado estatístico.
    # O cálculo de sensibilidade recebe somente o ponto e demais metadados.
    pontos = previsoes.drop(
        columns=["limite_inferior", "limite_superior"], errors="ignore"
    ).copy(deep=True)
    quantidades = pd.to_numeric(pontos["previsao"], errors="coerce")
    trajetorias = (
        ("Demanda menor", 1 - variacao / 100),
        ("Cenário base", 1.0),
        ("Demanda maior", 1 + variacao / 100),
    )
    resumos, saldos_cenarios = [], []
    for nome, fator in trajetorias:
        cenario = pontos.copy(deep=True)
        cenario["previsao"] = quantidades * fator
        saldos, recomendacoes = planejar_estoque(
            cenario,
            produtos,
            fornecedores,
            pedidos=pedidos,
            revisao_dias=revisao_dias,
        )
        metadados = {
            "cenario": nome,
            "fator_demanda": fator,
            "variacao_pct": variacao,
            "tipo_analise": TIPO_ANALISE,
        }
        resumos.append(recomendacoes.assign(**metadados))
        saldos_cenarios.append(saldos.assign(**metadados))
    return (
        pd.concat(resumos, ignore_index=True),
        pd.concat(saldos_cenarios, ignore_index=True),
    )
