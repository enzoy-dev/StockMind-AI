# StockMind-AI

Previsão de vendas por produto e planejamento de estoque com Python, scikit-learn,
Streamlit, FastAPI e SQLite. Compara métodos em períodos históricos, projeta saldos
com recebimentos e acompanha previsões salvas quando novas vendas chegam.

**Aplicação local em desenvolvimento.** Os exemplos são fictícios; resultados
nesses exemplos não comprovam redução de faltas ou desempenho em uma empresa real.

## Funcionalidades

- CSV com vários produtos; formato original `data,vendas` continua aceito.
- Previsões de 7, 14, 30 ou 90 dias, avaliadas no horizonte escolhido.
- Comparação de 7, 14 e 30 dias por produto, com erro frente à referência semanal.
- Até três janelas temporais para seleção e um teste final separado.
- Referências simples, regressões com calendário/atrasos, Croston-SBA e modelo
  contextual quando preços/promoções/feriados futuros são conhecidos.
- Faixas empíricas de 90%, calibradas em período independente quando há dados.
- Estimativas iniciais explícitas para históricos curtos; produtos sem vendas
  no catálogo ficam sem previsão, em vez de receber zero artificial.
- Cadastro de produtos, fornecedores, estoque de segurança, lotes e pedidos abertos.
- Saldo diário, dias até falta/segurança, prioridade e motivos dos alertas.
- Data-limite e data sugerida de compra, com quantidade recalculada na janela futura.
- Cenários de demanda menor/base/maior com variação percentual configurável.
- Dashboard com filtros, gráficos interativos e exportação de CSVs.
- SQLite com snapshots de entradas/previsões e comparação com vendas posteriores.
- API para análise, cadastros e atualização de vendas realizadas.
- Relatório de qualidade, testes e CI para Linux e Windows.

Não envia compras nem atualiza estoque de um ERP. O estoque informado é um snapshot
na data final do histórico, e não um livro de movimentações de estoque.

## Rodar o dashboard

Python 3.12 recomendado. No PowerShell, dentro desta pasta:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

No Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

Abra o endereço local informado pelo Streamlit. Não é necessária chave de IA,
GPU ou serviço externo.

1. **Carteira fictícia** já inclui vendas, fornecedores, estoque, pedidos e plano
   futuro de contexto. Possui três produtos com 420 dias, um com 10 dias e um
   produto cadastrado sem vendas. A origem é **20/10/2026**, independentemente de hoje.
2. **Exemplo de um produto** mantém o CSV original de 60 dias.
3. **Enviar CSV** aceita seus dados. Cadastros de estoque podem ser editados na
   tela, importados ou carregados do SQLite.
4. Escolha o horizonte, a comparação 7/14/30 e a variação percentual dos cenários.
   O dashboard abre em **Decisões de reposição**: revise urgências, compras futuras
   e excesso. As abas Previsões e Cenários de demanda detalham os cálculos.
5. **Salvar análise e entradas no histórico** registra um snapshot. Salvar não
   equivale a aprovar compras. Depois, registre novas vendas para comparar.

A análise é calculada em memória e pode ficar em cache por até cinco minutos.
A gravação de entradas e resultados ocorre por ações explícitas; abrir a interface
pode criar o arquivo SQLite vazio. Não coloque arquivos privados no repositório.

## Dados e planejamento

[Contratos completos dos CSVs e exemplos](docs/dados.md).

Vendas mínimas:

```csv
sku,data,vendas
CAF-001,2026-10-19,18
CAF-001,2026-10-20,20
```

Uma linha por dia/produto, datas consecutivas e mesma data final para todos os
produtos. Lacunas não são preenchidas com zero. Históricos de um dia são aceitos
com estimativa inicial e aviso, sem alegar validação.

Preço, promoção e feriado são opcionais. O modelo contextual só é comparado quando
há histórico **e plano futuro completos** desses campos; eles devem ter sido
conhecidos antes das previsões, inclusive na avaliação histórica.

A compra sugerida usa o caminho diário com as datas exatas dos pedidos e o maior
déficit em relação à segurança após a entrega possível, dentro da janela de proteção.
Aplica mínimo e múltiplo somente se existir necessidade. Assim, um pedido grande
e tardio não esconde uma falta anterior. Uma compra não resolve déficits que
ocorreriam antes de sua entrega; esses casos recebem prioridade de revisão.

A data-limite é a primeira passagem abaixo da segurança menos o prazo efetivo do
fornecedor. A data acionável nunca é anterior à referência; a quantidade é
recalculada considerando a depleção e os recebimentos na janela futura. Prazo zero
significa a manhã seguinte à compra feita no fechamento do dia.

[Regras de agendamento, prioridades e cenários](docs/reposicao.md).

Se a previsão não cobrir prazo + revisão, a sugestão fica indefinida com o horizonte
necessário. Uma compra futura pode exigir horizonte maior do que comprar na referência.
Sem cruzamento da segurança, a próxima data de compra fica desconhecida além do
período previsto. Excesso é uma triagem de 30 dias, indisponível em horizontes menores.
Compras de produtos com histórico curto são provisórias. Segurança não é estimada
automaticamente; vencimento, orçamento e custo de falta não são otimizados.

## Modelagem e limites

[Metodologia, separação temporal e avaliação sintética](docs/avaliacao.md).

| Horizonte | Dias mínimos para seleção + teste | Dias mínimos para faixas |
| --- | ---: | ---: |
| 7 | 28 | 42 |
| 14 | 42 | 70 |
| 30 | 74 | 134 |
| 90 | 194 | 374 |

Os números acima usam treino inicial mínimo de 14 dias. A quantidade de janelas
cresce até três conforme o histórico disponível. Séries curtas usam a média dos
últimos até 14 dias, sem métricas ou faixas artificiais.
O candidato com atrasos só participa quando o primeiro treino de validação tem
pelo menos 42 dias. Ele usa valores previstos na recursão, sem consultar vendas futuras.

A comparação 7/14/30 tem seleção independente por horizonte. Os testes cobrem
períodos distintos e seus erros não medem uma precisão em datas idênticas. Redução
de MAE positiva indica ganho sobre repetir a semana anterior; negativa indica perda.
O teste nunca troca o método escolhido na validação.

MAE/viés em unidades por dia; WAPE/cobertura em porcentagem. Viés positivo indica
superestimação. WAPE fica vazio quando as vendas reais somam zero. O teste final
não escolhe o método nem a largura da faixa.

Faixas são empíricas por ponto, não garantia de 90% de cobertura futura ou conjunta
de toda a trajetória. Vendas observadas não revelam demanda perdida em rupturas.
Promoções e preços podem estar associados a vendas sem demonstrar efeito causal.
Os cenários percentuais de demanda são sensibilidade determinística, sem probabilidade
atribuída; não são trajetórias extraídas dos limites estatísticos do modelo.

## Banco local e histórico

O padrão é `data/stockmind.sqlite3`, ignorado pelo Git. Dashboard e API compartilham
esse caminho; use a mesma variável para escolher outro arquivo:

```powershell
$env:STOCKMIND_DB = "C:\caminho\privado\stockmind.sqlite3"
```

Vendas realizadas são atualizadas por SKU/data. Correções não alteram as previsões
nem as entradas de análises já salvas. Datas sem realização continuam desconhecidas
e não entram nas métricas como zero. O cadastro salvo inclui a data do estoque;
reutilizá-lo com outra data de referência é bloqueado para evitar estoque antigo.
O SQLite é local, transacional e adequado a este estágio; não há sincronização ERP.

## API

```powershell
.\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Documentação interativa: `http://127.0.0.1:8000/docs`.

[Rotas, exemplos e acompanhamento de previsões pela API](docs/api.md).
A variável opcional `STOCKMIND_API_KEY` exige `X-API-Key` nas rotas de negócio.
Sem ela, a API local não exige chave. Essa configuração **não protege o dashboard
Streamlit**; ambos devem ser usados localmente nesta entrega. Nenhum serviço foi
publicado. Uma hospedagem exige tratar autenticação do dashboard e infraestrutura.

## Testes e desenvolvimento

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -v
```

CI executa a suíte com Python 3.12 no Linux e Windows. Os testes cobrem isolamento
temporal, calibração, histórico curto, contexto, lotes, recebimentos, validação,
rollback, snapshots, API e fluxos do dashboard.

```text
app.py                  dashboard
api.py                  FastAPI e autenticação opcional por chave
stockmind/data.py       importação e relatório de qualidade
stockmind/forecasting.py modelos, janelas temporais e faixas
stockmind/inventory.py   saldo e reposição
stockmind/scenarios.py   sensibilidade das decisões à demanda
stockmind/service.py     fluxo compartilhado, sem persistência implícita
stockmind/storage.py     SQLite e acompanhamento de realizações
```

Os CSVs fictícios podem ser regenerados com `python scripts/generate_examples.py`
(semente 42, sem dados externos). O projeto ainda precisa de avaliação com dados
reais de origem e autorização conhecidas; não apresenta resultados comerciais medidos.
