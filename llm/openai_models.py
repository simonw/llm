from . import Model, Prompt, OptionsError, Response, hookimpl
from typing import Optional
import openai


@hookimpl
def register_models(register):
    register(Chat("gpt-3.5-turbo"), aliases=("3.5", "chatgpt"))
    register(Chat("gpt-3.5-turbo-16k"), aliases=("chatgpt-16k", "3.5-16k"))
    register(Chat("gpt-4"), aliases=("4", "gpt4"))
    register(Chat("gpt-4-32k"), aliases=("4-32k",))


class ChatResponse(Response):
    def __init__(self, prompt, stream):
        self.prompt = prompt
        self.stream = stream
        super().__init__(prompt)

    def iter_prompt(self):
        messages = []
        if self.prompt.system:
            messages.append({"role": "system", "content": self.prompt.system})
        messages.append({"role": "user", "content": self.prompt.prompt})
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
    def __init__(self, model_id, stream=True):
        self.model_id = model_id
        self.stream = stream

    def execute(self, prompt: Prompt, stream: bool = True) -> ChatResponse:
        return ChatResponse(prompt, stream)

    def __str__(self):
        return "OpenAI Chat: {}".format(self.model_id)
