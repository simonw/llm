from . import Model, Prompt, OptionsError, Response, hookimpl
from .errors import NeedsKeyException
from typing import Optional
import openai


@hookimpl
def register_models(register):
    register(Chat("gpt-3.5-turbo"), aliases=("3.5", "chatgpt"))
    register(Chat("gpt-3.5-turbo-16k"), aliases=("chatgpt-16k", "3.5-16k"))
    register(Chat("gpt-4"), aliases=("4", "gpt4"))
    register(Chat("gpt-4-32k"), aliases=("4-32k",))


class ChatResponse(Response):
    def __init__(self, prompt, stream, key):
        super().__init__(prompt)
        self.stream = stream
        self.key = key

    def iter_prompt(self):
        messages = []
        if self.prompt.system:
            messages.append({"role": "system", "content": self.prompt.system})
        messages.append({"role": "user", "content": self.prompt.prompt})
        openai.api_key = self.key
        if self.stream:
            for chunk in openai.ChatCompletion.create(
                model=self.prompt.model.model_id,
                messages=messages,
                stream=True,
            ):
                self._debug["model"] = chunk.model
                content = chunk["choices"][0].get("delta", {}).get("content")
                if content is not None:
                    yield content
            self._done = True
        else:
            response = openai.ChatCompletion.create(
                model=self.prompt.model.model_id,
                messages=messages,
                stream=False,
            )
            self._debug["model"] = response.model
            self._debug["usage"] = response.usage
            content = response.choices[0].message.content
            self._done = True
            yield content


class Chat(Model):
    needs_key = "openai"
    key_env_var = "OPENAI_API_KEY"
    can_stream: bool = True

    def __init__(self, model_id, key=None):
        self.model_id = model_id
        self.key = key

    def execute(self, prompt: Prompt, stream: bool = True) -> ChatResponse:
        key = self.get_key()
        if key is None:
            raise NeedsKeyException(
                "{} needs an API key, label={}".format(str(self), self.needs_key)
            )
        return ChatResponse(prompt, stream, key=key)

    def __str__(self):
        return "OpenAI Chat: {}".format(self.model_id)
