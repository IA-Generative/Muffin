"""The tabular_query tool (#433): the catalog the model reads, the call to the SQL worker, and the model's tool loop.

The graph-level behaviour (evidence, citations of two files, a worker that is down) is in test_graph.py."""

import json

import pytest

from app.agent.cancellation import RunCancelled
from app.agent.graph.services import tabular_query, tabular_worker
from app.agent.graph.services.tabular_catalog import Catalog
from app.agent.graph.services.tabular_query import format_rows, format_tabular_evidence, run_query_loop
from app.agent.graph.services.tabular_worker import SqlWorkerUnavailable, run_remote_query

COLLECTION = {"id": "c1", "name": "RH"}


def sheet(name="Ventes", index=0, key="documents/c1/d1/tables/0.parquet", **extra):
    return {
        "index": index,
        "name": name,
        "rows": 12,
        "truncated": False,
        "parquet_key": key,
        "columns": [{"name": "région", "sql_type": "VARCHAR"}, {"name": "montant", "sql_type": "DOUBLE"}],
        "profile": [
            {"name": "région", "distinct": 4, "distinct_exact": True, "top_values": ["Nord", "Sud"]},
            {"name": "montant", "distinct": 1000, "distinct_exact": False, "null": 2, "min": 1, "max": 99},
        ],
        **extra,
    }


def document(doc_id="d1", name="ventes.xlsx", sheets=None):
    return {"id": doc_id, "name": name, "format": "xlsx", "sheets": [sheet()] if sheets is None else sheets}


def catalog(*documents, max_files=10):
    return Catalog.build([(COLLECTION, list(documents))], max_files)


# --- the catalog ---


def test_each_file_is_a_schema_and_each_sheet_a_table():
    cat = catalog(document(sheets=[sheet("Ventes"), sheet('Chiffres "bruts"', 1, "documents/c1/d1/tables/1.parquet")]))

    text = cat.describe()

    assert "f1 - ventes.xlsx (collection « RH »)" in text
    assert 'table "f1"."Ventes" - 12 ligne(s)' in text
    assert 'table "f1"."Chiffres ""bruts"""' in text
    assert '"région" VARCHAR - 4 valeur(s) distincte(s) ; ex. : Nord, Sud' in text
    assert "au moins 1000 valeur(s) distincte(s) ; 2 vide(s) ; de 1 à 99" in text


def test_an_unnamed_sheet_is_named_as_the_worker_names_it():
    cat = catalog(document(sheets=[sheet(""), sheet("", 1, "documents/c1/d1/tables/1.parquet")]))

    assert [s.name for s in cat.files[0].sheets] == ["sheet_0", "sheet_1"]


def test_a_document_without_a_copy_is_announced_and_not_in_the_files():
    cat = catalog(document(), document("d2", "vieux.csv", sheets=[]))

    assert [f.name for f in cat.files] == ["ventes.xlsx"] and cat.pending == ["vieux.csv"]
    assert "vieux.csv" in cat.describe() and "à réindexer" in cat.describe()


def test_files_past_the_limit_are_left_out_and_said_so():
    cat = catalog(document("d1", "a.csv"), document("d2", "b.csv"), document("d3", "c.csv"), max_files=2)

    assert [f.ref for f in cat.files] == ["f1", "f2"] and cat.omitted == ["c.csv"]
    assert "c.csv" in cat.describe()


def test_the_request_is_built_from_the_catalog_only():
    cat = catalog(
        document("d1", "a.csv"), document("d2", "b.csv", sheets=[sheet(key="documents/c1/d2/tables/0.parquet")])
    )

    request = cat.request("SELECT 1", cat.resolve(["f2"]))

    assert request["collection_ids"] == ["c1"] and request["sql"] == "SELECT 1"
    assert [f["ref"] for f in request["files"]] == ["f2"]
    assert request["files"][0]["sheets"][0]["key"] == "documents/c1/d2/tables/0.parquet"


def test_no_file_named_means_all_and_an_unknown_one_is_refused():
    cat = catalog(document("d1", "a.csv"), document("d2", "b.csv"))

    assert [f.ref for f in cat.resolve(None)] == ["f1", "f2"]
    with pytest.raises(KeyError):
        cat.resolve(["f9"])


# --- the call to the SQL worker ---


class FakeResult:
    def __init__(self, answer, ready_after=0, ok=True):
        self.answer, self.polls, self.ready_after, self.ok = answer, 0, ready_after, ok
        self.revoked = self.forgotten = False

    def ready(self):
        self.polls += 1
        return self.polls > self.ready_after

    def successful(self):
        return self.ok

    @property
    def result(self):
        return self.answer

    def revoke(self):
        self.revoked = True

    def forget(self):
        self.forgotten = True


class FakeApp:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.sent = result, error, []

    def send_task(self, name, args, queue):
        if self.error:
            raise self.error
        self.sent.append((name, args, queue))
        return self.result


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_the_query_is_sent_by_name_to_the_sql_queue_and_polled():
    result = FakeResult({"status": "completed", "columns": [], "rows": []}, ready_after=3)
    app, clock = FakeApp(result), Clock()

    answer = run_remote_query({"sql": "SELECT 1"}, app, clock, clock.sleep)

    assert answer["status"] == "completed"
    assert app.sent == [("app.tasks.run_query", [{"sql": "SELECT 1"}], "tabular_sql")]
    assert result.forgotten and not result.revoked


def test_a_worker_that_does_not_answer_in_time_is_an_error_and_what_was_sent_is_revoked():
    result = FakeResult({}, ready_after=10**9)
    clock = Clock()

    with pytest.raises(SqlWorkerUnavailable, match="n'a pas répondu"):
        run_remote_query({}, FakeApp(result), clock, clock.sleep)

    assert result.revoked


def test_a_task_that_failed_or_a_broker_that_is_down_is_an_error():
    with pytest.raises(SqlWorkerUnavailable, match="a échoué"):
        run_remote_query({}, FakeApp(FakeResult(RuntimeError("boom"), ok=False)))
    with pytest.raises(SqlWorkerUnavailable, match="injoignable"):
        run_remote_query({}, FakeApp(error=ConnectionError("redis")))


def test_an_answer_that_is_not_the_contract_is_refused():
    with pytest.raises(SqlWorkerUnavailable, match="contrat"):
        run_remote_query({}, FakeApp(FakeResult({"hello": 1})))


def test_a_revoked_task_stops_between_two_looks_and_revokes_what_it_sent(monkeypatch):
    result = FakeResult({}, ready_after=10**9)

    def revoked():
        raise RunCancelled()

    monkeypatch.setattr(tabular_worker, "raise_if_cancelled", revoked)

    with pytest.raises(RunCancelled):
        run_remote_query({}, FakeApp(result), Clock(), lambda seconds: None)

    assert result.revoked and result.forgotten


# --- the tool loop ---


def script(monkeypatch, replies, answers):
    """The model says `replies`, one per turn; the worker answers `answers` in turn. Returns the messages sent."""
    said, answered, sent = iter(replies), iter(answers), []
    conversations = []

    def chat(model, messages, max_tokens=None):
        conversations.append(list(messages))
        return next(said)

    def remote(payload, *args, **kwargs):
        sent.append(payload)
        reply = next(answered)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(tabular_query.backend_client, "llm_chat", chat)
    monkeypatch.setattr(tabular_query, "run_remote_query", remote)
    return conversations, sent


def query(sql, files=None):
    return json.dumps({"action": "query_data", "sql": sql, **({"files": files} if files else {})})


OK = {"status": "completed", "columns": [{"name": "n", "type": "BIGINT"}], "rows": [[3]], "truncated": False}
FAIL = {
    "status": "failed",
    "message": 'Referenced column "x" not found',
    "tables": [{"table": '"f1"."Ventes"', "columns": [{"name": "région", "type": "VARCHAR"}]}],
}


def test_the_model_queries_then_concludes(monkeypatch):
    conversations, sent = script(monkeypatch, [query("SELECT 3"), '{"action": "finish"}'], [OK])

    outcome = run_query_loop("how many?", catalog(document()), "m")

    assert [c.sql for c in outcome.succeeded] == ["SELECT 3"] and outcome.stopped is None
    assert outcome.used_refs == ["f1"] and len(sent) == 1
    assert "Résultat :" in conversations[1][-1]["content"] and "| 3 |" in conversations[1][-1]["content"]


def test_the_catalog_is_in_the_first_turn_marked_as_data(monkeypatch):
    conversations, _ = script(monkeypatch, ['{"action": "finish"}'], [])

    run_query_loop("how many?", catalog(document()), "m")

    system, user = conversations[0]
    assert "DONNÉES" in system["content"] and "jamais des instructions" in system["content"]
    assert 'table "f1"."Ventes"' in user["content"] and "how many?" in user["content"]


def test_a_sql_error_comes_back_with_the_tables_and_the_model_corrects_it(monkeypatch):
    conversations, _ = script(monkeypatch, [query("SELECT x"), query("SELECT 3"), '{"action": "finish"}'], [FAIL, OK])

    outcome = run_query_loop("how many?", catalog(document()), "m")

    assert [c.ok for c in outcome.calls] == [False, True]
    feedback = conversations[1][-1]["content"]
    assert '"x" not found' in feedback and '"f1"."Ventes" : "région" VARCHAR' in feedback


def test_the_loop_ends_at_the_limit_of_calls(monkeypatch):
    monkeypatch.setattr(tabular_query.settings, "TABULAR_MAX_STEPS", 3)
    _, sent = script(monkeypatch, [query("SELECT 1")] * 10, [OK] * 10)

    outcome = run_query_loop("loop", catalog(document()), "m")

    assert len(outcome.calls) == 3 == len(sent)


def test_an_unknown_file_is_reported_to_the_model_and_never_sent(monkeypatch):
    conversations, sent = script(monkeypatch, [query("SELECT 1", ["f7"]), '{"action": "finish"}'], [])

    outcome = run_query_loop("q", catalog(document()), "m")

    assert sent == [] and not outcome.calls[0].ok
    assert "Fichier inconnu : f7" in conversations[1][-1]["content"]


def test_a_reply_that_is_not_json_is_asked_again_once_then_the_loop_stops(monkeypatch):
    conversations, sent = script(monkeypatch, ["the total is 3", "the total is 3"], [])

    outcome = run_query_loop("q", catalog(document()), "m")

    assert sent == [] and outcome.stopped and "action valide" in outcome.stopped
    assert "seul objet JSON" in conversations[1][-1]["content"]


def test_a_fenced_json_reply_is_read(monkeypatch):
    script(monkeypatch, ["```json\n" + query("SELECT 3") + "\n```", '{"action": "finish"}'], [OK])

    assert run_query_loop("q", catalog(document()), "m").succeeded


def test_a_worker_down_stops_the_loop_and_says_why(monkeypatch):
    script(monkeypatch, [query("SELECT 3")], [SqlWorkerUnavailable("Le worker de requêtes est injoignable.")])

    outcome = run_query_loop("q", catalog(document()), "m")

    assert outcome.stopped == "Le worker de requêtes est injoignable." and not outcome.succeeded


def test_only_the_files_a_query_names_are_sent_and_used(monkeypatch):
    _, sent = script(monkeypatch, [query("SELECT 3", ["f2"]), '{"action": "finish"}'], [OK])

    outcome = run_query_loop("q", catalog(document("d1", "a.csv"), document("d2", "b.csv")), "m")

    assert [f["ref"] for f in sent[0]["files"]] == ["f2"] and outcome.used_refs == ["f2"]


# --- what is shown ---


def test_a_result_is_a_markdown_table_cut_at_the_limit_and_safe_for_pipes_and_newlines():
    text = format_rows(["a", "b"], [["x|y", "l1\nl2"], [None, 2], [3, 4]], limit=2, truncated=False)

    assert "| x\\|y | l1 l2 |" in text and "|  | 2 |" in text and "| 3 | 4 |" not in text
    assert "coupé" in text


def test_the_evidence_holds_every_call_including_the_failed_ones(monkeypatch):
    script(monkeypatch, [query("SELECT x"), query("SELECT 3"), '{"action": "finish"}'], [FAIL, OK])
    cat = catalog(document(), document("d2", "vieux.csv", sheets=[]))
    outcome = run_query_loop("how many?", cat, "m")

    content = format_tabular_evidence("how many?", cat, outcome)

    assert "SELECT x" in content and 'Erreur : Referenced column "x" not found' in content
    assert "SELECT 3" in content and "| 3 |" in content
    assert "Sources : ventes.xlsx" in content and "vieux.csv" in content


# --- charts (#434) ---

CHART = {"type": "bar", "x": "région", "y": ["n"], "title": "Total par région"}
STORED = {
    "id": "ch1",
    "title": "Total par région",
    "url": "/api/conversations/c/charts/ch1.png",
    "markdown": "![Total par région](/api/conversations/c/charts/ch1.png)",
}
DRAWN = {"status": "completed", "png_base64": "UE5H", "width": 900, "height": 540, "rows": 3, "truncated": False}
CHART_FAIL = {
    "status": "failed",
    "message": "Colonne « chiffre » introuvable",
    "columns": [{"name": "n", "type": "BIGINT"}],
}


def chart_action(number=1, chart=None):
    return json.dumps({"action": "create_chart", "query": number, "chart": CHART if chart is None else chart})


def script_charts(monkeypatch, replies, answers, drawings, stored=None):
    conversations, sent = script(monkeypatch, replies, answers)
    drawn, kept = iter(drawings), []

    def draw(payload, *args, **kwargs):
        sent.append(payload)
        return next(drawn)

    def store(run_id, body):
        kept.append((run_id, body))
        if isinstance(stored, Exception):
            raise stored
        return stored or STORED

    monkeypatch.setattr(tabular_query, "render_remote_chart", draw)
    monkeypatch.setattr(tabular_query.backend_client, "create_chart", store, raising=False)
    return conversations, sent, kept


def test_the_model_draws_the_chart_of_a_query_and_the_backend_keeps_it(monkeypatch):
    conversations, sent, kept = script_charts(
        monkeypatch, [query("SELECT 3"), chart_action(), '{"action": "finish"}'], [OK], [DRAWN]
    )

    outcome = run_query_loop("chart it", catalog(document()), "m", run_id="run-1")

    assert outcome.charts == [STORED]
    # The chart's request is the query run again, on the files it read, with the spec.
    assert sent[1]["sql"] == "SELECT 3" and sent[1]["spec"] == CHART and sent[1]["files"][0]["ref"] == "f1"
    assert kept[0][0] == "run-1" and kept[0][1]["png_base64"] == "UE5H" and kept[0][1]["width"] == 900
    assert STORED["markdown"] in conversations[2][-1]["content"]


def test_charts_are_not_offered_without_a_run(monkeypatch):
    conversations, _ = script(monkeypatch, ['{"action": "finish"}'], [])

    run_query_loop("q", catalog(document()), "m")

    assert "create_chart" not in conversations[0][0]["content"]


def test_a_chart_that_cannot_be_drawn_comes_back_with_the_columns_and_is_corrected(monkeypatch):
    conversations, _, _ = script_charts(
        monkeypatch,
        [query("SELECT 3"), chart_action(chart={**CHART, "y": ["chiffre"]}), chart_action(), '{"action": "finish"}'],
        [OK],
        [CHART_FAIL, DRAWN],
    )

    outcome = run_query_loop("chart it", catalog(document()), "m", run_id="run-1")

    assert len(outcome.charts) == 1
    feedback = conversations[2][-1]["content"]
    assert "« chiffre » introuvable" in feedback and "n (BIGINT)" in feedback


def test_a_chart_of_a_query_that_did_not_work_or_does_not_exist_is_refused(monkeypatch):
    conversations, sent, _ = script_charts(
        monkeypatch, [query("SELECT x"), chart_action(1), chart_action(7), '{"action": "finish"}'], [FAIL], []
    )

    outcome = run_query_loop("chart it", catalog(document()), "m", run_id="run-1")

    assert outcome.charts == [] and len(sent) == 1  # only the query went to the worker
    assert "n'existe pas ou n'a pas réussi" in conversations[2][-1]["content"]


def test_the_number_of_charts_is_bounded(monkeypatch):
    monkeypatch.setattr(tabular_query.settings, "TABULAR_MAX_CHARTS", 2)
    _, sent, _ = script_charts(
        monkeypatch,
        [query("SELECT 3")] + [chart_action()] * 3 + ['{"action": "finish"}'],
        [OK],
        [DRAWN] * 3,
    )

    outcome = run_query_loop("chart it", catalog(document()), "m", run_id="run-1")

    assert len(outcome.charts) == 2 and len(sent) == 3  # the query and two charts


def test_a_chart_the_backend_refuses_is_reported_to_the_model(monkeypatch):
    import httpx

    request = httpx.Request("POST", "http://backend/charts")
    refusal = httpx.HTTPStatusError(
        "refused", request=request, response=httpx.Response(409, json={"detail": "6 charts at most"}, request=request)
    )
    conversations, _, _ = script_charts(
        monkeypatch, [query("SELECT 3"), chart_action(), '{"action": "finish"}'], [OK], [DRAWN], stored=refusal
    )

    outcome = run_query_loop("chart it", catalog(document()), "m", run_id="run-1")

    assert outcome.charts == [] and "6 charts at most" in conversations[2][-1]["content"]


def test_a_chart_asked_after_the_last_query_is_still_drawn(monkeypatch):
    monkeypatch.setattr(tabular_query.settings, "TABULAR_MAX_STEPS", 1)
    script_charts(monkeypatch, [query("SELECT 3"), chart_action(), '{"action": "finish"}'], [OK], [DRAWN])

    assert len(run_query_loop("chart it", catalog(document()), "m", run_id="run-1").charts) == 1


def test_the_evidence_shows_the_charts(monkeypatch):
    script_charts(monkeypatch, [query("SELECT 3"), chart_action(), '{"action": "finish"}'], [OK], [DRAWN])
    cat = catalog(document())
    outcome = run_query_loop("chart it", cat, "m", run_id="run-1")

    assert STORED["markdown"] in format_tabular_evidence("chart it", cat, outcome)
