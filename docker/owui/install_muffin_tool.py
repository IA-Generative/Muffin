"""Installs (or updates) the Muffin tool in an Open WebUI (#476), shared with every user.

    OWUI_URL=http://localhost:3001 OWUI_API_KEY=sk-... python3 docker/owui/install_muffin_tool.py

With `OWUI_BASE_MODEL=<a model of the hub>` it also makes an "Assistant Muffin" model out of it: the tool attached, a
prompt that tells it to cite, and Open WebUI's own knowledge tools off - left on, the model may look for Muffin's
sources in its own knowledge bases, where they are not, and give up.

Idempotent: run it again after a change to `muffin_search_tool.py`. The address of Muffin's MCP server is a valve of the
tool (Open WebUI → Workspace → Tools → Muffin), `http://backend:8000/api/mcp/` by default.
"""

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

TOOL_ID = "muffin"
ASSISTANT_ID = "muffin-assistant"
SOURCE = pathlib.Path(__file__).with_name("muffin_search_tool.py")
# Everyone may use it, as `*` is everyone in the access grants of Open WebUI 0.12.
EVERYONE = [{"principal_type": "user", "principal_id": "*", "permission": "read"}]


def call(
    base: str, key: str, method: str, path: str, body: dict | None = None
) -> tuple[int, dict]:
    request = urllib.request.Request(
        base + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, {"detail": error.read().decode()[:300]}


def install_assistant(base: str, key: str, base_model: str) -> None:
    form = {
        "id": ASSISTANT_ID,
        "name": "Assistant Muffin",
        "base_model_id": base_model,
        "is_active": True,
        "meta": {
            "description": "Répond avec les documents de Muffin et cite ses sources.",
            "capabilities": {"builtin_tools": False, "citations": True},
            "toolIds": [TOOL_ID],
        },
        "params": {
            "system": (
                "Pour toute question sur des documents, utilise l'outil Muffin : suggest_collections pour trouver les "
                "collections, puis search. Réponds uniquement avec ce que les sources disent, et cite-les par leur "
                "numéro entre crochets, par exemple [1]."
            )
        },
        "access_grants": EVERYONE,
    }
    status, _ = call(base, key, "GET", f"/api/v1/models/model?id={ASSISTANT_ID}")
    if status == 200:
        status, answer = call(base, key, "POST", "/api/v1/models/model/update", form)
    else:
        status, answer = call(base, key, "POST", "/api/v1/models/create", form)
    if status != 200:
        sys.exit(
            f"Open WebUI refused the model ({status}): {answer.get('detail', answer)}"
        )
    print(f"Assistant Muffin model ready, on {base_model}")


def main() -> None:
    base = os.environ.get("OWUI_URL", "http://localhost:3001").rstrip("/")
    key = os.environ.get("OWUI_API_KEY")
    if not key:
        sys.exit("OWUI_API_KEY: the API key of an Open WebUI administrator")
    form = {
        "id": TOOL_ID,
        "name": "Muffin",
        "content": SOURCE.read_text(),
        "meta": {
            "description": "Cherche dans les collections de Muffin et affiche les sources dans le chat."
        },
        "access_grants": EVERYONE,
    }
    status, answer = call(base, key, "GET", f"/api/v1/tools/id/{TOOL_ID}")
    if status == 200:
        status, answer = call(
            base, key, "POST", f"/api/v1/tools/id/{TOOL_ID}/update", form
        )
        action = "updated"
    else:
        status, answer = call(base, key, "POST", "/api/v1/tools/create", form)
        action = "created"
    if status != 200:
        sys.exit(
            f"Open WebUI refused the tool ({status}): {answer.get('detail', answer)}"
        )
    # The answer of a creation does not carry the specs yet: read them back.
    _, installed = call(base, key, "GET", f"/api/v1/tools/id/{TOOL_ID}")
    print(
        f"Muffin tool {action}: {[spec['name'] for spec in installed.get('specs', [])]}"
    )
    if base_model := os.environ.get("OWUI_BASE_MODEL"):
        install_assistant(base, key, base_model)


if __name__ == "__main__":
    main()
