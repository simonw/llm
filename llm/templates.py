import string
from typing import Any

from pydantic import BaseModel, ConfigDict


class AttachmentType(BaseModel):
    type: str
    value: str


class Template(BaseModel):
    """A reusable prompt template."""

    name: str
    prompt: str | None = None
    system: str | None = None
    attachments: list[str] | None = None
    attachment_types: list[AttachmentType] | None = None
    model: str | None = None
    defaults: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    extract: bool | None = None  # For extracting fenced code blocks
    extract_last: bool | None = None
    schema_object: dict | None = None
    fragments: list[str] | None = None
    system_fragments: list[str] | None = None
    tools: list[str] | None = None
    functions: str | None = None

    model_config = ConfigDict(extra="forbid")

    class MissingVariables(Exception):
        pass

    def __init__(self, **data):
        super().__init__(**data)
        # Not a pydantic field to avoid YAML being able to set it
        # this controls if Python inline functions code is trusted
        self._functions_is_trusted = False

    def evaluate(
        self, input: str, params: dict[str, Any] | None = None
    ) -> tuple[str | None, str | None]:
        """Evaluate the template with the given input and parameters, returning (prompt, system)."""
        params = params or {}
        params["input"] = input
        if self.defaults:
            for k, v in self.defaults.items():
                if k not in params:
                    params[k] = v
        prompt: str | None = None
        system: str | None = None
        if not self.prompt:
            system = self.interpolate(self.system, params)
            prompt = input
        else:
            prompt = self.interpolate(self.prompt, params)
            system = self.interpolate(self.system, params)
        return prompt, system

    def vars(self) -> set:
        """Return the set of variable names used in the prompt and system templates."""
        all_vars = set()
        for text in [self.prompt, self.system]:
            if not text:
                continue
            all_vars.update(self.extract_vars(string.Template(text)))
        return all_vars

    @classmethod
    def interpolate(cls, text: str | None, params: dict[str, Any]) -> str | None:
        """Substitute template variables in text with values from params, raising MissingVariables if any are absent."""
        if not text:
            return text
        # Confirm all variables in text are provided
        string_template = string.Template(text)
        vars = cls.extract_vars(string_template)
        missing = [p for p in vars if p not in params]
        if missing:
            raise cls.MissingVariables(
                "Missing variables: {}".format(", ".join(missing))
            )
        return string_template.substitute(**params)

    @staticmethod
    def extract_vars(string_template: string.Template) -> list[str]:
        """Extract and return the list of named variable identifiers from a string.Template."""
        return [
            match.group("named")
            for match in string_template.pattern.finditer(string_template.template)
            if match.group("named")
        ]
