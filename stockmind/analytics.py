"""Estatísticas descritivas e sugestões de políticas, sem alterar o catálogo.

Quantis empíricos e classes ABC/XYZ descrevem os dados disponíveis. Não são
garantias de atendimento ou estimativas da demanda perdida durante rupturas.
"""

from __future__ import annotations

from datetime import date, datetime
import math
import re

import pandas as pd

from .data import DataError


ABC_COLUMNS = [
    "sku",
    "classe_abc",
    "base_abc",
    "valor_base",
    "participacao_pct",
    "acumulado_pct",
    "classe_xyz",
    "cv",
    "observacoes",
]
LEAD_COLUMNS = [
    "fornecedor_id",
    "nome",
    "prazo_manual",
    "prazo_medio",
    "prazo_desvio",
    "prazo_p90",
    "prazo_sugerido",
    "amostras",
    "atrasos_pct",
    "status",
    "observacoes",
]
SAFETY_COLUMNS = [
    "sku",
    "seguranca_manual",
    "seguranca_sugerida",
    "amostras",
    "metodo",
    "status",
    "nivel",
    "amostras_disponiveis",
    "observacoes",
]


def _table(raw, required, name):
    if not isinstance(raw, pd.DataFrame):
        raise DataError(f"{name}: informe uma tabela.")
    if raw.columns.duplicated().any():
        raise DataError(f"{name}: colunas duplicadas.")
    missing = set(required) - set(raw.columns)
    if missing:
        raise DataError(f"{name}: colunas ausentes: {', '.join(sorted(missing))}.")
    return raw.copy().reset_index(drop=True)


def _ids(frame, column, unique=False):
    values = []
    for value in frame[column]:
        if (
            not pd.api.types.is_scalar(value)
            or pd.isna(value)
            or not str(value).strip()
        ):
            raise DataError(f"{column}: identificador vazio ou inválido.")
        values.append(str(value).strip())
    frame[column] = values
    if unique and frame[column].duplicated().any():
        raise DataError(f"{column}: identificador duplicado.")


def _number(value, column, minimum=0, maximum=None, integer=False, nullable=False):
    if not pd.api.types.is_scalar(value):
        raise DataError(f"{column}: valor numérico inválido.")
    missing = pd.isna(value) or (isinstance(value, str) and not value.strip())
    if missing and nullable:
        return math.nan
    if missing or pd.api.types.is_bool(value):
        raise DataError(f"{column}: informe um número finito, sem booleanos.")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise DataError(f"{column}: valor numérico inválido.") from error
    if (
        not math.isfinite(number)
        or (minimum is not None and number < minimum)
        or (maximum is not None and number > maximum)
        or (integer and not number.is_integer())
    ):
        raise DataError(f"{column}: valor fora do intervalo permitido.")
    return number


def _numeric(frame, column, **options):
    frame[column] = frame[column].map(lambda value: _number(value, column, **options))


def _date(value, column):
    if not isinstance(value, (str, date, datetime, pd.Timestamp)) or pd.isna(value):
        raise DataError(f"{column}: use YYYY-MM-DD, sem horário ou fuso.")
    if isinstance(value, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise DataError(f"{column}: use YYYY-MM-DD, sem horário ou fuso.")
    try:
        result = pd.to_datetime(value, errors="raise")
    except (ValueError, TypeError, OverflowError) as error:
        raise DataError(f"{column}: data inválida.") from error
    if result.tzinfo is not None or result != result.normalize():
        raise DataError(f"{column}: use YYYY-MM-DD, sem horário ou fuso.")
    return result


def _dates(frame, column):
    frame[column] = pd.to_datetime([_date(value, column) for value in frame[column]])


def classificar_produtos(vendas):
    """Classifica ABC por uma base global consistente e XYZ por dias disponíveis.

    ABC usa faturamento registrado somente quando TODOS os preços de TODAS as
    linhas são conhecidos; caso contrário, todos os produtos usam unidades.
    Empates de valor ficam juntos, na classe do acumulado anterior ao grupo.
    Assim, o grupo que cruza 80% ainda é A; o que cruza 95% ainda é B. Valores
    zero são C quando existe uma base positiva; total zero é indefinido.

    XYZ usa o desvio-padrão amostral (ddof=1) sobre a média em pelo menos 28 dias
    observados com disponivel=1. Disponibilidade ausente deixa XYZ indefinida;
    não se presume que vendas registradas sejam a demanda potencial.
    """
    frame = _table(vendas, ["sku", "data", "vendas"], "vendas")
    _ids(frame, "sku")
    _dates(frame, "data")
    _numeric(frame, "vendas", integer=True)
    if frame.duplicated(["sku", "data"]).any():
        raise DataError("vendas: mais de uma observação por produto/dia.")
    disponibilidade_informada = "disponivel" in frame
    if disponibilidade_informada:
        _numeric(frame, "disponivel", integer=True, maximum=1)
    else:
        frame["disponivel"] = math.nan

    completo = "preco" in frame
    if completo:
        _numeric(frame, "preco", nullable=True)
        completo = frame["preco"].notna().all()
    base = "faturamento_registrado" if completo else "unidades_vendidas"
    frame["_base"] = frame["vendas"] * frame["preco"] if completo else frame["vendas"]
    if not frame["_base"].map(math.isfinite).all():
        raise DataError("Faturamento excede o intervalo numérico suportado.")
    valores = frame.groupby("sku", sort=False)["_base"].sum()
    if not valores.map(math.isfinite).all():
        raise DataError("Total por produto excede o intervalo numérico suportado.")
    total = float(valores.sum())
    if not math.isfinite(total):
        raise DataError("Base total excede o intervalo numérico suportado.")
    ranking = (
        valores.rename("valor_base")
        .reset_index()
        .sort_values(["valor_base", "sku"], ascending=[False, True], kind="stable")
    )
    classes = {}
    anterior = 0.0
    for valor, grupo in ranking.groupby("valor_base", sort=False):
        if total == 0:
            classe = "indefinida"
        elif valor == 0:
            classe = "C"
        elif anterior < 80 - 1e-9:
            classe = "A"
        elif anterior < 95 - 1e-9:
            classe = "B"
        else:
            classe = "C"
        for sku in grupo["sku"]:
            classes[sku] = classe
        anterior += float(grupo["valor_base"].sum()) / total * 100 if total else 0

    rows = []
    acumulado = 0.0
    grupos = {sku: grupo for sku, grupo in frame.groupby("sku", sort=False)}
    for item in ranking.itertuples(index=False):
        grupo = grupos[item.sku]
        disponiveis = grupo.loc[grupo["disponivel"].eq(1), "vendas"]
        censurados = int(grupo["disponivel"].eq(0).sum())
        notas = []
        if not completo:
            notas.append(
                "Preços incompletos ou ausentes: ABC de todos os produtos usa unidades"
            )
        if censurados:
            notas.append(
                f"{censurados} dias sem disponibilidade excluídos do XYZ; "
                "ABC mantém vendas registradas e não estima demanda perdida"
            )
        if not disponibilidade_informada:
            notas.append(
                "Disponibilidade não informada: XYZ indefinida, sem dias disponíveis confirmados"
            )
        cv = None
        xyz = "indefinida"
        if len(disponiveis) < 28:
            notas.append(f"XYZ exige 28 dias disponíveis; há {len(disponiveis)}")
        elif float(disponiveis.mean()) == 0:
            notas.append("XYZ indefinida: média de vendas disponíveis é zero")
        else:
            cv = float(disponiveis.std(ddof=1) / disponiveis.mean())
            xyz = "X" if cv <= 0.5 else "Y" if cv <= 1 else "Z"
        if total == 0:
            notas.append("ABC indefinida: base total zero")
        participacao = float(item.valor_base) / total * 100 if total else 0.0
        acumulado += participacao
        rows.append(
            {
                "sku": item.sku,
                "classe_abc": classes[item.sku],
                "base_abc": base,
                "valor_base": float(item.valor_base),
                "participacao_pct": participacao,
                "acumulado_pct": acumulado,
                "classe_xyz": xyz,
                "cv": cv,
                "observacoes": "; ".join(notas),
            }
        )
    return pd.DataFrame(rows, columns=ABC_COLUMNS)


def analisar_prazos(entregas, fornecedores, origem):
    """Sugere o P90 empírico dos prazos recebidos, sem alterar o prazo manual.

    São necessários cinco recebimentos até a referência. P90 usa interpolação
    linear e arredondamento para cima. Valores acima dos 60 dias suportados pelo
    planejador ficam explícitos, sem serem truncados nem aplicados. Recebimentos
    posteriores à referência não participam, inclusive em uma análise retrospectiva.
    """
    referencia = _date(origem, "origem")
    suppliers = _table(fornecedores, ["fornecedor_id", "prazo_dias"], "fornecedores")
    _ids(suppliers, "fornecedor_id", unique=True)
    _numeric(suppliers, "prazo_dias", integer=True, maximum=60)
    receipts = _table(
        entregas,
        [
            "entrega_id",
            "fornecedor_id",
            "data_pedido",
            "data_prevista",
            "data_recebida",
        ],
        "entregas",
    )
    _ids(receipts, "entrega_id", unique=True)
    _ids(receipts, "fornecedor_id")
    if not set(receipts["fornecedor_id"]).issubset(set(suppliers["fornecedor_id"])):
        raise DataError("Entregas possuem um fornecedor não cadastrado.")
    for coluna in ["data_pedido", "data_prevista", "data_recebida"]:
        _dates(receipts, coluna)
    if (
        receipts["data_prevista"].lt(receipts["data_pedido"]).any()
        or receipts["data_recebida"].lt(receipts["data_pedido"]).any()
    ):
        raise DataError("Entrega ou previsão não pode anteceder o pedido.")
    receipts["_prazo"] = (receipts["data_recebida"] - receipts["data_pedido"]).dt.days
    if receipts["_prazo"].gt(365).any():
        raise DataError("Histórico de entregas suporta prazos de até 365 dias.")
    rows = []
    for fornecedor in suppliers.sort_values("fornecedor_id").to_dict("records"):
        todas = receipts.loc[receipts["fornecedor_id"].eq(fornecedor["fornecedor_id"])]
        grupo = todas.loc[todas["data_recebida"].le(referencia)]
        n = len(grupo)
        media = float(grupo["_prazo"].mean()) if n else None
        desvio = float(grupo["_prazo"].std(ddof=1)) if n >= 2 else None
        p90 = math.ceil(float(grupo["_prazo"].quantile(0.9))) if n else None
        atrasos = (
            float(grupo["data_recebida"].gt(grupo["data_prevista"]).mean() * 100)
            if n
            else None
        )
        sugerido = None
        if n == 0:
            status = "sem_entregas"
        elif n < 5:
            status = "amostra_insuficiente"
        elif p90 > 60:
            status = "fora_limite_planejamento"
        else:
            status = "sugerido"
            sugerido = p90
        notas = ["P90 empírico é uma estimativa histórica, não garantia de entrega"]
        if len(todas) > n:
            notas.append(
                f"{len(todas) - n} recebimentos após a referência foram excluídos"
            )
        if status == "fora_limite_planejamento":
            notas.append(
                "P90 acima de 60 dias: manter prazo manual e revisar a política"
            )
        rows.append(
            {
                "fornecedor_id": fornecedor["fornecedor_id"],
                "nome": fornecedor.get("nome", fornecedor["fornecedor_id"]),
                "prazo_manual": int(fornecedor["prazo_dias"]),
                "prazo_medio": media,
                "prazo_desvio": desvio,
                "prazo_p90": p90,
                "prazo_sugerido": sugerido,
                "amostras": n,
                "atrasos_pct": atrasos,
                "status": status,
                "observacoes": "; ".join(notas),
            }
        )
    return pd.DataFrame(rows, columns=LEAD_COLUMNS)


def sugerir_seguranca(produtos, erros_reposicao, nivel=0.9, min_amostras=5):
    """Quantil dos erros acumulados em blocos positivos sem sobreposição.

    Os erros devem vir exclusivamente da calibração separada do teste, com alvos
    disponíveis e observados; esta tabela resumida não consegue reconstituir essa
    elegibilidade. O coletor de previsão garante essa origem. Blocos considerados
    são (origem, origem + prazo_dias]; prazo zero não produz uma amostra.
    Seleção gulosa pelo término mais cedo evita contar o mesmo dia duas vezes.
    """
    nivel = _number(nivel, "nivel", minimum=0, maximum=1)
    if nivel in (0, 1):
        raise DataError("nivel deve estar estritamente entre zero e um.")
    minimo = int(_number(min_amostras, "min_amostras", minimum=5, integer=True))
    catalogo = _table(produtos, ["sku", "estoque_seguranca"], "produtos")
    _ids(catalogo, "sku", unique=True)
    _numeric(catalogo, "estoque_seguranca", integer=True)
    colunas = ["sku", "origem", "prazo_dias", "erro_acumulado", "modelo"]
    if erros_reposicao is None:
        erros_reposicao = pd.DataFrame(columns=colunas)
    erros = _table(erros_reposicao, colunas, "erros_reposicao")
    _ids(erros, "sku")
    _ids(erros, "modelo")
    if not set(erros["sku"]).issubset(set(catalogo["sku"])):
        raise DataError("Erros de reposição possuem produto não cadastrado.")
    _dates(erros, "origem")
    _numeric(erros, "prazo_dias", integer=True, maximum=60)
    _numeric(erros, "erro_acumulado", minimum=None)
    if "proxy" in erros:
        erros["_proxy"] = erros["proxy"].map(
            lambda value: (
                bool(value)
                if pd.api.types.is_bool(value)
                else bool(_number(value, "proxy", maximum=1, integer=True))
            )
        )
    else:
        erros["_proxy"] = False
    try:
        erros["_fim"] = erros["origem"] + pd.to_timedelta(erros["prazo_dias"], unit="D")
    except (ValueError, OverflowError) as error:
        raise DataError(
            "Janela de erro fora do intervalo de datas suportado."
        ) from error
    rows = []
    for produto in catalogo.sort_values("sku").to_dict("records"):
        do_produto = erros.loc[erros["sku"].eq(produto["sku"])]
        descartados_proxy = int(do_produto["_proxy"].sum())
        grupo = do_produto.loc[do_produto["prazo_dias"].gt(0) & ~do_produto["_proxy"]]
        if grupo["prazo_dias"].nunique() > 1 or grupo["modelo"].nunique() > 1:
            raise DataError("Cada produto deve usar erros de um único prazo e modelo.")
        if (
            grupo.groupby(["origem", "prazo_dias"])["erro_acumulado"]
            .nunique()
            .gt(1)
            .any()
        ):
            raise DataError("Uma mesma janela possui erros acumulados conflitantes.")
        selecionados = []
        ultimo_fim = None
        for linha in grupo.sort_values(["_fim", "origem"], kind="stable").itertuples():
            fim = linha.origem + pd.Timedelta(days=linha.prazo_dias)
            if ultimo_fim is None or linha.origem >= ultimo_fim:
                selecionados.append(float(linha.erro_acumulado))
                ultimo_fim = fim
        n = len(selecionados)
        sugestao = None
        if n >= minimo:
            quantil = float(pd.Series(selecionados).quantile(nivel))
            sugestao = math.ceil(max(0.0, quantil))
        notas = [
            "Quantil empírico do erro acumulado: não garante nível de atendimento",
            "Somente blocos sem sobreposição; prazo zero não conta como amostra",
        ]
        if len(grupo) > n:
            notas.append(f"{len(grupo) - n} blocos sobrepostos excluídos")
        if descartados_proxy:
            notas.append(
                f"{descartados_proxy} blocos proxy de vendas excluídos; "
                "segurança automática exige alvos com disponibilidade conhecida"
            )
        rows.append(
            {
                "sku": produto["sku"],
                "seguranca_manual": int(produto["estoque_seguranca"]),
                "seguranca_sugerida": sugestao,
                "amostras": n,
                "metodo": "quantil_empirico_erro_acumulado",
                "status": "sugerida"
                if sugestao is not None
                else "amostra_insuficiente",
                "nivel": nivel,
                "amostras_disponiveis": len(grupo),
                "observacoes": "; ".join(notas),
            }
        )
    return pd.DataFrame(rows, columns=SAFETY_COLUMNS)
