import pandas as pd
import streamlit as st
from .components import tabela, baixar


def mostrar_avaliacao(resultado):
    st.subheader("Como as políticas se comportam no histórico?")
    if not resultado["avaliacao_reposicao"]:
        st.info(
            "Ative Avaliar políticas de reposição no histórico nas opções de planejamento."
        )
    else:
        st.caption(
            "Cenário retrospectivo com parâmetros manuais fixos, mesmos custos e estoque inicial para todas as políticas. Estimativas automáticas desta análise não são usadas no replay. Vendas censuradas bloqueiam a avaliação."
        )
        tabela(pd.DataFrame(resultado["avaliacao_reposicao"]))
        st.write(
            f"Período: {resultado['periodo_simulacao']} dias. Custos assumidos: {resultado['custos_simulacao']}. Valores são custos de cenário, sem evidência de economia ou ROI comercial."
        )
        with st.expander("Diário de estoque, atendimento e pedidos simulados"):
            tabela(pd.DataFrame(resultado["diario_reposicao"]))
        baixar(
            "Baixar avaliação das políticas",
            resultado["avaliacao_reposicao"],
            "avaliacao_reposicao.csv",
        )
        baixar(
            "Baixar diário da simulação",
            resultado["diario_reposicao"],
            "diario_reposicao.csv",
        )

    if resultado.get("avaliacao_multiperiodo"):
        st.subheader("Consistência em períodos históricos separados")
        st.caption(
            "Janelas sem sobreposição, com estoque inicial e custos do cenário reiniciados em cada período. Não é uma trajetória contínua."
        )
        tabela(pd.DataFrame(resultado["consistencia_politicas"]))
        tabela(pd.DataFrame(resultado["avaliacao_multiperiodo"]))
        baixar(
            "Baixar avaliação em vários períodos",
            resultado["avaliacao_multiperiodo"],
            "multiperiodo.csv",
        )
        baixar(
            "Baixar diário dos períodos",
            resultado["diario_multiperiodo"],
            "diario_multiperiodo.csv",
        )

    if resultado.get("avaliacao_estresse"):
        st.subheader("Políticas sob atrasos e mudanças de demanda")
        st.caption(
            "Base, prazo ampliado, demanda maior/menor e combinado. Estoque reinicia por janela; premissas conhecidas e custos assumidos, sem ROI comprovado. Não altera a recomendação operacional."
        )
        tabela(pd.DataFrame(resultado["avaliacao_estresse"]))
        baixar(
            "Baixar avaliação de estresse",
            resultado["avaliacao_estresse"],
            "estresse.csv",
        )
        baixar(
            "Baixar diário de estresse",
            resultado["diario_estresse"],
            "diario_estresse.csv",
        )
