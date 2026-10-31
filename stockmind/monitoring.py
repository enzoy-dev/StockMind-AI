"""Monitoramento local de previsões gravadas antes das realizações diárias.

Não altera análises, não envia notificações e não chama vendas censuradas de demanda.
"""

from datetime import date, datetime, timedelta, timezone
import math
from numbers import Integral, Real
from zoneinfo import ZoneInfo

import pandas as pd


TIMEZONE = ZoneInfo("America/Sao_Paulo")
MONITOR_COLUMNS = [
    "sku",
    "horizonte",
    "data_fim",
    "mae_recente",
    "vies_recente",
    "direcao_vies",
    "mae_base",
    "mae_referencia_recente",
    "amostras_referencia",
    "perde_referencia_semanal",
    "amostras_recente",
    "amostras_base",
    "periodos_censurados",
    "periodos_retrospectivos",
    "periodos_futuros",
    "disponibilidade_desconhecida",
    "aumento_pct",
    "alerta",
    "motivos_monitoramento",
    "status",
    "base_avaliacao",
]


def _created(raw):
    created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created


def _weekly_reference(row):
    """Referência recursiva baseada apenas nos dados conhecidos no snapshot."""
    origin = date.fromisoformat(row["origem"])
    reference_day = date.fromisoformat(row["data"]) - timedelta(days=7)
    while reference_day > origin:
        reference_day -= timedelta(days=7)
    for sale in row["entrada"].get("vendas", []):
        sku = str(sale.get("sku", "PRODUTO-001")).strip()
        if sku != row["sku"] or sale.get("data") != reference_day.isoformat():
            continue
        availability = sale.get("disponivel")
        if availability not in (None, ""):
            try:
                if float(availability) == 0:
                    return None
            except (TypeError, ValueError):
                return None
        try:
            value = float(sale["vendas"])
        except (KeyError, TypeError, ValueError):
            return None
        return value if math.isfinite(value) and value >= 0 else None
    return None


def monitorar_desempenho(
    store,
    horizonte=7,
    janela_recente=7,
    janela_base=21,
    limiar_aumento_pct=30,
):
    """Compara duas janelas de dias corridos por SKU, sem duplicar o mesmo alvo.

    A janela recente termina na última realização prospectiva do produto; a base
    vem imediatamente antes. Alertas exigem 7 e 14 alvos avaliáveis, respectivamente.
    Previsões criadas no dia-alvo ou depois, em São Paulo, são retrospectivas. Quando
    há sobreposição, vence a origem mais recente, depois criação e ID, dentre as
    previsões prospectivas. Períodos futuros e disponibilidade 0 não entram no erro.
    Com suporte suficiente, também sinaliza erro maior que a referência semanal
    nos mesmos alvos. A direção do viés é descritiva, sem teste de significância.
    """
    if isinstance(horizonte, bool) or horizonte not in (7, 14, 30, 90):
        raise ValueError("Horizonte deve ser 7, 14, 30 ou 90 dias.")
    for value, maximum, label in (
        (janela_recente, 90, "Janela recente"),
        (janela_base, 365, "Janela base"),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, Integral)
            or not 1 <= value <= maximum
        ):
            raise ValueError(f"{label} deve ser inteira entre 1 e {maximum} dias.")
    if (
        isinstance(limiar_aumento_pct, bool)
        or not isinstance(limiar_aumento_pct, Real)
        or not math.isfinite(limiar_aumento_pct)
        or not 0 <= limiar_aumento_pct <= 1000
    ):
        raise ValueError("Limiar deve ser um número finito entre 0 e 1000 por cento.")

    rows = store.monitoring_rows(horizonte)
    grouped = {}
    for row in rows:
        grouped.setdefault(row["sku"], []).append(row)
    summaries = []
    today = datetime.now(TIMEZONE).date()
    for sku, candidates in grouped.items():
        prospective, retrospective, future = {}, set(), set()
        for row in candidates:
            target = date.fromisoformat(row["data"])
            created = _created(row["criado_em"])
            if (
                created.astimezone(TIMEZONE).date() >= target
                or row["origem"] >= row["data"]
            ):
                retrospective.add(target)
                continue
            if target > today:
                future.add(target)
                continue
            freshness = (row["origem"], created, row["run_id"])
            if target not in prospective or freshness > prospective[target][0]:
                prospective[target] = (freshness, row)
        actuals = [
            row for _, row in prospective.values() if row["vendas_reais"] is not None
        ]
        summary = {
            "sku": sku,
            "horizonte": horizonte,
            "data_fim": None,
            "mae_recente": None,
            "vies_recente": None,
            "direcao_vies": None,
            "mae_base": None,
            "mae_referencia_recente": None,
            "amostras_referencia": 0,
            "perde_referencia_semanal": None,
            "amostras_recente": 0,
            "amostras_base": 0,
            "periodos_censurados": 0,
            "periodos_retrospectivos": len(retrospective),
            "periodos_futuros": len(future),
            "disponibilidade_desconhecida": 0,
            "aumento_pct": None,
            "alerta": False,
            "motivos_monitoramento": "",
            "status": "aguardando_realizacoes"
            if prospective
            else "sem_previsoes_prospectivas",
            "base_avaliacao": "sem_alvos_avaliaveis",
        }
        if not actuals:
            summaries.append(summary)
            continue
        end = max(date.fromisoformat(row["data"]) for row in actuals)
        recent_start = end - timedelta(days=int(janela_recente) - 1)
        base_start = recent_start - timedelta(days=int(janela_base))
        current_window = [
            r for r in actuals if base_start <= date.fromisoformat(r["data"]) <= end
        ]
        censored = [r for r in current_window if r["disponivel"] == 0]
        evaluable = [r for r in current_window if r["disponivel"] != 0]
        recent = [r for r in evaluable if date.fromisoformat(r["data"]) >= recent_start]
        base = [r for r in evaluable if date.fromisoformat(r["data"]) < recent_start]
        errors_recent = [r["previsao"] - r["vendas_reais"] for r in recent]
        errors_base = [r["previsao"] - r["vendas_reais"] for r in base]
        reference_errors = []
        for row in recent:
            reference = _weekly_reference(row)
            if reference is not None:
                reference_errors.append(abs(reference - row["vendas_reais"]))
        unknown = sum(r["disponivel"] is None for r in evaluable)
        summary.update(
            {
                "data_fim": end.isoformat(),
                "mae_recente": sum(abs(error) for error in errors_recent) / len(recent)
                if recent
                else None,
                "vies_recente": sum(errors_recent) / len(recent) if recent else None,
                "mae_base": sum(abs(error) for error in errors_base) / len(base)
                if base
                else None,
                "mae_referencia_recente": sum(reference_errors) / len(reference_errors)
                if reference_errors
                else None,
                "amostras_referencia": len(reference_errors),
                "amostras_recente": len(recent),
                "amostras_base": len(base),
                "periodos_censurados": len(censored),
                "disponibilidade_desconhecida": unknown,
                "base_avaliacao": "sem_alvos_avaliaveis"
                if not evaluable
                else (
                    "vendas_observadas_disponibilidade_desconhecida"
                    if unknown
                    else "vendas_em_dias_disponiveis"
                ),
                "status": "amostra_insuficiente"
                if evaluable
                else "sem_alvos_avaliaveis",
            }
        )
        if recent and base:
            initial, final = summary["mae_base"], summary["mae_recente"]
            summary["aumento_pct"] = (
                (final / initial - 1) * 100 if initial else (0 if final == 0 else None)
            )
            if len(recent) >= 7 and len(base) >= 14:
                if initial == 0 and final > 0:
                    summary.update(alerta=True, status="erro_apos_base_zero")
                else:
                    deteriorated = (
                        final > initial and summary["aumento_pct"] >= limiar_aumento_pct
                    )
                    summary.update(
                        alerta=deteriorated,
                        status="aumento_erro" if deteriorated else "estavel",
                    )
        bias = summary["vies_recente"]
        if bias is not None:
            summary["direcao_vies"] = (
                "superestimacao"
                if bias > 0
                else "subestimacao"
                if bias < 0
                else "equilibrado"
            )
        reasons = [summary["status"]] if summary["alerta"] else []
        # A referência só é comparável quando usa exatamente os mesmos alvos.
        if (
            len(recent) >= 7
            and len(base) >= 14
            and len(reference_errors) == len(recent)
        ):
            loses_reference = (
                summary["mae_recente"] > summary["mae_referencia_recente"] + 1e-9
            )
            summary["perde_referencia_semanal"] = loses_reference
            if loses_reference:
                summary["alerta"] = True
                reasons.append("abaixo_referencia_semanal")
                if summary["status"] not in ("aumento_erro", "erro_apos_base_zero"):
                    summary["status"] = "abaixo_referencia_semanal"
        summary["motivos_monitoramento"] = ";".join(reasons)
        summaries.append(summary)
    return pd.DataFrame(summaries, columns=MONITOR_COLUMNS)
