import pandas as pd
import streamlit as st
from stockmind.data import (
    DataError,
)
from stockmind.monitoring import monitorar_desempenho
from .components import ler_arquivo, tabela, baixar


def historico(store, vendas):
    st.subheader("Previsões salvas e vendas observadas depois")
    st.caption(
        "As previsões salvas são snapshots imutáveis. Atualizar vendas reais não reescreve o que foi previsto."
    )
    if st.button("Registrar este histórico como vendas realizadas"):
        count = store.save_actuals(vendas)
        st.success(
            f"{count} registros de vendas atualizados. Dias ausentes não são tratados como zero."
        )
    atualizacoes = st.file_uploader(
        "Atualizar vendas realizadas CSV (pode conter dias avulsos)",
        type="csv",
        key="vendas_reais",
    )
    if atualizacoes is not None and st.button("Registrar CSV de vendas realizadas"):
        try:
            count = store.save_actuals(ler_arquivo(atualizacoes))
            st.success(f"{count} registros atualizados.")
        except (ValueError, DataError) as erro:
            st.error(str(erro))
    estoques = st.file_uploader(
        "Snapshots reais de estoque CSV (sku,data,estoque_real)",
        type="csv",
        key="stock_actuals",
    )
    if estoques is not None and st.button("Registrar snapshots de estoque"):
        try:
            count = store.save_stock_actuals(ler_arquivo(estoques))
            st.success(
                f"{count} snapshots registrados; projeções originais preservadas."
            )
        except ValueError as error:
            st.error(str(error))
    runs = store.list_runs()
    if not runs:
        st.info(
            "Salve uma análise para acompanhar as previsões quando novas vendas estiverem disponíveis."
        )
        return
    with st.expander("Monitorar o desempenho recente"):
        st.caption(
            "Usa previsões gravadas antes do dia previsto, com realizações observadas. Dias censurados e previsões retrospectivas são excluídos; amostras pequenas não geram diagnóstico de piora."
        )
        h_monitor = st.selectbox("Horizonte para monitorar", [7, 14, 30, 90])
        if st.button("Verificar desempenho recente"):
            desempenho = monitorar_desempenho(store, horizonte=h_monitor)
            if desempenho.empty:
                st.info(
                    "Ainda não há previsões e realizações elegíveis para monitorar."
                )
            else:
                tabela(desempenho)
    labels = {
        run[
            "id"
        ]: f"{pd.to_datetime(run['criado_em'], utc=True).tz_convert('America/Sao_Paulo'):%d/%m/%Y %H:%M} (Brasília) · origem {run['origem']} · {run['horizonte']} dias"
        for run in runs
    }
    selected = st.selectbox("Análise salva", list(labels), format_func=labels.get)
    comparison = store.compare_run(selected)
    st.dataframe(pd.DataFrame(comparison["resumo"]), hide_index=True)
    st.dataframe(pd.DataFrame(comparison["comparacoes"]), hide_index=True)
    baixar(
        "Baixar comparação com vendas reais",
        comparison["comparacoes"],
        "comparacao_real.csv",
    )
    snapshot = store.get_run(selected)
    with st.expander("Entrada e resultado originais desta análise"):
        st.json(snapshot)

    with st.expander("Comparar estoque projetado e registrado"):
        stock = store.compare_stock_run(selected)
        st.caption(stock["premissa"])
        tabela(pd.DataFrame(stock["resumo"]))
        tabela(pd.DataFrame(stock["comparacoes"]))
        baixar(
            "Baixar comparação de estoque",
            stock["comparacoes"],
            "comparacao_estoque.csv",
        )
