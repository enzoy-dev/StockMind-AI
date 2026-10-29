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
    "primeira_abaixo_seguranca",
    "dias_ate_falta",
    "dias_ate_seguranca",
    "data_limite_compra",
    "data_compra_sugerida",
    "data_entrega_compra_sugerida",
    "quantidade_compra_na_data",
    "horizonte_necessario_agendamento",
    "prazo_compra_vencido",
    "falta_antes_entrega_compra",
    "status_agendamento",
    "prioridade",
    "prioridade_ordem",
    "motivos_alerta",
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


def _quantidade_na_data(caminho, data_compra, prazo, revisao, seguranca, minimo, lote):
    """Tamanho de uma compra considerando o caminho exato sem essa compra.

    O caminho já inclui o estoque inicial, TODA depleção até cada data e pedidos
    abertos na data correta. Portanto, não se descontam os pedidos novamente.
    Usa-se o maior déficit de segurança entre a chegada e o fim da proteção;
    considerar só o saldo final poderia esconder faltas antes de um pedido tardio.
    """
    chegada = data_compra + pd.Timedelta(days=max(1, prazo))
    fim = data_compra + pd.Timedelta(days=prazo + revisao)
    if caminho.empty or fim > caminho.index[-1]:
        return None
    protegido = caminho.loc[(caminho.index >= chegada) & (caminho.index <= fim)]
    if protegido.empty:
        return None
    necessidade = max(0.0, seguranca - float(protegido.min()))
    if necessidade <= 1e-9:
        return 0
    return math.ceil((max(necessidade, minimo) - 1e-9) / lote) * lote


def _agendar_compra(
    recomendacao, caminho, origem, prazo, revisao, seguranca, minimo, lote
):
    """Define um prazo teórico e uma ação possível, sem simular aprovação."""
    primeira_seguranca = recomendacao["primeira_abaixo_seguranca"]
    primeira_falta = recomendacao["primeira_falta"]
    motivos = []
    if primeira_falta is not None:
        recomendacao["dias_ate_falta"] = (primeira_falta - origem).days
        motivos.append(f"Falta projetada em {primeira_falta:%Y-%m-%d}")

    if primeira_seguranca is None:
        recomendacao["status_agendamento"] = "sem_gatilho_no_horizonte"
        motivos.append(
            f"Sem saldo abaixo da segurança nos {len(caminho)} dias previstos; "
            "a necessidade após esse horizonte é desconhecida"
        )
    else:
        recomendacao["dias_ate_seguranca"] = (primeira_seguranca - origem).days
        motivos.append(f"Saldo abaixo da segurança em {primeira_seguranca:%Y-%m-%d}")
        prazo_efetivo = max(1, prazo)
        limite = primeira_seguranca - pd.Timedelta(days=prazo_efetivo)
        data_compra = max(origem, limite)
        chegada = data_compra + pd.Timedelta(days=prazo_efetivo)
        horizonte_necessario = (data_compra - origem).days + prazo + revisao
        quantidade = _quantidade_na_data(
            caminho, data_compra, prazo, revisao, seguranca, minimo, lote
        )
        vencido = limite < origem
        falta_antes = bool(primeira_falta is not None and primeira_falta < chegada)
        recomendacao.update(
            {
                "data_limite_compra": limite,
                "data_compra_sugerida": data_compra,
                "data_entrega_compra_sugerida": chegada,
                "quantidade_compra_na_data": quantidade,
                "horizonte_necessario_agendamento": horizonte_necessario,
                "prazo_compra_vencido": vencido,
                "falta_antes_entrega_compra": falta_antes,
            }
        )
        if vencido:
            motivos.append("Prazo teórico para manter a segurança já vencido")
        if falta_antes:
            motivos.append(
                "Comprar na data possível não evita a falta anterior à entrega; "
                "revisar antecipação de recebimentos ou outra fonte de estoque"
            )
        if quantidade is None:
            recomendacao["status_agendamento"] = "horizonte_insuficiente"
            motivos.append(
                f"Previsão precisa cobrir {horizonte_necessario} dias para "
                "dimensionar a compra na data sugerida"
            )
        elif quantidade == 0:
            # Pedidos já abertos podem recuperar o saldo antes que uma compra
            # adicional pudesse chegar. Não inventar uma compra de zero unidades.
            recomendacao.update(
                {
                    "status_agendamento": "sem_compra_adicional",
                    "data_compra_sugerida": None,
                    "data_entrega_compra_sugerida": None,
                }
            )
            motivos.append(
                "Pedidos existentes cobrem a segurança após a primeira entrega "
                "possível; revisar o déficit anterior separadamente"
            )
        elif vencido:
            recomendacao["status_agendamento"] = "prazo_vencido"
        elif data_compra == origem:
            recomendacao["status_agendamento"] = "comprar_agora"
        else:
            recomendacao["status_agendamento"] = "compra_programada"
            motivos.append(f"Compra programada para {data_compra:%Y-%m-%d}")

    if recomendacao["em_transito_apos_janela"]:
        motivos.append("Há pedidos que chegam depois da janela de proteção atual")
    if recomendacao["excesso"]:
        motivos.append("Posição acima do alvo de vendas e segurança de 30 dias")

    # Um déficit anterior à entrega possível exige ação mesmo quando a quantidade
    # adicional é zero: um pedido grande e tardio não apaga uma ruptura anterior.
    if recomendacao["risco_antes_reposicao"]:
        prioridade = "critica"
        if recomendacao["status"] != "horizonte_insuficiente":
            recomendacao["status"] = "revisar_entrega_urgente"
    elif (
        recomendacao["prazo_compra_vencido"]
        or recomendacao["status_agendamento"] == "comprar_agora"
        or (primeira_falta is not None and (primeira_falta - origem).days <= revisao)
    ):
        prioridade = "alta"
    elif (
        primeira_seguranca is not None
        or recomendacao["status"] == "horizonte_insuficiente"
        or recomendacao["excesso"]
    ):
        prioridade = "media"
    else:
        prioridade = "baixa"
    recomendacao["prioridade"] = prioridade
    recomendacao["prioridade_ordem"] = {
        "critica": 1,
        "alta": 2,
        "media": 3,
        "baixa": 4,
    }[prioridade]
    recomendacao["motivos_alerta"] = "; ".join(motivos)


def planejar_estoque(previsoes, produtos, fornecedores, pedidos=None, revisao_dias=7):
    """Retorna saldos diários e sugestões sujeitas a revisão humana.

    A referência é o fechamento de um dia. Recebimentos futuros ocorrem antes das
    vendas previstas do dia; compras feitas em um fechamento chegam em
    ``data_compra + max(1, prazo_dias)``. Assim, prazo zero significa a próxima
    manhã, sem usar uma compra posterior para cobrir vendas que já aconteceram.

    O prazo teórico de compra é a primeira passagem estrita abaixo da segurança
    menos esse prazo efetivo. A data acionável nunca precede a referência; o
    prazo teórico pode estar vencido. O tamanho é o maior déficit de segurança
    diário após a chegada até ``data_compra + prazo_dias + revisao_dias``, com
    mínimo e lote. A janela precisa estar totalmente prevista. Sem passagem
    abaixo da segurança, o momento da próxima compra permanece desconhecido.

    ``compra_sugerida`` dimensiona comprar agora; ``quantidade_compra_na_data``
    recalcula a janela deslocada para a data programada. O alvo agregado e a
    posição são informativos: só o caminho diário detecta pedidos tardios.
    Excesso usa 30 dias e fica indefinido sem essa cobertura.
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
            "primeira_abaixo_seguranca": None,
            "dias_ate_falta": None,
            "dias_ate_seguranca": None,
            "data_limite_compra": None,
            "data_compra_sugerida": None,
            "data_entrega_compra_sugerida": None,
            "quantidade_compra_na_data": None,
            "horizonte_necessario_agendamento": None,
            "prazo_compra_vencido": None,
            "falta_antes_entrega_compra": None,
            "status_agendamento": "sem_previsao",
            "prioridade": "indefinida",
            "prioridade_ordem": 5,
            "motivos_alerta": "Sem previsão para calcular prazo e quantidade de compra",
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
        chegada_reposicao = origem + pd.Timedelta(days=max(1, prazo))
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
        caminho_saldos = []
        if estoque < seguranca:
            recomendacao["primeira_abaixo_seguranca"] = origem
        for data, quantidade in zip(projecao["data"], projecao["previsao"]):
            recebido = int(recebimentos.get(data, 0))
            saldo += recebido - float(quantidade)
            caminho_saldos.append(saldo)
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
            if (
                saldo < seguranca - 1e-9
                and recomendacao["primeira_abaixo_seguranca"] is None
            ):
                recomendacao["primeira_abaixo_seguranca"] = data
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
            compra = _quantidade_na_data(
                pd.Series(caminho_saldos, index=projecao["data"]),
                origem,
                prazo,
                revisao_dias,
                seguranca,
                minimo,
                lote,
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
        _agendar_compra(
            recomendacao,
            pd.Series(caminho_saldos, index=projecao["data"]),
            origem,
            prazo,
            revisao_dias,
            seguranca,
            minimo,
            lote,
        )
        recomendacoes.append(recomendacao)

    return (
        pd.DataFrame(linhas_saldos, columns=COLUNAS_SALDOS),
        pd.DataFrame(recomendacoes, columns=COLUNAS_RECOMENDACOES),
    )
