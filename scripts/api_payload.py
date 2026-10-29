"""Exporta a requisição demonstrativa sem incluir banco ou arquivos privados."""

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data/requisicao_exemplo.json"
    )
    args = parser.parse_args()
    result = {
        "horizonte": 30,
        "revisao_dias": 7,
        "comparar_horizontes": True,
        "variacao_cenario_pct": 20.0,
    }
    for key, filename in {
        "vendas": "vendas_multiplos_exemplo.csv",
        "contexto_futuro": "contexto_futuro_exemplo.csv",
        "produtos": "produtos_exemplo.csv",
        "fornecedores": "fornecedores_exemplo.csv",
        "pedidos": "pedidos_exemplo.csv",
    }.items():
        frame = pd.read_csv(
            ROOT / "data" / filename,
            dtype={"sku": str, "fornecedor_id": str, "pedido_id": str},
        )
        result[key] = json.loads(frame.to_json(orient="records"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(args.output)


if __name__ == "__main__":
    main()
