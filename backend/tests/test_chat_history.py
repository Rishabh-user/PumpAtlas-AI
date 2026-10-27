"""Chat history: stored per user, and never mistaken for evidence.

The history used to live in the browser. Moving it to the database must not blur the one
rule the chat is built on - a model's prose is not data - nor let one person read another's
questions, so these pin both.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import uuid

from app.api.v1 import chat_history, chat_routes
from app.models import Base
from app.models.chat import ChatConversation
from app.services import chat, chat_log

REPO = pathlib.Path(__file__).resolve().parents[2]


def _routes():
    return {
        node.name: ast.unparse(node)
        for node in ast.parse(pathlib.Path(chat_history.__file__).read_text("utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.decorator_list
    }


class TestHistoryIsStoredNotTrusted:
    def test_asking_writes_no_record(self):
        """`/chat/ask` stores no evidence; for an API key it logs the transcript only."""
        source = inspect.getsource(chat_routes.ask)
        assert "ChatConversation" not in source and "ChatTurn" not in source
        assert "db.add(" not in source and "db.commit()" not in source
        assert "chat_log.record_api_ask" in source

    def test_the_log_only_touches_the_transcript_tables(self):
        source = inspect.getsource(chat_log.record_api_ask)
        assert "db.add(" in source
        for evidence in ("Vendor", "Pump(", "FieldProvenance", "TechnicalSpec"):
            assert evidence not in source, evidence

    def test_logging_cannot_fail_an_answer(self):
        source = inspect.getsource(chat_log.record_api_ask)
        assert "except Exception" in source and "db.rollback()" in source

    def test_a_key_with_no_tenant_is_not_logged(self):
        class Db:
            def __getattr__(self, name):
                raise AssertionError("touched the database")

        key_only = chat_log.Principal(
            user_id=None, tenant_id=None, roles=[], is_platform_admin=False,
            api_key_id=uuid.uuid4(),
        )
        chat_log.record_api_ask(Db(), key_only, "q", {})

    def test_a_person_is_not_logged_by_ask(self):
        class Db:
            def __getattr__(self, name):
                raise AssertionError("touched the database")

        person = chat_log.Principal(
            user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), roles=[], is_platform_admin=False,
        )
        chat_log.record_api_ask(Db(), person, "q", {})

    def test_nothing_reads_the_transcript_back_into_the_record(self):
        """Search, scoring and capture must not consume stored conversations."""
        for module in ("services/chat.py", "services/discovery.py", "services/search.py"):
            text = (REPO / "backend/app" / module).read_text("utf-8")
            assert "ChatTurn" not in text and "chat_turns" not in text, module

    def test_the_tables_are_registered_and_tenant_scoped(self):
        for name in ("chat_conversations", "chat_turns"):
            table = Base.metadata.tables[name]
            assert "tenant_id" in table.c, name


class TestHistoryIsPrivate:
    def test_every_route_requires_search_read(self):
        for name, source in _routes().items():
            assert "require('search', 'read')" in source, name

    def test_a_thread_is_only_opened_by_someone_allowed_to_see_it(self):
        source = inspect.getsource(chat_history._find)
        assert "chat_log.may_see" in source
        # A colleague's thread must look absent, not forbidden - 403 confirms it exists.
        assert "HTTP_404_NOT_FOUND" in source

    def test_the_list_is_filtered_to_what_the_user_may_see(self):
        source = inspect.getsource(chat_history.list_conversations)
        assert "chat_log.visible_to(principal)" in source

    def test_a_colleague_never_sees_a_persons_thread(self):
        """Only a thread an API key started is open to others, and only to admins."""
        person = chat_log.Principal(
            user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), roles=["research_analyst"],
            is_platform_admin=False,
        )
        admin = chat_log.Principal(
            user_id=uuid.uuid4(), tenant_id=person.tenant_id, roles=["admin"],
            is_platform_admin=False,
        )
        mine = ChatConversation(user_id=person.user_id, source=chat_log.SOURCE_APP)
        by_key = ChatConversation(user_id=None, source=chat_log.SOURCE_API_KEY)
        assert chat_log.may_see(mine, person)
        assert not chat_log.may_see(mine, admin)  # not even a tenant admin
        assert not chat_log.may_see(by_key, person)
        assert chat_log.may_see(by_key, admin)

    def test_only_the_owner_adds_a_turn(self):
        assert "_own(" in inspect.getsource(chat_history.add_turn)

    def test_every_route_that_takes_an_id_checks_ownership(self):
        routes = (
            chat_history.get_conversation,
            chat_history.add_turn,
            chat_history.delete_conversation,
        )
        for fn in routes:
            body = inspect.getsource(fn)
            assert "_own(" in body or "_find(" in body, fn.__name__

    def test_an_api_key_cannot_start_a_personal_thread(self):
        """A key's questions are logged by /chat/ask against its tenant, not here."""
        assert "principal.user_id is None" in inspect.getsource(chat_history.create_conversation)

    def test_history_is_bounded(self):
        assert chat_history.MAX_CONVERSATIONS_PER_USER <= 200


class TestSchemaAndMigration:
    def test_rls_lists_both_tables(self):
        rls = (REPO / "db/rls.sql").read_text("utf-8")
        assert "'chat_conversations', 'chat_turns'" in rls

    def test_schema_defines_both_tables(self):
        schema = (REPO / "db/schema.sql").read_text("utf-8")
        assert "CREATE TABLE chat_conversations" in schema
        assert "CREATE TABLE chat_turns" in schema

    def test_a_second_migration_adds_the_api_key_source(self):
        text = (REPO / "db/migrations/005_chat_conversations_api_key_source.sql").read_text("utf-8")
        assert "DROP NOT NULL" in text and "api_key_id" in text and "source_label" in text
        schema = (REPO / "db/schema.sql").read_text("utf-8")
        assert "source_label VARCHAR(160)" in schema

    def test_migration_secures_and_grants_both_tables(self):
        text = (REPO / "db/migrations/004_chat_conversations.sql").read_text("utf-8")
        for name in ("chat_conversations", "chat_turns"):
            assert f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY" in text, name
            assert f"ON {name} TO pumpatlas_app" in text, name

    def test_the_chat_service_does_not_import_the_models(self):
        assert "app.models.chat" not in inspect.getsource(chat)

    def test_a_key_reads_back_what_it_asked(self):
        """The history an integration can actually use.

        `visible_to` had no branch for a key, so it fell through to the personal-thread
        clause and compiled to `user_id IS NULL AND source = 'app'`. A key's own threads
        are stored with `source = 'api_key'`, so the clause excluded exactly the rows the
        key was entitled to. An integration could log every question through /chat/ask
        and never read one back.
        """
        key_id = uuid.uuid4()
        caller = chat_log.Principal(
            user_id=None, tenant_id=uuid.uuid4(), roles=[],
            is_platform_admin=False, api_key_id=key_id,
        )
        mine = ChatConversation(
            user_id=None, api_key_id=key_id, source=chat_log.SOURCE_API_KEY
        )
        assert "api_key_id" in str(chat_log.visible_to(caller))
        assert chat_log.may_see(mine, caller)

    def test_a_key_does_not_read_another_keys_questions(self):
        """Two applications sharing a tenant have no business reading each other's
        queries. An administrator who should see all of them signs in instead."""
        caller = chat_log.Principal(
            user_id=None, tenant_id=uuid.uuid4(), roles=[],
            is_platform_admin=False, api_key_id=uuid.uuid4(),
        )
        theirs = ChatConversation(
            user_id=None, api_key_id=uuid.uuid4(), source=chat_log.SOURCE_API_KEY
        )
        person = ChatConversation(
            user_id=uuid.uuid4(), api_key_id=None, source=chat_log.SOURCE_APP
        )
        assert not chat_log.may_see(theirs, caller)
        assert not chat_log.may_see(person, caller)

    def test_the_list_and_the_fetch_agree_for_a_key(self):
        """A list that hides a thread and a fetch that returns it is a leak; the
        reverse is a thread you can see and cannot open."""
        caller = chat_log.Principal(
            user_id=None, tenant_id=uuid.uuid4(), roles=[],
            is_platform_admin=False, api_key_id=uuid.uuid4(),
        )
        assert "api_key_id" in str(chat_log.visible_to(caller))
        assert "api_key_id" in inspect.getsource(chat_log.may_see)

    def test_a_key_may_read_its_history_but_not_erase_it(self):
        """Logging an API thread exists so an administrator can see which tenant
        searched what. A key deleting its own trail would remove the only record."""
        source = inspect.getsource(chat_history.delete_conversation)
        assert "principal.api_key_id is not None" in source
        assert "HTTP_403_FORBIDDEN" in source

    def test_an_unapplied_migration_is_reported_at_startup(self):
        """These two tables were absent from the database for weeks and nothing said so.

        Every layer handled it politely - the route 500'd, the sidebar showed "no
        conversations yet", and `record_api_ask` caught its own exception - so the
        history simply did not work and no message anywhere named the cause. The server
        now compares the mapped tables against the database on the way up, which is the
        one place a restart puts it in front of whoever is working.
        """
        from app import main

        source = inspect.getsource(main.lifespan)
        assert "_warn_on_schema_drift()" in source
        drift = inspect.getsource(main._warn_on_schema_drift)
        # It must name what is missing; "schema drift detected" would not have helped.
        assert "missing_tables=missing" in drift
        assert "Base.metadata.sorted_tables" in drift
