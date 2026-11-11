"""Scrub known secrets out of content before it reaches the log database.

The log database stores prompts, fragments, tool arguments and attachment
bytes verbatim. That is deliberate - full logging is the documented design -
but a secret that happens to appear in one of those places (a key pasted
into a prompt, a fragment file containing a token, a tool call whose
arguments carry a credential) should not be preserved forever in plaintext
just because it passed through.

This module implements the scrub used by ``llm.logs`` on everything it
writes, and by the ``llm logs`` / ``llm fragments`` commands on what they
print (which also protects databases written before this scrub existed):

- Values the user has actually configured as keys - every string in
  ``keys.json`` plus ``*_API_KEY`` / ``*_API_TOKEN`` environment variables -
  are replaced wherever they appear.
- Strings shaped like well-known secret formats (OpenAI-style ``sk-...``
  keys, GitHub tokens, AWS access key IDs, Slack tokens) are replaced even
  when they are not configured keys, because pasted third-party secrets
  deserve the same treatment.
- ``provider_metadata`` subtrees are exempt from the shape patterns. They
  carry opaque provider blobs (reasoning signatures, encrypted content)
  that must be echoed back to the provider byte-for-byte on the next
  request; known configured values are still scrubbed inside them.

Deliberate limits, so nobody mistakes this for a general secret scanner:
a secret split across two strings, base64-encoded by the user, or in a
format with no recognizable shape and no configured value is not caught.
Set the ``LLM_NO_LOG_REDACTION`` environment variable to a non-empty
value to disable scrubbing entirely.
"""

import json
import os
import re
from typing import Any

REDACTION = "***"

OPT_OUT_ENV_VAR = "LLM_NO_LOG_REDACTION"

# Configured values shorter than this are not scrubbed: very short strings
# (a model alias, a one-word key name) would redact ordinary prose.
_MIN_KNOWN_LENGTH = 8

_SECRET_PATTERN_SOURCES = (
    r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}",  # OpenAI-style API keys
    r"ghp_[A-Za-z0-9]{36}",  # GitHub personal access tokens (classic)
    r"gho_[A-Za-z0-9]{36}",  # GitHub OAuth access tokens
    r"github_pat_[A-Za-z0-9_]{20,}",  # GitHub fine-grained tokens
    r"AKIA[0-9A-Z]{16}",  # AWS access key IDs
    r"xox[baprs]-[A-Za-z0-9-]{10,}",  # Slack tokens
)
_SECRET_PATTERNS = [re.compile(pattern) for pattern in _SECRET_PATTERN_SOURCES]
_SECRET_PATTERNS_BYTES = [
    re.compile(pattern.encode("ascii")) for pattern in _SECRET_PATTERN_SOURCES
]


def redaction_disabled() -> bool:
    "True when the user has opted out of log redaction."
    return bool(os.environ.get(OPT_OUT_ENV_VAR))


def known_secret_values() -> list[str]:
    """Every string the user has configured as an API key.

    Sources: all string values in ``keys.json`` (nested values included)
    and environment variables ending in ``_API_KEY`` or ``_API_TOKEN``.
    Sorted longest first so a value that contains another value is
    replaced whole rather than in pieces.
    """
    values: set[str] = set()

    def collect(obj: Any) -> None:
        if isinstance(obj, str):
            values.add(obj)
        elif isinstance(obj, dict):
            for value in obj.values():
                collect(value)
        elif isinstance(obj, (list, tuple)):
            for value in obj:
                collect(value)

    try:
        # Imported here: llm/__init__ imports most of the package.
        from llm import load_keys

        collect(load_keys())
    except Exception:
        pass
    for name, value in os.environ.items():
        if name.endswith("_API_KEY") or name.endswith("_API_TOKEN"):
            values.add(value)
    return sorted(
        (value for value in values if len(value) >= _MIN_KNOWN_LENGTH),
        key=len,
        reverse=True,
    )


class SecretScrubber:
    "Replaces known secret values and secret-shaped strings with ``***``."

    def __init__(self, known_values: list[str] | None = None):
        if known_values is None:
            known_values = known_secret_values()
        self.known_values = sorted(known_values, key=len, reverse=True)
        # A configured value can appear inside JSON output in its escaped
        # form, so scrub that form too.
        variants: list[str] = []
        for value in self.known_values:
            variants.append(value)
            escaped = json.dumps(value)[1:-1]
            if escaped != value:
                variants.append(escaped)
        self._variants = variants
        self._variants_bytes = [v.encode("utf-8") for v in self._variants]

    def scrub_text(self, text: str, *, known_only: bool = False) -> str:
        if not isinstance(text, str) or not text:
            return text
        for variant in self._variants:
            if variant in text:
                text = text.replace(variant, REDACTION)
        if not known_only:
            for pattern in _SECRET_PATTERNS:
                text = pattern.sub(REDACTION, text)
        return text

    def scrub_metadata(self, obj: Any) -> Any:
        "Scrub a provider_metadata value: known values only, never shapes."
        return self._scrub_obj(obj, in_metadata=True)

    def scrub_obj(self, obj: Any) -> Any:
        """Deep-scrub a JSON-shaped structure.

        Strings are scrubbed in full, except anything nested under a
        ``provider_metadata`` key, where only known configured values are
        replaced (see the module docstring for why).
        """
        return self._scrub_obj(obj, in_metadata=False)

    def _scrub_obj(self, obj: Any, *, in_metadata: bool) -> Any:
        if isinstance(obj, str):
            return self.scrub_text(obj, known_only=in_metadata)
        if isinstance(obj, dict):
            out = {}
            for key, value in obj.items():
                new_key = (
                    self.scrub_text(key, known_only=in_metadata)
                    if isinstance(key, str)
                    else key
                )
                out[new_key] = self._scrub_obj(
                    value,
                    in_metadata=in_metadata or key == "provider_metadata",
                )
            return out
        if isinstance(obj, (list, tuple)):
            return [self._scrub_obj(value, in_metadata=in_metadata) for value in obj]
        return obj

    def scrub_bytes(self, data: bytes) -> bytes:
        "Scrub attachment bytes: decoded as text when possible, raw otherwise."
        if not data:
            return data
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            scrubbed = data
            for variant in self._variants_bytes:
                scrubbed = scrubbed.replace(variant, REDACTION.encode("ascii"))
            for pattern in _SECRET_PATTERNS_BYTES:
                scrubbed = pattern.sub(REDACTION.encode("ascii"), scrubbed)
            return scrubbed
        return self.scrub_text(text).encode("utf-8")


def default_scrubber() -> SecretScrubber | None:
    "A scrubber built from the current configuration, or None if opted out."
    if redaction_disabled():
        return None
    return SecretScrubber()


def scrub_message(message, scrubber: SecretScrubber):
    """Return a copy of a ``Message`` with every part scrubbed.

    Attachments are scrubbed as bytes, never as the base64 text their
    dict form carries, so an encoded blob can neither hide a secret from
    the scrubber nor be corrupted by it. Unknown part types are passed
    through untouched: the logger must never fail on a part it does not
    recognize.
    """
    from .models import Attachment
    from .parts import (
        AttachmentPart,
        Message,
        ReasoningPart,
        TextPart,
        ToolCallPart,
        ToolResultPart,
    )

    def scrub_attachment(attachment):
        if attachment is None or attachment.content is None:
            return attachment
        new_content = scrubber.scrub_bytes(attachment.content)
        if new_content == attachment.content:
            return attachment
        return Attachment(
            type=attachment.type,
            path=attachment.path,
            url=attachment.url,
            content=new_content,
        )

    def scrub_part(part):
        metadata = (
            scrubber.scrub_metadata(part.provider_metadata)
            if part.provider_metadata
            else None
        )
        if isinstance(part, TextPart):
            return TextPart(text=scrubber.scrub_text(part.text), provider_metadata=metadata)
        if isinstance(part, ReasoningPart):
            return ReasoningPart(
                text=scrubber.scrub_text(part.text),
                redacted=part.redacted,
                provider_metadata=metadata,
            )
        if isinstance(part, ToolCallPart):
            return ToolCallPart(
                name=part.name,
                arguments=scrubber.scrub_obj(part.arguments),
                tool_call_id=part.tool_call_id,
                server_executed=part.server_executed,
                provider_metadata=metadata,
            )
        if isinstance(part, ToolResultPart):
            return ToolResultPart(
                name=part.name,
                output=scrubber.scrub_text(part.output),
                tool_call_id=part.tool_call_id,
                server_executed=part.server_executed,
                attachments=[scrub_attachment(a) for a in part.attachments],
                exception=(
                    scrubber.scrub_text(part.exception) if part.exception else None
                ),
                provider_metadata=metadata,
            )
        if isinstance(part, AttachmentPart):
            return AttachmentPart(
                attachment=scrub_attachment(part.attachment),
                provider_metadata=metadata,
            )
        return part

    return Message(
        role=message.role,
        parts=[scrub_part(part) for part in message.parts],
        provider_metadata=(
            scrubber.scrub_metadata(message.provider_metadata)
            if message.provider_metadata
            else None
        ),
    )


def scrub_fragment(fragment, scrubber: SecretScrubber):
    "Scrub a fragment's text, preserving its source attribution if it has one."
    from .utils import Fragment

    scrubbed = scrubber.scrub_text(str(fragment))
    if isinstance(fragment, Fragment):
        return Fragment(scrubbed, fragment.source)
    return scrubbed
