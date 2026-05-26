import pytest

from src.infrastructure.notion.dynamic_notion_service import DynamicNotionService


class _FakeEndpoint:
    def __init__(self, objects):
        self.objects = objects

    def retrieve(self, **kwargs):
        object_id = kwargs.get("database_id") or kwargs.get("page_id") or kwargs.get("block_id")
        return self.objects[object_id]


class _FakeClient:
    def __init__(self, *, databases=None, pages=None, blocks=None):
        self.databases = _FakeEndpoint(databases or {})
        self.pages = _FakeEndpoint(pages or {})
        self.blocks = _FakeEndpoint(blocks or {})


def _service(client, database_id="db1"):
    service = DynamicNotionService.__new__(DynamicNotionService)
    service.client = client
    service.database_id = database_id
    return service


def test_ensure_database_editable_rejects_trashed_database():
    client = _FakeClient(
        databases={
            "db1": {
                "object": "database",
                "id": "db1",
                "title": [{"plain_text": "Task DB"}],
                "in_trash": True,
            }
        }
    )

    with pytest.raises(ValueError, match="Notion database is in trash"):
        _service(client)._ensure_database_editable()


def test_ensure_database_editable_rejects_trashed_block_ancestor():
    client = _FakeClient(
        databases={
            "db1": {
                "object": "database",
                "id": "db1",
                "title": [{"plain_text": "Task DB"}],
                "in_trash": False,
                "parent": {"type": "block_id", "block_id": "block1"},
            }
        },
        blocks={
            "block1": {
                "object": "block",
                "id": "block1",
                "type": "callout",
                "callout": {},
                "in_trash": True,
            }
        },
    )

    with pytest.raises(ValueError, match="Notion block is in trash"):
        _service(client)._ensure_database_editable()


def test_ensure_page_editable_rejects_trashed_parent_database():
    client = _FakeClient(
        pages={
            "page1": {
                "object": "page",
                "id": "page1",
                "properties": {},
                "in_trash": False,
                "parent": {"type": "database_id", "database_id": "db1"},
            }
        },
        databases={
            "db1": {
                "object": "database",
                "id": "db1",
                "title": [{"plain_text": "Task DB"}],
                "in_trash": True,
            }
        },
    )

    with pytest.raises(ValueError, match="Notion database is in trash"):
        _service(client)._ensure_page_editable("page1", "updating task status")


def test_ensure_database_editable_accepts_active_parent_chain():
    client = _FakeClient(
        databases={
            "db1": {
                "object": "database",
                "id": "db1",
                "title": [{"plain_text": "Task DB"}],
                "in_trash": False,
                "parent": {"type": "block_id", "block_id": "block1"},
            }
        },
        blocks={
            "block1": {
                "object": "block",
                "id": "block1",
                "type": "callout",
                "callout": {},
                "in_trash": False,
                "parent": {"type": "page_id", "page_id": "page1"},
            }
        },
        pages={
            "page1": {
                "object": "page",
                "id": "page1",
                "properties": {},
                "in_trash": False,
                "parent": {"type": "workspace", "workspace": True},
            }
        },
    )

    _service(client)._ensure_database_editable()
