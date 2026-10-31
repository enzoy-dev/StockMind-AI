"""Exporta métricas sintéticas reproduzíveis, sem banco ou requisição externa.

Execute na raiz: python -m scripts.evaluate_examples
"""

import argparse
from pathlib import Path

import pandas as pd

from stockmind.data import ler_csv
from stockmind.service import executar_analise

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/avaliacao_exemplo.csv"
    )
    args = parser.parse_args()
    result = executar_analise(
        ler_csv(ROOT / "data/vendas_multiplos_exemplo.csv"),
        contexto_futuro=ler_csv(ROOT / "data/contexto_futuro_exemplo.csv"),
        horizonte=30,
        comparar_horizontes=True,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(result["comparacao_horizontes"]).to_csv(args.output, index=False)
    print(args.output)


if __name__ == "__main__":
    main()
