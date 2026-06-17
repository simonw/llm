import llm
from llm.default_plugins.openai_models import Chat, AsyncChat

PINSTRIPES_API_BASE = "https://pinstripes.io/v1"

MODELS = [
    # model_id, model_name, aliases
    ("ps/deepseek-v4-flash", "ps/deepseek-v4-flash", ("deepseek-v4-flash",)),
    ("ps/qwen3.6-35b-a3b", "ps/qwen3.6-35b-a3b", ("qwen3.6-35b",)),
    ("ps/qwen3-30b-a3b", "ps/qwen3-30b-a3b", ("qwen3-30b",)),
    ("ps/glm-4.5-air", "ps/glm-4.5-air", ("glm-4.5-air",)),
    ("ps/minimax-m2.7", "ps/minimax-m2.7", ("minimax-m2.7",)),
]


class PinstripesChat(Chat):
    needs_key = "pinstripes"
    key_env_var = "PINSTRIPES_API_KEY"

    def __str__(self):
        return "Pinstripes: {}".format(self.model_id)


class PinstripesAsyncChat(AsyncChat):
    needs_key = "pinstripes"
    key_env_var = "PINSTRIPES_API_KEY"

    def __str__(self):
        return "Pinstripes: {}".format(self.model_id)


@llm.hookimpl
def register_models(register):
    for model_id, model_name, aliases in MODELS:
        register(
            PinstripesChat(
                model_id=model_id,
                model_name=model_name,
                api_base=PINSTRIPES_API_BASE,
            ),
            PinstripesAsyncChat(
                model_id=model_id,
                model_name=model_name,
                api_base=PINSTRIPES_API_BASE,
            ),
            aliases=aliases,
        )
