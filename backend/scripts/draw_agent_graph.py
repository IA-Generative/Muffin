"""Le graphe de l'agent en Mermaid, tiré du graphe compilé (donc à jour), sans les arêtes vers `cancelled`.

    uv run python scripts/draw_graph.py > graph.mmd

Les nœuds qui appellent un LLM sont colorés ; les arêtes en pointillés sont conditionnelles. Les sous-graphes (`edit`,
`create`) sont dessinés avec leurs nœuds. Chaque nœud peut aussi aller à `cancelled` (annulation demandée), ce que le
dessin ne répète pas pour rester lisible.
"""

from app.agent.graph.graph import build_graph

# Les nœuds qui appellent un LLM, selon leur code : à tenir à jour avec app/graph/nodes.
LLM_NODES = {
    "answer_help",
    "create_write",
    "generate_answer",
    "plan",
}


def _id(node: str) -> str:
    return node.replace(":", "__")


def main() -> None:
    # xray: the sub-graphs (edit, create) are drawn with their own nodes.
    graph = build_graph().get_graph(xray=True)
    ends = {name for name in graph.nodes if name.endswith(":__end__")}

    def end_or(node: str) -> str:
        return "__end__" if node in ends else node

    groups: dict[str, list[str]] = {}
    top: list[str] = []
    for node in graph.nodes:
        if node in ("__start__", "__end__", "cancelled") or node in ends:
            continue
        if ":" in node:
            groups.setdefault(node.split(":", 1)[0], []).append(node)
        else:
            top.append(node)

    lines = ["flowchart TD"]
    lines += [f"    {_id(node)}[{node}]" for node in top]
    for group, nodes in groups.items():
        lines.append(f"    subgraph {group}_sub [{group}]")
        lines += [f"        {_id(node)}[{node.split(':', 1)[1]}]" for node in nodes]
        lines.append("    end")
    lines.append("    __start__(( début ))")
    lines.append("    __end__(( fin ))")
    seen = set()
    for edge in graph.edges:
        if "cancelled" in (edge.source, edge.target) or edge.source in ends:
            continue
        source, target = _id(end_or(edge.source)), _id(end_or(edge.target))
        arrow = "-.->" if edge.conditional else "-->"
        line = f"    {source} {arrow} {target}"
        if line not in seen:
            seen.add(line)
            lines.append(line)
    llm = sorted(
        _id(node) for node in top + [n for nodes in groups.values() for n in nodes] if node.split(":")[-1] in LLM_NODES
    )
    lines.append("    classDef llm fill:#fde7c8,stroke:#c77700")
    lines.append("    class " + ",".join(llm) + " llm")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
