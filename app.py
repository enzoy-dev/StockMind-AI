"""Dashboard local: previsões, estoque, qualidade e acompanhamento de resultados."""

from pathlib import Path
import os

import altair as alt
import pandas as pd
import streamlit as st

from stockmind.data import (
    DataError,
    ler_csv,
    validar_vendas,
    validar_contexto_futuro,
    validar_planejamento,
    PRODUCT_COLUMNS,
    SUPPLIER_COLUMNS,
    ORDER_COLUMNS,
)
from stockmind.service import executar_analise
from stockmind.storage import Store

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "data"
LABELS = {
    "sku": "Produto",
    "nome": "Nome",
    "data": "Data",
    "modelo": "Método",
    "previsao": "Vendas previstas",
    "limite_inferior": "Faixa inferior",
    "limite_superior": "Faixa superior",
    "mae_validacao": "MAE validação",
    "mae_teste": "MAE teste",
    "wape_teste": "WAPE teste (%)",
    "vies_teste": "Viés teste (unid./dia)",
    "janelas_validacao": "Janelas de validação",
    "selecionado": "Selecionado",
    "cobertura_teste": "Cobertura teste (%)",
    "estoque_atual": "Disponível",
    "compra_sugerida": "Compra sugerida",
    "estoque_alvo": "Estoque-alvo",
    "primeira_falta": "Primeira falta estimada",
    "prazo_dias": "Prazo (dias)",
    "em_transito": "Em trânsito na janela",
    "excesso": "Possível excesso (30 dias)",
    "saldo_estimado": "Saldo estimado",
    "recebimentos": "Recebimentos",
    "risco_falta": "Déficit projetado",
    "risco_antes_reposicao": "Falta antes de nova entrega",
    "fornecedor_id": "Fornecedor",
    "horizonte_necessario": "Horizonte necessário",
    "status": "Situação",
    "quantidade": "Quantidade",
    "data_entrega": "Entrega",
    "status_previsao": "Situação da previsão",
    "estoque_seguranca": "Segurança (unidades)",
    "pedido_minimo": "Mínimo de compra",
    "multiplo_compra": "Múltiplo de compra",
    "pedido_id": "Pedido",
}
SITUATIONS = {
    "revisar_compra": "Revisar compra",
    "acompanhar": "Acompanhar",
    "horizonte_insuficiente": "Aumente o horizonte",
    "sem_previsao": "Sem histórico de vendas",
    "historico_curto": "Histórico curto: estimativa inicial",
    "avaliado": "Avaliado no histórico",
}


def ler_arquivo(source):
    if hasattr(source, "seek"):
        source.seek(0)
    return ler_csv(source)


def tabela(frame, columns=None):
    view = frame.copy()
    if columns:
        view = view[[column for column in columns if column in view]]
    for campo in ("status", "status_previsao"):
        if campo in view:
            view[campo] = view[campo].map(lambda v: SITUATIONS.get(v, v))
    st.dataframe(view.rename(columns=LABELS), hide_index=True, use_container_width=True)


def baixar(label, records, filename):
    data = pd.DataFrame(records).to_csv(index=False).encode("utf-8-sig")
    st.download_button(label, data, filename, "text/csv", key=filename)


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


@st.cache_data(max_entries=4, ttl=300, show_spinner="Avaliando métodos por produto…")
def calcular(vendas, horizonte, contexto, produtos, fornecedores, pedidos, revisao):
    return executar_analise(
        vendas, horizonte, contexto, produtos, fornecedores, pedidos, revisao
    )


def grafico_previsao(vendas, previsoes, sku):
    history = vendas.loc[vendas["sku"].eq(sku), ["data", "vendas"]].tail(90)
    history = history.rename(columns={"vendas": "unidades"}).assign(
        serie="Vendas registradas"
    )
    future = previsoes.loc[previsoes["sku"].eq(sku)].copy()
    future["data"] = pd.to_datetime(future["data"])
    points = (
        future[["data", "previsao"]]
        .rename(columns={"previsao": "unidades"})
        .assign(serie="Previsão")
    )
    lines = (
        alt.Chart(pd.concat([history, points], ignore_index=True))
        .mark_line()
        .encode(
            x=alt.X("data:T", title="Data"),
            y=alt.Y("unidades:Q", title="Unidades", scale=alt.Scale(zero=True)),
            color=alt.Color("serie:N", title="Série"),
            tooltip=["data:T", "serie:N", alt.Tooltip("unidades:Q", format=".2f")],
        )
    )
    if future["limite_inferior"].notna().any():
        band = (
            alt.Chart(future)
            .mark_area(opacity=0.15, color="#3176b4")
            .encode(
                x="data:T",
                y="limite_inferior:Q",
                y2="limite_superior:Q",
                tooltip=[
                    "data:T",
                    alt.Tooltip("limite_inferior:Q", format=".2f"),
                    alt.Tooltip("limite_superior:Q", format=".2f"),
                ],
            )
        )
        lines = band + lines
    st.altair_chart(lines.interactive(), use_container_width=True)


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
    runs = store.list_runs()
    if not runs:
        st.info(
            "Salve uma análise para acompanhar as previsões quando novas vendas estiverem disponíveis."
        )
        return
    labels = {
        run[
            "id"
        ]: f"{run['criado_em']} · origem {run['origem']} · {run['horizonte']} dias"
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


def main():
    st.set_page_config(page_title="StockMind-AI", layout="wide")
    st.title("StockMind-AI")
    st.write(
        "Previsões por produto, planejamento de estoque e acompanhamento dos resultados."
    )
    origem = st.radio(
        "Histórico",
        ["Carteira fictícia", "Exemplo de um produto", "Enviar CSV"],
        horizontal=True,
    )
    exemplo = origem == "Carteira fictícia"
    horizonte = st.selectbox(
        "Horizonte (dias)",
        [7, 14, 30, 90],
        index=2 if exemplo else 0,
        key=f"horizonte_{origem}",
    )
    st.caption(
        "A avaliação usa o mesmo horizonte escolhido. Históricos curtos geram estimativas iniciais sem métricas ou faixas inventadas."
    )
    try:
        if exemplo:
            st.info(
                "Dados fictícios: vendas regulares, esporádicas, produto recente e um produto do catálogo sem histórico."
            )
            bruto = ler_csv(EXAMPLES / "vendas_multiplos_exemplo.csv")
        elif origem == "Exemplo de um produto":
            st.info(
                "Exemplo original de um produto: CSV com data e vendas continua aceito."
            )
            bruto = ler_csv(ROOT / "vendas_exemplo.csv")
        else:
            st.caption(
                "CSV: sku, data, vendas. Campos opcionais: preco, promocao, feriado. Formato antigo data,vendas também aceito."
            )
            arquivo = st.file_uploader("Histórico diário de vendas", type="csv")
            if arquivo is None:
                st.stop()
            bruto = ler_arquivo(arquivo)
        vendas = validar_vendas(bruto)
        contexto = None
        if st.checkbox(
            "Usar preço, promoções e feriados planejados",
            value=exemplo,
            key=f"contexto_{origem}",
        ):
            if exemplo:
                contexto = ler_csv(EXAMPLES / "contexto_futuro_exemplo.csv")
            else:
                future_file = st.file_uploader("Contexto futuro CSV", type="csv")
                if future_file is None:
                    st.info(
                        "Informe o calendário planejado com sku,data,preco,promocao,feriado."
                    )
                    st.stop()
                contexto = ler_arquivo(future_file)
        store = Store(
            os.environ.get("STOCKMIND_DB", str(EXAMPLES / "stockmind.sqlite3"))
        )
        produtos, fornecedores, pedidos = cadastros(vendas, origem, store, exemplo)
        revisao = (
            int(
                st.number_input(
                    "Revisão de estoque a cada quantos dias?",
                    min_value=1,
                    max_value=30,
                    value=7,
                )
            )
            if produtos is not None
            else 7
        )
        resultado = calcular(
            vendas, horizonte, contexto, produtos, fornecedores, pedidos, revisao
        )
    except DataError as erro:
        st.error(str(erro))
        st.dataframe(erro.report, hide_index=True)
        baixar(
            "Baixar relatório de erros",
            erro.report.to_dict("records"),
            "erros_importacao.csv",
        )
        st.stop()
    except ValueError as erro:
        st.error(str(erro))
        st.stop()

    previsoes = pd.DataFrame(resultado["previsoes"])
    metricas = pd.DataFrame(resultado["metricas"])
    saldos = pd.DataFrame(resultado["saldos"])
    recomendacoes = pd.DataFrame(resultado["recomendacoes"])
    st.caption(
        f"Data de referência: {resultado['origem']}. A previsão começa no dia seguinte ao histórico."
    )
    cards = st.columns(3)
    cards[0].metric("Produtos com previsão", previsoes["sku"].nunique())
    cards[1].metric(
        "Com déficit projetado",
        int(recomendacoes["primeira_falta"].notna().sum())
        if not recomendacoes.empty
        else "—",
    )
    cards[2].metric(
        "Possível excesso (30 dias)",
        int(recomendacoes["excesso"].eq(True).sum())
        if not recomendacoes.empty and recomendacoes["excesso"].notna().any()
        else "—",
    )
    if st.button("Salvar análise e entradas no histórico", type="primary"):
        planning = {}
        if produtos is not None:
            p, f, o = validar_planejamento(
                produtos,
                fornecedores,
                pedidos,
                vendas["sku"].unique(),
                vendas["data"].max(),
            )
            planning = {"produtos": p, "fornecedores": f, "pedidos": o}
        future = (
            validar_contexto_futuro(contexto, vendas, horizonte)
            if contexto is not None
            else None
        )
        run_id = store.save_run(
            resultado,
            vendas,
            contexto_futuro=future,
            parametros={"horizonte": horizonte, "revisao_dias": revisao},
            **planning,
        )
        st.success(f"Análise salva: {run_id}")

    forecasts_tab, stock_tab, quality_tab, history_tab = st.tabs(
        ["Previsões", "Estoque e compras", "Qualidade dos dados", "Histórico"]
    )
    with forecasts_tab:
        sku = st.selectbox("Produto", sorted(previsoes["sku"].unique()))
        selected = previsoes.loc[previsoes["sku"].eq(sku)]
        st.info(
            f"Método: {selected['modelo'].iloc[0]}. {SITUATIONS.get(selected['status'].iloc[0], selected['status'].iloc[0])}"
        )
        if selected["status"].iloc[0] == "historico_curto":
            st.warning(
                "Estimativa inicial por histórico insuficiente. Qualquer sugestão de compra deste produto é provisória e precisa de revisão."
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
                "selecionado",
                "cobertura_teste",
                "status",
            ],
        )
        st.caption(
            "MAE em unidades/dia; WAPE em %. Viés positivo indica previsão acima do realizado. A escolha usa apenas janelas anteriores ao teste final. Faixas de 90% são empíricas, calibradas em período separado; a cobertura observada não garante cobertura futura. Sem dados suficientes, a faixa fica vazia."
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
        baixar("Baixar todas as previsões", resultado["previsoes"], "previsoes.csv")
        baixar("Baixar métricas por produto", resultado["metricas"], "metricas.csv")
    with stock_tab:
        if recomendacoes.empty:
            st.info(
                "Ative o planejamento de estoque para informar produtos e fornecedores."
            )
        else:
            st.subheader("Prioridades para revisão")
            filtro = st.text_input("Buscar por SKU ou nome")
            problemas = st.checkbox("Mostrar somente itens que precisam de revisão")
            view = recomendacoes.copy()
            if filtro:
                view = view.loc[
                    view["sku"].str.contains(filtro, case=False, regex=False)
                    | view["nome"].str.contains(filtro, case=False, regex=False)
                ]
            if problemas:
                view = view.loc[
                    view["primeira_falta"].notna()
                    | view["excesso"].eq(True)
                    | ~view["status"].eq("acompanhar")
                ]
            view = view.assign(
                _falta=view["primeira_falta"].notna(), _excesso=view["excesso"].eq(True)
            )
            view = view.sort_values(
                ["_falta", "_excesso", "sku"], ascending=[False, False, True]
            )
            provisorios = view.loc[
                view["status_previsao"].eq("historico_curto"), "sku"
            ].tolist()
            if provisorios:
                st.warning(
                    "Sugestões provisórias por histórico curto: "
                    + ", ".join(provisorios)
                )
            tabela(
                view,
                [
                    "sku",
                    "nome",
                    "estoque_atual",
                    "compra_sugerida",
                    "primeira_falta",
                    "risco_antes_reposicao",
                    "excesso",
                    "horizonte_necessario",
                    "status",
                    "status_previsao",
                ],
            )
            st.warning(
                "Sugestões exigem revisão humana. Saldo negativo é déficit estimado, não estoque físico negativo. As compras sugeridas não são enviadas nem entram nos recebimentos. Se o horizonte não cobre prazo + revisão, a compra fica indefinida."
            )
            with st.expander("Cálculos de reposição e pedidos na janela"):
                st.write(
                    "Alvo = previsão no prazo do fornecedor + período de revisão + segurança informada. Compra = alvo − disponível − pedidos que chegam nessa janela; se positiva, aplica mínimo e múltiplo de compra. Pedidos posteriores não cobrem faltas anteriores. Excesso compara posição com previsão de 30 dias + segurança; pode ser intencional em fornecedores de prazo longo."
                )
                tabela(recomendacoes)
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
    with quality_tab:
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
    with history_tab:
        historico(store, vendas)
    st.caption(
        "Vendas observadas não revelam demanda perdida por falta de estoque. Aplicação local; valide os resultados com dados reais antes de decisões de compra."
    )


if __name__ == "__main__":
    main()
