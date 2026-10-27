"""StockMind-AI: um produto, um modelo simples e previsão de sete dias."""

import math
from pathlib import Path

import pandas as pd
import streamlit as st
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error


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


def prever_vendas(dados):
    """Avalia no passado, depois reajusta com todo o histórico para prever."""
    dias = pd.DataFrame({"dia": range(len(dados))})
    vendas = dados["vendas"]
    modelo = LinearRegression()

    # Últimos sete dias ficam fora do treinamento nesta avaliação.
    modelo.fit(dias.iloc[:-7], vendas.iloc[:-7])
    estimativa_teste = modelo.predict(dias.iloc[-7:]).clip(min=0)
    erro_modelo = float(mean_absolute_error(vendas.iloc[-7:], estimativa_teste))

    # Referência: prever sempre o último valor conhecido antes da semana de teste.
    referencia = [vendas.iloc[-8]] * 7
    erro_referencia = float(mean_absolute_error(vendas.iloc[-7:], referencia))

    # Agora usa todo o histórico disponível para prever os próximos sete dias.
    modelo.fit(dias, vendas)
    dias_futuros = pd.DataFrame({"dia": range(len(dados), len(dados) + 7)})
    previsao = pd.DataFrame(
        {
            "data": pd.date_range(
                dados["data"].iloc[-1] + pd.Timedelta(days=1), periods=7
            ),
            "previsao": modelo.predict(dias_futuros).clip(min=0),
        }
    )
    return previsao, erro_modelo, erro_referencia


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

    previsao, erro, erro_referencia = prever_vendas(dados)
    st.caption(
        f"Último dia do histórico: {dados['data'].iloc[-1]:%d/%m/%Y}. "
        "A previsão começa no dia seguinte a essa data."
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

    st.subheader("Como foi o teste no histórico?")
    esquerda, direita = st.columns(2)
    esquerda.metric("Erro médio do modelo", f"{erro:.2f} unidades/dia")
    direita.metric("Erro médio da referência", f"{erro_referencia:.2f} unidades/dia")
    st.caption(
        "Teste nos últimos sete dias, treinando somente nos dias anteriores. "
        "A referência repete a última venda conhecida. Menor erro é melhor; "
        "o modelo pode perder para essa referência. Isso não é uma porcentagem de acerto."
    )
    st.write(
        "O modelo é uma regressão linear: aprende apenas uma tendência ao longo do tempo. "
        "Não considera promoções, preços, dias da semana ou falta de estoque. "
        "As previsões podem ter casas decimais e não são garantia de vendas."
    )


if __name__ == "__main__":
    main()
