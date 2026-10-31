# Quando e quanto comprar

As regras apoiam revisão humana, sem emitir pedidos ou modificar estoque real.
Todas as datas são relativas à origem da análise (fechamento do último dia de
vendas), que pode ser anterior à data de hoje.

## Convenção diária

- Recebimentos já abertos entram antes das vendas previstas na sua data explícita.
- Uma compra nova é feita no fechamento da data sugerida.
- A chegada é `data_compra + max(1,prazo_dias)`: prazo zero significa a próxima manhã.
- O saldo sem compras novas é estoque inicial + recebimentos − vendas previstas
  acumuladas. Negativo significa déficit aritmético, não estoque físico negativo.
- Saldo igual à segurança não é passagem abaixo dela; saldo zero com segurança
  zero também não é falta. A falta aparece quando a previsão ultrapassa o disponível.

Os déficits são mantidos no saldo para mostrar a diferença acumulada. A regra não
estima quantas dessas vendas seriam perdidas ou virariam pedidos em espera.

## Data sugerida

1. Localize o primeiro saldo estritamente abaixo do estoque de segurança,
   incluindo a origem se o disponível já estiver abaixo dela.
2. `data_limite_compra = primeira_abaixo_seguranca − max(1,prazo_dias)`.
3. `data_compra_sugerida = max(origem,data_limite_compra)`.

A data-limite pode já ter passado. Comprar agora não evita uma falta que ocorrerá
antes da chegada possível. O alerta pede revisão de recebimentos ou outra fonte
de estoque, sem afirmar que uma compra nova resolve esse intervalo.

Sem passagem abaixo da segurança no período, as datas e a quantidade futura ficam
vazias com `sem_gatilho_no_horizonte`. Isso não afirma suficiência após o horizonte.

## Quantidade na data

O saldo projetado já contém todas as vendas e os pedidos nas datas corretas.
Para uma compra na data B:

```text
chegada = B + max(1,prazo_dias)
fim_protecao = B + prazo_dias + revisao_dias
necessidade = max(0, seguranca − menor_saldo_projetado[chegada:fim_protecao])
```

Se positiva, aplica-se o mínimo e arredonda-se para cima ao múltiplo de compra.
Sem necessidade, não se compra só para cumprir o mínimo. Os pedidos não são
subtraídos novamente, pois já estão no saldo.

`compra_sugerida` usa B=origem. `quantidade_compra_na_data` usa a data futura
calculada; assim considera a depleção anterior e uma janela de proteção deslocada.
O alvo agregado e a posição de estoque permanecem informativos: a compra usa o
maior déficit diário após a chegada, evitando que um pedido tardio esconda uma falta.

Se não há previsão até o fim da proteção, a quantidade fica vazia e
`horizonte_necessario_agendamento` indica a cobertura necessária. As datas já
conhecidas continuam visíveis. Pode haver cobertura para comprar na referência,
mas não para dimensionar a compra futura. Nenhuma previsão é extrapolada em silêncio.

Se pedidos existentes cobrem o saldo após a entrega possível e a quantidade é zero,
a data acionável fica vazia (`sem_compra_adicional`). Déficits anteriores continuam
visíveis e podem exigir ação urgente.

## Prioridades e excesso

| Prioridade | Regra |
| --- | --- |
| Crítica | Falta anterior à primeira entrega possível, mesmo com compra adicional zero |
| Alta | Prazo teórico vencido, compra na origem ou falta dentro do período de revisão |
| Média | Segurança cruzada, cobertura insuficiente ou possível excesso |
| Baixa | Nenhuma das condições anteriores dentro do período previsto |
| Indefinida | Produto sem previsão |

Os motivos acompanham cada linha. Histórico curto aparece como estimativa inicial;
a prioridade é calculada sobre essa trajetória provisória e não é probabilidade.
Excesso compara disponível + pedidos até 30 dias com vendas previstas de 30 dias +
segurança. `unidades_acima_alvo_30dias` quantifica a diferença; sem 30 dias,
a avaliação fica vazia. Pode haver excesso e falta antes de um pedido chegar.

## Valores manuais e sugestões calculadas

As opções novas de segurança e prazo alteram cópias dos parâmetros, com amostras
registradas e fallback manual. Por isso, o tamanho e a data de compra podem mudar
quando são habilitadas. Os valores originais continuam preservados no snapshot.
A classificação ABC/XYZ é descritiva e não troca a política automaticamente.

O exemplo agora inclui indisponibilidade e novos candidatos de previsão. Os
resultados numéricos da versão anterior não devem ser interpretados como fixos.
Confira as tabelas atuais e suas premissas em [Confiabilidade](confiabilidade.md).

## Cenários de demanda

A variação informada (0% a 80%) gera trajetórias menor/base/maior:
`previsao × (1−p/100)`, `previsao` e `previsao × (1+p/100)`.
Só as vendas previstas mudam. Estoque, pedidos, preços e política permanecem iguais.
Cada trajetória recalcula datas, quantidades, faltas e excesso. Compras sugeridas
não são tratadas como recebimentos.

Esses cenários são uma análise de sensibilidade determinística. Não têm
probabilidade atribuída, não representam um intervalo de confiança e não são
trajetórias construídas juntando limites estatísticos por dia. A variação percentual
não retreina os modelos nem recalibra as faixas. Com p=0, as três trajetórias coincidem.
