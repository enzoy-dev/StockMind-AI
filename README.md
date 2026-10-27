# StockMind-AI

Uma primeira experiência com Machine Learning: ler o histórico de vendas de
**um produto**, prever os próximos **sete dias** e visualizar o resultado.

Esta versão é pequena de propósito. Usa regressão linear e uma interface
Streamlit. Não exige chave de API, GPU ou banco de dados.

## O que funciona

- Abrir o exemplo fictício ou enviar um CSV próprio.
- Treinar um modelo de regressão linear com o histórico diário.
- Exibir vendas registradas, previsão e uma tabela dos próximos sete dias.
- Mostrar o erro em uma semana histórica separada do treinamento.

Estoque, alertas, recomendações de compra, vários produtos e outros modelos
ficam para versões futuras. Não é um sistema pronto para empresas.

## Executar no Windows

Python 3.12 recomendado. No terminal do VS Code, dentro da pasta do projeto:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Abra o endereço local mostrado no terminal, normalmente `http://localhost:8501`.
O exemplo já vem incluído. Não é necessário ativar o ambiente virtual para usar
os comandos acima.

No Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

## Seu CSV

Use somente as colunas `data` e `vendas`, separadas por vírgula:

```csv
data,vendas
2026-08-01,12
2026-08-02,15
2026-08-03,13
```

O trecho acima ilustra o formato; o arquivo completo precisa de **pelo menos
30 dias consecutivos**. Consulte [vendas_exemplo.csv](vendas_exemplo.csv), que
contém 60 dias inventados, de um único produto, para demonstração.

- `data`: formato YYYY-MM-DD, uma linha por dia.
- `vendas`: quantidade de unidades, inteira e não negativa; não é faturamento.
- Não misture produtos, nem use linhas de transações individuais sem agregá-las.
- Datas duplicadas, lacunas e números inválidos são rejeitados.
- Inclua zero somente se houver confirmação de que não houve vendas naquele dia.

A previsão começa no dia seguinte ao **último dia do arquivo**, não
necessariamente amanhã. Arquivos enviados não são gravados pelo aplicativo.
Use localmente: esta versão não tem login nem configuração de hospedagem pública.
Não adicione dados privados ao repositório.

## Como o modelo funciona

A regressão linear recebe o número do dia no histórico e aprende uma reta que
relaciona passagem do tempo e vendas. Assim, captura uma tendência simples de
crescimento ou queda. Previsões negativas são limitadas a zero.

Para avaliar, os últimos sete dias são separados. O modelo treina apenas nos
dias anteriores e tenta prever essa semana. O dashboard mostra o **MAE**, erro
absoluto médio em unidades por dia. Quanto menor, melhor; não é uma porcentagem
de acerto.

Também mostramos a referência que simplesmente repete a última venda conhecida
antes da semana de teste. O modelo pode ter erro maior que essa referência.
Não há seleção automática de modelo nesta versão.

Após essa avaliação, a regressão é ajustada novamente com todo o histórico para
produzir a previsão dos próximos sete dias. Essa previsão futura não tem vendas
reais disponíveis para medir seu erro ainda.

O modelo não considera dia da semana, promoções, preços, feriados nem falta de
estoque. Vendas registradas não revelam demanda perdida por ruptura. Os valores
previstos podem ter casas decimais; são estimativas, não garantia de vendas.
Um teste de uma semana e dados fictícios não demonstram eficácia em empresas.

## Arquivos e testes

| Arquivo | Função |
| --- | --- |
| `app.py` | Leitura do CSV, modelo e interface |
| `vendas_exemplo.csv` | Dados fictícios para experimentar |
| `requirements.txt` | Dependências |
| `test_app.py` | Testes de entrada, previsão e separação temporal |

Os testes usam `unittest`, incluído no Python. No Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

## Próximo passo

Entender o fluxo e experimentar com um histórico real de um único produto,
com origem e autorização conhecidas. Depois, comparar padrões semanais antes
de acrescentar controle de estoque.
