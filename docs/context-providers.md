(context-providers)=
# Context providers

LLM conversations can be augmented with additional context that is stored and
retrieved by **context providers**. A provider returns a `Context` object which
contains a list of `ContextItem` objects along with `ContextMetadata` about how
that context was generated.

`ContextItem` represents a single message in the context. It includes the text
`content`, a `role` such as `user` or `assistant`, a `timestamp` and optional
`relevance` score and extra `metadata`.

A `Context` object bundles these items together and records information about the
provider via `ContextMetadata`.

Plugins can implement new providers by subclassing `ContextProvider` and
implementing three methods:

* `initialize_context(conversation_id)` – return a fresh `Context` for a
  conversation.
* `update_context(conversation_id, response, previous_context=None)` – update
  stored context after a `Response` is produced.
* `get_context(conversation_id)` – retrieve the current context for that
  conversation.

Providers may also implement `format_for_prompt()` to return a string that should
be appended to the prompt, and `search_context()` to find relevant items.

## EmbeddingsContextProvider

LLM includes a built‑in `EmbeddingsContextProvider`. It stores the text of each
response in an {ref}`embeddings collection <embeddings-storage>` and can
retrieve relevant previous items using similarity search.

Plugins can register additional providers using the
`register_context_providers` plugin hook (see
{ref}`plugin-hooks-register-context-providers`).

## FragmentsContextProvider

LLM also includes a built‑in `FragmentsContextProvider`. It searches stored
prompt fragments (see {ref}`fragments`) using embeddings to find the most
relevant fragments and returns them as context items.

Plugins can register additional providers using the
`register_context_providers` plugin hook (see
{ref}`plugin-hooks-register-context-providers`).

## CLI usage

Run `llm context list` to see the names of all installed context providers.