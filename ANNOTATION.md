# Protocolo definitivo de anotação: cenário e proposta

## Unidade do rótulo e ordem das fases

O rótulo para Learning-to-Defer pertence a **uma proposta concreta**, identificada
por `proposal_id`. Um cenário pode originar várias propostas e rótulos diferentes.
A anotação de cenário descreve restrições, ambiguidades e resultados aceitáveis;
**não contém `act/defer`**. Os dois autores anotam independentemente cada fase.

Ordem obrigatória:

1. Anotar e adjudicar o cenário (fase A).
2. Gerar/importar propostas B aceites pelo Critic, sem alterar B.
3. Preparar pacotes de proposta, anotar e adjudicar cada proposta (fase B).
4. Exportar o dataset de treino do gate. Manter o teste reservado.

O espaço local `data/annotation_work/` é ignorado pelo Git. Os IDs `author_a`
e `author_b` são pseudónimos; cada autor abre apenas a sua pasta durante a fase
independente. O filesystem, por si só, não impede que um autor veja a pasta do
outro. Partilhar formulários só depois de ambos os bloquearem como `complete`.

## Fase A — cenário

```bash
python src/annotation_workflow.py prepare-scenarios author_a
python src/annotation_workflow.py prepare-scenarios author_b
```

Cada autor recebe `scenario/packets/<scenario_id>.json` e
`scenario/forms/<scenario_id>.json`. O pacote contém pedido, calendário
sintético, hora simulada e preferências. **Não** contém família, split,
`draft_label`, resultados A/B ou decisões de outro autor.

No formulário, preencher `hard_constraints`, uma ou várias descrições em
`acceptable_outcomes`, `impact_factors`, `ambiguity_present` e, se aplicável,
`ambiguity_notes`. Descrever várias soluções aceitáveis quando existirem, sem
exigir igualdade com uma agenda única. Alterar `status` para `complete` só ao
terminar. O formulário de cenário não pede decisão de autonomia.

Após os dois autores concluírem:

```bash
python src/annotation_workflow.py compare scenario author_a author_b
python src/annotation_workflow.py prepare-adjudications scenario author_a author_b
```

Comparar manualmente descrições de resultados, restrições e ambiguidades. A
comparação textual automática só assinala divergências literais após normalizar
maiúsculas e espaços; não identifica equivalência semântica. Ambos os autores
preenchem `adjudications/scenario/<scenario_id>.json` com o consenso,
`resolution_rationale`, `resolved_by=["author_a","author_b"]` e
`status="complete"`. O código não copia respostas automaticamente.

```bash
python src/annotation_workflow.py validate-adjudications scenario author_a author_b
```

## Gerar e importar propostas para anotação

A configuração B é a fonte de propostas. Executar apenas o lote e a frequência
aprovados para o estudo; **este procedimento não inicia experiências em massa**.
Exemplo de um único cenário, quando se decidir recolher mais uma proposta:

```bash
python eval/run_config_b.py --only soft_gym_01 --experiment-id annotation-pilot --repeat-index 0
python src/proposal_catalog.py eval/runs/<run_id>/B/soft_gym_01.json
```

Substituir `<run_id>` pelo diretório mostrado pelo executor. O importador só
aceita um registo B `proposal_ready` com aprovação do Critic. Cria
`data/proposal_sources/<proposal_id>.json` com ligação a cenário, base, família,
split, execução, modelos, score e **histórico completo de revisões**. O ID é
derivado do run ID, cenário e proposta final; repetir a importação é idempotente.
Propostas que falharam o limiar do Critic não entram no conjunto de treino do
gate, pois B já as defere antes de chegar ao gate.

O catálogo é material de proveniência, **não** é um pacote para anotadores.
Os anotadores não devem abrir `eval/runs/`, `data/proposal_sources/` ou os
resultados de outras configurações até concluírem os seus formulários.

## Fase B — proposta concreta

Depois da adjudicação do cenário correspondente:

```bash
python src/annotation_workflow.py prepare-proposals author_a
python src/annotation_workflow.py prepare-proposals author_b
```

O pacote em `proposal/packets/<proposal_id>.json` mostra o cenário original,
o consenso de restrições/resultados aceitáveis da fase A e **só a proposta
final com a sua justificação**. Omite decisões das regras fixas, pré-rótulos,
score/feedback do Critic, histórico de refinamento, modelo, split e resultados
de outras configurações.

Cada autor preenche em `proposal/forms/<proposal_id>.json`:

- `decision`: `act` se **esta proposta concreta** pode ser aplicada sem
  confirmação; `defer` se requer confirmação ou correção antes de agir.
- `decision_rationale`: motivo específico, incluindo o que a proposta alteraria.
- `scheduling_acceptable`: se as mudanças satisfazem um resultado aceitável
  da fase A; isto é distinto de autorizar autonomia.
- `intervention_impact` e `intervention_risk`: escala 1–5 para esta proposta.
- `risk_factors` e `ambiguity_notes`: consequências, terceiros afetados e
  informação em falta. Depois, `status="complete"`.

Os autores não recebem o rótulo preliminar do cenário nem a decisão das regras.
Uma proposta estruturalmente inviável ou fora dos resultados aceitáveis deve
ser assinalada como tal; o rótulo de autonomia não substitui a avaliação da
qualidade do scheduling.

Após ambos completarem a fase B:

```bash
python src/annotation_workflow.py compare proposal author_a author_b
python src/annotation_workflow.py prepare-adjudications proposal author_a author_b
```

A comparação calcula concordância observada e Cohen's kappa para `act/defer`
quando definido, e assinala diferenças de aceitabilidade, impacto e risco.
Kappa é indefinido sem pares ou quando a concordância esperada é 1; com poucos
exemplos, não o interpretar isoladamente. Os autores preenchem manualmente
`adjudications/proposal/<proposal_id>.json` com `final_decision`, razão,
aceitabilidade, impacto, risco, `resolved_by` e `status="complete"`.

```bash
python src/annotation_workflow.py validate-adjudications proposal author_a author_b
```

## Dataset do gate e separação experimental

Quando as duas fases estiverem completas e adjudicadas para todas as propostas
de treino importadas:

```bash
python src/gate_dataset.py --split train
```

O ficheiro local `data/gate_datasets/train.jsonl` contém metadados de
proveniência (`scenario_id`, `proposal_id`, `base_id`, `family`, `split`, `run_id`,
modelos), `critic_score`, `features` preditivas e `label` adjudicado da **proposta**.
IDs, família e split ficam fora de `features`. O extrator atual usa apenas
proposta final, score do Critic e calendário sintético: tipo e número de
mudanças, importância dos eventos tocados, sobreposições no calendário original,
impacto heurístico e categoria sensível. Não usa rótulos, pré-rótulos ou escalas
humanas como features. Estas heurísticas têm de ser congeladas antes de ver os
rótulos das famílias de teste.

O comando recusa exportar se faltar qualquer anotação independente ou
adjudicação de uma proposta do split selecionado. `--split test` exige
`--unlock-test` explícito e deve ser usado **só depois** de congelar features,
classificador e hiperparâmetros. Todas as propostas da mesma base pertencem à
mesma família/split; validação cruzada e treino devem agrupar por família ou,
  no mínimo, por base, nunca por linha individual. A função
  `grouped_gate_folds` prepara folds por família para linhas de treino e
  verifica que propostas da mesma base ficam juntas.

## Riscos a controlar antes da recolha completa

- Existem 41 variantes, mas só três famílias de treino; a validação cruzada
  agrupada é instável e cada fold pode omitir uma categoria inteira.
- Nos dez cenários originais, os pré-rótulos são enviesados por categoria:
  os dois casos rígidos têm `act` e os três ambíguos têm `defer`. Os restantes
  31 cenários não têm pré-rótulo. Estes valores **não são ground truth**.
- Recolher propostas B aceites para casos de baixo e alto impacto nas famílias
  de treino; verificar a diversidade **apenas depois** das anotações de treino.
  Se faltar diversidade, ampliar famílias de treino ou recolher mais propostas
  com um protocolo fixado. Não usar rótulos de teste para selecionar exemplos,
  regras, features ou limiares.
- Uma mesma proposta final pode ser parecida com outra do mesmo cenário-base.
  Manter todas no mesmo grupo evita fuga entre treino e avaliação.
- Os formulários de cenário fornecem resultados aceitáveis em texto livre; a
  correspondência com uma proposta concreta exige julgamento humano.
