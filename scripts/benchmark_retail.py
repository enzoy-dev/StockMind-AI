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


def selecionar_perfis(frame, start, cut, products=9):
    if type(products) is not int or not 3 <= products <= 60:
        raise ValueError("Recorte estratificado exige de 3 a 60 produtos.")
    training = frame.loc[frame.InvoiceDate.lt(cut + pd.Timedelta(days=1))].copy()
    training["dia"] = training.InvoiceDate.dt.normalize()
    daily = training.groupby(["StockCode", "dia"]).Quantity.sum()
    table = daily.groupby(level=0).agg(["sum", "count"])
    days = (cut - start).days + 1
    table["media_treino"] = table["sum"] / days
    second = daily.pow(2).groupby(level=0).sum() / days
    table["cv_treino"] = (second - table.media_treino.pow(2)).clip(lower=0).pow(
        0.5
    ) / table.media_treino
    table["fracao_dias_sem_fatura"] = 1 - table["count"] / days
    # Evita selecionar produtos com pouquíssimos eventos por um CV extremo.
    table = table.loc[table["count"].ge(28)].sort_index()
    selected, profiles = [], []
    for index, (profile, field) in enumerate(
        [
            ("volume_alto", "sum"),
            ("intermitente", "fracao_dias_sem_fatura"),
            ("variavel", "cv_treino"),
        ]
    ):
        quota = products // 3 + (index < products % 3)
        available = table.loc[~table.index.isin(selected)].sort_values(
            [field] + ([] if field == "sum" else ["sum"]),
            ascending=False,
            kind="stable",
        )
        if len(available) < quota:
            raise ValueError(
                "Produtos elegíveis insuficientes para os perfis solicitados."
            )
        for sku, row in available.head(quota).iterrows():
            selected.append(sku)
            profiles.append(
                {
                    "sku": sku,
                    "perfil": profile,
                    "unidades_treino": int(row["sum"]),
                    "dias_com_fatura_treino": int(row["count"]),
                    "media_treino": float(row.media_treino),
                    "cv_treino": float(row.cv_treino),
                    "fracao_dias_sem_fatura": float(row.fracao_dias_sem_fatura),
                }
            )
    return selected, profiles


def prepare(raw, products=3, estratificado=False):
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
    if type(products) is not int or products < 1:
        raise ValueError("Quantidade de produtos deve ser inteira positiva.")
    profiles = []
    if estratificado:
        skus, profiles = selecionar_perfis(frame, start, cut, products)
    else:
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
        "perfis_treino": profiles,
        "selecao": "perfis somente no treino"
        if estratificado
        else "volume somente no treino",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", type=Path, default=ROOT / "data/benchmark_raw/OnlineRetail.xlsx"
    )
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/uci_retail")
    parser.add_argument("--estratificado", action="store_true")
    parser.add_argument("--products", type=int, default=None)
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
    sales, metadata = prepare(
        raw,
        products=args.products
        if args.products is not None
        else (9 if args.estratificado else 3),
        estratificado=args.estratificado,
    )
    metrics = comparar_horizontes(sales)
    args.output.mkdir(parents=True, exist_ok=True)
    sales.assign(data=sales.data.dt.strftime("%Y-%m-%d")).to_csv(
        args.output / "vendas_agregadas.csv", index=False
    )
    if metadata["perfis_treino"]:
        profiles = pd.DataFrame(metadata["perfis_treino"])
        profiles.to_csv(args.output / "perfis_treino.csv", index=False)
        metrics = metrics.merge(
            profiles[["sku", "perfil"]], on="sku", validate="many_to_one"
        )
        valid = metrics.loc[metrics.ganho_mae_teste_pct.notna()].copy()
        valid["superou_referencia"] = valid.ganho_mae_teste_pct.gt(0)
        valid.groupby(["perfil", "horizonte"]).agg(
            series_avaliadas=("sku", "size"),
            series_superaram_referencia=("superou_referencia", "sum"),
        ).reset_index().to_csv(args.output / "resumo_perfis.csv", index=False)
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
            "transformacoes": "Remove cancelamentos, quantidades/preços não positivos e códigos não-produto. Seleção de SKUs somente no treino, conforme metadados. Agrega vendas diárias; ausência de fatura=zero registrado. Sem preço futuro ou disponibilidade.",
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
