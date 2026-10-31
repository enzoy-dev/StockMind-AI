"""Benchmark reproduzível de vendas registradas UCI Online Retail.

python -m scripts.benchmark_retail --input /caminho/OnlineRetail.xlsx
A planilha bruta não é redistribuída. Não contém estoque ou demanda perdida.
"""

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

import pandas as pd
from stockmind.data import validar_vendas
from stockmind.forecasting import comparar_horizontes

SOURCE = "https://archive.ics.uci.edu/dataset/352/online+retail"
MIRROR = "https://github.com/mrinmaisharma/Online-Retail-Dataset/raw/86f29b80be8887d6af5c5b603864e7cf2fe3caf0/OnlineRetail.xlsx"
SHA256 = "43465a06f2ccf7c8b5bd2892bc7defb52f97487934fe93b16ae4c3936424676d"
ROOT = Path(__file__).resolve().parents[1]


def prepare(raw, products=3):
    """Seleção de SKUs só no prefixo anterior aos últimos90dias.

    Datas sem fatura viram zero VENDAS REGISTRADAS no extrato completo, não demanda.
    Preço médio diário não é usado como covariável futura conhecida.
    """
    required = {"InvoiceNo", "StockCode", "Quantity", "InvoiceDate", "UnitPrice"}
    if not required.issubset(raw):
        raise ValueError("Colunas originais UCI ausentes.")
    frame = raw.copy()
    frame["InvoiceDate"] = pd.to_datetime(frame["InvoiceDate"])
    start, end = (
        frame.InvoiceDate.min().normalize() + pd.Timedelta(days=1),
        frame.InvoiceDate.max().normalize() - pd.Timedelta(days=1),
    )
    cut = end - pd.Timedelta(days=90)
    good = (
        ~frame.InvoiceNo.astype(str).str.upper().str.startswith("C")
        & frame.Quantity.gt(0)
        & frame.UnitPrice.gt(0)
        & frame.StockCode.astype(str).str.fullmatch(r"\d{5}[A-Z]?")
    )
    frame = frame.loc[
        good
        & frame.InvoiceDate.ge(start)
        & frame.InvoiceDate.lt(end + pd.Timedelta(days=1))
    ].copy()
    frame["StockCode"] = frame.StockCode.astype(str)
    ranked = (
        frame.loc[frame.InvoiceDate.lt(cut + pd.Timedelta(days=1))]
        .groupby("StockCode")
        .Quantity.sum()
        .sort_index()
        .sort_values(ascending=False, kind="stable")
    )
    skus = ranked.head(products).index.tolist()
    daily = (
        frame.assign(data=frame.InvoiceDate.dt.normalize())
        .groupby(["StockCode", "data"])
        .Quantity.sum()
    )
    rows = []
    for sku in skus:
        for day in pd.date_range(start, end):
            rows.append(
                {"sku": sku, "data": day, "vendas": int(daily.get((sku, day), 0))}
            )
    sales = validar_vendas(pd.DataFrame(rows))
    return sales, {
        "bordas_descartadas": "Primeiro e último dia excluídos por possível cobertura intradiária parcial.",
        "linhas_originais": len(raw),
        "linhas_apos_filtros": len(frame),
        "data_inicio": str(start.date()),
        "data_fim": str(end.date()),
        "corte_selecao_skus": str(cut.date()),
        "skus": skus,
        "dias": (end - start).days + 1,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", type=Path, default=ROOT / "data/benchmark_raw/OnlineRetail.xlsx"
    )
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/uci_retail")
    args = parser.parse_args()
    if args.download and not args.input.exists():
        args.input.parent.mkdir(parents=True, exist_ok=True)
        with (
            urllib.request.urlopen(MIRROR, timeout=60) as response,
            args.input.open("wb") as file,
        ):
            while data := response.read(1048576):
                file.write(data)
    digest = hashlib.sha256(args.input.read_bytes()).hexdigest()
    if digest != SHA256:
        raise ValueError(
            "SHA256 diferente do arquivo fixado; não executar um benchmark não comparável."
        )
    raw = pd.read_excel(
        args.input, engine="openpyxl", dtype={"StockCode": str, "InvoiceNo": str}
    )
    sales, metadata = prepare(raw)
    metrics = comparar_horizontes(sales)
    args.output.mkdir(parents=True, exist_ok=True)
    sales.assign(data=sales.data.dt.strftime("%Y-%m-%d")).to_csv(
        args.output / "vendas_agregadas.csv", index=False
    )
    metrics.to_csv(args.output / "metricas.csv", index=False)
    metadata["hash_motor_previsao"] = hashlib.sha256(
        (ROOT / "stockmind/forecasting.py").read_bytes()
    ).hexdigest()
    metadata.update(
        {
            "fonte": SOURCE,
            "doi": "10.24432/C5BW33",
            "citacao": "Chen, D. (2015). Online Retail. UCI Machine Learning Repository.",
            "licenca_dados": "CC BY 4.0",
            "licenca_url": "https://creativecommons.org/licenses/by/4.0/",
            "mirror": MIRROR,
            "sha256": digest,
            "transformacoes": "Remove cancelamentos, quantidades/preços não positivos e códigos não-produto. Seleciona 3 SKUs no treino. Agrega vendas diárias; ausência de fatura=zero registrado. Sem preço futuro ou disponibilidade.",
            "objetivo": "Previsão de vendas registradas, não demanda não atendida ou ROI.",
            "horizontes": [7, 14, 30],
        }
    )
    (args.output / "proveniencia.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        metrics[
            [
                "sku",
                "horizonte",
                "modelo",
                "mae_teste",
                "mae_teste_semana_anterior",
                "ganho_mae_teste_pct",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
