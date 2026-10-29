"""Fluxo compartilhado pelo dashboard e pela API, sem gravar dados implicitamente."""

import json
import math
from numbers import Real

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype

from stockmind.data import (
    inspecionar_vendas,
    validar_contexto_futuro,
    validar_planejamento,
    validar_vendas,
)
from stockmind.forecasting import (
    analisar_previsoes,
    comparar_horizontes as avaliar_horizontes,
)
from stockmind.inventory import planejar_estoque
from stockmind.scenarios import simular_cenarios


def registros(frame):
    """Converte datas, escalares NumPy e ausências em JSON padrão."""
    if frame is None or frame.empty:
        return []
    frame = frame.copy()
    for coluna in frame:
        if is_datetime64_any_dtype(frame[coluna]):
            frame[coluna] = frame[coluna].dt.strftime("%Y-%m-%d")
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def executar_analise(
    vendas,
    horizonte=7,
    contexto_futuro=None,
    produtos=None,
    fornecedores=None,
    pedidos=None,
    revisao_dias=7,
    comparar_horizontes=False,
    variacao_cenario_pct=20.0,
):
    """Valida, prevê, compara métodos e calcula o estoque; não realiza compras."""
    if isinstance(horizonte, bool) or horizonte not in (7, 14, 30, 90):
        raise ValueError("Horizonte deve ser 7, 14, 30 ou 90 dias.")
    if (
        isinstance(revisao_dias, bool)
        or not isinstance(revisao_dias, int)
        or not 1 <= revisao_dias <= 30
    ):
        raise ValueError("Revisão do estoque deve ser entre 1 e 30 dias.")
    if not isinstance(comparar_horizontes, bool):
        raise ValueError("comparar_horizontes deve ser booleano.")
    if (
        isinstance(variacao_cenario_pct, bool)
        or not isinstance(variacao_cenario_pct, Real)
        or not math.isfinite(variacao_cenario_pct)
        or not 0 <= variacao_cenario_pct <= 80
    ):
        raise ValueError(
            "Variação dos cenários deve ser um número entre 0 e 80 por cento."
        )
    qualidade = inspecionar_vendas(vendas)
    vendas = validar_vendas(vendas)
    origem = vendas["data"].max()
    contexto = None
    if contexto_futuro is not None:
        cobertura_contexto = max(horizonte, 30) if comparar_horizontes else horizonte
        contexto = validar_contexto_futuro(contexto_futuro, vendas, cobertura_contexto)
    elif any(campo in vendas for campo in ("preco", "promocao", "feriado")):
        qualidade = pd.concat(
            [
                qualidade,
                pd.DataFrame(
                    [
                        {
                            "nivel": "aviso",
                            "sku": "",
                            "campo": "contexto_futuro",
                            "mensagem": "Sem plano futuro completo: preço, promoção e feriado não entram nos modelos.",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

    usar_estoque = any(valor is not None for valor in (produtos, fornecedores, pedidos))
    if usar_estoque:
        if produtos is None or fornecedores is None:
            raise ValueError(
                "Para planejar estoque, informe produtos e fornecedores juntos."
            )
        if pedidos is None:
            pedidos = pd.DataFrame(
                columns=["pedido_id", "sku", "quantidade", "data_entrega"]
            )
        produtos, fornecedores, pedidos = validar_planejamento(
            produtos, fornecedores, pedidos, vendas["sku"].unique(), origem
        )
        sem_historico = sorted(set(produtos["sku"]) - set(vendas["sku"]))
        if sem_historico:
            qualidade = pd.concat(
                [
                    qualidade,
                    pd.DataFrame(
                        [
                            {
                                "nivel": "aviso",
                                "sku": sku,
                                "campo": "historico",
                                "mensagem": "Produto cadastrado sem vendas: previsão e compra sugerida ficam indefinidas.",
                            }
                            for sku in sem_historico
                        ]
                    ),
                ],
                ignore_index=True,
            )

    previsoes, metricas = analisar_previsoes(vendas, horizonte, contexto)
    comparacao = (
        avaliar_horizontes(vendas, contexto) if comparar_horizontes else pd.DataFrame()
    )
    saldos, recomendacoes = pd.DataFrame(), pd.DataFrame()
    cenarios, saldos_cenarios = pd.DataFrame(), pd.DataFrame()
    if usar_estoque:
        saldos, recomendacoes = planejar_estoque(
            previsoes, produtos, fornecedores, pedidos, revisao_dias
        )
        cenarios, saldos_cenarios = simular_cenarios(
            previsoes,
            produtos,
            fornecedores,
            pedidos,
            revisao_dias,
            variacao_cenario_pct,
        )
    return {
        "origem": origem.date().isoformat(),
        "horizonte": horizonte,
        "revisao_dias": revisao_dias,
        "comparar_horizontes": comparar_horizontes,
        "variacao_cenario_pct": float(variacao_cenario_pct),
        "previsoes": registros(previsoes),
        "metricas": registros(metricas),
        "saldos": registros(saldos),
        "recomendacoes": registros(recomendacoes),
        "qualidade": registros(qualidade),
        "comparacao_horizontes": registros(comparacao),
        "cenarios": registros(cenarios),
        "saldos_cenarios": registros(saldos_cenarios),
    }
