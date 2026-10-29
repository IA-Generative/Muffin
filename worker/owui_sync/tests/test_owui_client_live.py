"""Against a real Open WebUI (docs/owui-test-instance.md): skipped unless OWUI_API_KEY is set."""

import os

import pytest

from app.owui_client import OwuiClient

pytestmark = pytest.mark.skipif(not os.getenv("OWUI_API_KEY"), reason="no Open WebUI to read (OWUI_API_KEY)")


@pytest.fixture(scope="module")
def client() -> OwuiClient:
    return OwuiClient(os.getenv("OWUI_BASE_URL", "http://localhost:3001"), os.environ["OWUI_API_KEY"])


def test_users(client):
    assert "admin@example.test" in {user.email for user in client.users()}


def test_groups_and_their_members(client):
    groups = {group.name: group for group in client.groups()}
    members = client.group_member_ids(groups["equipe-a"].id)
    users = {user.id: user.email for user in client.users()}
    assert [users[member] for member in members] == ["alice@example.test"]


def test_knowledge_bases_files_and_grants(client):
    knowledge = {kb.name: kb for kb in client.knowledge_bases()}["kb-test"]
    assert {(g.principal_type, g.permission) for g in knowledge.access_grants} == {("group", "read"), ("user", "write")}
    assert [file.filename for file in client.knowledge_files(knowledge.id)] == ["test.txt"]
