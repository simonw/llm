import llm
import random
from typing import AsyncGenerator, Union


def build_markov_table(text):
    words = text.split()
    transitions = {}
    # Loop through all but the last word
    for i in range(len(words) - 1):
        word = words[i]
        next_word = words[i + 1]
        transitions.setdefault(word, []).append(next_word)
    return transitions


def generate(transitions, length, start_word=None):
    all_words = list(transitions.keys())
    next_word = start_word or random.choice(all_words)
    for i in range(length):
        yield next_word
        options = transitions.get(next_word) or all_words
        next_word = random.choice(options)


class Markov(llm.Model):
    model_id = "markov"

    def execute(self, prompt, stream, response, conversation):
        text = prompt.prompt
        transitions = build_markov_table(text)
        for word in generate(transitions, 20):
            yield word + " "


class AnnotationsModel(llm.Model):
    model_id = "annotations"
    can_stream = True

    def execute(self, prompt, stream, response, conversation):
        yield "Here is text before the annotation. "
        yield llm.Chunk(
            text="This is the annotated text. ",
            annotation={"title": "Annotation Title", "content": "Annotation Content"},
        )
        yield "Here is text after the annotation."


class AnnotationsModelAsync(llm.AsyncModel):
    model_id = "annotations"
    can_stream = True

    async def execute(
        self, prompt, stream, response, conversation=None
    ) -> AsyncGenerator[Union[llm.Chunk, str], None]:
        yield "Here is text before the annotation. "
        yield llm.Chunk(
            text="This is the annotated text. ",
            annotation={"title": "Annotation Title", "content": "Annotation Content"},
        )
        yield "Here is text after the annotation."
