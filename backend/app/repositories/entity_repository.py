import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document import Document
from app.models.entity import Entity, EntityDocument, EntityMention, EntityType, Relation


@dataclass(frozen=True)
class Occurrence:
    """Where an entity is in a page (#352): an interval of characters of that page's content."""

    page_number: int
    char_start: int
    char_end: int


@dataclass(frozen=True)
class RelationSource:
    """The sentence that justifies a relation, and where it is (#352)."""

    page: int
    excerpt: str
    start: int | None = None
    end: int | None = None


# What a window holds, in the shape the repository is given and gives back: (name, type, mentions) -
# optionally followed by the entity's occurrences - and (from name, to name, type), optionally followed by the
# relation's source. The short forms are what extractions made before the positions were kept give.
EntityRow = tuple
RelationRow = tuple


class EntityRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def replace_window(
        self,
        collection_id: uuid.UUID,
        document_id: uuid.UUID,
        window_key: str,
        entities: Sequence[EntityRow],
        relations: Sequence[RelationRow],
    ) -> None:
        """Records what was extracted from one window of a document's pages, replacing what an earlier
        extraction of the same window had recorded (#299): a task run twice leaves the same entities,
        relations, counts and occurrences as one run. `entities` are (name, type, mentions[, occurrences]) and
        `relations` (from name, to name, type[, source]); a relation naming an entity that was not extracted is
        dropped."""
        touched = await self._remove_contributions(document_id, window_key)
        await self.db.execute(
            delete(Relation).where(Relation.document_id == document_id, Relation.window_key == window_key)
        )
        await self.db.execute(
            delete(EntityMention).where(
                EntityMention.document_id == document_id, EntityMention.window_key == window_key
            )
        )

        # The same entity listed twice in a window is one entity mentioned twice.
        mentions_by_entity: dict[tuple[str, str], int] = {}
        occurrences_by_entity: dict[tuple[str, str], list[Occurrence]] = {}
        for name, type_, mentions, *rest in entities:
            mentions_by_entity[(name, type_)] = mentions_by_entity.get((name, type_), 0) + mentions
            if rest and rest[0]:
                known = occurrences_by_entity.setdefault((name, type_), [])
                known.extend(occurrence for occurrence in rest[0] if occurrence not in known)

        ids: dict[str, uuid.UUID] = {}
        for (name, type_), mentions in mentions_by_entity.items():
            entity = await self._get_or_create(collection_id, name, type_)
            entity.mentions += mentions
            link = await self.db.get(EntityDocument, (entity.id, document_id, window_key))
            if link is None:
                self.db.add(
                    EntityDocument(
                        entity_id=entity.id, document_id=document_id, window_key=window_key, mentions=mentions
                    )
                )
            else:
                link.mentions += mentions
            ids[name] = entity.id
            touched.discard(entity.id)
            self.db.add_all(
                EntityMention(
                    entity_id=entity.id,
                    document_id=document_id,
                    window_key=window_key,
                    page_number=occurrence.page_number,
                    char_start=occurrence.char_start,
                    char_end=occurrence.char_end,
                )
                for occurrence in occurrences_by_entity.get((name, type_), [])
            )
        await self.db.flush()

        for from_name, to_name, relation_type, *rest in relations:
            if from_name in ids and to_name in ids:
                source: RelationSource | None = rest[0] if rest else None
                self.db.add(
                    Relation(
                        collection_id=collection_id,
                        document_id=document_id,
                        window_key=window_key,
                        from_entity_id=ids[from_name],
                        to_entity_id=ids[to_name],
                        type=relation_type,
                        source_page=source.page if source else None,
                        source_excerpt=source.excerpt if source else None,
                        source_start=source.start if source else None,
                        source_end=source.end if source else None,
                    )
                )
        await self._delete_unmentioned(touched)
        await self.db.flush()

    async def export_windows(self, document_id: uuid.UUID) -> dict[str, tuple[list[EntityRow], list[RelationRow]]]:
        """What was extracted from each window of a document's pages, by window: its entities (name, type,
        mentions, occurrences) and relations (from name, to name, type, source) - what another document of the
        same file reuses (#300). A mention from before the windows were recorded has no window and is left
        out."""
        windows: dict[str, tuple[list[EntityRow], list[RelationRow]]] = {}
        occurrences: dict[tuple[str, uuid.UUID], list[Occurrence]] = {}
        located = await self.db.execute(
            select(EntityMention).where(EntityMention.document_id == document_id, EntityMention.window_key != "")
        )
        for mention in located.scalars().all():
            occurrences.setdefault((mention.window_key, mention.entity_id), []).append(
                Occurrence(mention.page_number, mention.char_start, mention.char_end)
            )
        links = await self.db.execute(
            select(EntityDocument.window_key, Entity.id, Entity.name, Entity.type, EntityDocument.mentions)
            .join(Entity, Entity.id == EntityDocument.entity_id)
            .where(EntityDocument.document_id == document_id, EntityDocument.window_key != "")
        )
        for window_key, entity_id, name, type_, mentions in links.all():
            windows.setdefault(window_key, ([], []))[0].append(
                (name, type_.value, mentions, occurrences.get((window_key, entity_id), []))
            )
        relations = await self.db.execute(
            select(Relation)
            .where(Relation.document_id == document_id, Relation.window_key.is_not(None))
            .options(selectinload(Relation.from_entity), selectinload(Relation.to_entity))
        )
        for relation in relations.scalars().all():
            source = (
                RelationSource(
                    relation.source_page, relation.source_excerpt, relation.source_start, relation.source_end
                )
                if relation.source_page and relation.source_excerpt
                else None
            )
            windows.setdefault(relation.window_key, ([], []))[1].append(
                (relation.from_entity.name, relation.to_entity.name, relation.type, source)
            )
        return windows

    async def remove_document(self, document_id: uuid.UUID) -> None:
        """Takes a document's contribution out of the collection: its mentions leave the entities' counts
        (an entity nothing mentions anymore goes), and its relations go (#299). For a document that is
        deleted or about to be extracted again."""
        touched = await self._remove_contributions(document_id, None)
        await self.db.execute(delete(Relation).where(Relation.document_id == document_id))
        await self.db.execute(delete(EntityMention).where(EntityMention.document_id == document_id))
        await self._delete_unmentioned(touched)
        await self.db.flush()

    async def _get_or_create(self, collection_id: uuid.UUID, name: str, type_: str) -> Entity:
        result = await self.db.execute(
            select(Entity).where(
                Entity.collection_id == collection_id, Entity.name == name, Entity.type == EntityType(type_)
            )
        )
        entity = result.scalar_one_or_none()
        if entity is None:
            entity = Entity(collection_id=collection_id, name=name, type=EntityType(type_), mentions=0)
            self.db.add(entity)
            await self.db.flush()
        return entity

    async def _remove_contributions(self, document_id: uuid.UUID, window_key: str | None) -> set[uuid.UUID]:
        """Subtracts a document's mentions - of one window, or of all - from the entities' counts and
        forgets them. Returns the entities that were affected."""
        condition = [EntityDocument.document_id == document_id]
        if window_key is not None:
            condition.append(EntityDocument.window_key == window_key)
        links = (await self.db.execute(select(EntityDocument).where(*condition))).scalars().all()
        touched: set[uuid.UUID] = set()
        for link in links:
            entity = await self.db.get(Entity, link.entity_id)
            if entity is not None:
                # Never below zero: a row written before the per-window breakdown existed may not add up.
                entity.mentions = max(0, entity.mentions - link.mentions)
                touched.add(entity.id)
            await self.db.delete(link)
        await self.db.flush()
        return touched

    async def _delete_unmentioned(self, entity_ids: set[uuid.UUID]) -> None:
        """An entity no document mentions anymore (its relations go with it)."""
        for entity_id in entity_ids:
            mentioned = await self.db.scalar(
                select(func.count()).select_from(EntityDocument).where(EntityDocument.entity_id == entity_id)
            )
            entity = await self.db.get(Entity, entity_id)
            if entity is not None and not mentioned and entity.mentions <= 0:
                await self.db.delete(entity)

    async def list_by_collection(self, collection_id: uuid.UUID) -> Sequence[Entity]:
        result = await self.db.execute(
            select(Entity).where(Entity.collection_id == collection_id).order_by(Entity.mentions.desc())
        )
        return result.scalars().all()

    async def list_relations_by_collection(self, collection_id: uuid.UUID) -> Sequence[Relation]:
        result = await self.db.execute(
            select(Relation)
            .where(Relation.collection_id == collection_id)
            .options(selectinload(Relation.from_entity), selectinload(Relation.to_entity))
        )
        return result.scalars().all()

    async def list_by_document(self, document_id: uuid.UUID) -> Sequence[Entity]:
        result = await self.db.execute(
            select(Entity)
            .join(EntityDocument, EntityDocument.entity_id == Entity.id)
            .where(EntityDocument.document_id == document_id)
            .group_by(Entity.id)
            .order_by(func.sum(EntityDocument.mentions).desc())
        )
        return result.scalars().all()

    async def list_relations_by_document(self, document_id: uuid.UUID) -> Sequence[Relation]:
        result = await self.db.execute(
            select(Relation)
            .where(Relation.document_id == document_id)
            .options(selectinload(Relation.from_entity), selectinload(Relation.to_entity))
        )
        return result.scalars().all()

    async def occurrence_counts(
        self, entity_ids: Sequence[uuid.UUID], document_id: uuid.UUID | None = None
    ) -> Mapping[uuid.UUID, int]:
        """How many occurrences of each entity were found in the text (#352) - in one document when given. An
        entity absent from the result was not found in the text: the model listed it, nothing could be framed."""
        if not entity_ids:
            return {}
        query = (
            select(EntityMention.entity_id, func.count())
            .where(EntityMention.entity_id.in_(entity_ids))
            .group_by(EntityMention.entity_id)
        )
        if document_id is not None:
            query = query.where(EntityMention.document_id == document_id)
        return {entity_id: count for entity_id, count in (await self.db.execute(query)).all()}

    async def list_mentions(
        self, collection_id: uuid.UUID, entity_id: uuid.UUID, document_id: uuid.UUID | None = None, limit: int = 500
    ) -> Sequence[tuple[EntityMention, str]]:
        """The occurrences of an entity of this collection, with the name of their document - by document, then
        page, then place in the page: the order one reads them in."""
        query = (
            select(EntityMention, Document.name)
            .join(Entity, Entity.id == EntityMention.entity_id)
            .join(Document, Document.id == EntityMention.document_id)
            .where(Entity.id == entity_id, Entity.collection_id == collection_id)
            .order_by(Document.name, EntityMention.document_id, EntityMention.page_number, EntityMention.char_start)
            .limit(limit)
        )
        if document_id is not None:
            query = query.where(EntityMention.document_id == document_id)
        return [(mention, name) for mention, name in (await self.db.execute(query)).all()]

    async def document_names(self, document_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not document_ids:
            return {}
        result = await self.db.execute(select(Document.id, Document.name).where(Document.id.in_(document_ids)))
        return {document_id: name for document_id, name in result.all()}
