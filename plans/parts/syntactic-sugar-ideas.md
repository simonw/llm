# Syntactic sugar ideas for `parts=[]`

The current `parts=[]` API works but is verbose for common cases:

```python
from llm.parts import TextPart, AttachmentPart

response = model.prompt(parts=[
    TextPart(role="system", text="You are a pirate."),
    TextPart(role="user", text="What's in this image?"),
    AttachmentPart(role="user", attachment=llm.Attachment(path="map.jpg")),
])
```

Here are ideas to make it more ergonomic.

---

## 1. Role-based class constructors

Static methods or classmethods that pre-fill the role:

```python
from llm.parts import TextPart

response = model.prompt(parts=[
    TextPart.system("You are a pirate."),
    TextPart.user("What's in this image?"),
    TextPart.assistant("I see a treasure map!"),  # for injecting history
])
```

Implementation is trivial — one-liner classmethods:

```python
@classmethod
def user(cls, text): return cls(role="user", text=text)

@classmethod
def system(cls, text): return cls(role="system", text=text)

@classmethod
def assistant(cls, text): return cls(role="assistant", text=text)
```

Could also do this for `AttachmentPart`:

```python
AttachmentPart.user(llm.Attachment(path="map.jpg"))
```

**Pros:** Minimal API surface, obvious what it does, easy to implement.
**Cons:** Still requires importing specific Part classes.

---

## 2. Top-level shortcut functions

Functions at the `llm` package level that construct parts without importing classes:

```python
import llm

response = model.prompt(parts=[
    llm.system("You are a pirate."),
    llm.user("What's in this image?"),
    llm.user(llm.Attachment(path="map.jpg")),
    llm.assistant("I see a treasure map!"),
])
```

The functions detect the argument type — string becomes `TextPart`, `Attachment` becomes `AttachmentPart`:

```python
def user(*args):
    parts = []
    for arg in args:
        if isinstance(arg, str):
            parts.append(TextPart(role="user", text=arg))
        elif isinstance(arg, Attachment):
            parts.append(AttachmentPart(role="user", attachment=arg))
    return parts if len(parts) > 1 else parts[0]
```

Could also accept mixed content in a single call:

```python
llm.user("What's in this image?", llm.Attachment(path="map.jpg"))
# Returns [TextPart(role="user", ...), AttachmentPart(role="user", ...)]
```

**Pros:** Very concise, feels natural, no extra imports.
**Cons:** Magic type detection. Returning list-or-single is awkward — maybe always return a list and have `parts=` accept nested lists that get flattened.

---

## 3. Chainable builder API

A builder that constructs the parts list fluently:

```python
import llm

response = model.prompt(
    parts=llm.Parts()
        .system("You are a pirate.")
        .user("What's in this image?")
        .user(llm.Attachment(path="map.jpg"))
        .assistant("I see a treasure map!")
)
```

Or using `__or__` for a pipe-style syntax:

```python
parts = llm.system("You are a pirate.") | llm.user("Describe this") | llm.user(att)
response = model.prompt(parts=parts)
```

The builder accumulates parts internally:

```python
class Parts:
    def __init__(self):
        self._parts = []

    def system(self, text):
        self._parts.append(TextPart(role="system", text=text))
        return self

    def user(self, content):
        if isinstance(content, str):
            self._parts.append(TextPart(role="user", text=content))
        elif isinstance(content, Attachment):
            self._parts.append(AttachmentPart(role="user", attachment=content))
        return self

    def assistant(self, text):
        self._parts.append(TextPart(role="assistant", text=text))
        return self

    def __iter__(self):
        return iter(self._parts)
```

`model.prompt(parts=)` would accept anything iterable.

**Pros:** Reads well, method chaining is familiar from ORMs/query builders.
**Cons:** Another class to learn. Chaining style can be hard to debug.

---

## 4. Conversation-style list of tuples

Accept `(role, content)` tuples as a shorthand:

```python
response = model.prompt(parts=[
    ("system", "You are a pirate."),
    ("user", "What's in this image?"),
    ("user", llm.Attachment(path="map.jpg")),
    ("assistant", "I see a treasure map!"),
])
```

The `Prompt` class would convert tuples to Part objects internally. This is similar to how OpenAI's `messages=` parameter works and will feel familiar to many developers.

**Pros:** Zero imports needed, very lightweight, familiar pattern.
**Cons:** No type checking, easy to typo role strings, doesn't extend to complex parts (tool calls).

---

## 5. Dict shorthand (messages-style)

Accept OpenAI-style message dicts directly:

```python
response = model.prompt(parts=[
    {"role": "system", "content": "You are a pirate."},
    {"role": "user", "content": "What's in this image?"},
    {"role": "assistant", "content": "I see a treasure map!"},
])
```

This would use `Part.from_dict()` (or a variant) to convert. Very familiar to anyone coming from the OpenAI SDK.

**Pros:** Zero imports, matches the mental model people already have from raw API usage.
**Cons:** Loses type safety, blurs the distinction between LLM's Part model and provider-specific message formats. Could be confused with the actual API message format which differs per provider.

---

## 6. Hybrid: accept Part objects, tuples, or dicts

Make `parts=` accept any mix of Part objects, `(role, content)` tuples, and `{"role": ..., "content": ...}` dicts:

```python
response = model.prompt(parts=[
    ("system", "You are a pirate."),                       # tuple
    llm.TextPart(role="user", text="Describe this"),       # Part object
    {"role": "assistant", "content": "A treasure map!"},   # dict
])
```

A normalizer function converts everything to Part objects before processing. This gives power users full control while keeping simple cases terse.

**Pros:** Maximum flexibility, each user picks their preferred style.
**Cons:** Too many ways to do the same thing. Documentation becomes complex. "There should be one obvious way to do it."

---

## 7. The `messages=` alias

Since `parts=` is really about constructing the messages list, an alias might be clearer:

```python
response = model.prompt(messages=[
    ("system", "You are a pirate."),
    ("user", "Hello!"),
])
```

`messages=` is what people expect from other SDKs. It could be a direct alias for `parts=`, or `parts=` could be the internal name with `messages=` as the public sugar.

**Pros:** Instantly familiar to anyone who's used the OpenAI SDK.
**Cons:** "Messages" suggests chat-style exchanges specifically, while "parts" is meant to be broader (reasoning, tool calls, attachments). Could create false expectations about format compatibility with raw API messages.

---

## Recommendation

Start with **option 1** (role-based classmethods) — it's the smallest change, fully backward compatible, and makes the common case meaningfully better:

```python
response = model.prompt(parts=[
    TextPart.system("You are a pirate."),
    TextPart.user("What's in this image?"),
])
```

Then consider adding **option 2** (top-level shortcuts) as a second layer if the pattern proves popular:

```python
response = model.prompt(parts=[
    llm.system("You are a pirate."),
    llm.user("What's in this image?"),
])
```

Avoid options 5-7 initially — they pull toward mimicking the OpenAI messages format, which is a different abstraction level. LLM's parts are meant to be provider-agnostic and richer than raw messages.
