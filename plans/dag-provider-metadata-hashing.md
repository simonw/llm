# `provider_metadata` and the message content hash

Status: design note. Companion to `plans/dag-schema.md`.

## Context

The DAG schema in `plans/dag-schema.md` identifies each message by a
`content_hash` over a canonical serialization of the `Message`. That
canonicalization currently includes `provider_metadata` in full. This
note captures why that choice is uncomfortable, and the incremental
path we plan to take.

## What `provider_metadata` holds

Three concrete cases:

- **Anthropic extended thinking** — reasoning blocks come back with a
  `signature` field, an HMAC the server uses to verify the block is
  unmodified. Continuation requests must echo signed blocks verbatim
  or the API rejects the turn.
- **OpenAI Responses API** — reasoning items carry `encrypted_content`
  in stateless mode. Same pattern: opaque blob, echo or reject.
- **Gemini** — `thoughtSignature` on thought parts, same pattern.

These blobs share three properties:

1. **Non-deterministic per generation.** Regenerate the same assistant
   turn twice, get two different signatures. Neither is wrong.
2. **Provider-scoped.** A signature minted by Anthropic is meaningless
   to OpenAI.
3. **Required for replay.** They can't be reconstructed; losing one
   means that branch can no longer be continued on that provider.

## The argument for hashing them

The hash identifies "a message you could replay." Two messages with
the same visible text but different signatures produce different API
requests on continuation — one accepted, one rejected. They are
legitimately different identities. Including `provider_metadata` in
the hash is coherent and trivial to implement.

## The argument against

Four failure modes:

### 1. Silent dedup failure on the stateless-API case

The motivating story in `dag-schema.md`: client resends
`[sys, u1, a1, u2, a2, u3]`, server recognizes the prefix and writes
only `u3` plus the new assistant turn.

That works *only if* the client echoes `a1` and `a2` with byte-identical
`provider_metadata`. If any middleware — a proxy, a client SDK that
re-serializes, the OpenAI-compat translation layer itself — reorders
keys, drops an unknown field, or re-encodes base64 with different
padding, the hash diverges and the "dedup" writes a parallel chain.
Result: silent storage bloat and conversations that look forked when
they aren't. This is exactly the case the DAG was supposed to handle
well.

### 2. Transcript import never dedups

Export a conversation from machine A, import into machine B, continue
it. Every imported message carries A's signatures. When B later
generates its own version of the same turn, the two never collapse.
Probably acceptable, worth naming.

### 3. Cross-provider continuation corrupts identity

A conversation that starts on Anthropic and continues on OpenAI (the
schema doc says this "works") carries dead Anthropic signatures inside
messages the OpenAI call will never use. They're still in the hash,
so dedup against a pure-OpenAI version of the same turn fails. The
hash key is made of data only one provider understands.

### 4. Adapter drift silently breaks hashes

If a plugin update changes which fields land in `provider_metadata` —
adds a `cache_hit` flag, a response id, a timestamp — every message
written after the update mismatches every message written before.
Canonicalization tests catch encoding drift but not semantic drift.

## Alternatives considered

- **Option 1 — hash everything (current design).** Simplest. Accepts
  failure modes above as constraints documented for users.
- **Option 2 — two hashes.** Add a second `semantic_hash` that omits
  `provider_metadata`. `content_hash` stays the write-time dedup key;
  `semantic_hash` enables "is this the same turn, ignoring signatures?"
  queries for UI, cross-DB merge, analytics.
- **Option 3 — hash excludes `provider_metadata`; signatures stored
  alongside.** Clean identity, but wrong for replay: a dedup hit keeps
  the first signature seen and will replay it even when a newer one
  would be correct. Anthropic will reject.
- **Option 4 — sidecar continuation-token table.** Multiple
  `(message_id, provider, token)` rows per message. Correct model of
  what these blobs are, most code to write.
- **Option 5 — adapters declare identity fields.** Principled but
  pushes hash-stability responsibility into every plugin forever.

## Plan: Option 1 now, Option 2 later

Ship Option 1. Keep the door open to Option 2.

### Why this is safe

Option 2 only *adds* a hash; it doesn't redefine the existing one.
`content_hash` keeps its exact meaning as the write-time dedup key,
so no existing row needs reinterpretation and no existing query
breaks. The upgrade cost is:

- One new column `messages.semantic_hash TEXT`, nullable during
  backfill then NOT NULL.
- One index on it.
- A `semantic_message_json()` function alongside
  `canonical_message_json()` that omits `provider_metadata`.
- A backfill migration that walks `messages`, recomputes, updates.
  Pure function of existing columns; idempotent; no provider calls.

Estimated work: a day, whenever we decide we need it.

### What to do now to keep that day cheap

While implementing Option 1, factor canonicalization so "include
`provider_metadata`" is a parameter, not baked in:

```python
def canonical_message_json(
    msg: Message,
    *,
    include_provider_metadata: bool = True,
) -> bytes:
    ...

def message_content_hash(msg: Message) -> str:
    return hashlib.sha256(
        canonical_message_json(msg, include_provider_metadata=True)
    ).hexdigest()
```

Then Option 2 is "add a second call site with `False` and a new
column." No untangling required later.

### The trap to avoid

Don't let Option 1's canonicalization tests pin behavior that makes a
clean semantic hash hard to define. Specifically: if `_canonical_part`
ends up smuggling `provider_metadata`-ish data into the "parts" side
of the serialization (e.g. merging a provider field into a part's
dict for convenience), separating them later is annoying. Keep part
canonicalization and `provider_metadata` canonicalization as visibly
separate code paths from day one.

### Triggers to actually do Option 2

Any one of these is enough:

- We ship the OpenAI-compat endpoint and observe parallel-chain
  duplication caused by middleware re-serialization.
- We build a logs UI that wants to group regenerations of the same
  turn.
- We build cross-DB merge tooling and need a principled "same turn"
  join key.
- A user reports that transcript import creates silent duplicates.

Until one of those bites, Option 1 is the correct amount of design.
