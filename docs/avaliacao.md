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
- Regressão com ciclo mensal: tendência/calendário e ciclo do dia do mês, com
  pelo menos 90 observações de venda elegíveis em cada treino de validação.
- Regressão com ciclo anual: calendário anual, com pelo menos 730 observações de venda elegíveis
  em cada treino de validação. Esses limiares são critérios de elegibilidade,
  não prova de que exista sazonalidade.
- Gradient Boosting: 40 árvores, profundidade 2, folha mínima 5, taxa .05 e semente
  42. Usa atributos de calendário conhecidos; exige pelo menos 60 alvos disponíveis
  por treino de validação. Parâmetros fixos, sem escolha pelo erro de teste.
- Regressão com contexto: tendência, indicadores, preço, promoção e feriado;
  padronização+Ridge (`alpha=1`) ajustados somente no histórico disponível de cada janela.

Observações elegíveis excluem as marcadas como censuradas. No formato legado sem
disponibilidade, são vendas observadas com essa limitação explícita, não confirmação
de demanda completa. Não há busca automática de hiperparâmetros. Valores negativos previstos são
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

## Disponibilidade e fallback

`disponivel=0` indica vendas censuradas: a quantidade registrada é preservada,
mas não é usada como demanda em alvos de treinamento, validação, teste ou calibração.
Regressões de calendário/contexto usam só alvos disponíveis, preservando suas datas.
Métodos semanais, Croston e atrasos precisam de um sufixo contínuo disponível.

A elegibilidade dos candidatos usa apenas prefixos da validação. Uma indisponibilidade
posterior não pode mudar retroativamente o vencedor. Se ele não puder ser ajustado
num bloco posterior, esse erro fica ausente; não se substitui uma previsão por
fallback enquanto se atribui o resultado ao modelo original. Se o ajuste operacional
for inviável, a média dos dias observáveis é identificada como fallback através de
`modelo_validacao`/`modelo_operacional`, sem transferir a faixa do modelo anterior.

Todos os dias censurados deixam o produto sem previsão, com `demanda_indisponivel`.
A análise pode ser salva com zero pontos, preservando seu diagnóstico. Ausência da
coluna não confirma disponibilidade: os resultados descrevem vendas observadas e
registram essa limitação. Consulte [segurança e avaliação de políticas](confiabilidade.md).

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

## Exemplos sintéticos reproduzíveis

A carteira fictícia contém três produtos com 420 dias, um com dez dias e um
produto cadastrado sem histórico. A origem é 20/10/2026. Há registros artificiais
de indisponibilidade e 24 entregas de fornecedores. Não são dados de uma empresa.
O exemplo de sazonalidade tem 1.100 dias confirmados disponíveis, permitindo
avaliar o candidato anual quando o treino de cada janela tiver suporte.

Os [resultados atuais por produto/horizonte](avaliacao_exemplo.csv) incluem datas,
número de alvos avaliados, censura, método escolhido e método operacional. Para
regenerar, execute `python -m scripts.evaluate_examples` na raiz. Os dados vêm de
`scripts/generate_examples.py`, com sementes fixas. Mudanças nos exemplos/modelos
podem alterar os números; nenhum deles mede retorno comercial.

A comparação tem uma linha por SKU/horizonte com seleção própria para 7/14/30.
Os períodos de teste diferem; erros com datas ou amostras distintas não medem
exatamente a mesma dificuldade. Um método novo pode perder para a referência.

## Limites atuais

Ainda faltam avaliação em dados reais de origem conhecida e validação comercial
das recomendações. O tratamento de censura, o monitoramento e o replay de políticas
são ferramentas de estudo com premissas explícitas; não recuperam demanda perdida
nem demonstram economia real.
Não há múltiplos depósitos, perecibilidade, calendário de compras otimizado ou
estimativa causal do impacto das promoções.
