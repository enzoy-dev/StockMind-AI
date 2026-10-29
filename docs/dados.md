# Contratos de dados

CSVs UTF-8 separados por vírgulas, com ponto decimal e datas YYYY-MM-DD.
Identificadores são textos; códigos como `001` preservam os zeros iniciais.
Arquivos demonstrativos estão em [data](../data). Todos são fictícios.

## Vendas

Obrigatórios: `sku,data,vendas`. O formato legado `data,vendas` recebe
`sku=PRODUTO-001`. Opcionalmente, `preco,promocao,feriado`.

- `vendas`: unidades inteiras não negativas, já agregadas por dia/produto.
- `preco`: número finito não negativo. Não é usado para estimar faturamento futuro.
- `promocao,feriado`: inteiros 0/1, conhecidos antes do período que se quer prever.
- Booleanos JSON não substituem números; use 0/1 explicitamente.
- Não há linhas duplicadas por SKU/data nem dias ausentes no intervalo de cadaSKU.
- Produtos podem começar em datas diferentes, mas terminam na mesma data.
- Catálogo sem vendas é permitido; não recebe demanda zero automaticamente.
- A entrada não transforma devoluções negativas nem transações brutas em unidades
  vendidas: essa preparação depende dos dados de origem.

Histórico curto é aviso, não erro. Duplicatas, lacunas e valores inválidos bloqueiam
a análise com relatório por campo/SKU/linha. Não complete lacunas com zero sem
confirmar que não houve vendas; o sistema não distingue falta de estoque de falta
de demanda a partir dessas duas colunas.

## Contexto futuro

Colunas `sku,data,preco,promocao,feriado`. Deve cobrir todos os próximos dias do
horizonte para todos os produtos das vendas. O exemplo tem 90 dias e pode ser usado
para pedir uma janela menor: datas posteriores são validadas e depois recortadas.
Datas anteriores/iguais à origem, duplicatas e lacunas na janela são erros.

O modelo contextual exige os três campos também no histórico. Colunas parciais
podem ser importadas, mas não habilitam esse modelo. Sem plano futuro, os métodos
continuam funcionando sem contexto e essa limitação é registrada.

As covariáveis históricas utilizadas no teste precisam ter sido conhecidas antes de
cada janela, como calendário de promoção e preço anunciado. Preço médio calculado
após as vendas, promoções registradas só depois ou feriados estimados a posteriori
podem introduzir vazamento que a validação de formato não consegue detectar.

## Produtos e estoque

```csv
sku,nome,fornecedor_id,estoque_atual,estoque_seguranca,pedido_minimo,multiplo_compra
CAF-001,Café,FOR-01,35,20,12,6
```

Quantidades inteiras não negativas; `multiplo_compra` pelo menos 1. Use estoque
disponível após reservas, ao fechamento do último dia das vendas. Todos os produtos
das vendas precisam estar no catálogo quando o planejamento estiver ativo.
Produtos adicionais são aceitos, com aviso de falta de histórico.

O cadastro é um snapshot: não há dedução automática do estoque ao inserir vendas
reais posteriormente. Ao avançar a data do histórico, atualize o estoque disponível.

## Fornecedores

```csv
fornecedor_id,nome,prazo_dias
FOR-01,Fornecedor A,5
```

Prazo inteiro de 0 a 60 dias corridos, contado da origem. O cadastro exige IDs únicos
e referências válidas. Estoque de segurança é informado, sem otimização estatística.
Compras feitas ao fechar o dia chegam em `data_compra + max(1,prazo_dias)`:
prazo zero significa a próxima manhã. Pedidos já abertos mantêm sua data explícita.

## Pedidos já abertos

```csv
pedido_id,sku,quantidade,data_entrega
PED-01,CAF-001,30,2026-10-23
```

`quantidade` inteira positiva; data após a origem; IDs únicos. Pedidos vazios são
aceitos. Um recebimento ocorre antes das vendas previstas do dia informado.
Compras sugeridas não criam pedidos automaticamente.

Os pedidos afetam o saldo somente em suas datas, inclusive no tamanho da compra.
Pedidos tardios não cobrem déficits anteriores. O saldo acumula déficits como diferença entre
estoque+entradas e vendas previstas, e não como estoque físico negativo.

## Atualização das vendas realizadas

O histórico para treinar deve ser contínuo. Já a atualização de realizações em
`POST /vendas` ou na aba Histórico pode conter dias avulsos:

```json
{"vendas":[{"sku":"CAF-001","data":"2026-10-21","vendas":20}]}
```

Esse exemplo é fictício. Ausência continua desconhecida; zero precisa ser enviado
explicitamente. Nova linha do mesmo SKU/data corrige a realização atual, sem alterar
snapshots de previsão. Use SKU explícito em carteiras com vários produtos.
