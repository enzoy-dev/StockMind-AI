import os
import pandas as pd
import streamlit as st
from stockmind.data import (
    DataError,
    validar_vendas,
    validar_contexto_futuro,
    validar_planejamento,
)
from stockmind.storage import Store
from .components import ROOT, EXAMPLES, ler_csv, ler_arquivo, baixar

from .forms import cadastros
from .calculations import calcular
from .history import historico
from .forecasts import mostrar_previsoes
from .decisions import mostrar_decisoes
from .scenarios import mostrar_cenarios
from .evaluation import mostrar_avaliacao
from .quality import mostrar_qualidade


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
        avancado = {
            "janela_classificacao": int(
                st.selectbox(
                    "Janela comum da classificação ABC (dias)",
                    [30, 60, 90, 180, 365],
                    index=2,
                )
            )
        }
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
                avancado.update(
                    {
                        "entregas": entregas,
                        "seguranca_automatica": seguranca_auto,
                        "ajustar_prazos": prazos_auto,
                        "avaliar_reposicao": simular,
                    }
                )
                if simular:
                    st.info(
                        "Replay com estoque inicial e parâmetros manuais do catálogo como cenário declarado. Não reconstrói o estoque real passado; custos abaixo são premissas em unidades monetárias."
                    )
                    periodo = st.selectbox(
                        "Período histórico da simulação (dias)", [7, 14, 30], index=2
                    )
                    numero_periodos = int(
                        st.number_input(
                            "Número de períodos históricos",
                            min_value=1,
                            max_value=6,
                            value=1,
                        )
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
                            "numero_periodos_simulacao": numero_periodos,
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
        mostrar_decisoes(resultado, vendas, produtos, fornecedores, pedidos, store)
    with scenarios_tab:
        mostrar_cenarios(resultado)
    with evaluation_tab:
        mostrar_avaliacao(resultado)
    with quality_tab:
        mostrar_qualidade(resultado)
    with history_tab:
        historico(store, vendas)
    st.caption(
        "Vendas observadas não revelam demanda perdida por falta de estoque. Aplicação local; valide os resultados com dados reais antes de decisões de compra."
    )
