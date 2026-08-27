"""Agent 工具层测试：重点是「红线靠结构保证」这条能不能被绕过。"""

import pytest

from boss_zhipin.agent.tools import (
    ExternalToolRejected,
    SideEffect,
    Tool,
    ToolRegistry,
    build_default_registry,
)
from boss_zhipin.persistence.database import Database


def test_external_side_effect_tool_cannot_be_registered():
    """发送/提交类工具进不了工具箱——这是设计上的硬失败，不是可配置项。"""
    registry = ToolRegistry()
    with pytest.raises(ExternalToolRejected, match="红线"):
        registry.register(
            Tool(
                name="send_boss_message",
                description="把招呼语发给招聘者",
                side_effect=SideEffect.EXTERNAL,
                call=lambda **_: None,
            )
        )
    assert len(registry) == 0


def test_duplicate_and_unknown_tool_names_are_errors():
    registry = ToolRegistry()
    tool = Tool("noop", "什么都不做", SideEffect.READ, lambda **_: 1)
    registry.register(tool)
    with pytest.raises(ValueError, match="duplicate tool name"):
        registry.register(Tool("noop", "重名", SideEffect.READ, lambda **_: 2))
    with pytest.raises(KeyError, match="unknown tool"):
        registry.get("missing")
    assert registry.get("noop")() == 1
    assert "noop" in registry


def test_default_registry_has_no_external_tool_and_describes_itself(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        registry = build_default_registry(database)
        described = registry.describe()
        assert described, "默认注册表不应为空"
        assert all(entry["sideEffect"] != SideEffect.EXTERNAL.value for entry in described)
        # 工具名里不该出现任何"发送/提交"语义
        assert not [
            name
            for name in registry.names()
            if any(word in name for word in ("send", "submit", "apply", "post"))
        ]
        assert "list_review_queue" in registry.readonly_names()
        assert "update_draft" not in registry.readonly_names()
    finally:
        database.close()


def test_readonly_tool_does_not_write(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        registry = build_default_registry(database)
        before = registry.get("list_applications")(limit=10)
        registry.get("list_review_queue")(limit=10)
        after = registry.get("list_applications")(limit=10)
        assert before["countsByStatus"] == after["countsByStatus"] == {}
    finally:
        database.close()
