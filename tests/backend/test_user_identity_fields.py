from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from app.models.user import User
from app.services.user_service import UserService


def test_user_model_does_not_expose_legacy_identity_aliases():
    mapped_attrs = set(User.__mapper__.attrs.keys())

    assert {"user_id", "username", "auth_provider", "external_id"} <= mapped_attrs
    assert {"id", "name", "provider", "provider_id"}.isdisjoint(mapped_attrs)


def test_user_model_defines_unique_oauth_provider_identity_index():
    indexes = {index.name: index for index in User.__table__.indexes}

    index = indexes["uq_users_auth_provider_external_id"]

    assert index.unique is True
    assert [column.name for column in index.columns] == ["auth_provider", "external_id"]
    assert index.dialect_options["sqlite"]["where"] is not None
    assert index.dialect_options["postgresql"]["where"] is not None


def test_user_service_update_profile_uses_username_parameter():
    signature = inspect.signature(UserService.update_profile)

    assert "username" in signature.parameters
    assert "name" not in signature.parameters


@pytest.mark.asyncio
async def test_user_service_update_profile_writes_username(monkeypatch):
    user = SimpleNamespace(username="old-name", avatar_url=None, updated_at=None)

    class FakeDb:
        async def flush(self):
            return None

        async def refresh(self, obj):
            return None

    service = UserService(FakeDb())

    async def fake_get_by_id_or_raise(user_id: str):
        assert user_id == "user-1"
        return user

    monkeypatch.setattr(service, "get_by_id_or_raise", fake_get_by_id_or_raise)

    result = await service.update_profile(
        "user-1",
        username="new-name",
        avatar_url="https://example.com/avatar.png",
    )

    assert result.username == "new-name"
    assert result.avatar_url == "https://example.com/avatar.png"
