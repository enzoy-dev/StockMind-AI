"""Projeção determinística de saldo e regras explícitas de reposição.

O saldo assinado é estoque + recebimentos - vendas previstas acumuladas. Um saldo
negativo representa déficit projetado, não estoque físico negativo ou uma
probabilidade de ruptura. Compras sugeridas nunca são tratadas como recebidas.
"""

from __future__ import annotations

import math

import pandas as pd


COLUNAS_SALDOS = [
    "sku",
    "data",
    "previsao",
    "recebimentos",
    "saldo_estimado",
    "risco_falta",
]
COLUNAS_RECOMENDACOES = [
    "sku",
    "nome",
    "fornecedor_id",
    "prazo_dias",
    "estoque_atual",
    "em_transito",
    "em_transito_total",
    "em_transito_apos_janela",
    "posicao_estoque",
    "estoque_alvo",
    "compra_sugerida",
    "primeira_falta",
    "risco_antes_reposicao",
    "data_reposicao_estimada",
    "deficit_maximo",
    "excesso",
    "unidades_acima_alvo_30dias",
    "horizonte_necessario",
    "dias_previstos",
    "status",
    "status_previsao",
]


def _colunas(dados, necessarias, nome):
    ausentes = set(necessarias) - set(dados.columns)
    if ausentes:
        raise ValueError(f"{nome}: colunas ausentes: {', '.join(sorted(ausentes))}.")


def _inteiro(valor, campo, minimo=0, maximo=None):
    try:
        numero = float(valor)
    except (TypeError, ValueError, OverflowError) as erro:
        raise ValueError(f"{campo} deve ser inteiro.") from erro
    if (
        isinstance(valor, bool)
        or not math.isfinite(numero)
        or not numero.is_integer()
        or numero < minimo
        or (maximo is not None and numero > maximo)
    ):
        raise ValueError(f"{campo} fora do intervalo permitido.")
    return int(numero)


def _datas(dados, coluna, nome):
    dados[coluna] = pd.to_datetime(dados[coluna], errors="coerce")
    if dados[coluna].isna().any():
        raise ValueError(f"{nome}: há uma data inválida.")
    if not dados[coluna].eq(dados[coluna].dt.normalize()).all():
        raise ValueError(f"{nome}: informe datas sem horário.")


def planejar_estoque(previsoes, produtos, fornecedores, pedidos=None, revisao_dias=7):
    """Retorna saldos diários e sugestões sujeitas a revisão humana.

    Recebimentos ocorrem antes das vendas previstas do dia. Uma compra nova,
    se aprovada hoje, chegaria em ``origem + prazo_dias``. O alerta anterior à
    reposição exclui o próprio dia da chegada. O estoque-alvo cobre prazo +
    revisão e segurança; apenas pedidos que chegam dentro dessa janela reduzem
    a quantidade sugerida. Excesso é uma triagem de 30 dias e fica indefinido
    quando a previsão não cobre esse período.
    """
    revisao_dias = _inteiro(revisao_dias, "revisao_dias", minimo=1, maximo=30)
    _colunas(previsoes, ["sku", "data", "previsao"], "Previsões")
    _colunas(
        produtos,
        [
            "sku",
            "nome",
            "fornecedor_id",
            "estoque_atual",
            "estoque_seguranca",
            "pedido_minimo",
            "multiplo_compra",
        ],
        "Produtos",
    )
    _colunas(fornecedores, ["fornecedor_id", "nome", "prazo_dias"], "Fornecedores")
    if pedidos is None:
        pedidos = pd.DataFrame(
            columns=["pedido_id", "sku", "quantidade", "data_entrega"]
        )
    _colunas(pedidos, ["pedido_id", "sku", "quantidade", "data_entrega"], "Pedidos")

    previsoes = previsoes.copy()
    pedidos = pedidos.copy()
    if produtos["sku"].duplicated().any():
        raise ValueError("Produtos: SKU duplicado.")
    if fornecedores["fornecedor_id"].duplicated().any():
        raise ValueError("Fornecedores: identificador duplicado.")
    if pedidos["pedido_id"].duplicated().any():
        raise ValueError("Pedidos: identificador duplicado.")
    if not set(previsoes["sku"]).issubset(set(produtos["sku"])):
        raise ValueError("Há previsões de um produto não cadastrado.")
    if not set(pedidos["sku"]).issubset(set(produtos["sku"])):
        raise ValueError("Há pedidos de um produto não cadastrado.")
    if not set(produtos["fornecedor_id"]).issubset(set(fornecedores["fornecedor_id"])):
        raise ValueError("Há produtos com fornecedor não cadastrado.")

    _datas(previsoes, "data", "Previsões")
    _datas(pedidos, "data_entrega", "Pedidos")
    origem = (
        previsoes["data"].min() - pd.Timedelta(days=1) if not previsoes.empty else None
    )
    if origem is not None and pedidos["data_entrega"].le(origem).any():
        raise ValueError("Pedidos abertos devem chegar depois da data de referência.")
    quantidades = pd.to_numeric(previsoes["previsao"], errors="coerce")
    if (
        quantidades.isna().any()
        or not quantidades.map(math.isfinite).all()
        or quantidades.lt(0).any()
    ):
        raise ValueError("Previsões devem ser finitas e não negativas.")
    previsoes["previsao"] = quantidades
    pedidos["quantidade"] = pedidos["quantidade"].map(
        lambda valor: _inteiro(valor, "quantidade", minimo=1)
    )

    linhas_saldos = []
    recomendacoes = []
    prazos = fornecedores.set_index("fornecedor_id")["prazo_dias"]
    for produto in produtos.sort_values("sku").to_dict("records"):
        sku = produto["sku"]
        prazo = _inteiro(prazos.loc[produto["fornecedor_id"]], "prazo_dias", maximo=60)
        estoque = _inteiro(produto["estoque_atual"], "estoque_atual")
        seguranca = _inteiro(produto["estoque_seguranca"], "estoque_seguranca")
        minimo = _inteiro(produto["pedido_minimo"], "pedido_minimo")
        lote = _inteiro(produto["multiplo_compra"], "multiplo_compra", minimo=1)
        projecao = previsoes.loc[previsoes["sku"].eq(sku)].sort_values("data")
        ordens = pedidos.loc[pedidos["sku"].eq(sku)]
        janela = prazo + revisao_dias
        em_transito_total = int(ordens["quantidade"].sum())
        recomendacao = {
            "sku": sku,
            "nome": produto["nome"],
            "fornecedor_id": produto["fornecedor_id"],
            "prazo_dias": prazo,
            "estoque_atual": estoque,
            "em_transito": None,
            "em_transito_total": em_transito_total,
            "em_transito_apos_janela": None,
            "posicao_estoque": None,
            "estoque_alvo": None,
            "compra_sugerida": None,
            "primeira_falta": None,
            "risco_antes_reposicao": None,
            "data_reposicao_estimada": None,
            "deficit_maximo": None,
            "excesso": None,
            "unidades_acima_alvo_30dias": None,
            "horizonte_necessario": janela,
            "dias_previstos": len(projecao),
            "status": "sem_previsao",
            "status_previsao": None,
        }
        if projecao.empty:
            recomendacoes.append(recomendacao)
            continue

        datas = projecao["data"]
        if (
            datas.duplicated().any()
            or datas.iloc[0] != origem + pd.Timedelta(days=1)
            or not datas.diff().iloc[1:].eq(pd.Timedelta(days=1)).all()
        ):
            raise ValueError(
                f"{sku}: previsões devem ser diárias, consecutivas e começar na mesma data."
            )
        chegada_reposicao = origem + pd.Timedelta(days=prazo)
        fim_janela = origem + pd.Timedelta(days=janela)
        consideradas = ordens["data_entrega"].le(fim_janela)
        em_transito = int(ordens.loc[consideradas, "quantidade"].sum())
        recomendacao.update(
            {
                "em_transito": em_transito,
                "em_transito_apos_janela": em_transito_total - em_transito,
                "posicao_estoque": estoque + em_transito,
                "data_reposicao_estimada": chegada_reposicao,
                "risco_antes_reposicao": False,
                "deficit_maximo": 0.0,
                "status_previsao": (
                    "; ".join(sorted(projecao["status"].dropna().astype(str).unique()))
                    if "status" in projecao
                    else None
                ),
            }
        )
        recebimentos = ordens.groupby("data_entrega")["quantidade"].sum()
        saldo = float(estoque)
        for data, quantidade in zip(projecao["data"], projecao["previsao"]):
            recebido = int(recebimentos.get(data, 0))
            saldo += recebido - float(quantidade)
            risco = saldo < -1e-9
            linhas_saldos.append(
                {
                    "sku": sku,
                    "data": data,
                    "previsao": float(quantidade),
                    "recebimentos": recebido,
                    "saldo_estimado": saldo,
                    "risco_falta": risco,
                }
            )
            if risco:
                if recomendacao["primeira_falta"] is None:
                    recomendacao["primeira_falta"] = data
                if data < chegada_reposicao:
                    recomendacao["risco_antes_reposicao"] = True
                recomendacao["deficit_maximo"] = max(
                    recomendacao["deficit_maximo"], -saldo
                )

        if len(projecao) >= janela:
            alvo = float(projecao["previsao"].iloc[:janela].sum() + seguranca)
            necessidade = max(0.0, alvo - (estoque + em_transito))
            # Tolerância numérica evita um lote inteiro por um resíduo de regressão.
            compra = (
                math.ceil((max(necessidade, minimo) - 1e-9) / lote) * lote
                if necessidade > 1e-9
                else 0
            )
            recomendacao.update(
                {
                    "estoque_alvo": alvo,
                    "compra_sugerida": compra,
                    "status": "revisar_compra" if compra else "acompanhar",
                }
            )
        else:
            recomendacao["status"] = "horizonte_insuficiente"

        if len(projecao) >= 30:
            fim_30dias = origem + pd.Timedelta(days=30)
            recebido_30dias = int(
                ordens.loc[ordens["data_entrega"].le(fim_30dias), "quantidade"].sum()
            )
            alvo_30dias = float(projecao["previsao"].iloc[:30].sum() + seguranca)
            acima = max(0.0, estoque + recebido_30dias - alvo_30dias)
            recomendacao["excesso"] = acima > 1e-9
            recomendacao["unidades_acima_alvo_30dias"] = acima
        recomendacoes.append(recomendacao)

    return (
        pd.DataFrame(linhas_saldos, columns=COLUNAS_SALDOS),
        pd.DataFrame(recomendacoes, columns=COLUNAS_RECOMENDACOES),
    )
