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


def test_group_members_carry_their_keycloak_subject(client):
    """Needs julie and michou signed in through Keycloak and in the group (docs/owui-test-instance.md)."""
    group = {group.name: group for group in client.groups()}["equipe-a"]
    subjects = {member.email: member.keycloak_sub for member in client.group_members(group.id)}
    assert subjects == {
        "julie@example.com": subjects["julie@example.com"],
        "michou@example.com": subjects["michou@example.com"],
        "alice@example.test": None,
    }
    assert subjects["julie@example.com"] and subjects["michou@example.com"]


def test_knowledge_bases_files_and_grants(client):
    knowledge = {kb.name: kb for kb in client.knowledge_bases()}["kb-test"]
    assert {(g.principal_type, g.permission) for g in knowledge.access_grants} == {("group", "read"), ("user", "write")}
    assert {file.filename for file in client.knowledge_files(knowledge.id)} == {"test.txt", "deux-pages.pdf"}


def test_one_knowledge_base_and_the_embedding_model(client):
    knowledge = {kb.name: kb for kb in client.knowledge_bases()}["kb-test"]
    assert client.knowledge(knowledge.id).name == "kb-test"
    assert client.embedding_model()


def test_a_file_has_its_s3_path_and_its_text_and_its_chunks_are_in_qdrant(client):
    from app.owui_vectors import OwuiVectors

    knowledge = {kb.name: kb for kb in client.knowledge_bases()}["kb-test"]
    files = {file.filename: file for file in client.knowledge_files(knowledge.id)}
    pdf = client.file(files["deux-pages.pdf"].id)

    assert pdf.path.startswith("s3://") and pdf.path.endswith(f"{pdf.id}_deux-pages.pdf")
    assert "Page un" in client.file_text(pdf.id) and "Page deux" in client.file_text(pdf.id)
    [chunk] = OwuiVectors().chunks(knowledge.id, pdf.id)
    assert "Page un" in chunk.text and "Page deux" in chunk.text
