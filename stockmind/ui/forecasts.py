import pandas as pd
import streamlit as st
from .components import SITUATIONS, tabela, baixar, grafico_previsao


def mostrar_previsoes(vendas, previsoes, metricas, resultado):
    sku = st.selectbox("Produto", sorted(metricas["sku"].unique()))
    selected = previsoes.loc[previsoes["sku"].eq(sku)]
    if selected.empty:
        st.warning(
            "Não há demanda observável suficiente para gerar previsão deste produto. Vendas em dias de indisponibilidade não são tratadas como demanda zero."
        )
        tabela(metricas.loc[metricas["sku"].eq(sku)])
        baixar(
            "Baixar diagnóstico de demanda",
            metricas.loc[metricas["sku"].eq(sku)].to_dict("records"),
            "diagnostico_demanda.csv",
        )
        return
    st.info(
        f"Método: {selected['modelo'].iloc[0]}. {SITUATIONS.get(selected['status'].iloc[0], selected['status'].iloc[0])}"
    )
    if selected["status"].iloc[0] in ("historico_curto", "avaliacao_parcial"):
        st.warning(
            "Histórico curto ou demanda parcialmente observável. Confira as amostras avaliadas e revise as sugestões de compra deste produto."
        )
    if "observacao" in selected and selected["observacao"].iloc[0]:
        st.caption(selected["observacao"].iloc[0])
    grafico_previsao(vendas, previsoes, sku)
    tabela(selected, ["data", "previsao", "limite_inferior", "limite_superior"])
    st.subheader("Comparação temporal dos métodos")
    tabela(
        metricas.loc[metricas["sku"].eq(sku)],
        [
            "modelo",
            "mae_validacao",
            "mae_teste",
            "wape_teste",
            "vies_teste",
            "janelas_validacao",
            "janelas_vencidas",
            "mae_validacao_desvio",
            "selecionado",
            "cobertura_teste",
            "status",
        ],
    )
    st.caption(
        "MAE em unidades/dia; WAPE em %. Viés positivo indica previsão acima do realizado. A escolha usa apenas janelas anteriores ao teste final. Faixas de 90% são empíricas, calibradas em período separado; a cobertura observada não garante cobertura futura. Sem dados suficientes, a faixa fica vazia."
    )
    st.caption(
        "Vitórias e dispersão nas janelas descrevem estabilidade histórica; não garantem ganho futuro. Empates contam como vitória para todos os métodos empatados."
    )
    with st.expander("Períodos de avaliação e detalhes por método"):
        tabela(metricas.loc[metricas["sku"].eq(sku)])
    with st.expander("Produtos com maiores erros no teste"):
        ranking = metricas.loc[metricas["selecionado"]].sort_values(
            "mae_teste", ascending=False, na_position="last"
        )
        tabela(
            ranking,
            ["sku", "modelo", "mae_teste", "wape_teste", "vies_teste", "status"],
        )
    if resultado["comparacao_horizontes"]:
        st.subheader("Qual método funciona melhor em cada horizonte?")
        comparacao = pd.DataFrame(resultado["comparacao_horizontes"])
        tabela(
            comparacao.loc[comparacao["sku"].eq(sku)],
            [
                "horizonte",
                "modelo",
                "mae_validacao",
                "mae_teste",
                "mae_teste_semana_anterior",
                "ganho_mae_teste_pct",
                "wape_teste",
                "janelas_validacao",
                "status",
            ],
        )
        st.caption(
            "Redução positiva do MAE indica erro menor que repetir a semana anterior; negativa indica erro maior. O teste não escolhe o método. Os períodos de teste diferem entre horizontes; não interprete a tabela como comparação de precisão em datas idênticas."
        )
        baixar(
            "Baixar comparação de horizontes",
            resultado["comparacao_horizontes"],
            "comparacao_horizontes.csv",
        )
    baixar("Baixar todas as previsões", resultado["previsoes"], "previsoes.csv")
    baixar("Baixar métricas por produto", resultado["metricas"], "metricas.csv")
