from pydantic import BaseModel
import string
from typing import Optional, Any, Dict, List, Tuple
import platform


class Template(BaseModel):
    name: str
    prompt: Optional[str] = None
    system: Optional[str] = None
    model: Optional[str] = None
    defaults: Optional[Dict[str, Any]] = None
    # Should a fenced code block be extracted?
    extract: Optional[bool] = None
    extract_last: Optional[bool] = None

    class Config:
        extra = "forbid"

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

    @classmethod
    def interpolate(cls, text: Optional[str], params: Dict[str, Any]) -> Optional[str]:
        if not text:
            return text
        # Confirm all variables in text are provided
        string_template = string.Template(text)
        vars = cls.extract_identifiers(string_template)
        missing = [p for p in vars if p not in params]
        if missing:
            raise cls.MissingVariables(
                "Missing variables: {}".format(", ".join(missing))
            )
        return string_template.substitute(**params)

    @classmethod
    def extract_identifiers(cls, template: string.Template) -> List[str]:
        (major, minor, patchlevel) = platform.python_version_tuple()
        if int(major) >= 3 and int(minor) >= 11:
            result = template.get_identifiers() # type: ignore
            result.sort()
            # Added in Python 3.11
            return result
        else:
            result = set()
            # Adapted from source at https://github.com/python/cpython/blob/86e5e063aba76a7f4fc58f7d06b17b0a4730fd8e/Lib/string.py#L157
            for match in template.pattern.finditer(template.template):
                named = match.group("named") or match.group("braced")
                if named is not None:
                    result.add(named)
            result = list(result)
            result.sort()
            return result
