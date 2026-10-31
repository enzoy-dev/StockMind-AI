import pandas as pd
import streamlit as st
from .components import tabela, baixar


def mostrar_cenarios(resultado):
    st.subheader("Como uma demanda diferente muda a reposição?")
    st.caption(
        f"Análise de sensibilidade escolhida por você: demanda menor/base/maior em {resultado['variacao_cenario_pct']:g}%. As trajetórias não têm probabilidade atribuída e não são os limites estatísticos de 90% do modelo."
    )
    if not resultado["cenarios"]:
        st.info("Ative o planejamento de estoque para comparar cenários.")
    else:
        resumo_cenarios = pd.DataFrame(resultado["cenarios"])
        sku_cenario = st.selectbox(
            "Produto nos cenários", sorted(resumo_cenarios["sku"].unique())
        )
        tabela(
            resumo_cenarios.loc[resumo_cenarios["sku"].eq(sku_cenario)],
            [
                "cenario",
                "data_compra_sugerida",
                "quantidade_compra_na_data",
                "compra_sugerida",
                "primeira_falta",
                "dias_ate_falta",
                "unidades_acima_alvo_30dias",
                "prioridade",
                "status_agendamento",
            ],
        )
        trajetorias = pd.DataFrame(resultado["saldos_cenarios"])
        if not trajetorias.empty:
            trajetorias = trajetorias.loc[trajetorias["sku"].eq(sku_cenario)].copy()
        if not trajetorias.empty:
            trajetorias["data"] = pd.to_datetime(trajetorias["data"])
            st.line_chart(
                trajetorias.pivot(
                    index="data", columns="cenario", values="saldo_estimado"
                )
            )
        else:
            st.info("Sem histórico para projetar saldo deste produto.")
        st.write(
            "Estoque, pedidos abertos, preços, segurança, mínimos e lotes são mantidos. Só as vendas previstas mudam; os modelos não são treinados novamente e nenhuma compra é realizada."
        )
        baixar(
            "Baixar recomendações dos cenários",
            resultado["cenarios"],
            "cenarios.csv",
        )
        baixar(
            "Baixar saldos dos cenários",
            resultado["saldos_cenarios"],
            "saldos_cenarios.csv",
        )
