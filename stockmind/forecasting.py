"""Previsão por SKU com seleção, calibração e teste temporalmente separados.

Recebe dados diários já validados. WAPE e cobertura são porcentagens (0–100);
o viés é previsão menos observado. Faixas empíricas são pontuais, não garantias.
"""

import math

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


MODELOS = (
    "Última venda",
    "Semana anterior",
    "Média recente",
    "Croston-SBA",
    "Regressão linear",
    "Regressão com dia da semana",
)
MODELO_CONTEXTO = "Regressão com contexto"
MODELO_INICIAL = "Estimativa inicial (média observada)"
COLUNAS_CONTEXTO = ("preco", "promocao", "feriado")
MIN_TREINO = 14
NIVEL_FAIXA = 0.90


def criar_atributos(datas, inicio, incluir_semana, contexto=None):
    """Usa apenas calendário e covariáveis conhecidas antes da previsão."""
    datas = pd.DatetimeIndex(datas)
    atributos = pd.DataFrame({"dia": (datas - inicio).days})
    if incluir_semana:
        for dia in range(1, 7):
            atributos[f"dia_semana_{dia}"] = (datas.dayofweek == dia).astype(int)
    if contexto is not None:
        for coluna in COLUNAS_CONTEXTO:
            atributos[coluna] = contexto[coluna].to_numpy(dtype=float)
    return atributos


def _croston_sba(vendas, alpha=0.1):
    """Tamanho e intervalo suavizados, com correção de viés SBA e alpha fixo."""
    vendas = np.asarray(vendas, dtype=float)
    positivos = np.flatnonzero(vendas > 0)
    if not len(positivos):
        return 0.0
    primeiro = int(positivos[0])
    tamanho = vendas[primeiro]
    intervalo = float(primeiro + 1)
    anterior = primeiro
    for indice in positivos[1:]:
        tamanho += alpha * (vendas[indice] - tamanho)
        intervalo += alpha * (indice - anterior - intervalo)
        anterior = int(indice)
    return float((1 - alpha / 2) * tamanho / intervalo)


def prever_com_modelo(dados, nome, horizonte=7, contexto_futuro=None):
    """Projeta exatamente o horizonte pedido, sem consultar vendas futuras."""
    vendas = dados["vendas"].to_numpy(dtype=float)
    if not len(vendas):
        raise ValueError("O modelo precisa de pelo menos um dia observado.")
    if nome == "Última venda":
        return np.full(horizonte, vendas[-1])
    if nome == "Semana anterior":
        if len(vendas) < 7:
            raise ValueError("A referência semanal precisa de sete dias.")
        return np.resize(vendas[-7:], horizonte)
    if nome in ("Média recente", MODELO_INICIAL):
        janela = 14 if nome == MODELO_INICIAL else 28
        return np.full(horizonte, vendas[-janela:].mean())
    if nome == "Croston-SBA":
        return np.full(horizonte, _croston_sba(vendas))
    if nome not in ("Regressão linear", "Regressão com dia da semana", MODELO_CONTEXTO):
        raise ValueError("Modelo desconhecido.")

    inicio = dados["data"].iloc[0]
    futuro = pd.date_range(
        dados["data"].iloc[-1] + pd.Timedelta(days=1), periods=horizonte
    )
    semanal = nome != "Regressão linear"
    com_contexto = nome == MODELO_CONTEXTO
    if com_contexto and not _contexto_completo(dados, contexto_futuro, horizonte):
        raise ValueError(
            "O modelo contextual exige histórico e plano futuro completos."
        )
    treino = criar_atributos(
        dados["data"], inicio, semanal, dados if com_contexto else None
    )
    futuros = criar_atributos(
        futuro, inicio, semanal, contexto_futuro if com_contexto else None
    )
    modelo = (
        make_pipeline(StandardScaler(), Ridge(alpha=1.0))
        if com_contexto
        else LinearRegression()
    )
    modelo.fit(treino, vendas)
    return np.maximum(0, modelo.predict(futuros))


def _contexto_completo(dados, contexto, horizonte):
    if contexto is None or len(contexto) != horizonte:
        return False
    if not set(COLUNAS_CONTEXTO).issubset(dados.columns) or not set(
        ("data", *COLUNAS_CONTEXTO)
    ).issubset(contexto.columns):
        return False
    esperado = pd.date_range(
        dados["data"].iloc[-1] + pd.Timedelta(days=1), periods=horizonte
    )
    if not pd.DatetimeIndex(contexto["data"]).equals(esperado):
        return False
    try:
        for frame in (dados, contexto):
            valores = frame[list(COLUNAS_CONTEXTO)].to_numpy(dtype=float)
            if not np.isfinite(valores).all() or (valores[:, 0] < 0).any():
                return False
            if not np.isin(valores[:, 1:], (0, 1)).all():
                return False
    except (TypeError, ValueError):
        return False
    return True


def _mae(real, estimado):
    return float(np.abs(np.asarray(real, dtype=float) - estimado).mean())


def _quantil_calibracao(erros):
    """Quantil conservador de resíduos externos; dependência temporal permanece."""
    erros = np.asarray(erros, dtype=float)
    if len(erros) < 14:
        return None
    ordem = math.ceil((len(erros) + 1) * NIVEL_FAIXA)
    if ordem > len(erros):
        return None
    return float(np.sort(erros)[ordem - 1])


def _origens_validacao(fim, horizonte):
    origens = []
    origem = fim - horizonte
    while origem >= MIN_TREINO and len(origens) < 3:
        origens.append(origem)
        origem -= horizonte
    return sorted(origens)


def _prever_bloco(dados, nome, inicio, horizonte):
    # As covariáveis históricas desse bloco precisam ter sido conhecidas antes
    # dele, como preços e promoções anunciados; vendas nunca entram nos atributos.
    contexto = (
        dados.iloc[inicio : inicio + horizonte] if nome == MODELO_CONTEXTO else None
    )
    return prever_com_modelo(dados.iloc[:inicio], nome, horizonte, contexto)


def _analisar_sku(dados, horizonte, contexto):
    n = len(dados)
    sku = str(dados["sku"].iloc[0])
    contexto_ok = _contexto_completo(dados, contexto, horizonte)
    contexto_historico = any(coluna in dados.columns for coluna in COLUNAS_CONTEXTO)
    nota_contexto = (
        "Contexto ignorado: histórico ou plano futuro incompleto de preço, promoção e feriado."
        if (contexto_historico or contexto is not None) and not contexto_ok
        else ""
    )
    dias_futuros = pd.date_range(
        dados["data"].iloc[-1] + pd.Timedelta(days=1), periods=horizonte
    )
    inicio_teste = n - horizonte
    tamanho_calibracao = 2 * horizonte if n >= MIN_TREINO + 4 * horizonte else 0
    inicio_calibracao = inicio_teste - tamanho_calibracao
    origens = _origens_validacao(inicio_calibracao, horizonte)
    if not origens:
        previsao = prever_com_modelo(dados, MODELO_INICIAL, horizonte)
        observacao = (
            f"Histórico de {n} dias insuficiente para selecionar e testar métodos em "
            f"horizonte de {horizonte} dias. Média dos últimos {min(n, 14)} dias; "
            "não há erro de validação, teste ou faixa estimada."
        )
        metricas = [
            {
                "sku": sku,
                "modelo": MODELO_INICIAL,
                "mae_validacao": None,
                "mae_teste": None,
                "wape_teste": None,
                "vies_teste": None,
                "janelas_validacao": 0,
                "selecionado": True,
                "cobertura_teste": None,
                "amostras_calibracao": 0,
                "status": "historico_curto",
                "observacao": observacao,
                "contexto_utilizado": False,
                "validacao_inicio": None,
                "validacao_fim": None,
                "calibracao_inicio": None,
                "calibracao_fim": None,
                "teste_inicio": None,
                "teste_fim": None,
            }
        ]
        escolhido = MODELO_INICIAL
        largura = None
        status = "historico_curto"
    else:
        nomes = (*MODELOS, MODELO_CONTEXTO) if contexto_ok else MODELOS
        metricas = []
        escolhido, menor_erro = None, math.inf
        larguras = {}
        for nome in nomes:
            erros_validacao = []
            for origem in origens:
                esperado = (
                    dados["vendas"]
                    .iloc[origem : origem + horizonte]
                    .to_numpy(dtype=float)
                )
                previsto = _prever_bloco(dados, nome, origem, horizonte)
                erros_validacao.extend(np.abs(esperado - previsto))
            mae_validacao = float(np.mean(erros_validacao))
            if escolhido is None or mae_validacao < menor_erro - 1e-9:
                escolhido, menor_erro = nome, mae_validacao

            erros_calibracao = []
            for origem in range(inicio_calibracao, inicio_teste, horizonte):
                esperado = (
                    dados["vendas"]
                    .iloc[origem : origem + horizonte]
                    .to_numpy(dtype=float)
                )
                previsto = _prever_bloco(dados, nome, origem, horizonte)
                erros_calibracao.extend(np.abs(esperado - previsto))
            largura = _quantil_calibracao(erros_calibracao)
            larguras[nome] = largura

            previsto = _prever_bloco(dados, nome, inicio_teste, horizonte)
            real = dados["vendas"].iloc[inicio_teste:].to_numpy(dtype=float)
            soma_real = float(real.sum())
            cobertura = None
            if largura is not None:
                inferior, superior = (
                    np.maximum(0, previsto - largura),
                    previsto + largura,
                )
                cobertura = float(
                    ((real >= inferior) & (real <= superior)).mean() * 100
                )
            metricas.append(
                {
                    "sku": sku,
                    "modelo": nome,
                    "mae_validacao": mae_validacao,
                    "mae_teste": _mae(real, previsto),
                    "wape_teste": float(np.abs(real - previsto).sum() / soma_real * 100)
                    if soma_real
                    else None,
                    "vies_teste": float((previsto - real).mean()),
                    "janelas_validacao": len(origens),
                    "cobertura_teste": cobertura,
                    "amostras_calibracao": len(erros_calibracao),
                    "status": "avaliado",
                    "observacao": nota_contexto,
                    "contexto_utilizado": nome == MODELO_CONTEXTO,
                    "validacao_inicio": dados["data"].iloc[origens[0]],
                    "validacao_fim": dados["data"].iloc[inicio_calibracao - 1],
                    "calibracao_inicio": dados["data"].iloc[inicio_calibracao]
                    if tamanho_calibracao
                    else None,
                    "calibracao_fim": dados["data"].iloc[inicio_teste - 1]
                    if tamanho_calibracao
                    else None,
                    "teste_inicio": dados["data"].iloc[inicio_teste],
                    "teste_fim": dados["data"].iloc[-1],
                }
            )
        for linha in metricas:
            linha["selecionado"] = linha["modelo"] == escolhido
        largura = larguras[escolhido]
        previsao = prever_com_modelo(dados, escolhido, horizonte, contexto)
        observacao = nota_contexto
        status = "avaliado"

    previsoes = pd.DataFrame(
        {
            "sku": sku,
            "data": dias_futuros,
            "previsao": previsao,
            "limite_inferior": np.maximum(0, previsao - largura)
            if largura is not None
            else np.nan,
            "limite_superior": previsao + largura if largura is not None else np.nan,
            "modelo": escolhido,
            "status": status,
            "status_faixa": "calibrada_empiricamente"
            if largura is not None
            else "dados_insuficientes",
            "amostras_calibracao": tamanho_calibracao if largura is not None else 0,
            "nivel_faixa": NIVEL_FAIXA if largura is not None else np.nan,
            "contexto_utilizado": escolhido == MODELO_CONTEXTO,
            "observacao": observacao,
        }
    )
    avaliacao = pd.DataFrame(metricas)
    # Tipos consistentes permitem misturar produtos novos e séries avaliadas,
    # preservando ausências como NaN/NaT em vez de zeros inventados.
    for coluna in (
        "mae_validacao",
        "mae_teste",
        "wape_teste",
        "vies_teste",
        "cobertura_teste",
    ):
        avaliacao[coluna] = pd.to_numeric(avaliacao[coluna]).astype(float)
    for coluna in (
        "validacao_inicio",
        "validacao_fim",
        "calibracao_inicio",
        "calibracao_fim",
        "teste_inicio",
        "teste_fim",
    ):
        avaliacao[coluna] = pd.to_datetime(avaliacao[coluna])
    return previsoes, avaliacao


def analisar_previsoes(vendas, horizonte=7, contexto_futuro=None):
    """Analisa SKUs separadamente; recebe histórico diário validado e ordena cópia.

    Até três janelas de validação escolhem o método. Quando há dados, dois
    horizontes separados calibram uma faixa empírica de referência de 90%.
    O último horizonte é teste e nunca escolhe o modelo ou a largura da faixa.
    Faixas agregam resíduos pontuais; não são limites simultâneos para a trajetória.
    Séries temporais dependentes não têm garantia de cobertura nominal.
    """
    if (
        isinstance(horizonte, bool)
        or not isinstance(horizonte, (int, np.integer))
        or horizonte not in (7, 14, 30, 90)
    ):
        raise ValueError("Horizonte deve ser 7, 14, 30 ou 90 dias.")
    if vendas.empty or not {"sku", "data", "vendas"}.issubset(vendas.columns):
        raise ValueError("Informe histórico validado com sku, data e vendas.")
    previsoes, metricas = [], []
    for sku, grupo in vendas.groupby("sku", sort=True):
        grupo = grupo.sort_values("data").reset_index(drop=True)
        futuro = None
        if contexto_futuro is not None and "sku" in contexto_futuro:
            futuro = (
                contexto_futuro.loc[contexto_futuro["sku"].eq(sku)]
                .sort_values("data")
                .reset_index(drop=True)
            )
        previsao, avaliacao = _analisar_sku(grupo, int(horizonte), futuro)
        previsoes.append(previsao)
        metricas.append(avaliacao)
    return pd.concat(previsoes, ignore_index=True), pd.concat(
        metricas, ignore_index=True
    )
