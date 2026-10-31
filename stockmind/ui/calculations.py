import streamlit as st
from stockmind.service import executar_analise


@st.cache_data(max_entries=4, ttl=300, show_spinner="Avaliando métodos por produto…")
def calcular(
    vendas,
    horizonte,
    contexto,
    produtos,
    fornecedores,
    pedidos,
    revisao,
    comparar=False,
    variacao=20.0,
    avancado=None,
):
    return executar_analise(
        vendas,
        horizonte,
        contexto,
        produtos,
        fornecedores,
        pedidos,
        revisao,
        comparar_horizontes=comparar,
        variacao_cenario_pct=variacao,
        **(avancado or {}),
    )
