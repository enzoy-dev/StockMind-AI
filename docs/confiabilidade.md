# Disponibilidade, segurança e avaliação das decisões

## Disponibilidade histórica

No CSV de vendas, `disponivel` é opcional, inteiro 0/1, completo quando informado:

- 1: produto disponível durante todo o dia.
- 0: indisponibilidade durante parte ou todo o dia; vendas registradas são censuradas.

Zero vendas com disponibilidade 1 é uma observação de zero. Disponibilidade 0 não
revela a demanda perdida. Não se substituem as vendas por zero, nem se inventam
alvos para completar o histórico. A coluna ausente significa desconhecida.
Disponibilidade futura não é aceita como covariável planejada.

Os modelos excluem alvos censurados e mostram contagens de amostras. Quando não
há demanda observável, a análise retorna diagnóstico sem fabricar previsões.
A comparação com realizações também exclui esses alvos do MAE/viés/cobertura,
preservando a venda registrada e distinguindo dias observados de dias avaliados.

## ABC e XYZ

ABC usa o total de `vendas × preco` informado, como faturamento registrado, se
todos os preços de todos os produtos estiverem disponíveis. Sem essa cobertura,
a base passa a unidades para todos os produtos, sem misturar bases monetárias
com quantidades. Não considera custos nem mede lucro.

A fronteira usa o acumulado anterior ao grupo de valores empatados: o grupo que
cruza 80% permanece A; o que cruza 95% permanece B. Empates ficam juntos. Valores
zero são C se houver base positiva; total zero fica indefinido.

XYZ usa desvio-padrão amostral/média das vendas em pelo menos 28 dias confirmados
disponíveis: X até 0,5; Y até 1; Z acima de 1. Média zero, histórico curto ou
coluna de disponibilidade ausente deixam a classe indefinida. Essa classificação
é descritiva e não muda a prioridade ou a política de compra automaticamente.

## Histórico de entregas e prazo sugerido

CSV de recebimentos já concluídos:

```csv
entrega_id,fornecedor_id,data_pedido,data_prevista,data_recebida
ENT-01,FOR-01,2026-09-01,2026-09-06,2026-09-08
```

IDs únicos, datas sem horário, pedido anterior/igual à previsão e ao recebimento.
Entregas antecipadas são permitidas. Recebimento posterior à origem da análise
é rejeitado. Prazos planejados/realizados de até 365 dias são aceitos no histórico.
Pedidos ainda abertos continuam no CSV de pedidos, com `data_entrega`.

Com pelo menos cinco recebimentos por fornecedor, mostra média, desvio, atraso e
P90 empírico do prazo real, arredondado para cima. É uma estimativa histórica,
sem garantia de atendimento. Sugestões acima dos 60 dias aceitos pelo planejador
ficam indefinidas, sem truncar o prazo para um valor menor.

A opção **Aplicar prazo sugerido pelo histórico de entregas** usa a estimativa
na cópia da análise. O cadastro manual e os inputs salvos continuam preservados.
Sem amostras suficientes, mantém-se o prazo manual e a tabela explica o motivo.

## Estoque de segurança calculado

Para o método selecionado, a calibração reservada produz blocos sem sobreposição
do prazo de reposição. O erro acumulado é demanda observável do bloco menos a
previsão feita antes dele. O teste final não gera essas amostras.

```text
segurança sugerida = ceil(max(0, quantil90(erros acumulados)))
```

São exigidos cinco blocos sem sobreposição, separados do teste, do mesmo método/prazo, com prazo positivo
e alvos confirmados disponíveis. Sobreposições e proxies de vendas são excluídos;
duplicatas conflitantes são rejeitadas. Prazo zero ou histórico insuficiente mantêm
a segurança manual. Não se calcula uma reserva a partir de demanda desconhecida.

O período de calibração continua sendo duas vezes o horizonte. Por isso, horizonte
7 com prazo 5 pode não fornecer cinco blocos; horizonte 30 pode fornecer. A faixa
estatística diária de 90% e a segurança acumulada têm finalidades distintas.
O quantil é empírico: não garante um nível de serviço de 90%.

A opção **Aplicar estoque de segurança calculado** altera apenas a cópia usada
nas projeções e cenários. A tabela distingue valor manual, sugerido, amostras e
aplicação. O usuário pode manter a configuração manual.

## Replay das políticas de reposição

A opção de avaliação compara **Sem reposição**, **Média histórica** e **Previsão
selecionada**, nos últimos 7, 14 ou 30 dias, com as mesmas condições iniciais.

- Estoque inicial do catálogo é uma premissa do cenário, não o estoque real passado.
- Prazos, segurança, mínimos e lotes são os valores manuais declarados. Estimativas
  aprendidas hoje não são aplicadas retroativamente ao período de avaliação.
- Não se copiam os pedidos atualmente abertos para uma época anterior.
- Cada decisão usa somente vendas já observadas até seu fechamento. Recebimentos
  simulados entram antes das vendas do dia; prazo zero chega na próxima manhã.
- O estoque físico fica em zero quando insuficiente; a demanda não atendida é
  contada, sem virar estoque físico negativo. Não há backorders neste replay.

Conhecida indisponibilidade em qualquer dia do período bloqueia o replay do
produto: não se conhece sua demanda completa. Se a coluna não existir, somente a
opção explícita **Assumir vendas como demanda** permite um cenário com esse proxy.
Essa opção nunca libera dias sabidamente censurados. O replay pressupõe demanda
conhecida após cada dia, inclusive perdas simuladas; não modela como a própria
política limitaria a observação da demanda futura.

As métricas incluem unidades não atendidas, atendimento, estoque médio/final,
pedidos e custos assumidos por falta, unidade em estoque/dia e pedido.
Os custos padrão são exemplos em unidades monetárias e podem ser alterados.
Não são economia medida ou ROI. A linha inicial do diário registra a primeira
decisão e não entra no estoque médio nem no custo de manutenção.

## Monitoramento de previsões salvas

O botão na aba Histórico e `GET /monitoramento` comparam erros recentes com uma
base anterior por SKU/horizonte. A janela recente tem sete dias e a base 21 por
padrão; um alerta exige pelo menos sete e quatorze alvos avaliáveis, respectivamente.
Aumento de MAE de pelo menos 30% gera alerta; base com erro zero recebe tratamento
explícito, sem divisão por zero. Também se mostra a direção descritiva do viés.
Perda para a referência semanal gera um motivo de alerta quando ambos são
comparados nos mesmos alvos, com sete amostras recentes e quatorze de base. Isso
não é teste de significância nem comprovação de deterioração causal.

Somente previsões gravadas **antes do dia previsto**, no fuso America/Sao_Paulo,
entram no monitoramento prospectivo. Reruns do próprio dia ou posteriores são
retrospectivos; realizações de dias futuros e alvos censurados são excluídos.
Sobreposições são deduplicadas por SKU/data, escolhendo a origem mais recente,
depois criação e ID, entre previsões elegíveis. A referência usa somente o snapshot.

Disponibilidade ausente permanece identificada como avaliação de vendas observadas.
As janelas terminam na última realização elegível, não necessariamente hoje.
Uma mudança de erro sinaliza investigação; não comprova mudança causal de demanda.
O monitoramento é leitura local, sem envio de mensagens ou gravação de alertas.

Os exemplos com origem 20/10/2026 salvos depois de seus dias-alvo são retrospectivos.
É esperado que não sustentem um alerta prospectivo: a tela informa as exclusões.
