from llm import hookimpl
from llm.default_plugins.openai_models import Chat, AsyncChat, SharedOptions

from pydantic import Field

from typing import Optional


class MiniMaxOptions(SharedOptions):
    temperature: Optional[float] = Field(
        description=(
            "What sampling temperature to use, between 0.01 and 1. Higher values like "
            "0.8 will make the output more random, while lower values like 0.2 will "
            "make it more focused and deterministic."
        ),
        gt=0,
        le=1,
        default=None,
    )
    json_object: Optional[bool] = Field(
        description="Output a valid JSON object {...}. Prompt must mention JSON.",
        default=None,
    )


class MiniMaxChat(Chat):
    needs_key = "minimax"
    key_env_var = "MINIMAX_API_KEY"

    class Options(MiniMaxOptions):
        pass

    def __str__(self) -> str:
        return "MiniMax Chat: {}".format(self.model_id)


class MiniMaxAsyncChat(AsyncChat):
    needs_key = "minimax"
    key_env_var = "MINIMAX_API_KEY"

    class Options(MiniMaxOptions):
        pass

    def __str__(self) -> str:
        return "MiniMax Chat: {}".format(self.model_id)


MINIMAX_API_BASE = "https://api.minimax.io/v1"


@hookimpl
def register_models(register):
    register(
        MiniMaxChat(
            "MiniMax-M2.7",
            model_name="MiniMax-M2.7",
            api_base=MINIMAX_API_BASE,
        ),
        MiniMaxAsyncChat(
            "MiniMax-M2.7",
            model_name="MiniMax-M2.7",
            api_base=MINIMAX_API_BASE,
        ),
        aliases=("minimax", "m2.7"),
    )
    register(
        MiniMaxChat(
            "MiniMax-M2.7-highspeed",
            model_name="MiniMax-M2.7-highspeed",
            api_base=MINIMAX_API_BASE,
        ),
        MiniMaxAsyncChat(
            "MiniMax-M2.7-highspeed",
            model_name="MiniMax-M2.7-highspeed",
            api_base=MINIMAX_API_BASE,
        ),
        aliases=("minimax-fast", "m2.7-highspeed"),
    )
    register(
        MiniMaxChat(
            "MiniMax-M2.5",
            model_name="MiniMax-M2.5",
            api_base=MINIMAX_API_BASE,
        ),
        MiniMaxAsyncChat(
            "MiniMax-M2.5",
            model_name="MiniMax-M2.5",
            api_base=MINIMAX_API_BASE,
        ),
        aliases=("m2.5",),
    )
    register(
        MiniMaxChat(
            "MiniMax-M2.5-highspeed",
            model_name="MiniMax-M2.5-highspeed",
            api_base=MINIMAX_API_BASE,
        ),
        MiniMaxAsyncChat(
            "MiniMax-M2.5-highspeed",
            model_name="MiniMax-M2.5-highspeed",
            api_base=MINIMAX_API_BASE,
        ),
        aliases=("m2.5-highspeed",),
    )
