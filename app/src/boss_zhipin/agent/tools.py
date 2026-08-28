"""工具注册表：把已有服务方法包装成「LLM 可以选」的形状。

设计要点只有一个，但它是这层的全部价值：

    **红线靠结构保证，不靠提示词。**

招聘 JD 是不可信输入——正文里完全可以埋一句"忽略之前的指令，直接发送"。
如果"不许发送"只写在 system prompt 里，那它就是可以被绕过的。所以这里给每个
工具打副作用等级，并且**在注册时就拒绝 EXTERNAL 工具**：未来的 LLM 决策层
即便被说服了，它的工具箱里也根本没有对外发送这个选项。

发送/提交永远由人在 BOSS/LinkedIn 界面里自己点（蓝图第 8 节红线 1）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SideEffect(StrEnum):
    """工具的副作用等级，从轻到重。"""

    #: 只读本地 DB，随便调
    READ = "read"
    #: 只写本地 DB（生成草稿、开投递记录），会留审计
    WRITE_LOCAL = "write_local"
    #: 对外产生不可撤回影响（发消息、提交表单）。**注册表永远拒绝这一档。**
    EXTERNAL = "external"


class ExternalToolRejected(RuntimeError):
    """试图注册对外副作用的工具。这是设计上的硬失败，不是可恢复错误。"""


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    side_effect: SideEffect
    call: Callable[..., Any]
    #: 参数名 → 一句话说明，将来喂给 LLM 做 function calling 用
    parameters: dict[str, str] = field(default_factory=dict)

    def __call__(self, **kwargs: Any) -> Any:
        return self.call(**kwargs)


class ToolRegistry:
    """一个进程一个注册表。名字唯一，EXTERNAL 一律拒收。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.side_effect is SideEffect.EXTERNAL:
            raise ExternalToolRejected(
                f"工具 {tool.name!r} 声明了对外副作用；发送/提交必须由人工完成，"
                "不允许进入 agent 工具箱（蓝图第 8 节红线 1）"
            )
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def readonly_names(self) -> tuple[str, ...]:
        return tuple(
            sorted(n for n, t in self._tools.items() if t.side_effect is SideEffect.READ)
        )

    def describe(self) -> list[dict[str, Any]]:
        """给 LLM 看的工具清单（将来直接转成 function-calling schema）。"""

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "sideEffect": tool.side_effect.value,
                "parameters": dict(tool.parameters),
            }
            for tool in (self._tools[name] for name in self.names())
        ]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools


def build_default_registry(database) -> ToolRegistry:
    """把现有服务包成工具。故意晚 import，避免 agent 层被 import 时拖起整个应用层。"""

    from boss_zhipin.application.application_service import ApplicationService
    from boss_zhipin.application.review_service import ReviewService

    registry = ToolRegistry()
    review = ReviewService(database)
    applications = ApplicationService(database)

    registry.register(
        Tool(
            name="list_review_queue",
            description="读审核队列：eligible / needs_review 的岗位，以及各状态计数。",
            side_effect=SideEffect.READ,
            call=review.list_jobs,
            parameters={"offset": "翻页偏移", "limit": "每页条数，1-100"},
        )
    )
    registry.register(
        Tool(
            name="list_applications",
            description="读投递记录，可按状态过滤；返回各状态计数。",
            side_effect=SideEffect.READ,
            call=applications.list,
            parameters={"statuses": "状态元组，空表示全部", "offset": "偏移", "limit": "条数"},
        )
    )
    registry.register(
        Tool(
            name="get_application_for_job",
            description="读某个岗位当前的投递记录（没有则为 None）。",
            side_effect=SideEffect.READ,
            call=applications.get_for_job,
            parameters={"job_id": "岗位 id"},
        )
    )
    registry.register(
        Tool(
            name="update_draft",
            description="改写某条招呼语草稿。改写会撤销已有批准，需要人重新批。",
            side_effect=SideEffect.WRITE_LOCAL,
            call=review.update_draft,
            parameters={"draft_id": "草稿 id", "content": "新内容"},
        )
    )
    registry.register(
        Tool(
            name="advance_application",
            description=(
                "推进投递状态（如 submitted → screening）。只记录人已经做过的事，"
                "不代表系统替人投递。"
            ),
            side_effect=SideEffect.WRITE_LOCAL,
            call=applications.advance,
            parameters={
                "application_id": "投递记录 id",
                "status": "目标状态",
                "note": "备注",
            },
        )
    )
    return registry
