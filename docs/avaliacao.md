# Modelagem e avaliação

## Métodos

- Última venda: mantém o último valor observado.
- Semana anterior: repete os últimos sete dias, alinhados ao dia da semana.
- Média recente: média dos últimos até 28 dias.
- Croston-SBA: suaviza tamanho e intervalo das vendas não zeradas, com correção
  SBA e `alpha=0.1` fixo. É candidato para séries com vendas esporádicas, não uma
  garantia de superioridade nesses produtos.
- Regressão linear: tendência em dias desde o início.
- Regressão com dia da semana: tendência e seis indicadores, segunda como referência.
- Regressão com atrasos: `StandardScaler + Ridge(alpha=10)`, atrasos de 1/7/14 dias,
  médias móveis de 7/14 dias e calendário. Atributos do treino usam apenas vendas
  anteriores ao alvo; na previsão de vários passos, os atrasos usam as previsões
  já geradas. Só participa se o primeiro treino de validação tiver pelo menos 42 dias.
- Regressão com contexto: tendência, indicadores, preço, promoção e feriado;
  padronização+Ridge (`alpha=1`) ajustados somente no histórico disponível de cada janela.

Não há busca automática de hiperparâmetros. Valores negativos previstos são
limitados a zero. Não se agregam vendas de produtos distintos para treinar.

## Separação temporal

Para horizonte `h`, o último bloco de `h` dias é o teste final intocado.
Antes dele, reservam-se 2 blocos de `h` para calibração quando há pelo menos
`14+4*h` observações. Antes da calibração ficam até 3 janelas consecutivas de
validação, com treino inicial de pelo menos 14 dias e origem crescente.
Sem dados para calibração, as janelas terminam antes do teste e as faixas ficam vazias.

O menor MAE agregado da validação escolhe o método. Diferenças de até `1e-9`
favorecem a ordem dos métodos acima. A calibração não troca o vencedor e o teste
não escolhe nem método nem largura de faixa. Cada previsão histórica só recebe
vendas anteriores à janela, com covariáveis daquele futuro conhecido quando aplicável.

Para a previsão operacional, o vencedor é ajustado com todo o histórico disponível.
Isso inclui o teste histórico, pois ele já é passado na origem operacional. As
métricas continuam sendo as previsões que foram calculadas sem esses valores.

Se há menos de `14+2*h` dias, não existe validação+teste suficiente: usa-se média
dos últimos até 14 dias, status de histórico curto, sem métricas/faixas inventadas.
Produto sem nenhuma venda no catálogo fica sem previsão e compra sugerida.

## Faixas empíricas

Resíduos absolutos de previsões externas ao treino, em dois blocos de calibração,
produzem uma largura com quantil conservador de referência 90%. O limite inferior
é cortado em zero. A cobertura é medida no teste final separado e mostrada em %.

São faixas **por ponto**, de largura constante por produto/análise. Dependência
temporal, mudança de padrão e seleção de modelos impedem uma garantia automática
de cobertura nominal. Não são limites simultâneos para todos os dias nem uma
probabilidade de ficar sem estoque. O cálculo de compra usa a previsão pontual e
segurança informada, sem afirmar otimização probabilística.

## Métricas

- MAE: média dos erros absolutos, unidades/dia.
- WAPE: soma dos erros absolutos/soma das vendas reais×100; vazio se o denominador é zero.
- Viés: média de previsão−venda real; positivo significa previsão acima do realizado.
- Cobertura: fração de vendas dentro da faixa×100; vazia sem faixa válida.
- Redução do MAE frente à semana anterior: `(MAE_semanal - MAE_escolhido) / MAE_semanal × 100`.
  Positiva indica erro menor; negativa indica piora. Fica vazia quando o erro da
  referência é zero ou não há avaliação. O resultado não escolhe o método.

Não se publica uma “precisão geral da IA”. Produtos de volumes distintos exigem
leitura individual dos erros, incluindo erros altos em produtos esporádicos.

## Exemplo sintético reproduzível

Gerado com semente 42 em `scripts/generate_examples.py`. Origem 20/10/2026;
três produtos com 420 dias, um com 10 dias e catálogo com um produto sem histórico.
Preço/promoção/calendário são artificiais e conhecidos no exemplo. Não há ruptura
simulada nem resultados comerciais medidos.

No horizonte 30, com contexto completo e o novo candidato com atrasos, a execução produziu:

| Produto | Método selecionado | MAE teste | WAPE teste (%) | Cobertura teste (%) |
| --- | --- | ---: | ---: | ---: |
| CAF-001 | Regressão com contexto | 1,80 | 8,21 | 96,67 |
| CHA-002 | Regressão com contexto | 1,74 | 14,24 | 86,67 |
| CAC-003 | Regressão com atrasos | 2,63 | 151,54 | 90,00 |
| NOV-004 | Estimativa inicial | — | — | — |

Esses números ilustram inclusive um erro relativo alto e cobertura abaixo de 90%
para um produto. Não comprovam utilidade em dados reais. Para reproduzir, abra a
carteira fictícia, selecione 30 dias, mantenha contexto ligado e confira as métricas.

## Comparação de 7, 14 e 30 dias

`comparar_horizontes` executa a mesma separação temporal para cada horizonte e
retorna uma linha por SKU/horizonte com o método selecionado, datas de teste,
janelas, erros e referência semanal. A comparação não escolhe um horizonte
“vencedor”: os períodos de teste são diferentes. Contexto planejado mais longo é
recortado corretamente para cada horizonte, sem desabilitar o modelo contextual.

No mesmo exemplo, a redução do MAE no teste frente à referência semanal foi:

| Produto | 7 dias | 14 dias | 30 dias |
| --- | ---: | ---: | ---: |
| CAF-001 | 32,14% | 42,50% | 50,34% |
| CHA-002 | -11,76% | 38,94% | 42,08% |
| CAC-003 | 0,00% | 19,05% | 9,42% |

O produto CHA-002 perde para a referência no teste de 7 dias. O novo candidato
com atrasos selecionado para CAC-003 tem erro de teste maior que o Croston-SBA
selecionado na versão anterior (2,63 contra 2,57). Não se muda a escolha usando
esse teste: são exemplos de por que um modelo novo e uma boa validação não
garantem melhora futura. Os valores são apenas do conjunto sintético incluído.

## Limites atuais

Ainda faltam avaliação em dados reais de origem conhecida, tratamento de rupturas
históricas, monitoramento de mudança de padrão e avaliação econômica da reposição.
Não há múltiplos depósitos, perecibilidade, calendário de compras otimizado ou
estimativa causal do impacto das promoções.
