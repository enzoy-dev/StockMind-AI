import pandas as pd
import streamlit as st
from .components import baixar


def mostrar_qualidade(resultado):
    st.subheader("Relatório de importação")
    if resultado["qualidade"]:
        st.dataframe(pd.DataFrame(resultado["qualidade"]), hide_index=True)
    else:
        st.success(
            "Nenhum problema de contrato identificado. Isso não comprova a qualidade dos dados de origem."
        )
    st.write(
        "Dias ausentes e duplicatas bloqueiam a análise. Históricos curtos recebem aviso e um método inicial. Produtos sem histórico não recebem previsão de zero. Contexto futuro deve ser conhecido no momento da previsão; não use informações que só seriam observadas depois."
    )
    baixar("Baixar relatório de qualidade", resultado["qualidade"], "qualidade.csv")
