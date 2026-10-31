from pathlib import Path
import altair as alt
import pandas as pd
import streamlit as st
from stockmind import data as contratos

ROOT = Path(__file__).resolve().parents[2]

EXAMPLES = ROOT / "data"

LABELS = {
    "abc_provisoria": "ABC provisória",
    "dias_cobertos": "Dias cobertos na janela",
    "janela_dias": "Janela ABC (dias)",
    "janelas_vencidas": "Vitórias na validação",
    "mae_validacao_desvio": "Variação do MAE entre janelas",
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


def ler_csv(source):
    return contratos.ler_csv(source)


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
