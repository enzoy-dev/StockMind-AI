# API local

A API e o dashboard usam o mesmo serviço de análise e podem compartilhar o SQLite.
Nenhum servidor foi publicado; os comandos abaixo abrem somente em localhost.

```powershell
.\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Swagger: `http://127.0.0.1:8000/docs`. O padrão do banco é `data/stockmind.sqlite3`;
`STOCKMIND_DB` altera o caminho. Defina as variáveis antes de iniciar o processo.

## Rotas

| Método e rota | Comportamento |
| --- | --- |
| `GET /health` | Estado do processo e indicação de chave configurada; não testa o banco |
| `POST /analises` | Valida, prevê e salva entradas+resultado em transação; retorna 201 e ID |
| `GET /analises` | Lista análises, com `limit` de 1 a 1000, padrão 100 |
| `GET /analises/{id}` | Snapshot original de entradas e resultados |
| `GET /analises/{id}/comparacao` | Compara previsões salvas com realizações já registradas |
| `POST /vendas` | Insere/corrige realizações por SKU/data, inclusive dias avulsos |
| `GET /planejamento` | Produtos, fornecedores, pedidos e data do estoque salvo |
| `PUT /planejamento` | Substitui o cadastro completo em uma transação |
| `POST /estoques-reais` | Importa snapshots observados de estoque |
| `GET /analises/{id}/estoque-real` | Compara saldo projetado e estoque observado |
| `GET /monitoramento` | Diagnóstico prospectivo de erro, sem gravar alertas |

## Exemplo de análise

Gere um JSON com os dados fictícios incluídos:

```powershell
.\.venv\Scripts\python.exe scripts/api_payload.py
$body = Get-Content -Raw -Encoding UTF8 data/requisicao_exemplo.json
$resposta = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/analises -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
$resposta.id
```

No Linux/macOS, com API aberta em outro terminal:

```bash
.venv/bin/python scripts/api_payload.py
curl --json @data/requisicao_exemplo.json http://127.0.0.1:8000/analises
```

O corpo aceita:

```json
{
  "vendas": [{"sku":"A","data":"2026-10-20","vendas":10}],
  "horizonte": 7,
  "contexto_futuro": null,
  "produtos": null,
  "fornecedores": null,
  "pedidos": null,
  "revisao_dias": 7,
  "comparar_horizontes": false,
  "variacao_cenario_pct": 20.0,
  "usar_planejamento_salvo": false,
  "entregas": null,
  "seguranca_automatica": false,
  "ajustar_prazos": false,
  "avaliar_reposicao": false,
  "assumir_vendas_como_demanda": false,
  "periodo_simulacao": 30,
  "custo_falta_unitario": 1.0,
  "custo_estoque_unitario_dia": 0.01,
  "custo_pedido": 1.0
}
```

Uma única observação produz estimativa inicial sem avaliação. O script gera uma
carteira maior, com contexto, estoque e horizonte 30. Os contratos são os mesmos
dos [CSVs](dados.md). Produtos/fornecedores são opcionais juntos para previsão
sem estoque; pedidos podem ser omitidos ou `[]`.

O retorno inclui `id` e `resultado`, com `previsoes,metricas,saldos,recomendacoes,qualidade`,
origem e horizonte. Valores desconhecidos aparecem como `null`, não como 0.

`comparar_horizontes:true` habilita o resumo por SKU para 7/14/30 dias, mantendo o
horizonte principal para a previsão e o planejamento. Nesse caso, o contexto futuro,
se enviado, precisa cobrir `max(horizonte,30)` dias. O padrão `false` preserva o
comportamento das requisições anteriores.

`variacao_cenario_pct` é um número finito de 0 a 80, padrão 20. Com planejamento,
gera demanda menor/base/maior por sensibilidade percentual. Strings e booleanos
não são aceitos como percentual; `comparar_horizontes` exige booleano JSON.

Os novos resultados são `comparacao_horizontes`, `cenarios` e `saldos_cenarios`.
Sem comparação, o primeiro é vazio; sem planejamento, os dois últimos são vazios.
Tudo fica preservado no snapshot com seus parâmetros. O SQLite antigo recebe
uma coluna nullable de disponibilidade por migração aditiva, mantendo o desconhecido.
As recomendações incluem data-limite, data acionável, quantidade na data e prioridade;
veja as [regras de reposição](reposicao.md) antes de interpretar valores vazios.

## Confiabilidade e políticas

Na API 0.5.0, `entregas` recebe registros com `entrega_id,fornecedor_id,data_pedido,
data_prevista,data_recebida`. São recebimentos históricos até a origem, separados
de pedidos abertos. As flags `seguranca_automatica` e `ajustar_prazos` aplicam cópias
das sugestões quando há amostras; os cadastros manuais salvos não são sobrescritos.

`avaliar_reposicao:true` ativa o replay de 7/14/30 dias (`periodo_simulacao`). Os
três custos são números finitos não negativos, usados como premissas de cenário.
Essas três flags exigem produtos e fornecedores. Com disponibilidade ausente,
`assumir_vendas_como_demanda:true` libera somente um proxy explícito na simulação;
nunca libera dias conhecidos como indisponíveis e não autoriza segurança automática
a partir de demanda desconhecida.

O resultado acrescenta `classificacao_produtos,prazos_fornecedores,seguranca_estoque,
residuos_reposicao,avaliacao_reposicao,diario_reposicao,produtos_planejados,
fornecedores_planejados`. Inputs originais e valores efetivos ficam distinguíveis.
Análise totalmente censurada pode retornar 201 com zero pontos e diagnóstico
`demanda_indisponivel`; não são previsões de zero vendas.

`GET /monitoramento?horizonte=7&janela_recente=7&janela_base=21&limiar_aumento_pct=30`
usa a mesma autenticação das outras rotas de negócio. Exige suporte mínimo e
previsões gravadas antes dos dias-alvo em São Paulo. Consulte as
[premissas de disponibilidade, segurança, simulação e monitoramento](confiabilidade.md).

## Acompanhar uma previsão

Após salvar uma análise, registre somente as vendas que realmente observou:

```json
{"vendas":[{"sku":"CAF-001","data":"2026-10-21","vendas":20}]}
```

O exemplo acima é fictício. Envie para `POST /vendas` e consulte
`GET /analises/{id}/comparacao`. A resposta contém resumo por produto e linhas
comparáveis. MAE/viés estão em unidades; WAPE/cobertura são porcentagens.
Datas não observadas ficam fora dos erros; uma venda 0 é uma observação válida.
Se `disponivel=0`, a realização fica registrada, mas não entra em erros ou cobertura.
`periodos_observados` conta registros; `periodos_avaliados` exclui os censurados,
com contagens separadas para disponibilidade desconhecida. Não envie disponibilidade
futura como contexto planejado.
Correções atualizam os resultados realizados, sem mudar o snapshot original.

## Planejamento salvo

`PUT /planejamento` recebe `origem` (YYYY-MM-DD), `produtos`, `fornecedores` e `pedidos`.
A origem é a data do estoque, não a data atual do servidor.
Uma nova análise pode usar `usar_planejamento_salvo:true` sem enviar cadastros no
corpo. Isso exige que o último dia das vendas coincida com a origem salva.
Cadastros enviados no corpo e planejamento salvo não podem ser misturados.

## Chave e limites

Para exigir chave nas rotas de negócio:

```powershell
$env:STOCKMIND_API_KEY = "defina-uma-chave-local"
```

Reinicie o servidor e envie `X-API-Key` em cada requisição protegida. Esse valor de
exemplo não é uma credencial pronta para uso. O dashboard não usa esse mecanismo.
`/health`, Swagger e OpenAPI continuam legíveis; sem variável, a API local é aberta.
A entrega não inclui autenticação de usuários, HTTPS, limites de requisição ou
hospedagem pública. Não exponha o dashboard usando apenas essa chave como proteção.

Dados inválidos retornam 422, incluindo relatório de qualidade quando disponível;
ID ausente retorna 404; chave inválida 401; falha SQLite 503, com operação revertida.
A análise treina localmente por SKU e pode levar tempo em catálogos grandes. Não há
fila distribuída ou agendamento automático de treinamento.

## Comparabilidade e períodos

`janela_classificacao` é inteiro de 1 a 3650, padrão 90. `numero_periodos_simulacao`
é inteiro de 1 a 6, padrão 1, e só executa replay adicional quando `avaliar_reposicao`
está ativo. Esses parâmetros são salvos no snapshot. As novas saídas são
`avaliacao_multiperiodo,diario_multiperiodo,consistencia_politicas`.

`POST /estoques-reais` recebe `{"estoques":[{"sku":"A","data":"2026-10-21","estoque_real":47}]}`.
A consulta de comparação mantém desconhecido um dia sem snapshot; não altera a
análise original. As rotas usam a mesma configuração de chave das demais.
Veja [cache, ABC, estabilidade e comparação de estoque](maturidade.md).
