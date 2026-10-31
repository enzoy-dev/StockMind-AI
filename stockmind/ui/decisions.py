import pandas as pd
import streamlit as st
from stockmind.data import (
    validar_planejamento,
)
from .components import tabela, baixar, precisam_revisao


def mostrar_decisoes(resultado, vendas, produtos, fornecedores, pedidos, store):
    saldos = pd.DataFrame(resultado["saldos"])
    recomendacoes = pd.DataFrame(resultado["recomendacoes"])
    if recomendacoes.empty:
        st.info(
            "Ative o planejamento de estoque para informar produtos e fornecedores."
        )
    else:
        st.subheader("Prioridades para revisão")
        st.caption(
            f"Datas e prioridades referem-se ao fechamento de {resultado['origem']}. Sem cruzamento do limite no período previsto, não se afirma que o estoque durará indefinidamente."
        )
        filtro = st.text_input("Buscar por SKU ou nome")
        problemas = st.checkbox("Mostrar somente itens que precisam de revisão")
        grupo = st.radio(
            "Decisão a revisar",
            [
                "Todas",
                "Falta ou prazo vencido",
                "Compras futuras",
                "Excesso",
                "Dados insuficientes",
            ],
            horizontal=True,
        )
        view = recomendacoes.copy()
        classes = pd.DataFrame(resultado["classificacao_produtos"])
        if not classes.empty:
            view = view.merge(
                classes[["sku", "classe_abc", "classe_xyz"]], on="sku", how="left"
            )
        if filtro:
            view = view.loc[
                view["sku"].str.contains(filtro, case=False, regex=False)
                | view["nome"].str.contains(filtro, case=False, regex=False)
            ]
        if problemas:
            view = view.loc[precisam_revisao(view)]
        if grupo == "Falta ou prazo vencido":
            view = view.loc[
                view["primeira_falta"].notna() | view["prazo_compra_vencido"].eq(True)
            ]
        elif grupo == "Compras futuras":
            view = view.loc[
                view["data_compra_sugerida"].fillna("").gt(resultado["origem"])
            ]
        elif grupo == "Excesso":
            view = view.loc[view["excesso"].eq(True)]
        elif grupo == "Dados insuficientes":
            view = view.loc[
                view["status"].isin(["sem_previsao", "horizonte_insuficiente"])
                | view["status_previsao"].eq("historico_curto")
                | view["status_agendamento"].eq("horizonte_insuficiente")
            ]
        if "prioridade_ordem" in view:
            view = view.sort_values(
                ["prioridade_ordem", "dias_ate_falta", "sku"], na_position="last"
            )
        provisorios = view.loc[
            view["status_previsao"].isin(["historico_curto", "avaliacao_parcial"]),
            "sku",
        ].tolist()
        if provisorios:
            st.warning(
                "Sugestões com histórico curto ou demanda parcialmente observável: "
                + ", ".join(provisorios)
            )
        colunas_decisao = [
            "sku",
            "nome",
            "prioridade",
            "data_compra_sugerida",
            "quantidade_compra_na_data",
            "dias_ate_falta",
            "unidades_acima_alvo_30dias",
            "motivos_alerta",
        ]
        if grupo == "Excesso":
            colunas_decisao = [
                "sku",
                "nome",
                "prioridade",
                "classe_abc",
                "classe_xyz",
                "estoque_atual",
                "unidades_acima_alvo_30dias",
                "excesso",
                "motivos_alerta",
            ]
        elif grupo == "Dados insuficientes":
            colunas_decisao = [
                "sku",
                "nome",
                "prioridade",
                "status_previsao",
                "status_agendamento",
                "horizonte_necessario_agendamento",
                "motivos_alerta",
            ]
        tabela(view, colunas_decisao)
        st.warning(
            "Sugestões exigem revisão humana. A data-limite pode já ter passado: uma compra feita na referência não evita faltas anteriores à entrega. Saldo negativo é déficit estimado. Compras sugeridas não entram como recebimentos. Sem cobertura da janela de compra futura, a quantidade fica indefinida."
        )
        with st.expander("Cálculos de reposição e pedidos na janela"):
            st.write(
                "A data-limite deriva do primeiro saldo abaixo da segurança, descontando o prazo do fornecedor. O agendamento considera compra ao fechar o dia e prazo efetivo de pelo menos um dia. A quantidade cobre o maior déficit em relação à segurança após a entrega, na janela de proteção, aplicando mínimo e lote. Compras futuras usam uma janela deslocada; compra_sugerida representa comprar na data-base. Excesso compara posição com previsão de 30 dias + segurança."
            )
            tabela(recomendacoes)
        with st.expander("Classificação, segurança e prazos utilizados"):
            st.write(
                "ABC descreve o faturamento registrado, ou unidades quando faltam preços. XYZ exige dias confirmados disponíveis. As categorias não alteram a política automaticamente."
            )
            tabela(pd.DataFrame(resultado["classificacao_produtos"]))
            st.write(
                "Segurança pelo quantil dos erros acumulados no prazo de reposição, em blocos de calibração sem sobreposição. Sem amostras suficientes, mantém-se o cadastro manual."
            )
            tabela(pd.DataFrame(resultado["seguranca_estoque"]))
            st.write(
                "O prazo sugerido usa o percentil empírico das entregas históricas, sem garantia de prazo futuro. Estimativas fora dos limites ou com poucas amostras não são aplicadas."
            )
            tabela(pd.DataFrame(resultado["prazos_fornecedores"]))
            baixar(
                "Baixar erros de calibração da reposição",
                resultado["residuos_reposicao"],
                "residuos_reposicao.csv",
            )
        if not saldos.empty:
            product_stock = st.selectbox(
                "Produto para saldo diário", sorted(saldos["sku"].unique())
            )
            daily = saldos.loc[saldos["sku"].eq(product_stock)].copy()
            daily["data"] = pd.to_datetime(daily["data"])
            st.line_chart(daily.set_index("data")["saldo_estimado"])
            tabela(daily)
        if st.button("Salvar cadastros e estoque desta data"):
            p, f, o = validar_planejamento(
                produtos,
                fornecedores,
                pedidos,
                vendas["sku"].unique(),
                vendas["data"].max(),
            )
            store.save_planning(p, f, o, origem=resultado["origem"])
            st.success("Cadastros e data do estoque salvos.")
        baixar(
            "Baixar sugestões de reposição",
            resultado["recomendacoes"],
            "reposicao.csv",
        )
        baixar("Baixar saldo projetado", resultado["saldos"], "saldos.csv")
        baixar(
            "Baixar classificação ABC/XYZ",
            resultado["classificacao_produtos"],
            "classificacao.csv",
        )
        baixar(
            "Baixar segurança e amostras",
            resultado["seguranca_estoque"],
            "seguranca.csv",
        )
        baixar(
            "Baixar análise dos fornecedores",
            resultado["prazos_fornecedores"],
            "prazos.csv",
        )
