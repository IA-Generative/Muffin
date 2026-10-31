"""What the agent can do, written once for the prompts that describe it (the plan, the identity answer)."""

BASE_TOOLS: tuple[str, ...] = (
    "search",
    "list_collections",
    "collection_summary",
    "list_documents",
    "page_content",
    "tabular_query",
    "time",
)

BASE_TOOL_GUIDE = (
    "Tool guide:\n"
    '- "search": look for information inside document content - the default for most questions.\n'
    '- "list_collections": the user asks how many knowledge bases/collections they have, or wants them listed.\n'
    '- "collection_summary": the user wants a summary/description of one specific collection.\n'
    '- "list_documents": the user asks how many documents are in a collection, or wants a document\'s summary.\n'
    '- "page_content": the user wants the text and/or screenshot of one specific page of one document.\n'
    '- "tabular_query": the user asks an analytical question about tabular data (CSV/XLSX/Parquet/JSON) - '
    "aggregations, counts, averages, sums, filters, sorting, grouping, min/max. Use this when the question "
    "requires computing over data rows rather than reading document text. This is the correct tool for ANY "
    'question involving: averages/means, totals/sums, counts ("how many"), min/max, medians, rankings, '
    'grouping, filtering, or comparisons across rows. Examples: "how many rows have X > 100?", '
    '"what is the average of column Y grouped by Z?", "show me the top 5 by revenue", '
    '"quel est le revenu moyen ?", "combien y a-t-il de déclarants ?". '
    "When in doubt between search and tabular_query for a question that involves numbers or "
    "aggregation, prefer tabular_query.\n"
    '- "time": the user asks about the current date/time, or references relative periods (today, this week, '
    "last month, etc.) to filter or compare documents/tasks. Always pick this tool when the query needs "
    "temporal context the LLM cannot infer alone.\n"
)

# Only ever appended when the run opted in (chat composer toggle, off by default - see
# AgentState.web_search_enabled) - the planner must never even be told this tool exists
# otherwise, since offering it is itself the opt-in the issue this ships for requires.
WEB_SEARCH_TOOL_GUIDE = (
    '- "web_search": the accessible knowledge bases are insufficient, or the question is explicitly about '
    "something outside the user's own documents (current events, general knowledge). The query sent to this "
    "tool must stay the user's own question - never paste in excerpts from private documents.\n"
)

AUTHORING_CAPABILITIES = (
    "Writing in the user's collections (the user always reviews and validates first - nothing is "
    "written to a collection without their approval):\n"
    "- Modify an existing living document (an ODT or Markdown document in one of the user's own "
    "collections): add, rewrite, remove or correct content. The change is shown as a proposal to "
    "compare with the current version, then validate, adjust or refuse.\n"
    "- Create a new document in one of the user's own collections - Markdown (.md) only, never Word, "
    "ODT, PDF or Excel. It is written from the request and the conversation, without searching the "
    "collections, and shown as a proposal to create or refuse.\n"
    "Both are only possible in collections the user owns.\n"
    "Explaining how to use the Muffin application itself (collections, adding documents, sharing, "
    'living documents, settings...) when asked "how do I...?".'
)


def valid_tools(web_search_enabled: bool) -> frozenset[str]:
    return frozenset((*BASE_TOOLS, "web_search") if web_search_enabled else BASE_TOOLS)
