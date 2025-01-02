from pydantic import BaseModel
import string
from typing import Optional, Any, Dict, List, Tuple, Type, Literal
from .plugins import pm


class Template(BaseModel):
    name: str
    type: Optional[str] = None
    prompt: Optional[str] = None
    system: Optional[str] = None
    model: Optional[str] = None
    defaults: Optional[Dict[str, Any]] = None
    # Should first fenced code block be extracted?
    extract: Optional[bool] = None

    class Config:
        extra = "allow"

    class MissingVariables(Exception):
        pass

    @classmethod
    def get_template_class(cls, type: Optional[str]) -> Type["Template"]:
        """Get the template class for a given type."""
        if not type:
            return cls
        
        # Get registered template types from plugins
        template_types = {}
        for hook_result in pm.hook.register_template_types():
            if hook_result:
                template_types.update(hook_result)
        
        if type not in template_types:
            raise ValueError(f"Unknown template type: {type}")
        
        return template_types[type]

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
