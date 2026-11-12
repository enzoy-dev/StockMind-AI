import pandas as pd
import streamlit as st
from .components import tabela, baixar


def parametros_orcamento(produtos):
    if not st.checkbox("Planejar compras com orçamento limitado", value=False):
        return {}
    st.caption(
        "Informe custos na mesma moeda do orçamento. Reserva por prioridade, sem frete/tributos e sem garantia de melhor combinação. Custo ausente não vira zero."
    )
    amount = st.text_input("Orçamento disponível (decimal com ponto)", value="1000.00")
    edited = st.data_editor(
        pd.DataFrame(
            {"sku": produtos.sku.tolist(), "custo_unitario": [""] * len(produtos)}
        ),
        disabled=["sku"],
        hide_index=True,
        key="custos_compra",
    )
    costs = {
        r["sku"]: str(r["custo_unitario"]).strip()
        for r in edited.to_dict("records")
        if pd.notna(r["custo_unitario"]) and str(r["custo_unitario"]).strip()
    }
    return {"orcamento_compras": amount, "custos_unitarios": costs}


def mostrar_compras(resultado):
    if resultado.get("diagnosticos_decisao"):
        with st.expander("Qualidade dos dados para decidir compras"):
            st.caption(
                "Avaliada não é garantia de acerto. Sugestões provisórias precisam de revisão; sem trajetória ou cobertura suficiente não há quantidade definida."
            )
            tabela(pd.DataFrame(resultado["diagnosticos_decisao"]))
    if resultado.get("memoria_compras"):
        with st.expander("Por que comprar esta quantidade nesta data?"):
            rows = pd.DataFrame(resultado["memoria_compras"])
            sku = st.selectbox(
                "Produto da memória de cálculo", sorted(rows.sku.unique())
            )
            tabela(rows.loc[rows.sku.eq(sku)])
            st.caption(
                "O saldo já inclui os recebimentos nas datas corretas. Não some os pedidos novamente. A compra agendada e a compra na origem podem ter quantidades diferentes."
            )
            baixar(
                "Baixar memória de cálculo",
                resultado["memoria_compras"],
                "memoria_compras.csv",
            )
    if resultado.get("resumo_orcamento") is not None:
        st.subheader("Reserva do orçamento de compras")
        summary = resultado["resumo_orcamento"]
        cards = st.columns(3)
        cards[0].metric("Orçamento informado", summary["orcamento"])
        cards[1].metric("Valor reservado", summary["reservado"])
        cards[2].metric("Orçamento restante", summary["restante"])
        st.caption(summary["metodo"])
        st.caption(summary["escopo"])
        tabela(pd.DataFrame(resultado["plano_orcamento"]))
        st.warning(
            "A reserva não altera a sugestão original, não recalcula uma política de estoque e não envia pedidos. Compras parciais e dados provisórios exigem revisão humana."
        )
        baixar(
            "Baixar plano de orçamento", resultado["plano_orcamento"], "orcamento.csv"
        )
