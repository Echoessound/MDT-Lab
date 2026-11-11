"""Extension contract only. V0.1 makes no external API requests."""

from typing import Protocol, TypeVar

from pydantic import BaseModel

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class LLMClient(Protocol):
    def generate_structured(
        self, system_prompt: str, user_prompt: str, response_model: type[ResponseModel],
    ) -> ResponseModel: ...


class LLMNotImplementedError(NotImplementedError):
    def __init__(self) -> None:
        super().__init__(
            "V0.1 尚未实现 LLM 适配器，仅提供 LLMClient 协议；请使用 --mode mock。"
        )
