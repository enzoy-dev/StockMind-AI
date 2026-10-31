"""Previsão por SKU com seleção, calibração e teste temporalmente separados.

Recebe dados diários já validados. WAPE e cobertura são porcentagens (0–100);
o viés é previsão menos observado. Faixas empíricas são pontuais, não garantias.
"""

import math

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
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
    "Regressão com atrasos",
    "Regressão com ciclo mensal",
    "Regressão com ciclo anual",
    "Gradient Boosting",
)
MODELO_ATRASOS = "Regressão com atrasos"
MODELO_CONTEXTO = "Regressão com contexto"
MODELO_INICIAL = "Estimativa inicial (média observada)"
MODELO_INDISPONIVEL = "Demanda indisponível"
MODELO_MENSAL = "Regressão com ciclo mensal"
MODELO_ANUAL = "Regressão com ciclo anual"
MODELO_ARVORE = "Gradient Boosting"
COLUNAS_CONTEXTO = ("preco", "promocao", "feriado")
MIN_TREINO = 14
MIN_TREINO_ATRASOS = 42
NIVEL_FAIXA = 0.90


def _observavel(dados):
    """Sem disponibilidade, só conhecemos vendas observadas, não demanda perdida."""
    if "disponivel" not in dados:
        return np.ones(len(dados), dtype=bool)
    return dados["disponivel"].eq(1).to_numpy()


def _sufixo_disponivel(dados):
    censurados = np.flatnonzero(~_observavel(dados))
    inicio = int(censurados[-1]) + 1 if len(censurados) else 0
    return dados.iloc[inicio:].reset_index(drop=True)


def _pode_ajustar(dados, nome):
    observavel = _observavel(dados)
    quantidade = int(observavel.sum())
    if not quantidade:
        return False
    if nome in ("Última venda", MODELO_INICIAL):
        return True
    if nome == "Média recente":
        return bool(observavel[-28:].any())
    if nome in ("Semana anterior", "Croston-SBA", MODELO_ATRASOS):
        minimo = {"Semana anterior": 7, "Croston-SBA": 14, MODELO_ATRASOS: 42}[nome]
        return len(_sufixo_disponivel(dados)) >= minimo
    minimo = {MODELO_MENSAL: 90, MODELO_ANUAL: 730, MODELO_ARVORE: 60}.get(
        nome, MIN_TREINO
    )
    return quantidade >= minimo and len(dados) >= minimo


def _atributos_calendario(datas, inicio, nome):
    atributos = criar_atributos(datas, inicio, True)
    datas = pd.DatetimeIndex(datas)
    if nome in (MODELO_MENSAL, MODELO_ARVORE):
        fase = (datas.day - 1) / datas.days_in_month
        atributos["mes_seno"] = np.sin(2 * np.pi * fase)
        atributos["mes_cosseno"] = np.cos(2 * np.pi * fase)
    if nome in (MODELO_ANUAL, MODELO_ARVORE):
        fase = (datas.dayofyear - 1) / np.where(datas.is_leap_year, 366, 365)
        atributos["ano_seno"] = np.sin(2 * np.pi * fase)
        atributos["ano_cosseno"] = np.cos(2 * np.pi * fase)
    return atributos


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


def _prever_com_atrasos(dados, horizonte):
    """Ridge com parâmetros fixos e previsão recursiva sem teacher forcing.

    Cada linha de treinamento usa somente vendas anteriores ao seu alvo. Na
    projeção, valores futuros de atrasos e médias vêm das próprias previsões.
    O ajuste do padronizador também ocorre somente no histórico recebido.
    """
    if len(dados) < MIN_TREINO_ATRASOS:
        raise ValueError("A regressão com atrasos precisa de pelo menos 42 dias.")
    vendas = dados["vendas"].to_numpy(dtype=float)
    inicio = dados["data"].iloc[0]
    treino = criar_atributos(dados["data"], inicio, True).iloc[14:].copy()
    treino["atraso_1"] = vendas[13:-1]
    treino["atraso_7"] = vendas[7:-7]
    treino["atraso_14"] = vendas[:-14]
    serie = pd.Series(vendas)
    treino["media_7"] = serie.rolling(7).mean().shift(1).iloc[14:].to_numpy()
    treino["media_14"] = serie.rolling(14).mean().shift(1).iloc[14:].to_numpy()
    modelo = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
    modelo.fit(treino, vendas[14:])

    datas = pd.date_range(
        dados["data"].iloc[-1] + pd.Timedelta(days=1), periods=horizonte
    )
    calendario = criar_atributos(datas, inicio, True)
    historico = vendas.tolist()
    previsoes = []
    for passo in range(horizonte):
        atributos = calendario.iloc[[passo]].copy()
        atributos["atraso_1"] = historico[-1]
        atributos["atraso_7"] = historico[-7]
        atributos["atraso_14"] = historico[-14]
        atributos["media_7"] = float(np.mean(historico[-7:]))
        atributos["media_14"] = float(np.mean(historico[-14:]))
        valor = max(0.0, float(modelo.predict(atributos)[0]))
        previsoes.append(valor)
        historico.append(valor)
    return np.asarray(previsoes)


def prever_com_modelo(dados, nome, horizonte=7, contexto_futuro=None):
    """Projeta sem usar vendas censuradas como alvos ou atrasos de demanda."""
    if not _pode_ajustar(dados, nome):
        raise ValueError(f"Histórico disponível insuficiente para {nome}.")
    observavel = _observavel(dados)
    vendas = dados["vendas"].to_numpy(dtype=float)
    observadas = vendas[observavel]
    if nome == "Última venda":
        return np.full(horizonte, observadas[-1])
    if nome == "Semana anterior":
        sufixo = _sufixo_disponivel(dados)
        return np.resize(sufixo["vendas"].iloc[-7:].to_numpy(dtype=float), horizonte)
    if nome == MODELO_INICIAL:
        return np.full(horizonte, observadas[-14:].mean())
    if nome == "Média recente":
        janela = dados.iloc[-28:]
        return np.full(horizonte, janela.loc[_observavel(janela), "vendas"].mean())
    if nome == "Croston-SBA":
        return np.full(horizonte, _croston_sba(_sufixo_disponivel(dados)["vendas"]))
    if nome == MODELO_ATRASOS:
        return _prever_com_atrasos(_sufixo_disponivel(dados), horizonte)
    if nome not in (
        "Regressão linear",
        "Regressão com dia da semana",
        MODELO_CONTEXTO,
        MODELO_MENSAL,
        MODELO_ANUAL,
        MODELO_ARVORE,
    ):
        raise ValueError("Modelo desconhecido.")

    inicio = dados["data"].iloc[0]
    futuro = pd.date_range(
        dados["data"].iloc[-1] + pd.Timedelta(days=1), periods=horizonte
    )
    com_contexto = nome == MODELO_CONTEXTO
    if com_contexto and not _contexto_completo(dados, contexto_futuro, horizonte):
        raise ValueError(
            "O modelo contextual exige histórico e plano futuro completos."
        )
    if nome in (MODELO_MENSAL, MODELO_ANUAL, MODELO_ARVORE):
        treino = _atributos_calendario(dados["data"], inicio, nome)
        futuros = _atributos_calendario(futuro, inicio, nome)
    else:
        semanal = nome != "Regressão linear"
        treino = criar_atributos(
            dados["data"], inicio, semanal, dados if com_contexto else None
        )
        futuros = criar_atributos(
            futuro, inicio, semanal, contexto_futuro if com_contexto else None
        )
    if nome == MODELO_ARVORE:
        modelo = GradientBoostingRegressor(
            n_estimators=40,
            max_depth=2,
            min_samples_leaf=5,
            learning_rate=0.05,
            loss="squared_error",
            random_state=42,
        )
    elif com_contexto:
        modelo = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    else:
        modelo = LinearRegression()
    modelo.fit(treino.loc[observavel], observadas)
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
    observavel = _observavel(dados)
    censurados = int((~observavel).sum())
    informada = "disponivel" in dados
    contexto_ok = _contexto_completo(dados, contexto, horizonte)
    contexto_historico = any(coluna in dados for coluna in COLUNAS_CONTEXTO)
    notas = []
    if (contexto_historico or contexto is not None) and not contexto_ok:
        notas.append(
            "Contexto ignorado: histórico ou plano futuro incompleto de preço, promoção e feriado."
        )
    if not informada:
        notas.append(
            "Disponibilidade não informada: a avaliação usa vendas observadas e não identifica demanda perdida."
        )
    elif censurados:
        notas.append(
            f"{censurados} dias censurados excluídos do ajuste e avaliação; demanda perdida não foi imputada."
        )
    else:
        notas.append("Ajuste e avaliação usam os dias declarados disponíveis.")
    nota = " ".join(notas)
    dias_futuros = pd.date_range(
        dados["data"].iloc[-1] + pd.Timedelta(days=1), periods=horizonte
    )
    inicio_teste = n - horizonte
    tamanho_calibracao = 2 * horizonte if n >= MIN_TREINO + 4 * horizonte else 0
    inicio_calibracao = inicio_teste - tamanho_calibracao
    origens = [
        origem
        for origem in _origens_validacao(inicio_calibracao, horizonte)
        if _observavel(dados.iloc[:origem]).any()
        and _observavel(dados.iloc[origem : origem + horizonte]).any()
    ]
    nomes = tuple(
        nome
        for nome in MODELOS
        if origens
        and all(_pode_ajustar(dados.iloc[:origem], nome) for origem in origens)
    )
    if (
        contexto_ok
        and origens
        and all(_pode_ajustar(dados.iloc[:o], MODELO_CONTEXTO) for o in origens)
    ):
        nomes = (*nomes, MODELO_CONTEXTO)

    def linha_nula(modelo, status, observacao):
        return {
            "sku": sku,
            "modelo": modelo,
            "mae_validacao": None,
            "mae_teste": None,
            "wape_teste": None,
            "vies_teste": None,
            "janelas_validacao": 0,
            "selecionado": True,
            "cobertura_teste": None,
            "amostras_calibracao": 0,
            "amostras_validacao": 0,
            "amostras_teste": 0,
            "blocos_calibracao_ignorados": 0,
            "status": status,
            "observacao": observacao,
            "contexto_utilizado": False,
            "validacao_inicio": None,
            "validacao_fim": None,
            "calibracao_inicio": None,
            "calibracao_fim": None,
            "teste_inicio": None,
            "teste_fim": None,
        }

    if not observavel.any():
        status = "demanda_indisponivel"
        observacao = (
            "Nenhum dia com demanda observável: não há previsão nem reposição inferida. "
            + nota
        )
        escolhido = operacional = MODELO_INDISPONIVEL
        metricas = [linha_nula(escolhido, status, observacao)]
        previsao, largura = None, None
        amostras_calibracao = 0
    elif not nomes:
        escolhido = operacional = MODELO_INICIAL
        previsao = prever_com_modelo(dados, operacional, horizonte)
        observacao = (
            f"Histórico observável insuficiente para selecionar e testar métodos em horizonte de {horizonte} dias. "
            "Estimativa pelas últimas até 14 observações disponíveis, sem erros ou faixas validados. "
            + nota
        )
        status = "historico_curto"
        metricas = [linha_nula(escolhido, status, observacao)]
        largura = None
        amostras_calibracao = 0
    else:
        metricas = []
        escolhido, menor_erro = None, math.inf
        larguras, amostras = {}, {}
        for nome in nomes:
            erros_validacao = []
            for origem in origens:
                bloco = dados.iloc[origem : origem + horizonte]
                mascara = _observavel(bloco)
                esperado = bloco["vendas"].to_numpy(dtype=float)
                previsto = _prever_bloco(dados, nome, origem, horizonte)
                erros_validacao.extend(np.abs(esperado[mascara] - previsto[mascara]))
            mae_validacao = float(np.mean(erros_validacao))
            if escolhido is None or mae_validacao < menor_erro - 1e-9:
                escolhido, menor_erro = nome, mae_validacao

            erros_calibracao, blocos_ignorados = [], 0
            for origem in range(inicio_calibracao, inicio_teste, horizonte):
                if not _pode_ajustar(dados.iloc[:origem], nome):
                    blocos_ignorados += 1
                    continue
                bloco = dados.iloc[origem : origem + horizonte]
                mascara = _observavel(bloco)
                esperado = bloco["vendas"].to_numpy(dtype=float)
                previsto = _prever_bloco(dados, nome, origem, horizonte)
                erros_calibracao.extend(np.abs(esperado[mascara] - previsto[mascara]))
            largura = _quantil_calibracao(erros_calibracao)
            larguras[nome], amostras[nome] = largura, len(erros_calibracao)

            mascara = _observavel(dados.iloc[inicio_teste:])
            real = dados["vendas"].iloc[inicio_teste:].to_numpy(dtype=float)[mascara]
            pode_testar = _pode_ajustar(dados.iloc[:inicio_teste], nome) and bool(
                len(real)
            )
            mae_teste = wape = vies = cobertura = None
            if pode_testar:
                previsto = _prever_bloco(dados, nome, inicio_teste, horizonte)[mascara]
                soma_real = float(real.sum())
                mae_teste = _mae(real, previsto)
                wape = (
                    float(np.abs(real - previsto).sum() / soma_real * 100)
                    if soma_real
                    else None
                )
                vies = float((previsto - real).mean())
                if largura is not None:
                    inferior, superior = (
                        np.maximum(0, previsto - largura),
                        previsto + largura,
                    )
                    cobertura = float(
                        ((real >= inferior) & (real <= superior)).mean() * 100
                    )
            observacao_modelo = nota
            if not pode_testar:
                observacao_modelo += " Teste sem alvos observáveis ou treino disponível suficiente para este método; erro indefinido."
            metricas.append(
                {
                    "sku": sku,
                    "modelo": nome,
                    "mae_validacao": mae_validacao,
                    "mae_teste": mae_teste,
                    "wape_teste": wape,
                    "vies_teste": vies,
                    "janelas_validacao": len(origens),
                    "cobertura_teste": cobertura,
                    "amostras_calibracao": len(erros_calibracao),
                    "amostras_validacao": len(erros_validacao),
                    "amostras_teste": len(real) if pode_testar else 0,
                    "blocos_calibracao_ignorados": blocos_ignorados,
                    "status": "avaliacao_parcial"
                    if censurados or not pode_testar
                    else "avaliado",
                    "observacao": observacao_modelo,
                    "contexto_utilizado": nome == MODELO_CONTEXTO,
                    "validacao_inicio": dados["data"].iloc[origens[0]],
                    "validacao_fim": dados["data"].iloc[origens[-1] + horizonte - 1],
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
        operacional = escolhido
        largura = larguras[escolhido]
        amostras_calibracao = amostras[escolhido]
        observacao = nota
        status = "avaliacao_parcial" if censurados else "avaliado"
        if not _pode_ajustar(dados, escolhido):
            operacional, largura, amostras_calibracao = MODELO_INICIAL, None, 0
            observacao += (
                " Método selecionado sem histórico disponível suficiente na origem atual; "
                "previsão operacional usa média observada disponível, sem validação ou faixa próprias."
            )
            status = "avaliacao_parcial"
        previsao = prever_com_modelo(dados, operacional, horizonte, contexto)
        for linha in metricas:
            linha["selecionado"] = linha["modelo"] == escolhido
            if linha["selecionado"] and operacional != escolhido:
                linha["observacao"] += observacao[len(nota) :]

    for linha in metricas:
        linha["modelo_operacional"] = operacional if linha["selecionado"] else None
        linha["dias_disponiveis"] = int(observavel.sum()) if informada else None
        linha["dias_censurados"] = censurados if informada else None
        linha["disponibilidade_informada"] = informada
        linha["alvo_avaliacao"] = (
            "vendas_em_dias_disponiveis" if informada else "vendas_observadas_proxy"
        )

    if previsao is None:
        previsoes = _quadro_previsao_vazio()
    else:
        previsoes = pd.DataFrame(
            {
                "sku": sku,
                "data": dias_futuros,
                "previsao": previsao,
                "limite_inferior": np.maximum(0, previsao - largura)
                if largura is not None
                else np.nan,
                "limite_superior": previsao + largura
                if largura is not None
                else np.nan,
                "modelo": operacional,
                "modelo_validacao": escolhido,
                "status": status,
                "status_faixa": "calibrada_empiricamente"
                if largura is not None
                else "dados_insuficientes",
                "amostras_calibracao": amostras_calibracao,
                "nivel_faixa": NIVEL_FAIXA if largura is not None else np.nan,
                "contexto_utilizado": operacional == MODELO_CONTEXTO,
                "observacao": observacao,
                "disponibilidade_informada": informada,
            }
        )
    avaliacao = pd.DataFrame(metricas)
    for coluna in (
        "mae_validacao",
        "mae_teste",
        "wape_teste",
        "vies_teste",
        "cobertura_teste",
        "dias_disponiveis",
        "dias_censurados",
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
    semanal = avaliacao.loc[avaliacao["modelo"].eq("Semana anterior"), "mae_teste"]
    mae_semanal = float(semanal.iloc[0]) if len(semanal) else np.nan
    avaliacao["mae_teste_semana_anterior"] = mae_semanal
    avaliacao["ganho_mae_teste_pct"] = (
        (mae_semanal - avaliacao["mae_teste"]) / mae_semanal * 100
        if math.isfinite(mae_semanal) and mae_semanal > 0
        else np.nan
    )
    return previsoes, avaliacao


def _quadro_previsao_vazio():
    return pd.DataFrame(
        columns=[
            "sku",
            "data",
            "previsao",
            "limite_inferior",
            "limite_superior",
            "modelo",
            "modelo_validacao",
            "status",
            "status_faixa",
            "amostras_calibracao",
            "nivel_faixa",
            "contexto_utilizado",
            "observacao",
            "disponibilidade_informada",
        ]
    )


def _recortar_contexto(vendas, contexto_futuro, horizonte):
    """Reutiliza o mesmo calendário planejado, sem exigir um CSV para cada h."""
    if contexto_futuro is None:
        return None
    if not {"sku", "data"}.issubset(contexto_futuro.columns):
        return contexto_futuro
    partes = []
    for sku, grupo in vendas.groupby("sku", sort=True):
        origem = grupo["data"].max()
        limite = origem + pd.Timedelta(days=horizonte)
        partes.append(
            contexto_futuro.loc[
                contexto_futuro["sku"].eq(sku)
                & contexto_futuro["data"].gt(origem)
                & contexto_futuro["data"].le(limite)
            ]
        )
    return pd.concat(partes, ignore_index=True)


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
    contexto_futuro = _recortar_contexto(vendas, contexto_futuro, int(horizonte))
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
    previsoes = [quadro for quadro in previsoes if not quadro.empty]
    return (
        pd.concat(previsoes, ignore_index=True)
        if previsoes
        else _quadro_previsao_vazio()
    ), pd.concat(metricas, ignore_index=True)


def comparar_horizontes(vendas, contexto_futuro=None, horizontes=(7, 14, 30)):
    """Resume o método escolhido na validação em cada SKU/horizonte.

    A comparação de MAE de teste com a referência semanal é somente um relatório;
    nunca seleciona o método. Os testes têm durações e datas distintas por h,
    portanto os números não constituem uma comparação de dificuldade equivalente.
    Um ganho positivo significa MAE menor que o semanal, negativo significa maior.
    Quando o MAE semanal é zero ou ausente, o ganho relativo fica indefinido.
    """
    horizontes = tuple(horizontes)
    if not horizontes or len(set(horizontes)) != len(horizontes):
        raise ValueError("Informe horizontes distintos e não vazios.")
    resumos = []
    for horizonte in horizontes:
        contexto = _recortar_contexto(vendas, contexto_futuro, horizonte)
        _, metricas = analisar_previsoes(vendas, horizonte, contexto)
        selecionados = metricas.loc[metricas["selecionado"]].copy()
        selecionados["horizonte"] = horizonte
        selecionados["comparacao_observacao"] = (
            "Método escolhido pela validação; ganho no teste é apenas relatório. "
            "Horizontes diferentes têm semanas e durações de teste distintas."
        )
        resumos.append(selecionados)
    return pd.concat(resumos, ignore_index=True)


def coletar_erros_reposicao(vendas, metricas, prazos, permitir_proxy=False):
    """Erros acumulados independentes do teste para calibrar segurança.

    Usa apenas o bloco de calibração reservado do método selecionado. Cada alvo
    ocupa (origem, origem+prazo] e os blocos não se sobrepõem. Exige todos os dias
    declarados disponíveis; desconhecimento da disponibilidade só é aceito com
    opt-in explícito, e cada registro fica identificado como proxy de vendas.
    Prazos zero não têm exposição temporal e não geram amostras artificiais.
    O sinal positivo significa subprevisão (real acumulado menos previsto).
    """
    colunas = [
        "sku",
        "origem",
        "prazo_dias",
        "erro_acumulado",
        "modelo",
        "proxy",
        "fonte",
        "alvo_inicio",
        "alvo_fim",
    ]
    if not isinstance(permitir_proxy, bool):
        raise ValueError("permitir_proxy deve ser booleano.")
    if metricas.empty:
        return pd.DataFrame(columns=colunas)
    selecionadas = metricas.loc[metricas["selecionado"].eq(True)]
    if selecionadas["sku"].duplicated().any():
        raise ValueError(
            "Use as métricas de um único horizonte, com um vencedor por SKU."
        )
    amostras = []
    for _, metrica in selecionadas.iterrows():
        sku = metrica["sku"]
        prazo = prazos.get(sku)
        if prazo is None:
            continue
        if (
            isinstance(prazo, bool)
            or not isinstance(prazo, (int, np.integer))
            or not 0 <= prazo <= 60
        ):
            raise ValueError("Prazos devem ser inteiros entre zero e 60 dias.")
        if (
            not prazo
            or pd.isna(metrica.get("calibracao_inicio"))
            or pd.isna(metrica.get("calibracao_fim"))
        ):
            continue
        nome = metrica["modelo"]
        operacional = metrica.get("modelo_operacional", nome)
        if pd.notna(operacional) and operacional != nome:
            continue
        dados = (
            vendas.loc[vendas["sku"].eq(sku)].sort_values("data").reset_index(drop=True)
        )
        if dados.empty or ("disponivel" not in dados and not permitir_proxy):
            continue
        proxy = "disponivel" not in dados
        inicio = pd.Timestamp(metrica["calibracao_inicio"])
        fim = pd.Timestamp(metrica["calibracao_fim"])
        if pd.notna(metrica.get("teste_inicio")):
            fim = min(fim, pd.Timestamp(metrica["teste_inicio"]) - pd.Timedelta(days=1))
        atual = inicio
        while atual + pd.Timedelta(days=int(prazo) - 1) <= fim:
            alvo_fim = atual + pd.Timedelta(days=int(prazo) - 1)
            prefixo = dados.loc[dados["data"].lt(atual)]
            bloco = dados.loc[dados["data"].between(atual, alvo_fim)]
            if (
                len(bloco) == prazo
                and _observavel(bloco).all()
                and _pode_ajustar(prefixo, nome)
            ):
                contexto = bloco if nome == MODELO_CONTEXTO else None
                estimado = prever_com_modelo(prefixo, nome, int(prazo), contexto)
                amostras.append(
                    {
                        "sku": str(sku),
                        "origem": atual - pd.Timedelta(days=1),
                        "prazo_dias": int(prazo),
                        "erro_acumulado": float(bloco["vendas"].sum() - estimado.sum()),
                        "modelo": nome,
                        "proxy": proxy,
                        "fonte": "vendas_proxy" if proxy else "dias_disponiveis",
                        "alvo_inicio": atual,
                        "alvo_fim": alvo_fim,
                    }
                )
            atual += pd.Timedelta(days=int(prazo))
    return pd.DataFrame(amostras, columns=colunas)
