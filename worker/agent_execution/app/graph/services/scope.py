"""The collections a search covers: the plan's, the pinned ones, or every accessible one."""

from typing import Any


def scope_ids(plan_collections: list[str], pinned: list[str], accessible: list[dict[str, Any]]) -> list[str]:
    """The ids to search, only ever among the accessible ones (the plan can narrow the user's collections, never widen
    them). Empty when neither the plan nor the user chose any: that means every accessible collection."""
    accessible_ids = {str(vdb["id"]) for vdb in accessible}
    return [vdb_id for vdb_id in dict.fromkeys([*plan_collections, *pinned]) if vdb_id in accessible_ids]


def scope_vdbs(ids: list[str], accessible: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The collections themselves, in the order of `ids` - every accessible one when `ids` is empty."""
    if not ids:
        return list(accessible)
    by_id = {str(vdb["id"]): vdb for vdb in accessible}
    return [by_id[vdb_id] for vdb_id in ids if vdb_id in by_id]
