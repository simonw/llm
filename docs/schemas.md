# Schemas

LLM schemas allow for the definition of custom schemas, which may be useful for parsing unstructured data into a useful format.

## Defining schemas

Plugins must be installed in the same virtual environment as LLM itself. You can use the `llm install` command (a thin wrapper around `pip install`) for this:


For example the following schema may be used to extract data from an LAPD press release (as seen [on Twitter](https://twitter.com/kcimc/status/1668789461780668416):

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

Schemas work best with unstructured text and with complementary tools like `strip-tags` as noted [here](https://simonwillison.net/2023/May/18/cli-tools-for-llms/).

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

## Creating new schemas

Identify the schema file by using `llm schemas path`. By default, it will be saved under the schemas folder in the same `user_dir` as other `llm` files.

Schemas use a combination of Pydantic and OpenAISchema to define a field type and description. This will be used by the ChatGPT functions capability to parse the incoming data into the pre-defined fields.