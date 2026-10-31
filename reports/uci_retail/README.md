# Benchmark real: UCI Online Retail

Fonte: Chen, D. (2015). **Online Retail** [Dataset]. UCI Machine Learning Repository.
DOI: [10.24432/C5BW33](https://doi.org/10.24432/C5BW33).
Licença do conjunto: [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/).

O catálogo oficial é https://archive.ics.uci.edu/dataset/352/online+retail.
Como esse domínio estava bloqueado no ambiente de execução, a planilha foi obtida
por uma cópia pública fixada em commit, indicada em [proveniencia.json](proveniencia.json).
A licença MIT do código desse espelho não substitui a licença dos dados da UCI.
O arquivo bruto não é redistribuído aqui; os agregados não incluem clientes ou faturas.
Os dados foram filtrados/agregados conforme descrito abaixo e não são o original intacto.

## Reproduzir

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-benchmark.txt
.\.venv\Scripts\python.exe -m scripts.benchmark_retail --download
```

Também é possível baixar o arquivo original e usar `--input CAMINHO`. A execução
verifica seu SHA-256 contra a cópia fixada, em vez de aceitar dados diferentes em
silêncio. Relatórios incluem o hash do motor de previsão e do arquivo de entrada.

## Preparação e alcance

- 541.909 linhas brutas, de um varejista britânico, em 2010–2011.
- Primeiro e último dia descartados por possível cobertura intradiária parcial.
- Retirados cancelamentos, quantidades/preços não positivos e códigos não-produto.
- Três SKUs selecionados pelo volume apenas no prefixo anterior aos últimos 90 dias.
- Agregação diária de unidades positivas registradas, incluindo zero quando não há
  fatura para o produto no extrato daquele dia. Isso não confirma demanda zero.
- Preço realizado não é informado como preço futuro planejado. Disponibilidade,
  perdas, estoque e prazos de fornecedor não existem nessa base.
- Cada horizonte de 7/14/30 mantém suas janelas temporais e teste final próprio.

[Vendas agregadas](vendas_agregadas.csv) e [métricas por horizonte](metricas.csv)
permitem revisar o resultado. Há métodos selecionados que perdem para a referência
semanal: por exemplo, no relatório de 7 dias, o produto 85099B apresentou MAE maior.
Não se escolhe um método diferente depois de observar o teste.

Esse recorte de três produtos não representa todo o varejo e pode ser sensível às
datas e a compras de grande volume. Ele mede previsão de unidades faturadas positivas,
sem cancelamentos/devoluções; não mede lucro, demanda perdida ou economia de estoque.
