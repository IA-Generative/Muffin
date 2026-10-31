# Le graphe de l'agent d'exécution

Le graphe LangGraph de `worker/agent_execution` (`app/graph/graph.py`), tel que le compile `build_graph()`.
Les nœuds orange appellent un LLM. Les flèches en pointillés sont des arêtes conditionnelles (`app/graph/routing/conditions.py`).
Chaque nœud peut aussi aller à `cancelled` quand l'annulation est demandée : l'arête n'est pas dessinée, pour rester lisible.

![Le graphe de l'agent d'exécution](agent-execution-graph.png)

Le même dessin en Mermaid, que GitHub affiche directement :

```mermaid
flowchart TD
    load_context[load_context]
    load_accessible_vdbs[load_accessible_vdbs]
    detect_edit[detect_edit]
    detect_create[detect_create]
    delegate_create[delegate_create]
    delegate_edit[delegate_edit]
    analyze_query[analyze_query]
    answer_identity[answer_identity]
    answer_help[answer_help]
    request_clarification[request_clarification]
    decompose_query[decompose_query]
    build_research_plan[build_research_plan]
    route_collections[route_collections]
    research_task[research_task]
    merge_evidence[merge_evidence]
    evaluate_coverage[evaluate_coverage]
    clarify_coverage[clarify_coverage]
    build_answer_context[build_answer_context]
    generate_answer[generate_answer]
    validate_grounding[validate_grounding]
    targeted_research[targeted_research]
    rewrite_citations[rewrite_citations]
    __start__(( début ))
    __end__(( fin ))
    __start__ --> load_context
    analyze_query -.-> answer_help
    analyze_query -.-> answer_identity
    analyze_query -.-> decompose_query
    analyze_query -.-> request_clarification
    answer_help -.-> __end__
    answer_identity -.-> __end__
    build_answer_context -.-> generate_answer
    build_research_plan -.-> route_collections
    clarify_coverage -.-> __end__
    decompose_query -.-> build_research_plan
    delegate_create -.-> __end__
    delegate_edit -.-> __end__
    detect_create -.-> analyze_query
    detect_create -.-> delegate_create
    detect_edit -.-> delegate_edit
    detect_edit -.-> detect_create
    evaluate_coverage -.-> build_answer_context
    evaluate_coverage -.-> clarify_coverage
    generate_answer -.-> __end__
    generate_answer -.-> validate_grounding
    load_accessible_vdbs -.-> detect_edit
    load_context -.-> load_accessible_vdbs
    merge_evidence -.-> evaluate_coverage
    merge_evidence -.-> research_task
    request_clarification -.-> __end__
    request_clarification -.-> decompose_query
    research_task --> merge_evidence
    rewrite_citations -.-> generate_answer
    route_collections -.-> __end__
    route_collections -.-> merge_evidence
    route_collections -.-> research_task
    targeted_research -.-> merge_evidence
    validate_grounding -.-> __end__
    validate_grounding -.-> rewrite_citations
    validate_grounding -.-> targeted_research
    classDef llm fill:#fde7c8,stroke:#c77700
    class analyze_query,answer_help,answer_identity,clarify_coverage,decompose_query,delegate_create,detect_create,detect_edit,evaluate_coverage,generate_answer,research_task,validate_grounding llm
```

## Lire le dessin

- **Détection d'une édition ou d'une création** (`detect_edit`, `detect_create`) : un filtre par mots-clés passe d'abord, le LLM n'est appelé que si la demande y ressemble.
- **`analyze_query`** : toujours un appel LLM. Selon l'intention, la question part vers l'identité, l'aide, une demande de précision ou la recherche.
- **`decompose_query`** : le LLM n'est appelé que pour une question qui n'est pas simple. Sinon, une tâche de recherche unique est créée sans appel.
- **`route_collections`** : une sonde de recherche (sans LLM) dit si la question tombe clairement dans une collection. Sinon, la run se termine sur une question à l'utilisateur.
- **`research_task`** : une branche par tâche, en parallèle (`MAX_PARALLEL_TASKS`). Chaque branche enchaîne le choix des collections (LLM), la recherche QA, les résumés (LLM de suffisance), puis les chunks.
- **`merge_evidence`** revient sur `research_task` tant que des tâches dépendantes sont prêtes, puis passe à `evaluate_coverage` (LLM).
- **`generate_answer`** écrit la réponse en streaming. `validate_grounding` (LLM) ne passe que pour une réponse de synthèse ou de comparaison, ou multi-sources. Un échec peut relancer une recherche ciblée (`targeted_research`, une fois) ou une réécriture des citations (`rewrite_citations`, une fois).

## Régénérer

```bash
cd worker/agent_execution
uv run python scripts/draw_graph.py
```

La liste des nœuds qui appellent un LLM (`LLM_NODES`) est écrite à la main dans le script : elle est à tenir à jour avec `app/graph/nodes`.
