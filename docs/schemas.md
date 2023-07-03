# Schemas

LLM schemas allow for the definition of custom schemas, which may be useful for parsing unstructured data into a useful format. Schemas use a combination of Pydantic and OpenAISchema to define field types and descriptions, which ultimately will be used by the OpenAI functions to parse data into a structured format. By default, the output of the `schema` command is in JSON format.

## Defining schemas

Schemas must be defined in the `schemas.py` file as valid Pydantic model classes. A sample schema file is provided, and on the first run will be saved under the schemas folder in the same `user_dir` as other `llm` files.

Further, the schema file path can be viewed by using `llm schemas path`.

As an example, the following schema may be used to extract data from a [CFTC press release](https://www.cftc.gov/PressRoom/PressReleases/8726-23):

```python
class CFTCEnforcementDetails(OpenAISchema):
    """Extract information regarding CFTC enforcement action(s)"""
    date:               str = Field(..., description="Date of the action")
    regulator:          str = Field(..., description="Name of the regulator bringing the action")
    enforcement_type:   str = Field(..., description="Type of enforcement action: warning letter, civil fines, suspension/revocation of license, civil lawsuit, criminal lawsuit")
    impacted_entities:  List[str] = Field(..., description="Names of entities impacted by the enforcement action")
    related_case:       str = Field(..., description="Case number(s) of related actions")
    defendants:         List[str] = Field(..., description="Names of individuals or entities named as defendants")
    alleged_crimes:     List[str] = Field(..., description="Specific crimes alleged")
    penalty_amount:     int = Field( ..., description="Penalty amount, if any")
```

## Listing installed schemas

Run `llm schemas list` to list installed plugins:

```bash
llm schemas list
```

```text
Available schemas:
------------------

CFTCEnforcementDetails
LAPDEventDetails
```

By default, two example schemas are provided.

## Using schemas

Schemas are typically useful when working with unstructured text and are complemented by tools like `strip-tags` as noted [here](https://simonwillison.net/2023/May/18/cli-tools-for-llms/).

Once defined, simply specify the schema (based on what is available using `llm schemas list`) to use. 

For example:

```bash
curl -s "https://www.cftc.gov/PressRoom/PressReleases/8726-23" | strip-tags | llm schemas use CFTCEnforcementDetails 
```

This will output JSON as defined in the schema, such as:

```json
{
   "alleged_crimes" : [
      "fraud",
      "misappropriation"
   ],
   "date" : "June 22, 2023",
   "defendants" : [
      "Cunwen Zhu",
      "Justby International Auctions"
   ],
   "enforcement_type" : "civil enforcement action",
   "impacted_entities" : [
      "Cunwen Zhu",
      "Justby International Auctions"
   ],
   "penalty_amount" : 0,
   "regulator" : "Commodity Futures Trading Commission",
   "related_case" : "United States of America v. Cunwen Zhu, Case No. 3:23-cr-66-BDJMCR"
}
```

### Specifying which model to use

By default, the `gpt-3.5-turbo-0613` will be used. Otherwise, you may use the `-m` or `--model` flags to specify which model to use, exactly as you would when using `llm` with other prompts.