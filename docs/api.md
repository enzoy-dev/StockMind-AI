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
  "usar_planejamento_salvo": false
}
```

Uma única observação produz estimativa inicial sem avaliação. O script gera uma
carteira maior, com contexto, estoque e horizonte 30. Os contratos são os mesmos
dos [CSVs](dados.md). Produtos/fornecedores são opcionais juntos para previsão
sem estoque; pedidos podem ser omitidos ou `[]`.

O retorno inclui `id` e `resultado`, com `previsoes,metricas,saldos,recomendacoes,qualidade`,
origem e horizonte. Valores desconhecidos aparecem como `null`, não como 0.

## Acompanhar uma previsão

Após salvar uma análise, registre somente as vendas que realmente observou:

```json
{"vendas":[{"sku":"CAF-001","data":"2026-10-21","vendas":20}]}
```

O exemplo acima é fictício. Envie para `POST /vendas` e consulte
`GET /analises/{id}/comparacao`. A resposta contém resumo por produto e linhas
comparáveis. MAE/viés estão em unidades; WAPE/cobertura são porcentagens.
Datas não observadas ficam fora dos erros; uma venda 0 é uma observação válida.
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
