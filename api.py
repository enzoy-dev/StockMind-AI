"""API local do StockMind-AI. Execute: uvicorn api:app --host 127.0.0.1."""

from contextlib import asynccontextmanager
from datetime import date
import hmac
import os
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from stockmind.storage import Store, _records


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisRequest(RequestModel):
    vendas: list[dict[str, Any]] = Field(min_length=1)
    horizonte: Literal[7, 14, 30, 90] = 7
    contexto_futuro: list[dict[str, Any]] | None = None
    produtos: list[dict[str, Any]] | None = None
    fornecedores: list[dict[str, Any]] | None = None
    pedidos: list[dict[str, Any]] | None = None
    revisao_dias: int = Field(default=7, ge=1, le=30)
    usar_planejamento_salvo: bool = False
    comparar_horizontes: StrictBool = False
    variacao_cenario_pct: float = Field(
        default=20.0, strict=True, ge=0, le=80, allow_inf_nan=False
    )
    entregas: list[dict[str, Any]] | None = None
    seguranca_automatica: StrictBool = False
    ajustar_prazos: StrictBool = False
    avaliar_reposicao: StrictBool = False
    assumir_vendas_como_demanda: StrictBool = False
    periodo_simulacao: Literal[7, 14, 30] = 30
    custo_falta_unitario: float = Field(
        default=1.0, strict=True, ge=0, allow_inf_nan=False
    )
    custo_estoque_unitario_dia: float = Field(
        default=0.01, strict=True, ge=0, allow_inf_nan=False
    )
    custo_pedido: float = Field(default=1.0, strict=True, ge=0, allow_inf_nan=False)
    janela_classificacao: int = Field(default=90, strict=True, ge=1, le=3650)
    numero_periodos_simulacao: int = Field(default=1, strict=True, ge=1, le=6)


class ActualsRequest(RequestModel):
    vendas: list[dict[str, Any]] = Field(min_length=1)


class StockActualsRequest(RequestModel):
    estoques: list[dict[str, Any]] = Field(min_length=1)


class PlanningRequest(RequestModel):
    origem: date
    produtos: list[dict[str, Any]]
    fornecedores: list[dict[str, Any]]
    pedidos: list[dict[str, Any]] = Field(default_factory=list)


def executar_analise(*args, **kwargs):
    # Importação tardia permite inicializar API e documentação sem treinar modelos.
    from stockmind.service import executar_analise as service

    return service(*args, **kwargs)


def create_app(db_path=None):
    database = (
        db_path
        or os.environ.get("STOCKMIND_DB")
        or Path(__file__).with_name("data") / "stockmind.sqlite3"
    )
    api_key = os.environ.get("STOCKMIND_API_KEY", "")
    lock = Lock()

    @asynccontextmanager
    async def lifespan(application):
        yield
        if application.state.store is not None:
            application.state.store.close()

    application = FastAPI(
        title="StockMind-AI",
        version="0.5.0",
        lifespan=lifespan,
        description="Previsões e planejamento local. A aplicação não realiza compras.",
    )
    application.state.store = None

    def store():
        with lock:
            if application.state.store is None:
                application.state.store = Store(database)
        return application.state.store

    def authenticate(x_api_key: str | None = Header(default=None)):
        if api_key and not hmac.compare_digest(
            (x_api_key or "").encode("utf-8"), api_key.encode("utf-8")
        ):
            raise HTTPException(
                status_code=401, detail="Chave de API ausente ou inválida."
            )

    @application.exception_handler(ValueError)
    async def invalid_data(_request, error):
        report = getattr(error, "report", None)
        return JSONResponse(
            status_code=422,
            content={
                "detail": {"mensagem": str(error), "relatorio": _records(report)},
            },
        )

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request, error):
        # JSON não finito pode chegar de clientes externos; a resposta de erro
        # também precisa ser JSON válido, sem deixar NaN/Infinity no payload.
        return JSONResponse(
            status_code=422,
            content={"detail": _records(jsonable_encoder(error.errors()))},
        )

    @application.exception_handler(sqlite3.Error)
    async def database_failure(_request, _error):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Não foi possível acessar a persistência local. A operação foi revertida.",
            },
        )

    @application.get("/health")
    def health():
        return {"status": "ok", "autenticacao_configurada": bool(api_key)}

    @application.post(
        "/analises", status_code=201, dependencies=[Depends(authenticate)]
    )
    def analyse(body: AnalysisRequest):
        from stockmind.data import (
            ORDER_COLUMNS,
            RECEIPT_COLUMNS,
            validar_contexto_futuro,
            validar_entregas,
            validar_planejamento,
            validar_vendas,
        )

        sales = validar_vendas(pd.DataFrame(body.vendas))
        products, suppliers, orders = body.produtos, body.fornecedores, body.pedidos
        if body.usar_planejamento_salvo:
            if products is not None or suppliers is not None or orders is not None:
                raise ValueError(
                    "Escolha planejamento salvo ou planejamento no corpo, não ambos."
                )
            saved = store().get_planning()
            if not saved["produtos"]:
                raise ValueError("Não há planejamento salvo.")
            # Validação da origem acontece antes de qualquer escrita.
            origin = sales["data"].max().date().isoformat()
            if saved["origem"] != origin:
                raise ValueError(
                    "A data do estoque salvo difere do fechamento das vendas. Atualize o planejamento."
                )
            products, suppliers, orders = (
                saved["produtos"],
                saved["fornecedores"],
                saved["pedidos"],
            )
        product_frame = None if products is None else pd.DataFrame(products)
        supplier_frame = None if suppliers is None else pd.DataFrame(suppliers)
        order_frame = (
            None
            if orders is None
            else pd.DataFrame(orders, columns=ORDER_COLUMNS if not orders else None)
        )
        future = (
            None if body.contexto_futuro is None else pd.DataFrame(body.contexto_futuro)
        )
        if products is not None or suppliers is not None or orders is not None:
            product_frame, supplier_frame, order_frame = validar_planejamento(
                product_frame,
                supplier_frame,
                order_frame,
                skus=sales["sku"].unique(),
                origem=sales["data"].max(),
            )
        if future is not None:
            horizonte_contexto = (
                max(body.horizonte, 30) if body.comparar_horizontes else body.horizonte
            )
            future = validar_contexto_futuro(future, sales, horizonte_contexto)
        receipts = None
        if body.entregas is not None:
            receipts = validar_entregas(
                pd.DataFrame(
                    body.entregas,
                    columns=RECEIPT_COLUMNS if not body.entregas else None,
                ),
                sales["data"].max(),
                supplier_frame,
            )
        result = executar_analise(
            sales,
            horizonte=body.horizonte,
            contexto_futuro=future,
            produtos=None if product_frame is None else product_frame.copy(deep=True),
            fornecedores=None
            if supplier_frame is None
            else supplier_frame.copy(deep=True),
            pedidos=None if order_frame is None else order_frame.copy(deep=True),
            revisao_dias=body.revisao_dias,
            comparar_horizontes=body.comparar_horizontes,
            variacao_cenario_pct=body.variacao_cenario_pct,
            entregas=receipts,
            seguranca_automatica=body.seguranca_automatica,
            ajustar_prazos=body.ajustar_prazos,
            avaliar_reposicao=body.avaliar_reposicao,
            assumir_vendas_como_demanda=body.assumir_vendas_como_demanda,
            periodo_simulacao=body.periodo_simulacao,
            custo_falta_unitario=body.custo_falta_unitario,
            custo_estoque_unitario_dia=body.custo_estoque_unitario_dia,
            custo_pedido=body.custo_pedido,
            janela_classificacao=body.janela_classificacao,
            numero_periodos_simulacao=body.numero_periodos_simulacao,
        )
        run_id = store().save_run(
            result,
            sales,
            produtos=product_frame,
            fornecedores=supplier_frame,
            pedidos=order_frame,
            contexto_futuro=future,
            entregas=body.entregas,
            vendas_originais=body.vendas,
            parametros={
                "horizonte": body.horizonte,
                "revisao_dias": body.revisao_dias,
                "comparar_horizontes": body.comparar_horizontes,
                "variacao_cenario_pct": body.variacao_cenario_pct,
                "seguranca_automatica": body.seguranca_automatica,
                "ajustar_prazos": body.ajustar_prazos,
                "avaliar_reposicao": body.avaliar_reposicao,
                "assumir_vendas_como_demanda": body.assumir_vendas_como_demanda,
                "periodo_simulacao": body.periodo_simulacao,
                "custo_falta_unitario": body.custo_falta_unitario,
                "custo_estoque_unitario_dia": body.custo_estoque_unitario_dia,
                "custo_pedido": body.custo_pedido,
                "janela_classificacao": body.janela_classificacao,
                "numero_periodos_simulacao": body.numero_periodos_simulacao,
            },
        )
        return {"id": run_id, "resultado": result}

    @application.get("/analises", dependencies=[Depends(authenticate)])
    def list_analyses(limit: int = Query(default=100, ge=1, le=1000)):
        return store().list_runs(limit)

    @application.get("/analises/{run_id}", dependencies=[Depends(authenticate)])
    def get_analysis(run_id: str):
        result = store().get_run(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Análise não encontrada.")
        return result

    @application.get(
        "/analises/{run_id}/comparacao", dependencies=[Depends(authenticate)]
    )
    def comparison(run_id: str):
        result = store().compare_run(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Análise não encontrada.")
        return result

    @application.get("/monitoramento", dependencies=[Depends(authenticate)])
    def monitoring(
        horizonte: int = Query(default=7, ge=7, le=90),
        janela_recente: int = Query(default=7, ge=1, le=90),
        janela_base: int = Query(default=21, ge=1, le=365),
        limiar_aumento_pct: float = Query(
            default=30, ge=0, le=1000, allow_inf_nan=False
        ),
    ):
        from stockmind.monitoring import monitorar_desempenho

        return _records(
            monitorar_desempenho(
                store(),
                horizonte,
                janela_recente,
                janela_base,
                limiar_aumento_pct,
            )
        )

    @application.post("/vendas", dependencies=[Depends(authenticate)])
    def ingest_actuals(body: ActualsRequest):
        return {"linhas_salvas": store().save_actuals(body.vendas)}

    @application.get("/planejamento", dependencies=[Depends(authenticate)])
    def get_planning():
        return store().get_planning()

    @application.put("/planejamento", dependencies=[Depends(authenticate)])
    def save_planning(body: PlanningRequest):
        from stockmind.data import ORDER_COLUMNS, validar_planejamento

        products, suppliers, orders = validar_planejamento(
            pd.DataFrame(body.produtos),
            pd.DataFrame(body.fornecedores),
            pd.DataFrame(
                body.pedidos, columns=ORDER_COLUMNS if not body.pedidos else None
            ),
            skus=[p.get("sku") for p in body.produtos],
            origem=pd.Timestamp(body.origem),
        )
        store().save_planning(products, suppliers, orders, origem=body.origem)
        return {"produtos_salvos": len(products), "origem": body.origem.isoformat()}

    @application.post("/estoques-reais", dependencies=[Depends(authenticate)])
    def save_stock(body: StockActualsRequest):
        return {"linhas_salvas": store().save_stock_actuals(body.estoques)}

    @application.get(
        "/analises/{run_id}/estoque-real", dependencies=[Depends(authenticate)]
    )
    def compare_stock(run_id: str):
        result = store().compare_stock_run(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Análise não encontrada.")
        return result

    return application


app = create_app()
