"""Le graphe de l'agent en Mermaid, tiré du graphe compilé (donc à jour), sans les arêtes vers `cancelled`.

    uv run python scripts/draw_graph.py > graph.mmd

Les nœuds qui appellent un LLM sont colorés ; les arêtes en pointillés sont conditionnelles. Chaque nœud peut aller à
`cancelled` (annulation demandée), ce que le dessin ne répète pas pour rester lisible.
"""

from app.graph.graph import build_graph

# Les nœuds qui appellent un LLM, selon leur code : à tenir à jour avec app/graph/nodes.
LLM_NODES = {
    "analyze_query",
    "answer_help",
    "answer_identity",
    "clarify_coverage",
    "decompose_query",
    "delegate_create",
    "detect_create",
    "detect_edit",
    "evaluate_coverage",
    "generate_answer",
    "research_task",
    "validate_grounding",
}


def main() -> None:
    graph = build_graph().get_graph()
    lines = ["flowchart TD"]
    for node in graph.nodes:
        if node in ("__start__", "__end__", "cancelled"):
            continue
        lines.append(f"    {node}[{node}]")
    lines.append("    __start__(( début ))")
    lines.append("    __end__(( fin ))")
    for edge in graph.edges:
        if edge.target == "cancelled" or edge.source == "cancelled":
            continue
        arrow = "-.->" if edge.conditional else "-->"
        lines.append(f"    {edge.source} {arrow} {edge.target}")
    lines.append("    classDef llm fill:#fde7c8,stroke:#c77700")
    lines.append("    class " + ",".join(sorted(LLM_NODES)) + " llm")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
