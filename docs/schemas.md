(schemas)=

# Schemas

Large Language Models are very good at producing structured output as JSON or other formats. LLM's **schemas** feature allows you to define the exact structure of JSON data you want to receive from a model.

This feature is supported by models from OpenAI, Anthropic, Google Gemini and can be implemented for others {ref}`via plugins <advanced-model-plugins-schemas>`.

(schemas-json-schemas)=

## Understanding JSON schemas

A [JSON schema](https://json-schema.org/) is a specification that describes the expected structure of a JSON object. It defines:

- The data types of fields (string, number, array, object, etc.)
- Required vs. optional fields
- Nested data structures
- Constraints on values (minimum/maximum, patterns, etc.)
- Descriptions of those fields - these can be used to guide the language model

Different models may support different subsets of the overall JSON schema language. You should experiment to figure out what works for the model you are using.

(schemas-using-with-llm)=

## Using schemas with LLM

LLM provides several ways to use schemas:

1. Directly via the command line with the `--schema` option
2. Through stored schemas in the database
3. Via templates that include schemas
4. Through the {ref}`Python API <python-api-schemas>`

(schemas-using-cli)=

### Basic usage with the command line

To get structured data from a language model you can provide a JSON schema directly using the `--schema` option:

```bash
curl https://www.nytimes.com/ | uvx strip-tags | \
  llm --schema '{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "headline": {
            "type": "string"
          },
          "short_summary": {
            "type": "string"
          },
          "key_points": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "required": ["headline", "short_summary", "key_points"]
      }
    }
  },
  "required": ["items"]
}' | jq
```
This example uses [uvx](https://docs.astral.sh/uv/guides/tools/) to run [strip-tags](https://github.com/simonw/strip-tags) against the front page of the New York Times, runs GPT-4o mini with a schema to extract story headlines and summaries, then pipes the result through [jq](https://jqlang.org/) to format it.

This will instruct the model to return an array of JSON objects with the specified structure, each containing a headline, summary, and array of key people mentioned.

For a list of available models that support schemas, run this command:
```bash
llm models --schemas
```

(schemas-dsl)=

## Alternative schema syntax

JSON schema's can be time-consuming to construct by hand. LLM also supports a concise alternative syntax for specifying a schema.

The New York Times example above can be condensed to this, though note that key points is now a string rather than an array of strings:

```bash
curl https://www.nytimes.com/ | uvx strip-tags | \
  llm --schema-multi 'headline, short_summary, key_points' | jq
```

### How that syntax works

A simple schema for an object with two string properties called `name` and `bio` looks like this:

    name, bio

You can include type information by adding a type indicator after the property name, separated by a space.

    name, bio, age int

Supported types are `int` for integers, `float` for floating point numbers, `str` for strings (the default) and `bool` for true/false booleans.

To include a description of the field to act as a hint to the model, add one after a colon:

    name: the person's name, age int: their age, bio: a short bio

If your schema is getting long you can switch from comma-separated to newline-separated, which also allows you to use commas in those descriptions:

    name: the person's name
    age int: their age
    bio: a short bio, no more than three sentences

### Using alternative schema syntax

This format is supported by the `--schema` option. The format will be detected any time you provide a string with at least one space that doesn't start with a `{` (indicating JSON):

```bash
llm --schema 'name,description,fave_toy' 'invent a dog'
```
To return multiple items matching your schema, use the `--schema-multi` option. This is equivalent to using `--schema` with a JSON schema that specifies an `items` key containing multiple objects.

```bash
llm --schema-multi 'name,description,fave_toy' 'invent 3 dogs'
```
The Python utility function `llm.schema_dsl(schema)` can be used to convert this syntax into the equivalent JSON schema dictionary when working with schemas {ref}`in the Python API <python-api-schemas>`.

You can experiment with the syntax using the `llm schemas dsl` command, which converts the input into a JSON schema:
```bash
llm schemas dsl 'name, age int'
```
Output:
```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    },
    "age": {
      "type": "integer"
    }
  },
  "required": [
    "name",
    "age"
  ]
}
```

(schemas-logs)=

## Browsing logged JSON objects created using schemas

By default, all JSON produced using schemas is logged to {ref}`a SQLite database <logging>`. You can use special options to the `llm logs` command to extract just those JSON objects in a useful format.

The `llm logs --schema X` filter option can be used to filter just for responses that were created using the specified schema. You can pass the full schema JSON, a path to the schema on disk or the schema ID.

The `--data` option causes just the JSON data collected by that schema to be outputted, as newline-delimited JSON.

If you instead want a JSON array of objects (with starting and ending square braces) you can use `--data-array` instead.

Let's invent some dogs:

```bash
llm --schema-multi 'name, ten_word_bio' 'invent 3 cool dogs'
llm --schema-multi 'name, ten_word_bio' 'invent 2 cool dogs'
```
Having logged these cool dogs, you can see just the data that was returned by those prompts like this:
```bash
llm logs --schema-multi 'name, ten_word_bio' --data
```
We need to use `--schema-multi` here because we used that when we first created these records. The `--schema` option is also supported, and can be passed a filename or JSON schema or schema ID as well.

Output:
```
{"items": [{"name": "Robo", "ten_word_bio": "A cybernetic dog with laser eyes and super intelligence."}, {"name": "Flamepaw", "ten_word_bio": "Fire-resistant dog with a talent for agility and tricks."}]}
{"items": [{"name": "Bolt", "ten_word_bio": "Lightning-fast border collie, loves frisbee and outdoor adventures."}, {"name": "Luna", "ten_word_bio": "Mystical husky with mesmerizing blue eyes, enjoys snow and play."}, {"name": "Ziggy", "ten_word_bio": "Quirky pug who loves belly rubs and quirky outfits."}]}
```
Note that the dogs are nested in that `"items"` key. To access the list of items from that key use `--data-key items`:
```bash
llm logs --schema-multi 'name, ten_word_bio' --data-key items
```
Output:
```
{"name": "Bolt", "ten_word_bio": "Lightning-fast border collie, loves frisbee and outdoor adventures."}
{"name": "Luna", "ten_word_bio": "Mystical husky with mesmerizing blue eyes, enjoys snow and play."}
{"name": "Ziggy", "ten_word_bio": "Quirky pug who loves belly rubs and quirky outfits."}
{"name": "Robo", "ten_word_bio": "A cybernetic dog with laser eyes and super intelligence."}
{"name": "Flamepaw", "ten_word_bio": "Fire-resistant dog with a talent for agility and tricks."}
```
Finally, to output a JSON array instead of newline-delimited JSON use `--data-array`:
```bash
llm logs --schema-multi 'name, ten_word_bio' --data-key items --data-array
```
Output:
```json
[{"name": "Bolt", "ten_word_bio": "Lightning-fast border collie, loves frisbee and outdoor adventures."},
 {"name": "Luna", "ten_word_bio": "Mystical husky with mesmerizing blue eyes, enjoys snow and play."},
 {"name": "Ziggy", "ten_word_bio": "Quirky pug who loves belly rubs and quirky outfits."},
 {"name": "Robo", "ten_word_bio": "A cybernetic dog with laser eyes and super intelligence."},
 {"name": "Flamepaw", "ten_word_bio": "Fire-resistant dog with a talent for agility and tricks."}]
```