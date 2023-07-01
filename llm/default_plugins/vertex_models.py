from llm import Model, Prompt, Response, hookimpl
from llm.errors import NeedsKeyException
import requests


@hookimpl
def register_models(register):
    register(Vertex("text-bison-001"), aliases=("palm2",))


class VertexResponse(Response):
    def __init__(self, prompt, key):
        self.key = key
        super().__init__(prompt)

    def iter_prompt(self):
        url = (
            f"https://generativelanguage.googleapis.com/v1beta2/models/{self.prompt.model.model_id}:generateText"
            f"?key={self.key}"
        )
        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json={"prompt": {"text": self.prompt.prompt}},
        )
        data = response.json()
        candidate = data["candidates"][0]
        self._debug = {"safetyRatings": candidate["safetyRatings"]}
        self._done = True
        yield candidate["output"]


class Vertex(Model):
    needs_key = "vertex"

    def __init__(self, model_id, key=None):
        self.model_id = model_id
        self.key = key

    def execute(self, prompt: Prompt, stream: bool) -> VertexResponse:
        # ignore stream, since we cannot stream
        if self.key is None:
            raise NeedsKeyException(
                "{} needs an API key, label={}".format(str(self), self.needs_key)
            )
        return VertexResponse(prompt, key=self.key)

    def __str__(self):
        return "Vertex Chat: {}".format(self.model_id)
