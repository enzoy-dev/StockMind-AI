"""Gera somente exemplos fictícios com semente fixa; não acessa dados externos."""

from pathlib import Path
from random import Random
import csv
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parents[1] / "data"


def write(name, columns, rows):
    ROOT.mkdir(exist_ok=True)
    with (ROOT / name).open("w", newline="", encoding="utf-8") as file:
        out = csv.writer(file, lineterminator="\n")
        out.writerow(columns)
        out.writerows(rows)


def generate():
    rng = Random(42)
    end = date(2026, 10, 20)
    sales, future = [], []
    for sku, base, price, length in [
        ("CAF-001", 18, 24.9, 420),
        ("CHA-002", 8, 14.5, 420),
        ("CAC-003", 2, 19.9, 420),
        ("NOV-004", 3, 9.9, 10),
    ]:
        for i in range(length):
            day = end - timedelta(days=length - 1 - i)
            promotion = int(day.day in (5, 6, 20))
            holiday = int(day.month == 1 and day.day == 1)
            mean = base + i * 0.008 + (5 if day.weekday() == 5 else 0) + promotion * 6
            units = max(0, round(mean + rng.randint(-3, 3)))
            if sku == "CAC-003":
                units = rng.randint(1, 15) if rng.random() < 0.18 else 0
            sales.append(
                [
                    sku,
                    day.isoformat(),
                    units,
                    round(price * (0.9 if promotion else 1), 2),
                    promotion,
                    holiday,
                ]
            )
        for i in range(1, 91):
            day = end + timedelta(days=i)
            promo = int(day.day in (5, 6, 20))
            future.append(
                [
                    sku,
                    day.isoformat(),
                    round(price * (0.9 if promo else 1), 2),
                    promo,
                    int(day.month == 1 and day.day == 1),
                ]
            )
    write(
        "vendas_multiplos_exemplo.csv",
        ["sku", "data", "vendas", "preco", "promocao", "feriado"],
        sales,
    )
    write(
        "contexto_futuro_exemplo.csv",
        ["sku", "data", "preco", "promocao", "feriado"],
        future,
    )
    write(
        "fornecedores_exemplo.csv",
        ["fornecedor_id", "nome", "prazo_dias"],
        [
            ["FOR-01", "Fornecedor demonstrativo A", 5],
            ["FOR-02", "Fornecedor demonstrativo B", 10],
        ],
    )
    write(
        "produtos_exemplo.csv",
        [
            "sku",
            "nome",
            "fornecedor_id",
            "estoque_atual",
            "estoque_seguranca",
            "pedido_minimo",
            "multiplo_compra",
        ],
        [
            ["CAF-001", "Café fictício", "FOR-01", 35, 20, 12, 6],
            ["CHA-002", "Chá fictício", "FOR-02", 140, 10, 6, 6],
            ["CAC-003", "Cacau fictício", "FOR-01", 300, 5, 10, 5],
            ["NOV-004", "Produto recente", "FOR-01", 10, 5, 5, 5],
            ["SEM-005", "Produto sem histórico", "FOR-02", 0, 0, 1, 1],
        ],
    )
    write(
        "pedidos_exemplo.csv",
        ["pedido_id", "sku", "quantidade", "data_entrega"],
        [
            ["PED-01", "CAF-001", 30, (end + timedelta(days=3)).isoformat()],
            ["PED-02", "CHA-002", 60, (end + timedelta(days=8)).isoformat()],
            ["PED-03", "CAF-001", 100, (end + timedelta(days=45)).isoformat()],
        ],
    )


if __name__ == "__main__":
    generate()
