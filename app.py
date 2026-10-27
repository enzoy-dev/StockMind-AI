"""StockMind-AI: comparação simples de previsões de sete dias para um produto."""

import math
from pathlib import Path

import pandas as pd
import streamlit as st
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error


MODELOS = (
    "Última venda",
    "Semana anterior",
    "Regressão linear",
    "Regressão com dia da semana",
)


def carregar_vendas(arquivo):
    """Lê um CSV diário sem preencher lacunas nem somar duplicatas em silêncio."""
    dados = pd.read_csv(arquivo)
    if set(dados.columns) != {"data", "vendas"}:
        raise ValueError(
            "O CSV deve ter somente as colunas data e vendas, de um único produto."
        )
    if len(dados) < 30:
        raise ValueError("Informe pelo menos 30 dias de vendas.")

    datas = dados["data"].astype(str)
    if not datas.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise ValueError("Use datas no formato YYYY-MM-DD, sem horário.")
    dados["data"] = pd.to_datetime(datas, format="%Y-%m-%d", errors="coerce")
    if dados["data"].isna().any():
        raise ValueError("Há uma data inválida no arquivo.")
    if dados["data"].duplicated().any():
        raise ValueError("Use apenas uma linha por dia, para um único produto.")

    dados["vendas"] = pd.to_numeric(dados["vendas"], errors="coerce")
    vendas = dados["vendas"]
    if (
        vendas.isna().any()
        or not vendas.map(math.isfinite).all()
        or vendas.lt(0).any()
        or vendas.mod(1).ne(0).any()
    ):
        raise ValueError("Vendas devem ser unidades inteiras, não negativas e finitas.")

    dados = dados.sort_values("data").reset_index(drop=True)
    if not dados["data"].diff().iloc[1:].eq(pd.Timedelta(days=1)).all():
        raise ValueError(
            "Faltam dias no histórico. Informe zero apenas nos dias com zero vendas confirmado."
        )
    return dados


def criar_atributos(datas, inicio, incluir_semana):
    """Calendário conhecido: tendência e seis indicadores de dia da semana."""
    datas = pd.DatetimeIndex(datas)
    atributos = pd.DataFrame({"dia": (datas - inicio).days})
    if incluir_semana:
        # Segunda-feira é a referência. Indicadores evitam tratar domingo como
        # uma quantidade seis vezes maior que terça-feira.
        for dia in range(1, 7):
            atributos[f"dia_semana_{dia}"] = (datas.dayofweek == dia).astype(int)
    return atributos


def prever_com_modelo(dados, nome):
    """Prevê sete dias usando somente o histórico recebido."""
    if nome == "Última venda":
        return [float(dados["vendas"].iloc[-1])] * 7
    if nome == "Semana anterior":
        return dados["vendas"].iloc[-7:].astype(float).tolist()
    if nome not in MODELOS:
        raise ValueError("Modelo desconhecido.")

    inicio = dados["data"].iloc[0]
    futuro = pd.date_range(dados["data"].iloc[-1] + pd.Timedelta(days=1), periods=7)
    incluir_semana = nome == "Regressão com dia da semana"
    treino = criar_atributos(dados["data"], inicio, incluir_semana)
    atributos_futuros = criar_atributos(futuro, inicio, incluir_semana)
    modelo = LinearRegression().fit(treino, dados["vendas"])
    return modelo.predict(atributos_futuros).clip(min=0).tolist()


def prever_vendas(dados):
    """Seleciona na validação, avalia no teste e reajusta para a previsão futura."""
    comparacao = []
    escolhido = None
    menor_erro = math.inf
    for nome in MODELOS:
        # Validação: penúltima semana. A última semana não participa da escolha.
        validacao = prever_com_modelo(dados.iloc[:-14], nome)
        erro_validacao = float(
            mean_absolute_error(dados["vendas"].iloc[-14:-7], validacao)
        )
        # Teste final: reajusta apenas nos dados anteriores à última semana.
        teste = prever_com_modelo(dados.iloc[:-7], nome)
        erro_teste = float(mean_absolute_error(dados["vendas"].iloc[-7:], teste))
        comparacao.append(
            {"modelo": nome, "mae_validacao": erro_validacao, "mae_teste": erro_teste}
        )
        # Empates numéricos favorecem os métodos mais simples, listados primeiro.
        if escolhido is None or erro_validacao < menor_erro - 1e-9:
            escolhido, menor_erro = nome, erro_validacao

    avaliacao = pd.DataFrame(comparacao)
    avaliacao["selecionado"] = avaliacao["modelo"].eq(escolhido)
    # Só agora o método escolhido recebe todo o histórico para prever o futuro.
    previsao = pd.DataFrame(
        {
            "data": pd.date_range(
                dados["data"].iloc[-1] + pd.Timedelta(days=1), periods=7
            ),
            "previsao": prever_com_modelo(dados, escolhido),
        }
    )
    return previsao, avaliacao


def main():
    st.set_page_config(page_title="StockMind-AI", layout="centered")
    st.title("StockMind-AI")
    st.write("Uma previsão simples de vendas para os próximos sete dias.")

    origem = st.radio("Histórico", ["Exemplo fictício", "Enviar CSV"], horizontal=True)
    if origem == "Exemplo fictício":
        st.info("Exemplo de um único produto, com 60 dias inventados para estudo.")
        arquivo = Path(__file__).with_name("vendas_exemplo.csv")
    else:
        st.caption(
            "CSV de um único produto: data (YYYY-MM-DD) e vendas (unidades). Mínimo de 30 dias consecutivos."
        )
        arquivo = st.file_uploader("Histórico diário", type="csv")
        if arquivo is None:
            st.stop()

    try:
        dados = carregar_vendas(arquivo)
    except (ValueError, UnicodeError) as erro:
        st.error(str(erro))
        st.stop()

    previsao, avaliacao = prever_vendas(dados)
    escolhido = avaliacao.loc[avaliacao["selecionado"], "modelo"].iloc[0]
    st.caption(
        f"Último dia do histórico: {dados['data'].iloc[-1]:%d/%m/%Y}. "
        "A previsão começa no dia seguinte a essa data."
    )
    st.info(
        f"Método usado na previsão: {escolhido}. Escolhido pelo menor erro de validação."
    )
    historico = dados.set_index("data")["vendas"].rename("Vendas registradas")
    futuro = previsao.set_index("data")["previsao"].rename("Previsão")
    st.line_chart(pd.concat([historico, futuro], axis=1))
    st.subheader("Previsão por dia")
    st.dataframe(
        previsao.assign(data=previsao["data"].dt.strftime("%d/%m/%Y")).rename(
            columns={"data": "Data", "previsao": "Unidades previstas"}
        ),
        hide_index=True,
    )

    st.subheader("Comparação no histórico")
    st.dataframe(
        avaliacao.rename(
            columns={
                "modelo": "Método",
                "mae_validacao": "MAE validação (unidades/dia)",
                "mae_teste": "MAE teste (unidades/dia)",
                "selecionado": "Usado na previsão",
            }
        ),
        hide_index=True,
    )
    st.caption(
        f"Validação: {dados['data'].iloc[-14]:%d/%m/%Y} a {dados['data'].iloc[-8]:%d/%m/%Y}. "
        f"Teste: {dados['data'].iloc[-7]:%d/%m/%Y} a {dados['data'].iloc[-1]:%d/%m/%Y}. "
        "Cada previsão histórica usa somente dados anteriores à sua semana. "
        "MAE é o erro absoluto médio: menor é melhor, não é porcentagem de acerto."
    )
    with st.expander("Como os métodos são comparados?"):
        st.write(
            "Última venda: repete o último valor conhecido. Semana anterior: repete "
            "as vendas do mesmo dia da semana passada. Regressão linear: aprende "
            "uma tendência. Regressão com dia da semana: aprende a tendência e "
            "diferenças entre os dias da semana."
        )
        st.write(
            "A penúltima semana escolhe o método, com preferência pelo mais simples "
            "em caso de empate. A última semana mede o erro depois dessa escolha; "
            "ela não troca o vencedor. O escolhido é reajustado com todo o histórico "
            "para prever os próximos sete dias. Uma referência simples também pode vencer."
        )
    st.write(
        "Uma semana de validação e uma de teste são uma avaliação inicial. "
        "Os métodos não consideram promoções, preços, feriados ou falta de estoque. "
        "As previsões podem ter casas decimais e não são garantia de vendas."
    )


if __name__ == "__main__":
    main()
