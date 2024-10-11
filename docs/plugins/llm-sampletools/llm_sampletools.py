import random
import sys
from typing import Annotated
import enum
import datetime

import pydantic
import llm


@llm.hookimpl
def register_tools(register):
    # Annotated function, will be introspected
    register(llm.Tool(random_number))
    register(llm.Tool(best_restaurant_in))

    # Generate parameter schema from pydantic model
    register(llm.Tool(current_temperature, WeatherInfo.model_json_schema()))

    # No parameters, no parameter schema needed - no doc comment so provide description
    register(
        llm.Tool(best_restaurant, description="Find the best restaurant in the world.")
    )

    # Manually specify parameter schema
    register(
        llm.Tool(
            current_time,
            {
                "type": "object",
                "properties": {
                    "time_format": {
                        "description": "The format to use for the returned datetime, either ISO 8601 or unix ctime format.",
                        "type": "string",
                        "enum": ["iso", "ctime"],
                    },
                },
                "required": ["time_format"],
                "additionalProperties": False,
            },
        )
    )


##########


def random_number(
    minimum: Annotated[int, "The minimum value of the random number, default is 0"] = 0,
    maximum: Annotated[
        int, f"The maximum value of the random number, default is {sys.maxsize}."
    ] = sys.maxsize,
) -> str:
    """Generate a random number."""
    return str(random.randrange(minimum, maximum))  # noqa: S311


##########


def best_restaurant():
    return "WorldsBestRestaurant"


##########


def best_restaurant_in(
    location: Annotated[str, "The city the restaurant is located in."]
) -> str:
    """Find the best restaurant in the given location."""
    return "CitiesBestRestaurant"


##########


class Degrees(enum.Enum):
    CELSIUS = "celsius"
    FAHRENHEIT = "fahrenheit"


class WeatherInfo(pydantic.BaseModel):
    location: str = pydantic.Field(
        description="The location to return the current temperature for."
    )
    degrees: Degrees = pydantic.Field(
        description="The degree scale to return temperature in."
    )


def current_temperature(**weather_info) -> str:
    """Return the current temperature in the provided location."""
    info = WeatherInfo(**weather_info)
    return f"The current temperature in {info.location} is 42° {info.degrees.value}."


##########


def current_time(time_format):
    """Return the current date and time in UTC using the specified format."""
    time = datetime.datetime.now(datetime.timezone.utc)
    if time_format == "iso":
        return time.isoformat()
    elif time_format == "ctime":
        return time.ctime()
    raise ValueError(f"Unsupported time format: {time_format}")
