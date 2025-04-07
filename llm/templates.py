from pydantic import BaseModel, ConfigDict
import string
from typing import Optional, Any, Dict, List, Tuple


class AttachmentType(BaseModel):
    type: str
    value: str


class Template(BaseModel):
    name: str
    prompt: Optional[str] = None
    system: Optional[str] = None
    attachments: Optional[List[str]] = None
    attachment_types: Optional[List[AttachmentType]] = None
    model: Optional[str] = None
    defaults: Optional[Dict[str, Any]] = None
    options: Optional[Dict[str, Any]] = None
    extract: Optional[bool] = None  # For extracting fenced code blocks
    extract_last: Optional[bool] = None
    schema_object: Optional[dict] = None
    fragments: Optional[List[str]] = None
    system_fragments: Optional[List[str]] = None

    model_config = ConfigDict(extra="forbid")

    class MissingVariables(Exception):
        pass

    def evaluate(
        self, input: str, params: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        params = params or {}
        params["input"] = input
        if self.defaults:
            for k, v in self.defaults.items():
                if k not in params:
                    params[k] = v
        prompt: Optional[str] = None
        system: Optional[str] = None
        if not self.prompt:
            system = self.interpolate(self.system, params)
            prompt = input
        else:
            prompt = self.interpolate(self.prompt, params)
            system = self.interpolate(self.system, params)
        return prompt, system

    def vars(self) -> set:
        all_vars = set()
        for text in [self.prompt, self.system]:
            if not text:
                continue
            all_vars.update(self.extract_vars(string.Template(text)))
        return all_vars

    @classmethod
    def interpolate(cls, text: Optional[str], params: Dict[str, Any]) -> Optional[str]:
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
    def extract_vars(string_template: string.Template) -> List[str]:
        return [
            match.group("named")
            for match in string_template.pattern.finditer(string_template.template)
        ]
