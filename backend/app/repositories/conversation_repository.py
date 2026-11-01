import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.run import Run

# The text search configuration of the migration (#509): French, and blind to accents. The same expression as the index.
_SEARCH_CONFIG = literal_column("'muffin_french'::regconfig")

# Around the words found in a snippet: control characters, which a message cannot be expected to hold and which are no
# markup - the page that shows the snippet splits on them and never builds HTML from the text.
HIGHLIGHT_START = "\x02"
HIGHLIGHT_END = "\x03"
_HEADLINE_OPTIONS = f'StartSel="{HIGHLIGHT_START}", StopSel="{HIGHLIGHT_END}", MaxFragments=1, MaxWords=24, MinWords=8'


@dataclass(frozen=True)
class ConversationHit:
    """A conversation the search found: in its title, or in its best message (`message_id` and `snippet`)."""

    conversation: Conversation
    in_title: bool
    message_id: uuid.UUID | None
    snippet: str | None


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, conversation_id: uuid.UUID, user_id: str) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_by_owner(self, user_id: str, *, limit: int, offset: int) -> tuple[Sequence[Conversation], int]:
        """Most recently active first - "active" meaning its last message, not just when the
        conversation row itself was last touched (title generation, say), since that's what a
        chat sidebar means by "recent"."""
        where = (Conversation.user_id == user_id) & Conversation.source.is_(None)
        total = await self.db.scalar(select(func.count()).select_from(Conversation).where(where))

        last_message_at = (
            select(Message.conversation_id, func.max(Message.created_at).label("last_at"))
            .group_by(Message.conversation_id)
            .subquery()
        )
        result = await self.db.execute(
            select(Conversation)
            .outerjoin(last_message_at, last_message_at.c.conversation_id == Conversation.id)
            .where(where)
            .order_by(func.coalesce(last_message_at.c.last_at, Conversation.updated_at).desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total or 0

    async def search_by_owner(
        self, user_id: str, query: str, *, limit: int, offset: int
    ) -> tuple[list[ConversationHit], int]:
        """The conversations of this user whose title or messages hold the words of `query` (web search syntax: quotes,
        `-`, `or`), accents and case ignored, the best match first: a title match, then the better message. One hit per
        conversation, with the snippet of its best message."""
        tsquery = func.websearch_to_tsquery(_SEARCH_CONFIG, query)
        vector = Message.content_tsv
        rank = func.ts_rank(vector, tsquery)
        best = (
            select(Message.conversation_id, Message.id.label("message_id"), rank.label("rank"))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user_id, Conversation.source.is_(None), vector.op("@@")(tsquery))
            .distinct(Message.conversation_id)
            .order_by(Message.conversation_id, rank.desc(), Message.created_at.desc())
            .subquery("best")
        )
        in_title = func.to_tsvector(_SEARCH_CONFIG, func.coalesce(Conversation.title, "")).op("@@")(tsquery)
        found = (
            select(Conversation, in_title.label("in_title"), best.c.message_id, best.c.rank)
            .outerjoin(best, best.c.conversation_id == Conversation.id)
            .where(
                Conversation.user_id == user_id,
                Conversation.source.is_(None),
                or_(best.c.message_id.is_not(None), in_title),
            )
        )
        total = await self.db.scalar(select(func.count()).select_from(found.subquery()))
        rows = (
            await self.db.execute(
                found.order_by(in_title.desc(), func.coalesce(best.c.rank, 0).desc(), Conversation.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()

        message_ids = [row.message_id for row in rows if row.message_id is not None]
        snippets: dict[uuid.UUID, str] = {}
        if message_ids:
            headlines = await self.db.execute(
                select(Message.id, func.ts_headline(_SEARCH_CONFIG, Message.content, tsquery, _HEADLINE_OPTIONS)).where(
                    Message.id.in_(message_ids)
                )
            )
            snippets = {message_id: snippet for message_id, snippet in headlines.all()}
        hits = [
            ConversationHit(row.Conversation, bool(row.in_title), row.message_id, snippets.get(row.message_id))
            for row in rows
        ]
        return hits, total or 0

    async def list_messages(
        self, conversation_id: uuid.UUID
    ) -> Sequence[
        tuple[Message, list[dict] | None, dict | None, list[str] | None, str | None, str | None, str | None, int | None]
    ]:
        """Joined to Run rather than storing citations on Message too - Run is already the
        source of truth for them (§ conversation persistence), and a message never outlives the
        run that produced it in any way that would make them diverge. Same for the edit proposal
        a run may have delegated (#171), the sub-collections it left unexplored (#219), what the guardrails on
        the input did to its request (#516), and how many items of the person's memory shaped its answer (#283)."""
        result = await self.db.execute(
            select(
                Message,
                Run.citations,
                Run.edit_proposal,
                Run.unexplored_collection_ids,
                Run.assistant_name,
                Run.guardrail_outcome,
                Run.guardrail_notice,
                Run.memory_used,
            )
            .outerjoin(Run, Message.run_id == Run.id)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return result.all()

    async def get_assistant_message_by_run_id(self, run_id: uuid.UUID) -> Message | None:
        """The assistant's answer message for a run - not Run.message_id, which is the *user*
        message that triggered it (see Run.message_id's docstring). This is what a feedback
        (always given on the answer, never the question) attaches to."""
        result = await self.db.execute(
            select(Message).where(Message.run_id == run_id, Message.role == MessageRole.ASSISTANT)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, conversation_id: uuid.UUID) -> Conversation | None:
        """No owner check - internal/worker use only, never exposed on a user-facing route."""
        result = await self.db.execute(select(Conversation).where(Conversation.id == conversation_id))
        return result.scalar_one_or_none()

    async def set_generated_title(self, conversation: Conversation, title: str) -> None:
        conversation.title = title
        conversation.title_generated = True

    async def purge_from_source(self, source: str, older_than: datetime) -> int:
        """Deletes the conversations a program made (see Conversation.source) that were last touched before
        `older_than`, with their messages and runs. Returns how many."""
        result = await self.db.execute(
            delete(Conversation).where(Conversation.source == source, Conversation.updated_at < older_than)
        )
        return result.rowcount

    async def delete(self, conversation: Conversation) -> None:
        await self.db.delete(conversation)

    async def create(self, user_id: str, title: str | None = None, source: str | None = None) -> Conversation:
        conversation = Conversation(user_id=user_id, title=title, source=source)
        self.db.add(conversation)
        await self.db.flush()
        return conversation

    async def add_message(
        self,
        conversation_id: uuid.UUID,
        role: MessageRole,
        content: str,
        run_id: uuid.UUID | None = None,
        latency_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        questions: list[dict] | None = None,
        created_at: datetime | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            run_id=run_id,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            questions=questions,
            **({} if created_at is None else {"created_at": created_at}),
        )
        self.db.add(message)
        await self.db.flush()
        return message

    async def get_last_message(self, conversation_id: uuid.UUID) -> Message | None:
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
