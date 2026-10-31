# Comparabilidade, desempenho e avaliação

## Classificação por período comum

O serviço usa `janela_classificacao=90` dias corridos terminando na última data das
vendas. Produtos com cobertura completa são comparados na mesma janela. Um produto
recente não tem suas vendas projetadas para preencher dias anteriores: recebe
ABC provisória e fica fora do denominador das classes definitivas. Seu valor
registrado continua visível. XYZ também usa os dias da janela, exigindo observações
confirmadas disponíveis. A função descritiva `classificar_produtos(..., janela_dias=None)`
preserva a análise antiga do histórico inteiro para chamadas existentes.

A UI permite 30/60/90/180/365 dias; a API aceita inteiros de 1 a 3650. A escolha da
janela muda o significado da classificação, não o modelo de previsão.

## Reutilização dos cálculos

`stockmind/cache.py` guarda até 16 entradas por processo por até cinco minutos.
As chaves incluem conteúdo/dtypes dos dados, horizonte e contexto efetivamente
utilizado. Previsões não dependem de estoque, mínimo de compra, variação de cenários
ou custos. Alterar só esses parâmetros reutiliza os resultados da previsão.

A comparação de horizontes compartilha as entradas individuais de 7/14/30, evitando
ajustar novamente o horizonte principal. Erros de calibração de reposição têm chave
própria com dados, métricas e prazos. Prazos ou dados diferentes invalidam esse cálculo.
Resultados retornam como cópias para evitar mutação de análises anteriores.

É cache em memória, sem arquivo de modelo nem sincronização entre processos. Pode
conter dados enviados enquanto a aplicação local estiver aberta. Reiniciar limpa
as entradas. O cache não substitui os snapshots explícitos do SQLite.

## Estabilidade na validação

Cada método mostra mínimo, máximo e desvio populacional dos MAEs das janelas,
quantas venceu e a proporção de vitórias. Empates numéricos contam para todos os
empatados, portanto a soma de vitórias pode ultrapassar o número de janelas.
Essas informações usam somente validação, sem mudar a seleção pelo teste final.
Uma única janela não demonstra estabilidade, mesmo com desvio descritivo zero.

## Políticas em vários períodos

`numero_periodos_simulacao` varia de 1 a 6. Com avaliação habilitada, valores maiores
que um acrescentam janelas históricas sem sobreposição de `periodo_simulacao` dias.
Em cada janela, o replay reinicia o estoque e parâmetros manuais declarados; não é
uma trajetória contínua nem reconstrução do estoque histórico. Só dados anteriores
à decisão alimentam seus modelos. Janelas sem cobertura não geram resultados fictícios.

Os resultados originais do período mais recente continuam em `avaliacao_reposicao`.
Os novos campos `avaliacao_multiperiodo`, `diario_multiperiodo` e `consistencia_politicas`
mostram os períodos e estatísticas descritivas. Custos médios devem ser comparados
sobre os mesmos períodos válidos; contagens de cobertura ficam explícitas. Mais
janelas custam processamento. Isso não demonstra economia real.

## Estoque previsto versus registrado

Snapshots esparsos podem ser importados na aba Histórico ou em `POST /estoques-reais`:

```json
{"estoques":[{"sku":"A","data":"2026-10-21","estoque_real":47}]}
```

São unidades inteiras não negativas, uma linha por SKU/data, ao fechamento do dia.
Uma correção atualiza apenas o observado. `GET /analises/{id}/estoque-real` conserva
os saldos originais e compara só as datas com observação, sem preencher ausências.
O SQLite acrescenta uma tabela idempotentemente; os snapshots existentes não mudam.

O saldo aritmético negativo do planejamento representa déficit, não estoque físico.
A comparação usa `max(0,saldo_aritmetico)` e mantém ambos os valores na tabela.
Não reconcilia reservas, perdas ou vendas não atendidas, nem atribui causa à diferença.
Importe somente observações de dias encerrados; a análise não comprova a origem dos dados.

## Benchmark real

Consulte [UCI Online Retail](../reports/uci_retail/README.md). Os resultados e a
preparação são reproduzíveis, com hash do arquivo de entrada e seleção de produtos
anterior aos períodos de teste. O objetivo é prever vendas registradas. Não há
dados de estoque/disponibilidade para afirmar recuperação de demanda perdida.

## Interface e diagnóstico de testes

`app.py` é a entrada. `stockmind/ui/` separa componentes, formulários, previsões,
decisões, cenários, avaliação e histórico. Dashboard e API continuam compartilhando
o serviço de domínio, sem treinar modelos dentro dos componentes de apresentação.

A CI executa `python tools/run_tests.py` nas duas plataformas e publica
`test-results-ubuntu-latest` e `test-results-windows-latest`, inclusive quando testes
falham. Cada artefato contém `unittest.log` com nomes/tracebacks e `junit.xml`.
O código de saída de falha é preservado e um SO não cancela a coleta do outro.
A API do GitHub/log autenticado estava inacessível neste ambiente; o resumo enviado
do erro anterior de Windows não continha o traceback. A causa anterior permanece
sem diagnóstico confirmado. Não há exclusão de testes de Windows nesta alteração.

A [execução de verificação #10](https://github.com/enzoy-dev/StockMind-AI/actions/runs/41246244317)
também terminou com erro no job Windows e publicou os dois artefatos. A falha de
Windows continua pendente. Para continuar o diagnóstico, abra essa execução com
login, baixe `test-results-windows-latest` em **Artifacts**, extraia `unittest.log`
e consulte o bloco `ERROR`/`Traceback` no final. O resumo `Process completed with
exit code 1` não identifica o teste nem a causa.
