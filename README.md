# StockMind-AI

Uma primeira experiência com Machine Learning: ler o histórico de vendas de
**um produto**, prever os próximos **sete dias** e visualizar o resultado.

Esta versão é pequena de propósito. Compara regressões lineares e referências
simples em uma interface Streamlit. Não exige chave de API, GPU ou banco de dados.

## O que funciona

- Abrir o exemplo fictício ou enviar um CSV próprio.
- Aprender tendência e diferenças de vendas entre os dias da semana.
- Comparar a regressão original com a regressão semanal e duas referências simples.
- Escolher o método pelo erro em uma semana de validação.
- Exibir vendas registradas, previsão e uma tabela dos próximos sete dias.
- Mostrar o erro em uma semana de teste separada do treinamento e da seleção.

Estoque, alertas, recomendações de compra, vários produtos e modelos mais complexos
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

## Métodos comparados

| Método | Como prevê |
| --- | --- |
| Última venda | Repete o último valor conhecido em todos os próximos sete dias |
| Semana anterior | Repete a venda do mesmo dia da semana anterior |
| Regressão linear | Aprende uma tendência de crescimento ou queda com a passagem dos dias |
| Regressão com dia da semana | Aprende a tendência e diferenças entre segunda, terça, etc. |

A regressão semanal usa indicadores de categoria para os dias da semana, com
segunda-feira como referência. Por exemplo, pode aprender que sábado costuma
vender mais, mantendo uma tendência de crescimento. Não é usado um número
ordinal para supor que domingo vale mais que segunda. Previsões negativas são
limitadas a zero.

## Seleção e avaliação temporal

O dashboard mostra o **MAE**, erro absoluto médio em unidades por dia. Quanto
menor, melhor; não é uma porcentagem de acerto. Os dados são divididos em ordem
cronológica, sem embaralhar:

```text
histórico inicial | validação: penúltimos 7 dias | teste: últimos 7 dias
```

1. Cada método recebe apenas o histórico inicial e prevê a semana de validação.
   O menor MAE de validação escolhe o método para a previsão futura.
2. Em empates numéricos (diferença de até `1e-9` unidade/dia), é mantido o método
   mais simples, na ordem da tabela. Uma referência simples também pode vencer.
3. Para medir o erro de teste, cada método recebe o histórico anterior à última
   semana, incluindo a validação. O resultado de teste **não troca o vencedor**,
   mesmo quando outro método apresenta um erro menor nessa semana.
4. O método escolhido recebe todo o histórico disponível para produzir a previsão
   dos próximos sete dias. Essa previsão futura ainda não tem valores reais para
   medir seu erro.

Com o mínimo de 30 dias, o ajuste da validação usa somente os primeiros 16 dias.
Uma semana de validação e uma de teste permitem uma comparação inicial, mas
podem não representar outros períodos. Mais histórico e várias janelas de
avaliação são necessários antes de concluir qual método é mais confiável.

Os métodos não consideram promoções, preços, feriados nem falta de estoque.
Vendas registradas não revelam demanda perdida por ruptura. Os valores previstos
podem ter casas decimais; são estimativas, não garantia de vendas. Dados fictícios
não demonstram eficácia em empresas.

## Arquivos e testes

| Arquivo | Função |
| --- | --- |
| `app.py` | Leitura do CSV, métodos de previsão, comparação e interface |
| `vendas_exemplo.csv` | Dados fictícios para experimentar |
| `requirements.txt` | Dependências |
| `test_app.py` | Testes de entrada, padrões semanais, separação temporal e interface |

Os testes usam `unittest`, incluído no Python. No Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

Incluem casos em que mudar as vendas da semana de teste não muda a escolha do
método, e em que os métodos simples vencem. Também verificam o carregamento da
tabela de comparação e o modo de envio de CSV.

## Próximo passo

Experimentar com um histórico real de um único produto, com origem e autorização
conhecidas, e comparar mais janelas temporais antes de acrescentar controle de estoque.
