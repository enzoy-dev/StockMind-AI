# UCI Online Retail — nove produtos em três perfis de treinamento

Fonte: Chen, D. (2015), Online Retail, UCI Machine Learning Repository.
DOI: [10.24432/C5BW33](https://doi.org/10.24432/C5BW33).
Licença dos dados: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Este recorte é filtrado e agregado; não é o arquivo original intacto. Não inclui
identificadores de clientes ou faturas. Fonte, espelho fixado e SHA-256 estão em
[proveniencia.json](proveniencia.json), como no [benchmark original](../uci_retail/README.md).
A licença do código do espelho não substitui a licença do conjunto de dados.

## Reprodução

```bash
python -m pip install -r requirements-benchmark.txt
python -m scripts.benchmark_retail --download --estratificado --products 9 --output reports/uci_retail_expanded
```

Alternativa: `--input caminho/OnlineRetail.xlsx`, com o mesmo hash de entrada.
A opção sem `--estratificado` preserva a seleção por volume do benchmark anterior.

## Seleção anterior à avaliação

Todos os perfis usam somente o prefixo até 09/09/2011, anterior aos últimos 90 dias.
São nove SKUs distintos, em seleção sequencial e sem reposição:

1. Três maiores volumes de unidades positivas faturadas no treino.
2. Entre os restantes, três com maior fração de dias sem fatura no treino.
3. Entre os restantes, três com maior coeficiente de variação diário no treino.

Exige-se pelo menos 28 dias com fatura por SKU, para evitar extremos baseados em
um único evento. A média, variância e ausência de fatura usam o calendário diário
completo do treino. Os desempates usam volume e código em ordenação estável.
Os rótulos são descrições deste procedimento, não classes populacionais disjuntas:
um produto de alto volume também pode ser variável/intermitente.

Mantêm-se os filtros documentados: sem cancelamentos, quantidades/preços não
positivos ou códigos não-produto; exclusão conservadora dos dois dias de borda.
Ausência de fatura vira zero de venda registrada, sem afirmar disponibilidade
ou demanda zero. Não há preço futuro planejado, estoque ou prazo de fornecedor.

## Resultados e limites

- [Perfis e estatísticas apenas do treino](perfis_treino.csv).
- [Vendas diárias agregadas](vendas_agregadas.csv).
- [27 comparações produto/horizonte](metricas.csv), com ganhos, empates e perdas.
- [Contagens por perfil e horizonte](resumo_perfis.csv).

Na execução registrada, os métodos selecionados superaram a referência semanal
em 2/9 comparações de 7 dias, 5/9 de 14 dias e 4/9 de 30 dias. Empates não contam
como melhora. Isso não é percentual geral de acerto: são comparações de MAE em
períodos finais distintos por horizonte, em um recorte pequeno e dirigido.

A seleção é anterior ao teste, mas não aleatória nem representativa de todo varejo.
A base é histórica de 2010–2011 e inclui compras volumosas. Os resultados não são
novos períodos independentes do benchmark anterior: os três produtos de volume
permanecem os mesmos. Não somar as duas avaliações como amostras independentes.
Não foi escolhido outro modelo depois de observar o teste. Este benchmark não
mede redução de faltas, recuperação de demanda ou economia de compras.
