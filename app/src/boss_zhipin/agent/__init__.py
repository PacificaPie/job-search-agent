"""Agent 层：工具注册表 + 当日操盘决策。

现在决策层是确定性的（``planner``）。它存在的意义不只是"先能用"，更是将来
LLM planner 上线时的**对照组**——LLM 版本必须在测评上打赢它才允许接管。
详见 ``docs/agent化改造方案.md``。
"""

from boss_zhipin.agent.tools import SideEffect, Tool, ToolRegistry, build_default_registry

__all__ = ["SideEffect", "Tool", "ToolRegistry", "build_default_registry"]
