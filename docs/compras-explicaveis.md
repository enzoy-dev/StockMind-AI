# Compras explicáveis, orçamento e cenários de estresse

A análise acrescenta memória de cálculo e diagnóstico por SKU, sem enviar compras.
A recomendação original continua disponível para revisão. Não há garantia de
nível de serviço, lucro ou eliminação de ruptura.

## Memória e diagnóstico

`memoria_compras` contém duas linhas por produto: comprar na origem e comprar na
data agendada. Mostra estoque, segurança, prazo, revisão, chegada, fim da proteção,
menor saldo/data, necessidade antes do lote, mínimo/múltiplo e quantidade final.
Recebimentos e consumo acumulados explicam o caminho até o fim da proteção.
Pedidos já fazem parte do saldo e não são descontados novamente.

`diagnosticos_decisao` usa os estados `avaliada`, `provisoria` e `insuficiente`.
Sem trajetória ou cobertura da janela, não há dimensionamento sustentado.
Disponibilidade desconhecida/censurada, histórico inicial, ausência de faixa e
perda para a referência no teste recebem ressalvas. O diagnóstico é uma regra
explicativa de dados, não confiança probabilística ou aprovação automática.
Dados de disponibilidade são declarados pelo usuário, não auditados pelo sistema.

## Reserva do orçamento

Campos opcionais da API, também disponíveis no dashboard:

```json
{
  "orcamento_compras": "1000.00",
  "custos_unitarios": {"CAF-001": "12.50", "CHA-002": "7.20"}
}
```

São custos de aquisição informados separadamente do preço de venda histórico.
Orçamento e custos devem estar na mesma moeda. O orçamento é não negativo; custos
são positivos e ambos aceitam até duas casas, sem arredondamento silencioso.
Valores inválidos, não finitos e SKUs fora do catálogo são recusados.
Custos ausentes deixam o SKU sem reserva, com motivo; não viram zero.

A ordenação é prioridade comercial existente, dias até falta e SKU, com ausências
no final. A heurística percorre essa ordem, reserva no máximo a quantidade da
compra agendada, respeita mínimo e múltiplo e passa ao próximo produto quando o
mínimo não cabe. Compras parciais permanecem identificadas. Internamente o dinheiro
é inteiro em centavos e a API devolve strings decimais.

O resultado `plano_orcamento` guarda quantidade desejada/reservada/descoberta,
custos, saldo e ressalvas dos dados. `resumo_orcamento` reconcilia orçamento,
reservado e restante. A reserva abrange as compras sugeridas em todo o horizonte,
sem fluxo de caixa por data, frete, tributos ou otimização de lucro. Não é uma
solução de mochila ótima. Uma compra parcial pode deixar déficit; o saldo original
não é reescrito como se a reserva tivesse sido recebida. Compare os dois resultados.
Sugestões provisórias podem entrar na reserva, com suas ressalvas explícitas.

## Políticas sob estresse

Ative `avaliar_estresse=true`. `atraso_fornecedor_dias` vai de 0 a 30 (padrão 3);
`choque_demanda_pct` vai de 0 a 80 (padrão 20). Há cinco cenários: base, prazo
ampliado, demanda maior, demanda menor e combinado. Usa os mesmos parâmetros de
período, revisão, número de períodos, demanda proxy e custos do replay existente.

O prazo ampliado é conhecido por todas as políticas desde o início: este cenário
não simula descobrir um atraso surpresa depois de emitir o pedido. Prazo resultante
acima de 60 é recusado, sem truncar. O estoque reinicia a cada janela.
Só as realizações no bloco avaliado recebem o choque; o treino anterior permanece
igual. A quantidade contrafactual é arredondada para cima a unidades inteiras e
entra no prefixo apenas depois do fechamento correspondente. Para demanda menor,
o arredondamento pode produzir alteração efetiva menor em séries de baixo volume.

Conhecida censura continua bloqueando avaliação; desconhecimento exige autorizar
vendas como proxy. Custos e diferenças para a base só são reportados quando
mensuráveis. As tabelas `avaliacao_estresse` e `diario_estresse` preservam cenário,
janela e premissas. As diferenças são sensibilidade do cenário, não economia real.
Mais cenários/períodos aumentam custo de processamento; a opção vem desativada.

## Persistência e compatibilidade

API e dashboard compartilham o serviço. Ao salvar uma análise, resultados e
parâmetros (inclusive custos) ficam no snapshot original. Corrigir dados posteriores
não reescreve esse registro. As novas opções são desativadas ou nulas por padrão;
os snapshots antigos continuam consultáveis e a tela tolera ausência dos campos.

## Benchmark ampliado

[Relatórios por perfil](../reports/uci_retail_expanded/README.md) complementam o
recorte original de três produtos. Eles avaliam vendas registradas e não validam
estoque, demanda perdida ou retorno financeiro das recomendações.
