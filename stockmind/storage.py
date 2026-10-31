"""Persistência local transacional e acompanhamento de previsões imutáveis."""

from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from uuid import uuid4

import pandas as pd


def _plain(value):
    """Converte tipos pandas/numpy e valores ausentes em JSON padrão."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (datetime, date)):
        return (
            value.date().isoformat()
            if isinstance(value, datetime)
            else value.isoformat()
        )
    if hasattr(value, "item"):
        return _plain(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _records(value):
    if value is None:
        return []
    if isinstance(value, pd.DataFrame):
        value = value.to_dict("records")
    return _plain(value)


def _day(value):
    if isinstance(value, (datetime, date)):
        value = (
            value.date().isoformat()
            if isinstance(value, datetime)
            else value.isoformat()
        )
    if not isinstance(value, str):
        raise ValueError("Datas devem usar YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Datas devem usar YYYY-MM-DD.") from exc
    if parsed.isoformat() != value:
        raise ValueError("Datas devem usar YYYY-MM-DD.")
    return value


def _identifier(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} deve ser um identificador não vazio.")
    return value.strip()


def _number(value, field, *, integer=False, positive=False):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} deve ser um número não negativo.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} deve ser um número não negativo.") from exc
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"{field} deve ser um número não negativo e finito.")
    if integer and (not number.is_integer() or number > 2**53 - 1):
        raise ValueError(f"{field} deve ser uma quantidade inteira válida.")
    return int(number) if integer else number


def _sales_rows(sales):
    records = sales.to_dict("records") if isinstance(sales, pd.DataFrame) else sales
    if not isinstance(records, list) or not records:
        raise ValueError("Informe pelo menos uma venda realizada.")
    rows, seen = [], set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError(
                "Cada realização deve ser um objeto com data, sku e vendas."
            )
        sku = _identifier(row.get("sku", "PRODUTO-001"), "sku")
        day = _day(row.get("data"))
        if (sku, day) in seen:
            raise ValueError("Há mais de uma venda para o mesmo SKU e dia.")
        seen.add((sku, day))
        units = _number(row.get("vendas"), "vendas", integer=True)
        price = None if row.get("preco") is None else _number(row["preco"], "preco")
        flags = []
        for field in ("promocao", "feriado"):
            flag = row.get(field)
            if flag is not None:
                flag = _number(flag, field, integer=True)
                if flag not in (0, 1):
                    raise ValueError(f"{field} deve ser 0 ou 1.")
            flags.append(flag)
        availability = row.get("disponivel")
        if availability is pd.NA or (
            isinstance(availability, float) and math.isnan(availability)
        ):
            availability = None
        if availability is not None:
            availability = _number(availability, "disponivel", integer=True)
            if availability not in (0, 1):
                raise ValueError("disponivel deve ser 0, 1 ou ausente.")
        rows.append((sku, day, units, price, *flags, availability))
    return rows


SCHEMA = """
CREATE TABLE IF NOT EXISTS sales (
    sku TEXT NOT NULL,
    data TEXT NOT NULL,
    vendas INTEGER NOT NULL CHECK(vendas >= 0 AND typeof(vendas) = 'integer'),
    preco REAL CHECK(preco >= 0),
    promocao INTEGER CHECK(promocao IN (0, 1)),
    feriado INTEGER CHECK(feriado IN (0, 1)),
    disponivel INTEGER CHECK(disponivel IN (0, 1)),
    atualizado_em TEXT NOT NULL,
    PRIMARY KEY(sku, data)
);
CREATE TABLE IF NOT EXISTS suppliers (
    fornecedor_id TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    prazo_dias INTEGER NOT NULL CHECK(prazo_dias BETWEEN 0 AND 60)
);
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    fornecedor_id TEXT NOT NULL REFERENCES suppliers(fornecedor_id),
    estoque_atual INTEGER NOT NULL CHECK(estoque_atual >= 0),
    estoque_seguranca INTEGER NOT NULL CHECK(estoque_seguranca >= 0),
    pedido_minimo INTEGER NOT NULL CHECK(pedido_minimo >= 0),
    multiplo_compra INTEGER NOT NULL CHECK(multiplo_compra >= 1)
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    pedido_id TEXT PRIMARY KEY,
    sku TEXT NOT NULL REFERENCES products(sku),
    quantidade INTEGER NOT NULL CHECK(quantidade > 0),
    data_entrega TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS planning_metadata (
    id INTEGER PRIMARY KEY CHECK(id=1),
    origem TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    criado_em TEXT NOT NULL,
    origem TEXT NOT NULL,
    horizonte INTEGER NOT NULL CHECK(horizonte > 0),
    resultado_json TEXT NOT NULL,
    entrada_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecasts (
    run_id TEXT NOT NULL REFERENCES runs(id),
    sku TEXT NOT NULL,
    data TEXT NOT NULL,
    previsao REAL NOT NULL CHECK(previsao >= 0),
    limite_inferior REAL,
    limite_superior REAL,
    modelo TEXT,
    PRIMARY KEY(run_id, sku, data)
);
CREATE INDEX IF NOT EXISTS forecasts_sku_date ON forecasts(sku, data);
"""


class Store:
    def __init__(self, path):
        self.path = str(path)
        self._anchor = None
        self._uri = self.path == ":memory:"
        if self._uri:
            self.path = f"file:stockmind-{uuid4().hex}?mode=memory&cache=shared"
            self._anchor = sqlite3.connect(self.path, uri=True, check_same_thread=False)
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            # Migração aditiva para instalações anteriores; não regrava snapshots.
            connection.execute("BEGIN IMMEDIATE")
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(sales)")
            }
            if "disponivel" not in columns:
                connection.execute(
                    "ALTER TABLE sales ADD COLUMN disponivel INTEGER CHECK(disponivel IN (0, 1))"
                )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, uri=self._uri, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def close(self):
        if self._anchor is not None:
            self._anchor.close()
            self._anchor = None

    @staticmethod
    def _upsert_sales(connection, rows):
        now = datetime.now(timezone.utc).isoformat()
        connection.executemany(
            """INSERT INTO sales
                (sku, data, vendas, preco, promocao, feriado, disponivel, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sku, data) DO UPDATE SET
                vendas=excluded.vendas, preco=COALESCE(excluded.preco, sales.preco),
                promocao=COALESCE(excluded.promocao, sales.promocao),
                feriado=COALESCE(excluded.feriado, sales.feriado),
                disponivel=COALESCE(excluded.disponivel, sales.disponivel),
                atualizado_em=excluded.atualizado_em""",
            [(*row, now) for row in rows],
        )

    def save_actuals(self, sales):
        """Recebe realizações esparsas; cada data ausente continua desconhecida."""
        rows = _sales_rows(sales)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._upsert_sales(connection, rows)
        return len(rows)

    @staticmethod
    def _replace_planning(connection, produtos, fornecedores, pedidos):
        # Uma configuração completa substitui a anterior dentro da mesma transação.
        connection.execute("DELETE FROM purchase_orders")
        connection.execute("DELETE FROM products")
        connection.execute("DELETE FROM suppliers")
        connection.executemany(
            "INSERT INTO suppliers VALUES (?, ?, ?)",
            [(r["fornecedor_id"], r["nome"], r["prazo_dias"]) for r in fornecedores],
        )
        connection.executemany(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                tuple(
                    r[key]
                    for key in (
                        "sku",
                        "nome",
                        "fornecedor_id",
                        "estoque_atual",
                        "estoque_seguranca",
                        "pedido_minimo",
                        "multiplo_compra",
                    )
                )
                for r in produtos
            ],
        )
        connection.executemany(
            "INSERT INTO purchase_orders VALUES (?, ?, ?, ?)",
            [
                (r["pedido_id"], r["sku"], r["quantidade"], _day(r["data_entrega"]))
                for r in pedidos
            ],
        )

    def save_planning(self, produtos, fornecedores, pedidos=None, *, origem=None):
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._replace_planning(
                connection,
                _records(produtos),
                _records(fornecedores),
                _records(pedidos),
            )
            connection.execute(
                "INSERT OR REPLACE INTO planning_metadata VALUES (1, ?)",
                (None if origem is None else _day(origem),),
            )

    def get_planning(self):
        with self._connection() as connection:
            metadata = connection.execute(
                "SELECT origem FROM planning_metadata WHERE id=1"
            ).fetchone()
            return {
                "produtos": [
                    dict(row)
                    for row in connection.execute("SELECT * FROM products ORDER BY sku")
                ],
                "fornecedores": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM suppliers ORDER BY fornecedor_id"
                    )
                ],
                "pedidos": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM purchase_orders ORDER BY pedido_id"
                    )
                ],
                "origem": metadata["origem"] if metadata else None,
            }

    def save_run(
        self,
        result,
        sales,
        *,
        produtos=None,
        fornecedores=None,
        pedidos=None,
        contexto_futuro=None,
        parametros=None,
        entregas=None,
        vendas_originais=None,
    ):
        """Salva snapshot imutável; falhas revertem realizações e configuração juntas."""
        rows = _sales_rows(sales)
        result = _plain(result)
        forecasts = result.get("previsoes", [])
        if not forecasts:
            unavailable = {
                str(metric.get("sku"))
                for metric in result.get("metricas", [])
                if metric.get("status") == "demanda_indisponivel"
            }
            if not {row[0] for row in rows}.issubset(unavailable):
                raise ValueError(
                    "Análise sem previsões exige diagnóstico explícito de demanda indisponível."
                )
            empty_horizon = _number(
                result.get("horizonte"), "horizonte", integer=True, positive=True
            )
        forecast_rows = []
        for forecast in forecasts:
            forecast_rows.append(
                (
                    _identifier(forecast.get("sku"), "sku"),
                    _day(forecast.get("data")),
                    _number(forecast.get("previsao"), "previsao"),
                    forecast.get("limite_inferior"),
                    forecast.get("limite_superior"),
                    forecast.get("modelo"),
                )
            )
        origin = max(row[1] for row in rows)
        horizon = (
            max(
                sum(1 for r in forecast_rows if r[0] == sku)
                for sku in {r[0] for r in forecast_rows}
            )
            if forecast_rows
            else empty_horizon
        )
        run_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        input_snapshot = {
            "vendas": _records(sales if vendas_originais is None else vendas_originais),
            "produtos": _records(produtos),
            "fornecedores": _records(fornecedores),
            "pedidos": _records(pedidos),
            "contexto_futuro": _records(contexto_futuro),
            "parametros": _plain(parametros or {}),
            "entregas": _records(entregas),
        }
        result_json = json.dumps(result, ensure_ascii=False, allow_nan=False)
        input_json = json.dumps(input_snapshot, ensure_ascii=False, allow_nan=False)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._upsert_sales(connection, rows)
            if produtos is not None or fornecedores is not None:
                if produtos is None or fornecedores is None:
                    raise ValueError("Forneça produtos e fornecedores juntos.")
                self._replace_planning(
                    connection,
                    _records(produtos),
                    _records(fornecedores),
                    _records(pedidos),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO planning_metadata VALUES (1, ?)", (origin,)
                )
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, now, origin, horizon, result_json, input_json),
            )
            connection.executemany(
                "INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(run_id, *row) for row in forecast_rows],
            )
        return run_id

    def list_runs(self, limit=100):
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Limite deve estar entre 1 e 1000.")
        with self._connection() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    """SELECT runs.id, criado_em, origem, horizonte,
                    (SELECT COUNT(*) FROM forecasts WHERE forecasts.run_id=runs.id) AS quantidade_previsoes
                FROM runs ORDER BY criado_em DESC, id DESC LIMIT ?""",
                    (limit,),
                )
            ]

    def get_run(self, run_id):
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE id=?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "criado_em": row["criado_em"],
            "origem": row["origem"],
            "horizonte": row["horizonte"],
            "resultado": json.loads(row["resultado_json"]),
            "entrada": json.loads(row["entrada_json"]),
        }

    def compare_run(self, run_id):
        with self._connection() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM runs WHERE id=?", (run_id,)
                ).fetchone()
                is None
            ):
                return None
            joined = connection.execute(
                """SELECT f.sku, f.data, f.previsao, f.limite_inferior, f.limite_superior,
                   s.vendas AS vendas_reais, s.disponivel FROM forecasts f LEFT JOIN sales s
                   ON s.sku=f.sku AND s.data=f.data WHERE f.run_id=? ORDER BY f.sku, f.data""",
                (run_id,),
            ).fetchall()
        comparisons, grouped = [], {}
        for row in joined:
            record = dict(row)
            record["erro"] = (
                None
                if row["vendas_reais"] is None or row["disponivel"] == 0
                else row["previsao"] - row["vendas_reais"]
            )
            record["erro_absoluto"] = (
                None if record["erro"] is None else abs(record["erro"])
            )
            comparisons.append(record)
            grouped.setdefault(row["sku"], []).append(record)
        summaries = []
        for sku, predictions in grouped.items():
            actuals = [r for r in predictions if r["vendas_reais"] is not None]
            observed = [r for r in actuals if r["disponivel"] != 0]
            censored = len(actuals) - len(observed)
            intervals = [
                r
                for r in observed
                if r["limite_inferior"] is not None and r["limite_superior"] is not None
            ]
            n = len(observed)
            total_actual = sum(r["vendas_reais"] for r in observed)
            absolute_error = sum(r["erro_absoluto"] for r in observed)
            summaries.append(
                {
                    "sku": sku,
                    "periodos_previstos": len(predictions),
                    "periodos_observados": len(actuals),
                    "periodos_avaliados": n,
                    "periodos_censurados": censored,
                    "periodos_disponibilidade_desconhecida": sum(
                        r["disponivel"] is None for r in observed
                    ),
                    "mae": absolute_error / n if n else None,
                    "vies": sum(r["erro"] for r in observed) / n if n else None,
                    "wape": absolute_error / total_actual * 100
                    if total_actual
                    else None,
                    "cobertura_faixa": sum(
                        r["limite_inferior"]
                        <= r["vendas_reais"]
                        <= r["limite_superior"]
                        for r in intervals
                    )
                    / len(intervals)
                    * 100
                    if intervals
                    else None,
                    "status": "sem_realizacoes"
                    if not actuals
                    else (
                        "sem_alvos_avaliaveis"
                        if n == 0
                        else (
                            (
                                "parcial"
                                if len(actuals) < len(predictions)
                                else "completo"
                            )
                            + ("_com_censura" if censored else "")
                        )
                    ),
                    "base_avaliacao": "sem_alvos_avaliaveis"
                    if n == 0
                    else (
                        "vendas_observadas_disponibilidade_desconhecida"
                        if any(r["disponivel"] is None for r in observed)
                        else "vendas_em_dias_disponiveis"
                    ),
                }
            )
        return {"id": run_id, "resumo": summaries, "comparacoes": comparisons}

    def monitoring_rows(self, horizonte=7):
        """Leitura para monitoramento; entradas compartilhadas entre linhas do run."""
        if isinstance(horizonte, bool) or horizonte not in (7, 14, 30, 90):
            raise ValueError("Horizonte deve ser 7, 14, 30 ou 90 dias.")
        with self._connection() as connection:
            inputs = {
                row["id"]: json.loads(row["entrada_json"])
                for row in connection.execute(
                    "SELECT id, entrada_json FROM runs WHERE horizonte=?", (horizonte,)
                )
            }
            rows = connection.execute(
                """SELECT r.id AS run_id, r.origem, r.criado_em, r.horizonte,
                    f.sku, f.data, f.previsao, s.vendas AS vendas_reais, s.disponivel
                FROM forecasts f JOIN runs r ON r.id=f.run_id
                LEFT JOIN sales s ON s.sku=f.sku AND s.data=f.data
                WHERE r.horizonte=? ORDER BY f.sku, f.data, r.origem, r.criado_em, r.id""",
                (horizonte,),
            ).fetchall()
        return [{**dict(row), "entrada": inputs[row["run_id"]]} for row in rows]
