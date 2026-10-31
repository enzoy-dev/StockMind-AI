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
    validar_entregas,
)
from stockmind.forecasting import (
    comparar_horizontes as avaliar_horizontes,
    coletar_erros_reposicao,
)
from stockmind.inventory import planejar_estoque
from stockmind.scenarios import simular_cenarios
from stockmind.analytics import classificar_produtos, analisar_prazos, sugerir_seguranca
from stockmind.evaluation import avaliar_politicas, avaliar_multiperiodo
from stockmind.cache import CACHE, forecast_cached


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
    entregas=None,
    seguranca_automatica=False,
    ajustar_prazos=False,
    avaliar_reposicao=False,
    assumir_vendas_como_demanda=False,
    periodo_simulacao=30,
    custo_falta_unitario=1.0,
    custo_estoque_unitario_dia=0.01,
    custo_pedido=1.0,
    janela_classificacao=90,
    numero_periodos_simulacao=1,
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
    for nome, valor in {
        "seguranca_automatica": seguranca_automatica,
        "ajustar_prazos": ajustar_prazos,
        "avaliar_reposicao": avaliar_reposicao,
        "assumir_vendas_como_demanda": assumir_vendas_como_demanda,
    }.items():
        if not isinstance(valor, bool):
            raise ValueError(f"{nome} deve ser booleano.")
    if isinstance(periodo_simulacao, bool) or periodo_simulacao not in (7, 14, 30):
        raise ValueError("Período da simulação deve ser 7, 14 ou 30 dias.")
    for nome, valor in {
        "custo_falta_unitario": custo_falta_unitario,
        "custo_estoque_unitario_dia": custo_estoque_unitario_dia,
        "custo_pedido": custo_pedido,
    }.items():
        if (
            isinstance(valor, bool)
            or not isinstance(valor, Real)
            or not math.isfinite(valor)
            or valor < 0
        ):
            raise ValueError(f"{nome} deve ser um número finito não negativo.")
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
    if (
        isinstance(janela_classificacao, bool)
        or not isinstance(janela_classificacao, int)
        or not 1 <= janela_classificacao <= 3650
    ):
        raise ValueError(
            "Janela da classificação deve ser inteira entre 1 e 3650 dias."
        )
    if (
        isinstance(numero_periodos_simulacao, bool)
        or not isinstance(numero_periodos_simulacao, int)
        or not 1 <= numero_periodos_simulacao <= 6
    ):
        raise ValueError("Número de períodos deve ser entre 1 e 6.")
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
    if not usar_estoque and (
        seguranca_automatica or ajustar_prazos or avaliar_reposicao
    ):
        raise ValueError(
            "Para ajustar segurança/prazos ou simular reposição, informe produtos e fornecedores."
        )
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

    classificacao = classificar_produtos(vendas, janela_classificacao)
    entregas = validar_entregas(
        entregas, origem, fornecedores if usar_estoque else None
    )
    produtos_manuais = produtos.copy() if usar_estoque else None
    fornecedores_manuais = fornecedores.copy() if usar_estoque else None
    prazos, seguranca, erros_reposicao = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    if usar_estoque:
        prazos = analisar_prazos(entregas, fornecedores, origem)
        prazos["aplicado"] = False
        fornecedores = fornecedores.copy()
        produtos = produtos.copy()
        if ajustar_prazos:
            for i, estimativa in prazos.iterrows():
                if pd.notna(estimativa["prazo_sugerido"]):
                    fornecedores.loc[
                        fornecedores["fornecedor_id"].eq(estimativa["fornecedor_id"]),
                        "prazo_dias",
                    ] = int(estimativa["prazo_sugerido"])
                    prazos.loc[i, "aplicado"] = True

    previsoes, metricas = forecast_cached(vendas, horizonte, contexto)
    comparacao = (
        avaliar_horizontes(vendas, contexto, executor=forecast_cached)
        if comparar_horizontes
        else pd.DataFrame()
    )
    saldos, recomendacoes = pd.DataFrame(), pd.DataFrame()
    cenarios, saldos_cenarios = pd.DataFrame(), pd.DataFrame()
    avaliacao_politicas, diario_politicas = pd.DataFrame(), pd.DataFrame()
    multiplos, diario_multiplos, consistencia = (
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
    )
    if usar_estoque:
        mapa_prazos = fornecedores.set_index("fornecedor_id")["prazo_dias"]
        prazos_sku = {
            row["sku"]: int(mapa_prazos.loc[row["fornecedor_id"]])
            for row in produtos.to_dict("records")
        }
        erros_reposicao = CACHE.obtain(
            "residuos-v1",
            (vendas, metricas, prazos_sku),
            lambda: coletar_erros_reposicao(vendas, metricas, prazos_sku),
        )
        seguranca = sugerir_seguranca(produtos, erros_reposicao)
        seguranca["aplicado"] = False
        if seguranca_automatica:
            for i, estimativa in seguranca.iterrows():
                if pd.notna(estimativa["seguranca_sugerida"]):
                    produtos.loc[
                        produtos["sku"].eq(estimativa["sku"]), "estoque_seguranca"
                    ] = int(estimativa["seguranca_sugerida"])
                    seguranca.loc[i, "aplicado"] = True
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
        indisponiveis = set(
            metricas.loc[metricas["status"].eq("demanda_indisponivel"), "sku"]
        )
        for frame in (recomendacoes, cenarios):
            censuradas = frame["sku"].isin(indisponiveis)
            frame.loc[censuradas, "status_previsao"] = "demanda_indisponivel"
            frame.loc[censuradas, "motivos_alerta"] = (
                "Todos os dias do histórico têm indisponibilidade; não há demanda observável para prever."
            )
        if avaliar_reposicao:
            # Os parâmetros originais são cenários declarados, não estimativas
            # aprendidas com o próprio período histórico que será avaliado.
            avaliacao_politicas, diario_politicas = avaliar_politicas(
                vendas,
                produtos_manuais,
                fornecedores_manuais,
                periodo_dias=periodo_simulacao,
                revisao_dias=revisao_dias,
                assumir_vendas_como_demanda=assumir_vendas_como_demanda,
                custo_falta_unitario=custo_falta_unitario,
                custo_estoque_unitario_dia=custo_estoque_unitario_dia,
                custo_pedido=custo_pedido,
            )
            if numero_periodos_simulacao > 1:
                multiplos, diario_multiplos, consistencia = avaliar_multiperiodo(
                    vendas,
                    produtos_manuais,
                    fornecedores_manuais,
                    numero_periodos=numero_periodos_simulacao,
                    periodo_dias=periodo_simulacao,
                    revisao_dias=revisao_dias,
                    assumir_vendas_como_demanda=assumir_vendas_como_demanda,
                    custo_falta_unitario=custo_falta_unitario,
                    custo_estoque_unitario_dia=custo_estoque_unitario_dia,
                    custo_pedido=custo_pedido,
                )
    return {
        "origem": origem.date().isoformat(),
        "horizonte": horizonte,
        "revisao_dias": revisao_dias,
        "comparar_horizontes": comparar_horizontes,
        "variacao_cenario_pct": float(variacao_cenario_pct),
        "seguranca_automatica": seguranca_automatica,
        "ajustar_prazos": ajustar_prazos,
        "avaliar_reposicao": avaliar_reposicao,
        "assumir_vendas_como_demanda": assumir_vendas_como_demanda,
        "periodo_simulacao": periodo_simulacao,
        "janela_classificacao": janela_classificacao,
        "numero_periodos_simulacao": numero_periodos_simulacao,
        "custos_simulacao": {
            "falta_unitaria": float(custo_falta_unitario),
            "estoque_unitario_dia": float(custo_estoque_unitario_dia),
            "pedido": float(custo_pedido),
        },
        "previsoes": registros(previsoes),
        "metricas": registros(metricas),
        "saldos": registros(saldos),
        "recomendacoes": registros(recomendacoes),
        "qualidade": registros(qualidade),
        "comparacao_horizontes": registros(comparacao),
        "cenarios": registros(cenarios),
        "saldos_cenarios": registros(saldos_cenarios),
        "classificacao_produtos": registros(classificacao),
        "prazos_fornecedores": registros(prazos),
        "seguranca_estoque": registros(seguranca),
        "residuos_reposicao": registros(erros_reposicao),
        "avaliacao_reposicao": registros(avaliacao_politicas),
        "diario_reposicao": registros(diario_politicas),
        "produtos_planejados": registros(produtos) if usar_estoque else [],
        "fornecedores_planejados": registros(fornecedores) if usar_estoque else [],
        "avaliacao_multiperiodo": registros(multiplos),
        "diario_multiperiodo": registros(diario_multiplos),
        "consistencia_politicas": registros(consistencia),
    }
