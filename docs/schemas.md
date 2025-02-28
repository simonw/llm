(schemas)=

# Schemas

Large Language Models are very good at producing structured output as JSON or other formats. LLM's **schemas** feature allows you to define the exact structure of JSON data you want to receive from a model.

This feature is supported by models from OpenAI, Anthropic, Google Gemini and can be implemented for others {ref}`via plugins <advanced-model-plugins-schemas>`.

This page describes schemas used via the `llm` command-line tool. Schemas can also be used from the {ref}`Python API <python-api-schemas>`.

(schemas-tutorial)=

## Schemas tutorial

In this tutorial we're going to use schemas to analyze some news stories.

But first, let's invent some dogs!

### Getting started with dogs

LLMs are great at creating test data. Let's define a simple schema for a dog, using LLM's {ref}`concise schema syntax <schemas-dsl>`. We'll pass that to LLm with `llm --schema` and prompt it to "invent a cool dog":
```bash
llm --schema 'name, age int, one_sentence_bio' 'invent a cool dog'
```
I got back Ziggy:
```json
{
  "name": "Ziggy",
  "age": 4,
  "one_sentence_bio": "Ziggy is a hyper-intelligent, bioluminescent dog who loves to perform tricks in the dark and guides his owner home using his glowing fur."
}
```
The response matched my schema, with `name` and `one_sentence_bio` string columns and an integer for `age`.

We're using the default LLM model here - `gpt-4o-mini`. Add `-m model` to use another model - for example use `-m o3-mini` to have O3 mini invent some dogs.

For a list of available models that support schemas, run this command:
```bash
llm models --schemas
```

Want several more dogs? You can pass in that same schema using `--schema-multi` and ask for several at once:
```bash
llm --schema-multi 'name, age int, one_sentence_bio' 'invent 3 really cool dogs'
```
Here's what I got:
```json
{
  "items": [
    {
      "name": "Echo",
      "age": 3,
      "one_sentence_bio": "Echo is a sleek, silvery-blue Siberian Husky with mesmerizing blue eyes and a talent for mimicking sounds, making him a natural entertainer."
    },
    {
      "name": "Nova",
      "age": 2,
      "one_sentence_bio": "Nova is a vibrant, spotted Dalmatian with an adventurous spirit and a knack for agility courses, always ready to leap into action."
    },
    {
      "name": "Pixel",
      "age": 4,
      "one_sentence_bio": "Pixel is a playful, tech-savvy Poodle with a rainbow-colored coat, known for her ability to interact with smart devices and her love for puzzle toys."
    }
  ]
}
```
So that's the basic idea: we can feed in a schema and LLM will pass it to the underlying model and (usually) get back JSON that conforms to that schema.

This stuff gets a _lot_ more useful when you start applying it to larger amounts of text, extracting structured details from unstructured content.

### Extracting people from a news articles

We are going to extract details of the people who are mentioned in different news stories, and then use those to compile a database.

Let's start by compiling a schema. For each person mentioned we want to extract the following details:

- Their name
- The organization they work for
- Their role
- What we learned about them from the story

We will also record the article headline and the publication date, to make things easier for us later on.

Using LLM's custom, concise schema language, this time with newlines separating the individual fields (for the dogs example we used commas):
```
name: the person's name
organization: who they represent
role: their job title or role
learned: what we learned about them from this story
article_headline: the headline of the story
article_date: the publication date in YYYY-MM-DD
```
As you can see, this schema definition is pretty simple - each line has the name of a property we want to capture, then an optional: followed by a description, which doubles as instructions for the model.

The full syntax is {ref}`described below <schemas-dsl>` - you can also include type information for things like numbers.

Let's run this against a news article.

Visit [AP News](https://apnews.com/) and grab the URL to an article. I'm using this one:

    https://apnews.com/article/trump-federal-employees-firings-a85d1aaf1088e050d39dcf7e3664bb9f

There's quite a lot of HTML on that page, possibly even enough to exceed GPT-4o mini's 128,000 token input limit. We'll use another tool called [strip-tags](https://github.com/simonw/strip-tags) to reduce that. If you have [uv](https://docs.astral.sh/uv/) installed you can call it using `uvx strip-tags`, otherwise you'll need to install it first:

```
uv tool install strip-tags
# Or "pip install" or "pipx install"
```
Now we can run this command to extract the people from that article:

```bash
curl 'https://apnews.com/article/trump-federal-employees-firings-a85d1aaf1088e050d39dcf7e3664bb9f' | \
  uvx strip-tags | \
  llm --schema-multi "
name: the person's name
organization: who they represent
role: their job title or role
learned: what we learned about them from this story
article_headline: the headline of the story
article_date: the publication date in YYYY-MM-DD
" --system 'extract people mentioned in this article'
```
The output I got started like this:
```json
{
  "items": [
    {
      "name": "William Alsup",
      "organization": "U.S. District Court",
      "role": "Judge",
      "learned": "He ruled that the mass firings of probationary employees were likely unlawful and criticized the authority exercised by the Office of Personnel Management.",
      "article_headline": "Judge finds mass firings of federal probationary workers were likely unlawful",
      "article_date": "2025-02-26"
    },
    {
      "name": "Everett Kelley",
      "organization": "American Federation of Government Employees",
      "role": "National President",
      "learned": "He hailed the court's decision as a victory for employees who were illegally fired.",
      "article_headline": "Judge finds mass firings of federal probationary workers were likely unlawful",
      "article_date": "2025-02-26"
    }
```
This data has been logged to LLM's {ref}`SQLite database <logging>`. We can retrieve the data back out again using the {ref}`llm logs <logging-view>` command like this:
```bash
llm logs -c --data
```
The `-c` flag means "use most recent conversation", and the `--data` flag outputs just the JSON data that was captured in the response.

We're going to want to use the same schema for other things. Schemas that we use are automatically logged to the database - we can view them using `llm schemas`:

```bash
llm schemas
```
Here's the output:
```
- id: 3b7702e71da3dd791d9e17b76c88730e
  summary: |
    {items: [{name, organization, role, learned, article_headline, article_date}]}
  usage: |
    1 time, most recently 2025-02-28T04:50:02.032081+00:00
```
To view the full schema, run that command with `--full`:

```bash
llm schemas --full
```
Which outputs:
```
- id: 3b7702e71da3dd791d9e17b76c88730e
  schema: |
    {
      "type": "object",
      "properties": {
        "items": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": {
                "type": "string",
                "description": "the person's name"
              },
    ...
```
That `3b7702e71da3dd791d9e17b76c88730e` ID can be used to run the same schema again. Let's try that now on a different URL:

```bash
curl 'https://apnews.com/article/bezos-katy-perry-blue-origin-launch-4a074e534baa664abfa6538159c12987' | \
  uvx strip-tags | \
  llm --schema 3b7702e71da3dd791d9e17b76c88730e \
    --system 'extract people mentioned in this article'
```
Here we are using `--schema` because our schema ID already corresponds to an array of items.

The result starts like this:
```json
{
  "items": [
    {
      "name": "Katy Perry",
      "organization": "Blue Origin",
      "role": "Singer",
      "learned": "Katy Perry will join the all-female celebrity crew for a spaceflight organized by Blue Origin.",
      "article_headline": "Katy Perry and Gayle King will join Jeff Bezos’ fiancee Lauren Sanchez on Blue Origin spaceflight",
      "article_date": "2023-10-15"
    },
```
One more trick: let's turn our schema and system prompt combination into a {ref}`template <prompt-templates>`.

```bash
llm --schema 3b7702e71da3dd791d9e17b76c88730e \
  --system 'extract people mentioned in this article' \
  --save people
```
This creates a new template called "people". We can confirm the template was created correctly using:
```bash
llm templates show people
```
Which will output the YAML version of the template looking like this:
```yaml
name: people
schema_object:
    properties:
        items:
            items:
                properties:
                    article_date:
                        description: the publication date in YYYY-MM-DD
                        type: string
                    article_headline:
                        description: the headline of the story
                        type: string
                    learned:
                        description: what we learned about them from this story
                        type: string
                    name:
                        description: the person's name
                        type: string
                    organization:
                        description: who they represent
                        type: string
                    role:
                        description: their job title or role
                        type: string
                required:
                - name
                - organization
                - role
                - learned
                - article_headline
                - article_date
                type: object
            type: array
    required:
    - items
    type: object
system: extract people mentioned in this article
```
We can now run our people extractor against another fresh URL. Let's use one from The Guardian:
```bash
curl https://www.theguardian.com/commentisfree/2025/feb/27/billy-mcfarland-new-fyre-festival-fantasist | \
  strip-tags | llm -t people
```
Storing the schema in a template means we can just use `llm -t people` to run the prompt. Here's what I got back:
```json
{
  "items": [
    {
      "name": "Billy McFarland",
      "organization": "Fyre Festival",
      "role": "Organiser",
      "learned": "Billy McFarland is known for organizing the infamous Fyre Festival and was sentenced to six years in prison for wire fraud related to it. He is attempting to revive the festival with Fyre 2.",
      "article_headline": "Welcome back Billy McFarland and a new Fyre festival. Shows you can’t keep a good fantasist down",
      "article_date": "2025-02-27"
    }
  ]
}
```
Depending on the model, schema extraction may work against images and PDF files as well.

I took a screenshot of part of [this story in the Onion](https://theonion.com/mark-zuckerberg-insists-anyone-with-same-skewed-values-1826829272/) and saved it to the following URL:

    https://static.simonwillison.net/static/2025/onion-zuck.jpg

We can pass that as an {ref}`attachment <usage-attachments>` using the `-a` option. This time let's use GPT-4o:

```bash
llm -t people -a https://static.simonwillison.net/static/2025/onion-zuck.jpg -m gpt-4o
```
Which gave me back this:
```json
{
  "items": [
    {
      "name": "Mark Zuckerberg",
      "organization": "Facebook",
      "role": "CEO",
      "learned": "He addressed criticism by suggesting anyone with similar values and thirst for power could make the same mistakes.",
      "article_headline": "Mark Zuckerberg Insists Anyone With Same Skewed Values And Unrelenting Thirst For Power Could Have Made Same Mistakes",
      "article_date": "2018-06-14"
    }
  ]
}
```
Now that we've extracted people from a number of different sources, let's load them into a database.

The {ref}`llm logs <logging-view>` command has several features for working with logged JSON objects. Since we've been recording multiple objects from each page in an `"items"` array using our `people` template we can access those using the following command:

```bash
llm logs --schema t:people --data-key items
```
In place of `t:people` we could use the `3b7702e71da3dd791d9e17b76c88730e` schema ID or even the original schema string instead, see {ref}`specifying a schema <schemas-specify>`.

This command outputs newline-delimited JSON for every item that has been captured using the specified schema:
```json
{"name": "Katy Perry", "organization": "Blue Origin", "role": "Singer", "learned": "She is one of the passengers on the upcoming spaceflight with Blue Origin."}
{"name": "Gayle King", "organization": "Blue Origin", "role": "TV Journalist", "learned": "She is participating in the upcoming Blue Origin spaceflight."}
{"name": "Lauren Sanchez", "organization": "Blue Origin", "role": "Helicopter Pilot and former TV Journalist", "learned": "She selected the crew for the Blue Origin spaceflight."}
{"name": "Aisha Bowe", "organization": "Engineering firm", "role": "Former NASA Rocket Scientist", "learned": "She is part of the crew for the spaceflight."}
{"name": "Amanda Nguyen", "organization": "Research Scientist", "role": "Activist and Scientist", "learned": "She is included in the crew for the upcoming Blue Origin flight."}
{"name": "Kerianne Flynn", "organization": "Movie Producer", "role": "Producer", "learned": "She will also be a passenger on the upcoming spaceflight."}
{"name": "Billy McFarland", "organization": "Fyre Festival", "role": "Organiser", "learned": "He was sentenced to six years in prison for wire fraud in 2018 and has launched a new festival called Fyre 2.", "article_headline": "Welcome back Billy McFarland and a new Fyre festival. Shows you can\u2019t keep a good fantasist down", "article_date": "2025-02-27"}
{"name": "Mark Zuckerberg", "organization": "Facebook", "role": "CEO", "learned": "He attempted to dismiss criticism by suggesting that anyone with similar values and thirst for power could have made the same mistakes.", "article_headline": "Mark Zuckerberg Insists Anyone With Same Skewed Values And Unrelenting Thirst For Power Could Have Made Same Mistakes", "article_date": "2018-06-14"}
```
If we add `--data-array` we'll get back a valid JSON array of objects instead:
```bash
llm logs --schema t:people --data-key items --data-array
```
Output starts:
```json
[{"name": "Katy Perry", "organization": "Blue Origin", "role": "Singer", "learned": "She is one of the passengers on the upcoming spaceflight with Blue Origin."},
 {"name": "Gayle King", "organization": "Blue Origin", "role": "TV Journalist", "learned": "She is participating in the upcoming Blue Origin spaceflight."},
```

We can load this into a SQLite database using [sqlite-utils](https://sqlite-utils.datasette.io/), in particular the [sqlite-utils insert](https://sqlite-utils.datasette.io/en/stable/cli.html#inserting-json-data) command.

```bash
uv tool install sqlite-utils
# or pip install or pipx install
```
Now we can pipe the JSON into that tool to create a database with a `people` table:
```bash
llm logs --schema t:people --data-key items --data-array | \
  sqlite-utils insert data.db people -
```
To see a table of the name, organization and role columns use [sqlite-utils rows](https://sqlite-utils.datasette.io/en/stable/cli.html#returning-all-rows-in-a-table):
```bash
sqlite-utils rows data.db people -t -c name -c organization -c role
```
Which produces:
```
name             organization        role
---------------  ------------------  -----------------------------------------
Katy Perry       Blue Origin         Singer
Gayle King       Blue Origin         TV Journalist
Lauren Sanchez   Blue Origin         Helicopter Pilot and former TV Journalist
Aisha Bowe       Engineering firm    Former NASA Rocket Scientist
Amanda Nguyen    Research Scientist  Activist and Scientist
Kerianne Flynn   Movie Producer      Producer
Billy McFarland  Fyre Festival       Organiser
Mark Zuckerberg  Facebook            CEO
```
We can also explore the database in a web interface using [Datasette](https://datasette.io/):

```bash
uvx datasette data.db
# Or install datasette first:
uv tool install datasette # or pip install or pipx install
datasette data.db
```
Visit `http://127.0.0.1:8001/data/people` to start navigating the data.

(schemas-json-schemas)=

## Using JSON schemas

The above examples have both used {ref}`concise schema syntax <schemas-dsl>`. LLM converts this format to [JSON schema](https://json-schema.org/), and you can use JSON schema directly yourself if you wish.

JSON schema covers the following:

- The data types of fields (string, number, array, object, etc.)
- Required vs. optional fields
- Nested data structures
- Constraints on values (minimum/maximum, patterns, etc.)
- Descriptions of those fields - these can be used to guide the language model

Different models may support different subsets of the overall JSON schema language. You should experiment to figure out what works for the model you are using.

LLM recommends that the top level of the schema is an object, not an array, for increased compatibility across multiple models. I suggest using `{"items": [array of objects]}` if you want to return an array.

The dogs schema above, `name, age int, one_sentence_bio`, would look like this as a full JSON schema:

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    },
    "age": {
      "type": "integer"
    },
    "one_sentence_bio": {
      "type": "string"
    }
  },
  "required": [
    "name",
    "age",
    "one_sentence_bio"
  ]
}
```
This JSON can be passed directly to the `--schema` option, or saved in a file and passed as the filename.
```bash
llm --schema '{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    },
    "age": {
      "type": "integer"
    },
    "one_sentence_bio": {
      "type": "string"
    }
  },
  "required": [
    "name",
    "age",
    "one_sentence_bio"
  ]
}' 'a surprising dog'
```
Example output:
```json
{
  "name": "Baxter",
  "age": 3,
  "one_sentence_bio": "Baxter is a rescue dog who learned to skateboard and now performs tricks at local parks, astonishing everyone with his skill!"
}
```

(schemas-specify)=

## Ways to specify a schema

LLM accepts schema definitions for both running prompts and exploring logged responses, using the `--schema` option.

This option can take multiple forms:

- A string providing a JSON schema: `--schema '{"type": "object", ...}'`
- A {ref}`condensed schema definition <schemas-dsl>`: `--schema 'name,age int'`
- The name or path of a file on disk containing a JSON schema: `--schema dogs.schema.json`
- The hexadecimal ID of a previously logged schema: `--schema 520f7aabb121afd14d0c6c237b39ba2d` - these IDs can be found using the `llm schemas` command.
- A schema that has been {ref}`saved in a template <prompt-templates-save>`: `--schema t:name-of-template`

(schemas-dsl)=

## Concise LLM schema syntax

JSON schema's can be time-consuming to construct by hand. LLM also supports a concise alternative syntax for specifying a schema.

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

The Python utility function `llm.schema_dsl(schema)` can be used to convert this syntax into the equivalent JSON schema dictionary when working with schemas {ref}`in the Python API <python-api-schemas>`.

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
Add `--data-ids` to include `"response_id"` and `"conversation_id"` fields in each of the returned objects reflecting the database IDs of the response and conversation they were a part of. This can be useful for tracking the source of each individual row.

```bash
llm logs --schema-multi 'name, ten_word_bio' --data-key items --data-ids
```
Output:
```json
{"name": "Nebula", "ten_word_bio": "A cosmic puppy with starry fur, loves adventures in space.", "response_id": "01jn4dawj8sq0c6t3emf4k5ryx", "conversation_id": "01jn4dawj8sq0c6t3emf4k5ryx"}
{"name": "Echo", "ten_word_bio": "A clever hound with extraordinary hearing, master of hide-and-seek.", "response_id": "01jn4dawj8sq0c6t3emf4k5ryx", "conversation_id": "01jn4dawj8sq0c6t3emf4k5ryx"}
{"name": "Biscuit", "ten_word_bio": "An adorable chef dog, bakes treats that everyone loves.", "response_id": "01jn4dawj8sq0c6t3emf4k5ryx", "conversation_id": "01jn4dawj8sq0c6t3emf4k5ryx"}
{"name": "Cosmo", "ten_word_bio": "Galactic explorer, loves adventures and chasing shooting stars.", "response_id": "01jn4daycb3svj0x7kvp7zrp4q", "conversation_id": "01jn4daycb3svj0x7kvp7zrp4q"}
{"name": "Pixel", "ten_word_bio": "Tech-savvy pup, builds gadgets and loves virtual playtime.", "response_id": "01jn4daycb3svj0x7kvp7zrp4q", "conversation_id": "01jn4daycb3svj0x7kvp7zrp4q"}
```
If a row already has a property called `"conversation_id"` or `"response_id"` additional underscores will be appended to the ID key until it no longer overlaps with the existing keys.

The `--id-gt $ID` and `--id-gte $ID` options can be useful for ignoring logged schema data prior to a certain point, see {ref}`logging-filter-id` for details.