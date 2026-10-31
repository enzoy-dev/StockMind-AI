import pandas as pd
import streamlit as st
from stockmind.data import (
    PRODUCT_COLUMNS,
    SUPPLIER_COLUMNS,
    ORDER_COLUMNS,
)
from .components import EXAMPLES, LABELS, ler_csv, ler_arquivo


def cadastros(vendas, origem, store, exemplo):
    """Editores de cadastro, importação de CSV ou reutilização de snapshot salvo."""
    if not st.checkbox(
        "Planejar estoque e reposição", value=exemplo, key=f"estoque_{origem}"
    ):
        return None, None, None
    with st.expander("Produtos, fornecedores e pedidos em trânsito", expanded=False):
        forma = st.radio(
            "Cadastros",
            ["Editar na tela", "Carregar CSVs", "Cadastro salvo"],
            horizontal=True,
            key=f"cadastro_{origem}",
        )
        if forma == "Carregar CSVs":
            produtos = st.file_uploader("Produtos CSV", type="csv")
            fornecedores = st.file_uploader("Fornecedores CSV", type="csv")
            pedidos = st.file_uploader("Pedidos abertos CSV (opcional)", type="csv")
            if produtos is None or fornecedores is None:
                st.info("Envie os produtos e fornecedores para calcular estoque.")
                st.stop()
            return (
                ler_arquivo(produtos),
                ler_arquivo(fornecedores),
                ler_arquivo(pedidos)
                if pedidos
                else pd.DataFrame(columns=ORDER_COLUMNS),
            )
        if forma == "Cadastro salvo":
            saved = store.get_planning()
            if not saved["produtos"]:
                st.info("Nenhum cadastro salvo. Edite ou importe os dados primeiro.")
                st.stop()
            date = vendas["data"].max().date().isoformat()
            if saved.get("origem") != date:
                st.error(
                    f"O estoque salvo é de {saved.get('origem') or 'data desconhecida'}, mas o histórico termina em {date}. Atualize o cadastro antes de reutilizá-lo."
                )
                st.stop()
            st.caption(f"Estoque salvo na data de referência {date}.")
            return (
                pd.DataFrame(saved["produtos"]),
                pd.DataFrame(saved["fornecedores"]),
                pd.DataFrame(saved["pedidos"], columns=ORDER_COLUMNS),
            )
        if exemplo:
            produtos = ler_csv(EXAMPLES / "produtos_exemplo.csv")
            fornecedores = ler_csv(EXAMPLES / "fornecedores_exemplo.csv")
            pedidos = ler_csv(EXAMPLES / "pedidos_exemplo.csv")
        else:
            produtos = pd.DataFrame(
                [[sku, sku, "FOR-01", 0, 0, 1, 1] for sku in vendas["sku"].unique()],
                columns=PRODUCT_COLUMNS,
            )
            fornecedores = pd.DataFrame(
                [["FOR-01", "Meu fornecedor", 3]], columns=SUPPLIER_COLUMNS
            )
            pedidos = pd.DataFrame(columns=ORDER_COLUMNS)
        st.caption(
            "Estoque disponível e pedidos referem-se ao fechamento do último dia do histórico. Recebimentos ocorrem antes das vendas do dia."
        )
        st.write("Produtos e estoque")
        produtos = st.data_editor(
            produtos,
            num_rows="dynamic",
            hide_index=True,
            key=f"produtos_{origem}",
            column_config={campo: LABELS.get(campo, campo) for campo in produtos},
        )
        st.write("Fornecedores: prazo em dias corridos")
        fornecedores = st.data_editor(
            fornecedores,
            num_rows="dynamic",
            hide_index=True,
            key=f"fornecedores_{origem}",
            column_config={campo: LABELS.get(campo, campo) for campo in fornecedores},
        )
        st.write(
            "Pedidos já abertos: a compra sugerida não entra nesta tabela automaticamente"
        )
        pedidos = st.data_editor(
            pedidos,
            num_rows="dynamic",
            hide_index=True,
            key=f"pedidos_{origem}",
            column_config={campo: LABELS.get(campo, campo) for campo in pedidos},
        )
        return produtos, fornecedores, pedidos
