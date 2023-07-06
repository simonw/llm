from llm import Model, Prompt, hookimpl
import llm
from collections import defaultdict
import random
import time


@hookimpl
def register_models(register):
    register(Markov())


class Markov(Model):
    can_stream = True
    model_id = "markov"

    class Options(Model.Options):
        length: int = 100

    class Response(llm.Response):
        def iter_prompt(self):
            self._prompt_json = {"input": self.prompt.prompt}

            length = self.prompt.options.length

            transitions = defaultdict(list)
            all_words = self.prompt.prompt.split()
            for i in range(len(all_words) - 1):
                transitions[all_words[i]].append(all_words[i + 1])

            result = [all_words[0]]
            for _ in range(length - 1):
                if transitions[result[-1]]:
                    token = random.choice(transitions[result[-1]])
                else:
                    token = random.choice(all_words)
                yield token + " "
                time.sleep(0.02)
                result.append(token)
            self._response_json = {
                "generated": " ".join(result),
                "transitions": dict(transitions),
            }

    def execute(self, prompt: Prompt, stream: bool = True) -> Response:
        return self.Response(prompt, self, stream)

    def __str__(self):
        return "Markov: {}".format(self.model_id)
