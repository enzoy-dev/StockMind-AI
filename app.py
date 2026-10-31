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
from stockmind.monitoring import monitorar_desempenho

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
    "data_limite_compra": "Data-limite para comprar",
    "data_compra_sugerida": "Comprar em",
    "data_entrega_compra_sugerida": "Entrega estimada da nova compra",
    "quantidade_compra_na_data": "Quantidade na data sugerida",
    "primeira_abaixo_seguranca": "Primeiro saldo abaixo da segurança",
    "dias_ate_falta": "Dias até a falta",
    "dias_ate_seguranca": "Dias até ficar abaixo da segurança",
    "prioridade": "Prioridade",
    "motivos_alerta": "Motivo da revisão",
    "unidades_acima_alvo_30dias": "Unidades acima do alvo de 30 dias",
    "status_agendamento": "Situação do agendamento",
    "cenario": "Cenário",
    "horizonte": "Horizonte (dias)",
    "mae_teste_semana_anterior": "MAE teste: referência semanal",
    "ganho_mae_teste_pct": "Redução do MAE vs. semana anterior (%)",
    "horizonte_necessario_agendamento": "Dias necessários para dimensionar compra futura",
    "classe_abc": "Classe ABC",
    "classe_xyz": "Classe XYZ",
    "base_abc": "Base da classificação ABC",
    "seguranca_manual": "Segurança manual",
    "seguranca_sugerida": "Segurança sugerida",
    "prazo_manual": "Prazo manual",
    "prazo_sugerido": "Prazo sugerido",
    "amostras": "Amostras",
    "aplicado": "Aplicado nesta análise",
    "participacao_pct": "Participação (%)",
    "acumulado_pct": "Acumulado (%)",
    "observacoes": "Observações",
    "prazo_medio": "Prazo médio (dias)",
    "prazo_desvio": "Desvio do prazo (dias)",
    "prazo_p90": "Percentil 90 do prazo",
    "atrasos_pct": "Entregas atrasadas (%)",
    "amostras_disponiveis": "Amostras disponíveis",
    "amostras_teste": "Dias avaliados no teste",
    "dias_censurados": "Dias com indisponibilidade",
    "dias_disponiveis": "Dias com vendas elegíveis",
    "direcao_vies": "Direção do viés médio",
    "perde_referencia_semanal": "Erro maior que a referência semanal",
    "motivos_monitoramento": "Motivos do alerta",
    "politica": "Política",
    "vendas_perdidas": "Unidades não atendidas na simulação",
    "estoque_medio": "Estoque médio simulado",
    "custo_total_estimado": "Custo estimado do cenário",
    "mae_recente": "MAE recente",
    "mae_base": "MAE anterior",
    "mae_referencia_recente": "MAE da referência semanal",
    "vies_recente": "Viés recente",
    "aumento_pct": "Aumento do MAE (%)",
    "periodos_censurados": "Dias censurados excluídos",
    "periodos_retrospectivos": "Dias com previsões retrospectivas excluídos",
}
SITUATIONS = {
    "critica": "Crítica",
    "alta": "Alta",
    "media": "Média",
    "baixa": "Baixa",
    "indefinida": "Indefinida",
    "revisar_entrega_urgente": "Revisar entrega urgente",
    "sem_gatilho_no_horizonte": "Sem necessidade de compra identificada neste horizonte",
    "sem_compra_adicional": "Pedidos existentes cobrem a entrega possível; revisar falta anterior",
    "prazo_vencido": "Prazo teórico vencido",
    "comprar_agora": "Comprar na data de referência",
    "compra_programada": "Compra futura sugerida",
    "revisar_compra": "Revisar compra",
    "acompanhar": "Acompanhar",
    "horizonte_insuficiente": "Aumente o horizonte",
    "sem_previsao": "Sem previsão disponível",
    "historico_curto": "Histórico curto: estimativa inicial",
    "avaliado": "Avaliado no histórico",
    "avaliacao_parcial": "Avaliação limitada aos dias observáveis",
    "demanda_indisponivel": "Sem demanda observável",
}


def ler_arquivo(source):
    if hasattr(source, "seek"):
        source.seek(0)
    return ler_csv(source)


def tabela(frame, columns=None):
    view = frame.copy()
    if columns:
        view = view[[column for column in columns if column in view]]
    for campo in ("status", "status_previsao", "status_agendamento", "prioridade"):
        if campo in view:
            view[campo] = view[campo].map(
                lambda v: (
                    SITUATIONS.get(v, v.replace("_", " ").capitalize())
                    if isinstance(v, str)
                    else v
                )
            )
    st.dataframe(view.rename(columns=LABELS), hide_index=True, width="stretch")


def baixar(label, records, filename):
    data = pd.DataFrame(records).to_csv(index=False).encode("utf-8-sig")
    st.download_button(label, data, filename, "text/csv", key=filename)


def precisam_revisao(recomendacoes):
    """Inclui compra futura por segurança mesmo sem falta física no horizonte."""
    return recomendacoes["prioridade"].isin(
        ["critica", "alta", "media", "indefinida"]
    ) | recomendacoes["status_previsao"].isin(
        ["historico_curto", "avaliacao_parcial", "demanda_indisponivel"]
    )


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


def main():
    st.set_page_config(page_title="StockMind-AI", layout="wide")
    st.title("StockMind-AI")
    st.write(
        "Previsões por produto, planejamento de estoque e acompanhamento dos resultados."
    )
    origem = st.radio(
        "Histórico",
        [
            "Carteira fictícia",
            "Exemplo de um produto",
            "Sazonalidade anual",
            "Enviar CSV",
        ],
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
    comparar = st.checkbox(
        "Comparar 7, 14 e 30 dias", value=exemplo, key=f"comparar_{origem}"
    )
    if comparar:
        st.caption(
            "Cada horizonte tem sua própria seleção e teste. Se usar contexto planejado, o calendário deve cobrir pelo menos 30 dias."
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
        elif origem == "Sazonalidade anual":
            st.info(
                "Exemplo fictício com 1.100 dias para avaliar padrões mensais e anuais."
            )
            bruto = ler_csv(EXAMPLES / "vendas_sazonais_exemplo.csv")
        else:
            st.caption(
                "CSV: sku, data, vendas. Opcionais: disponivel (0/1), preco, promocao, feriado. Disponível=1 exige disponibilidade durante todo o dia; 0 indica vendas censuradas."
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
        variacao = (
            float(st.slider("Variação de demanda nos cenários (%)", 0, 80, 20, step=5))
            if produtos is not None
            else 20.0
        )
        avancado = {}
        if produtos is not None:
            with st.expander(
                "Segurança calculada, entregas históricas e avaliação da reposição"
            ):
                st.caption(
                    "Estimativas só substituem valores manuais quando habilitadas e sustentadas por amostras suficientes."
                )
                if exemplo:
                    entregas = ler_csv(EXAMPLES / "entregas_exemplo.csv")
                    st.caption(
                        "Histórico fictício de 24 entregas incluído na carteira."
                    )
                else:
                    recibos = st.file_uploader("Histórico de entregas CSV", type="csv")
                    entregas = ler_arquivo(recibos) if recibos is not None else None
                seguranca_auto = st.checkbox(
                    "Aplicar estoque de segurança calculado", value=False
                )
                prazos_auto = st.checkbox(
                    "Aplicar prazo sugerido pelo histórico de entregas", value=False
                )
                simular = st.checkbox(
                    "Avaliar políticas de reposição no histórico", value=False
                )
                avancado = {
                    "entregas": entregas,
                    "seguranca_automatica": seguranca_auto,
                    "ajustar_prazos": prazos_auto,
                    "avaliar_reposicao": simular,
                }
                if simular:
                    st.info(
                        "Replay com estoque inicial e parâmetros manuais do catálogo como cenário declarado. Não reconstrói o estoque real passado; custos abaixo são premissas em unidades monetárias."
                    )
                    periodo = st.selectbox(
                        "Período histórico da simulação (dias)", [7, 14, 30], index=2
                    )
                    proxy = st.checkbox(
                        "Assumir vendas como demanda quando a disponibilidade não foi informada",
                        value=False,
                    )
                    perda = st.number_input(
                        "Custo assumido por unidade não atendida",
                        min_value=0.0,
                        value=1.0,
                    )
                    manutencao = st.number_input(
                        "Custo assumido por unidade em estoque por dia",
                        min_value=0.0,
                        value=0.01,
                        step=0.01,
                    )
                    pedido_custo = st.number_input(
                        "Custo assumido por pedido", min_value=0.0, value=1.0
                    )
                    avancado.update(
                        {
                            "periodo_simulacao": periodo,
                            "assumir_vendas_como_demanda": proxy,
                            "custo_falta_unitario": perda,
                            "custo_estoque_unitario_dia": manutencao,
                            "custo_pedido": pedido_custo,
                        }
                    )
        resultado = calcular(
            vendas,
            horizonte,
            contexto,
            produtos,
            fornecedores,
            pedidos,
            revisao,
            comparar,
            variacao,
            avancado,
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

    previsoes = (
        pd.DataFrame(resultado["previsoes"])
        if resultado["previsoes"]
        else pd.DataFrame(
            columns=[
                "sku",
                "data",
                "previsao",
                "limite_inferior",
                "limite_superior",
                "modelo",
                "status",
            ]
        )
    )
    metricas = pd.DataFrame(resultado["metricas"])
    saldos = pd.DataFrame(resultado["saldos"])
    recomendacoes = pd.DataFrame(resultado["recomendacoes"])
    st.caption(
        f"Data de referência: {resultado['origem']}. A previsão começa no dia seguinte ao histórico."
    )
    cards = st.columns(4)
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
    cards[3].metric(
        "Revisão urgente",
        int(recomendacoes["prioridade"].isin(["critica", "alta"]).sum())
        if not recomendacoes.empty
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
            validar_contexto_futuro(
                contexto, vendas, max(horizonte, 30) if comparar else horizonte
            )
            if contexto is not None
            else None
        )
        run_id = store.save_run(
            resultado,
            vendas,
            contexto_futuro=future,
            entregas=avancado.get("entregas"),
            vendas_originais=bruto,
            parametros={
                "horizonte": horizonte,
                "revisao_dias": revisao,
                "comparar_horizontes": comparar,
                "variacao_cenario_pct": variacao,
                **{key: value for key, value in avancado.items() if key != "entregas"},
            },
            **planning,
        )
        st.success(f"Análise salva: {run_id}")

    (
        stock_tab,
        forecasts_tab,
        scenarios_tab,
        evaluation_tab,
        quality_tab,
        history_tab,
    ) = st.tabs(
        [
            "Decisões de reposição",
            "Previsões",
            "Cenários de demanda",
            "Avaliação da reposição",
            "Qualidade dos dados",
            "Histórico",
        ]
    )
    with forecasts_tab:
        mostrar_previsoes(vendas, previsoes, metricas, resultado)
    with stock_tab:
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
                    view["primeira_falta"].notna()
                    | view["prazo_compra_vencido"].eq(True)
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
    with scenarios_tab:
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
    with evaluation_tab:
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
