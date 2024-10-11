import enum
import inspect
import json
from typing import Any, Annotated, Union, Optional, get_origin, get_args
from collections.abc import Callable
import click
import llm


# __origin__ could be types.UnionType instance (for optional parameters that have a None default) or a class
TYPEMAP = {
    int: "integer",
    Union[int, None]: "integer",
    float: "number",
    Union[float, None]: "number",
    list: "array",
    Union[list, None]: "array",
    bool: "boolean",
    Union[bool, None]: "boolean",
    str: "string",
    Union[str, None]: "string",
    type(None): "null",  # types.NoneType is Python 3.10+
}


def convert_parameter(param: inspect.Parameter) -> dict[str, Any]:
    """Convert a function parameter to a JSON schema parameter."""
    annotation = param.annotation
    # This will return Annotated, or None for inspect.Parameter.empty or other types
    unsubscriped_type = get_origin(annotation)
    if not (
        unsubscriped_type is Annotated
        and len(annotation.__metadata__) == 1
        and isinstance(annotation.__metadata__[0], str)
    ):
        raise ValueError(
            "Function parameters must be annotated with typing.Annotated[<type>, 'description']"
        )

    schema: dict[str, Any] = {
        "description": annotation.__metadata__[0],
    }

    origin = annotation.__origin__
    type_ = TYPEMAP.get(get_origin(origin)) or TYPEMAP.get(origin)
    if type_:
        schema["type"] = type_
        if type_ == "array":
            args = get_args(origin)
            if args:
                if len(args) == 1 and (arg := TYPEMAP.get(args[0])):
                    schema["items"] = {"type": arg}
                else:
                    raise TypeError(f"Annotated parameter type {origin} not supported")
    elif issubclass(origin, enum.Enum):
        # str values only for now, e.g. enum.StrEnum
        schema["type"] = "string"
        schema["enum"] = [m.value for m in origin if isinstance(m.value, str)]
    else:
        raise TypeError(f"Annotated parameter type {origin} not supported")

    return schema


def format_exception(e: Exception) -> str:
    return json.dumps({"is_error": True, "exception": repr(e)})


def format_error(message: str) -> str:
    return json.dumps({"is_error": True, "error": message})


class Tool:
    name: str
    schema: dict[str, Any]
    function: Callable[..., str]

    def __init__(
        self,
        function: Callable[..., str],
        parameters_schema: Optional[dict[str, Any]] = None,
        description: Optional[str] = None,
        name: Optional[str] = None,
    ):
        self.function = function
        self.name = name or function.__name__
        self.description = description or function.__doc__
        if not self.description:
            raise ValueError(
                "Tool functions must have a docstring or provide a description"
            )
        self.schema = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
            },
        }
        signature = inspect.signature(self.function)
        if (
            signature.return_annotation is not inspect.Parameter.empty
            and signature.return_annotation is not str
        ):
            raise ValueError("Tool functions must return a string")
        if not parameters_schema and signature.parameters:
            parameters_schema = self.introspect_function(signature)
        if parameters_schema:
            self.schema["function"]["parameters"] = parameters_schema

    def __call__(self, json_parameters: str) -> str:
        try:
            args = json.loads(json_parameters)
            params = ", ".join(f"{k}={v}" for k, v in args.items())
            click.secho(
                f"Tool: {self.name}({params})",
                err=True,
                italic=True,
                dim=True,
            )
            return self.function(**args)
        except llm.ModelError:
            raise
        except Exception as e:
            return format_exception(e)

    def introspect_function(self, signature: inspect.Signature) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                name: convert_parameter(param)
                for name, param in signature.parameters.items()
            },
            "required": [
                name
                for name, param in signature.parameters.items()
                if param.default is inspect.Parameter.empty
            ],
            "additionalProperties": False,
        }
