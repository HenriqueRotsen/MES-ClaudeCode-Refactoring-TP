<!--
Licensed to the Apache Software Foundation (ASF) under one or more
contributor license agreements.  See the NOTICE file distributed with
this work for additional information regarding copyright ownership.
The ASF licenses this file to You under the Apache License, Version 2.0
(the "License"); you may not use this file except in compliance with
the License.  You may obtain a copy of the License at

     https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Diretrizes de Manutenção e Refatoração

Este repositório está em manutenção perfectiva. Toda mudança deve deixar o código mais fácil de manter sem alterar o comportamento observável.

## Objetivo da refatoração
- Trate a causa estrutural do smell, não só a aparência. Renomear variáveis, reformatar ou reordenar código não conta como refatoração.
- Meta de complexidade: **nenhum método alterado ou criado pode ter complexidade ciclomática (McCabe) acima de 10**. Se a meta não for viável sem prejudicar a clareza ou o desempenho, deixe o método no menor valor razoável e explique o motivo no resumo final.
- Prefira técnicas de Fowler: Extract Method, Decompose Conditional, Replace Nested Conditional with Guard Clauses, Consolidate Duplicate Conditional Fragments. Substitua um `switch`/cadeia de `if` por polimorfismo ou tabela de despacho só quando isso reduzir o acoplamento de verdade.
- Cada método extraído deve ter **uma única responsabilidade** e um nome que diga *o que* ele faz no domínio (ex.: `handleFormattingElementStart`, não `helper1` nem `part2`).
- Não troque complexidade por acoplamento: evite métodos extraídos com mais de 4 parâmetros ou que devolvam várias informações por efeito colateral. Se isso acontecer, o agrupamento está errado.

## Invariantes que não podem ser quebrados
- **API pública e assinaturas inalteradas**: não mude métodos públicos/protegidos, visibilidade, exceções lançadas nem a ordem de efeitos colaterais.
- **Desempenho em caminhos quentes**: parsers e lexers rodam em laços apertados. Não introduza streams, lambdas por chamada, boxing, alocações de objetos, coleções novas ou reflexão dentro desses laços. Métodos `private` pequenos são aceitáveis (a JIT faz inline).
- Sem dependências novas; preserve o estilo de código, a licença e o Javadoc existentes.
- Mudança mínima fora do método-alvo: só altere outro código se a refatoração exigir.

## Testes (regra dura)
- **Proibido** criar, editar, mover ou apagar qualquer arquivo em `src/test`. Os testes existentes são o oráculo de comportamento.
- Proibido mascarar falhas: nada de `@Disabled`, `-DskipTests`, `-Dmaven.test.failure.ignore`, nem alterar configuração de build para pular testes.
- Se um teste falhar, o erro está na sua refatoração: corrija o código de produção.

## Processo de verificação (siga antes de declarar concluído)
1. Meça o método-alvo antes de mudar: `lizard -l java <arquivo>` (coluna CCN).
2. Refatore em passos pequenos e rode a suíte de testes indicada na tarefa.
3. Meça de novo com `lizard -l java <arquivo>` e confirme que nenhum método alterado/criado tem CCN > 10.
4. Rode `git diff --stat` e confirme que nenhum arquivo em `src/test` aparece.
5. No resumo final, informe: CCN antes/depois do método-alvo, métodos extraídos (nome e CCN) e resultado dos testes.
