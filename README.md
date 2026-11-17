# Claude Code refatorando Long Methods: o CLAUDE.md faz diferença?

Estudo empírico de **manutenção perfectiva** com o agente autônomo **Claude Code**, feito como trabalho prático da disciplina de Manutenção e Evolução de Software (MES).

O estudo avalia se um arquivo de contexto (`CLAUDE.md`) muda a qualidade da refatoração de *Long Methods* e se esse efeito depende da complexidade ciclomática do método.

## Questões de pesquisa

- **RQ1, Eficácia:** o agente conclui a refatoração sozinho, sem quebrar nem tocar nos testes?
- **RQ2, Qualidade:** a complexidade cai de verdade ou só muda de lugar?
- **RQ3, Contexto:** o `CLAUDE.md` melhora o resultado? O efeito depende da complexidade do método?

## Desenho experimental

O desenho é fatorial 4 × 2 × 2 × 3, totalizando **48 execuções**:

| Fator | Níveis |
|---|---|
| Faixa de risco de McCabe | 1–10, 11–20, 21–50, 51+ (um sistema e um método por faixa) |
| Modelo | `claude-sonnet-5-5`, `claude-haiku-5-5` |
| Condição | **A**: sem `CLAUDE.md` · **B**: com [`CLAUDE.md`](experiment/CLAUDE.md) |
| Réplicas | 3, em ordem sorteada dentro de cada réplica |

### Sistemas e métodos-alvo

| Faixa | Sistema | Método | CC | NLOC | Testes | Commit |
|---|---|---|---|---|---|---|
| 1–10 | Apache Commons Text | `AlphabetConverter.createConverter` | 10 | 70 | 2.043 | `af5dd3a` |
| 11–20 | Apache Commons CLI | `PosixParser.flatten` | 15 | 46 | 1.002 | `3a53a35` |
| 21–50 | Google Gson | `JsonReader.doPeek` | 41 | 156 | 4.707 | `e67037d` |
| 51+ | jsoup | `HtmlTreeBuilderState.inBodyStartTag` | 123 | 339 | 2.648 | `d90d575` |

A CC foi medida com o [lizard](https://github.com/terryyin/lizard) 1.26.1. Os commits completos estão em [`experiment/tasks.json`](experiment/tasks.json).

### Prompt (idêntico em A e B)

Veja [`experiment/prompts/template.txt`](experiment/prompts/template.txt). O prompt pede para refatorar o método sem alterar o comportamento externo, sem criar, modificar ou remover testes, e com a suíte inteira passando ao final.

### Protocolo de isolamento (por execução)

1. Clone novo no commit fixado, com HEAD e working tree verificados.
2. Sessão nova do Claude Code (`claude -p`) com `CLAUDE_CONFIG_DIR` vazio: sem memórias, histórico nem `CLAUDE.md` de usuário.
3. Prompt idêntico por tarefa, com hash SHA-256 registrado.
4. Versões fixas: Claude Code 2.1.325, OpenJDK 21.0.13, Maven 3.9.11 e lizard 1.26.1.
5. Nada herdado: pasta nova por execução, repositório Maven local exclusivo e `WebFetch`/`WebSearch` desabilitados.

O `AGENTS.md` presente em commons-text e commons-cli é removido nas duas condições. No grupo B, o `CLAUDE.md` leva o cabeçalho de licença Apache para não quebrar a checagem RAT. Sem esse cabeçalho, um agente do piloto contornou a falha com `-Drat.skip`, e essa execução foi descartada.

**Uma execução é válida quando** a build passa, nenhum teste falha, o número de testes executados é pelo menos o do baseline e nenhum arquivo em `src/test` foi tocado.

## Resultados

Todas as 48 execuções foram válidas: nenhum teste alterado, nenhum teste falhando e nenhuma mudança de build.

CC média do método-alvo depois da refatoração (3 réplicas):

| Faixa (CC inicial) | Haiku A | Haiku B | Sonnet A | Sonnet B |
|---|---|---|---|---|
| 1–10 (10) | 2,0 | 2,0 | 2,7 | 2,7 |
| 11–20 (15) | 3,0 | 3,0 | 3,0 | 3,0 |
| 21–50 (41) | 8,7 | 2,3 | 9,0 | 8,3 |
| 51+ (123) | 57,3 | 1,3 | 63,3 | 9,7 |

Síntese por modelo e condição (médias de 12 execuções):

| Grupo | CC final | Redução | Turnos | Minutos | US$/exec.* | Usou lizard |
|---|---|---|---|---|---|---|
| Haiku · A | 17,8 | 73% | 7,2 | 1,1 | 0,01 | 0/12 |
| Haiku · B | 2,2 | 88% | 10,0 | 1,8 | 0,02 | 12/12 |
| Sonnet · A | 19,5 | 70% | 4,6 | 1,0 | 0,11 | 0/12 |
| Sonnet · B | 5,9 | 81% | 5,7 | 1,5 | 0,16 | 12/12 |

\* `total_cost_usd` do Claude Code (custo equivalente em API; as execuções rodaram numa assinatura). Total das 48 execuções: US$ 3,59.

**Principais achados**

- O `CLAUDE.md` não muda nada até CC 20. Nos métodos de risco alto e muito alto, ele é decisivo. No jsoup, a CC final fica em 57–63 sem contexto e em 1–10 com contexto.
- Com uma meta numérica, o agente mira a meta. O Sonnet com `CLAUDE.md` parou em 9 ou 10, quebrando um `switch` em 9 `switch`es encadeados, um caso da lei de Goodhart.
- A complexidade muda de lugar e não desaparece: a CC total do arquivo aumentou em 47 das 48 execuções. Sem contexto, 10 métodos extraídos nasceram com CC acima de 10; com contexto, nenhum.
- Um modelo menor com bom contexto venceu um maior: o Haiku B teve a menor CC final, a cerca de 1/8 do custo do Sonnet B.

Dois pilotos com Opus 5.5 (grupo A) estão em [`runs/_pilots_opus`](runs/_pilots_opus) e ficaram fora da análise principal.

## Estrutura

```
experiment/
  tasks.json          # tarefas, commits fixados, modelos, réplicas, orçamento
  prompts/template.txt
  CLAUDE.md           # manifesto da condição B
  runner.py           # harness: plan | baseline | run
  analyze.py          # agrega runs/*/result.json -> results/
  save_token.sh, new_token.sh  # utilitários para gravar o token OAuth
results/
  runs.csv            # uma linha por execução
  summary.json        # agregados por célula, condição e modelo
runs/
  plan.json, baseline.json
  <tarefa>__<modelo>__<condição>__r<n>/
    result.json, diff.patch, test.log, prompt.txt
```

As transcrições completas das sessões do agente não foram publicadas.

## Como reproduzir

Requisitos: Claude Code 2.1.325, JDK 21, Maven 3.9.11 e Python 3 com `lizard` instalado.

1. Clone os 4 repositórios em `repos/` (`commons-text`, `commons-cli`, `gson`, `jsoup`).
2. Coloque o Maven em `tools/apache-maven-*/`.
3. Crie um `.venv` com `lizard`.
4. Gere um token com `claude setup-token` e grave em `.secrets/oauth_token`. Também é possível adaptar o `runner.py` para usar `ANTHROPIC_API_KEY`.
5. Rode:

```bash
python3 experiment/runner.py plan
python3 experiment/runner.py baseline
python3 experiment/runner.py run
python3 experiment/analyze.py
```

## Limitações

- Um único método por faixa e 3 réplicas por célula.
- Uma única métrica estrutural: a complexidade ciclomática medida pelo lizard.
- O desempenho do Gson e do jsoup depois da refatoração não foi medido.
- Os repositórios são públicos e podem fazer parte dos dados de treino dos modelos.
