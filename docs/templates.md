(prompt-templates)=
# Templates

A **template** can combine a prompt, system prompt, model, default model options, schema, and fragments into a single reusable unit.

Only one template can be used at a time. To compose multiple shorter pieces of prompts together consider using {ref}`fragments <fragments>` instead.

(prompt-templates-save)=

## Getting started with <code>--save</code>

The easiest way to create a template is using the `--save template_name` option.

Here's how to create a template for summarizing text:

```bash
llm '$input - summarize this' --save summarize
```
Put `$input` where you would like the user's input to be inserted. If you omit this their input will be added to the end of your regular prompt:
```bash
llm 'Summarize the following: ' --save summarize
```
You can also create templates using system prompts:
```bash
llm --system 'Summarize this' --save summarize
```
You can set the default model for a template using `--model`:

```bash
llm --system 'Summarize this' --model gpt-4o --save summarize
```
You can also save default options:
```bash
llm --system 'Speak in French' -o temperature 1.8 --save wild-french
```
If you want to include a literal `$` sign in your prompt, use `$$` instead:
```bash
llm --system 'Estimate the cost in $$ of this: $input' --save estimate
```
Use `--tool/-T` one or more times to add tools to the template:
```bash
llm -T llm_time --system 'Always include the current time in the answer' --save time
```
You can also use `--functions` to add Python function code directly to the template:
```bash
llm --functions 'def reverse_string(s): return s[::-1]' --system 'reverse any input' --save reverse
llm -t reverse 'Hello, world!'
```

Add `--schema` to bake a {ref}`schema <usage-schemas>` into your template:

```bash
llm --schema dog.schema.json 'invent a dog' --save dog
```

If you add `--extract` the setting to  {ref}`extract the first fenced code block <usage-extract-fenced-code>` will be persisted in the template.
```bash
llm --system 'write a Python function' --extract --save python-function
llm -t python-function 'calculate haversine distance between two points'
```
In each of these cases the template will be saved in YAML format in a dedicated directory on disk.

(prompt-templates-using)=

## Using a template

You can execute a named template using the `-t/--template` option:

```bash
curl -s https://example.com/ | llm -t summarize
```

This can be combined with the `-m` option to specify a different model:
```bash
curl -s https://llm.datasette.io/en/latest/ | \
  llm -t summarize -m gpt-3.5-turbo-16k
```
Templates can also be specified as a direct path to a YAML file on disk:
```bash
llm -t path/to/template.yaml 'extra prompt here'
```
Or as a URL to a YAML file hosted online:
```bash
llm -t https://raw.githubusercontent.com/simonw/llm-templates/refs/heads/main/python-app.yaml \
  'Python app to pick a random line from a file'
```
Note that templates loaded via URLs will have any `functions:` keys ignored, to avoid accidentally executing arbitrary code. This restriction also applies to templates loaded via the {ref}`template loaders plugin mechanism <plugin-hooks-register-template-loaders>`.

(prompt-templates-list)=

## Listing available templates

This command lists all available templates:
```bash
llm templates
```
The output looks something like this:
```
cmd        : system: reply with macos terminal commands only, no extra information
glados     : system: You are GlaDOS prompt: Summarize this:
```

(prompt-templates-yaml)=

## Templates as YAML files

Templates are stored as YAML files on disk.

You can edit (or create) a YAML file for a template using the `llm templates edit` command:
```
llm templates edit summarize
```
This will open the system default editor.

:::{tip}
You can control which editor will be used here using the `EDITOR` environment variable - for example, to use VS Code:
```bash
export EDITOR="code -w"
```
Add that to your `~/.zshrc` or `~/.bashrc` file depending on which shell you use (`zsh` is the default on macOS since macOS Catalina in 2019).
:::

You can create or edit template files directly in the templates directory. The location of this directory is shown by the `llm templates path` command:
```bash
llm templates path
```
Example output:
```
/Users/simon/Library/Application Support/io.datasette.llm/templates
```

A basic YAML template looks like this:

```yaml
prompt: 'Summarize this: $input'
```
Or use YAML multi-line strings for longer inputs. I created this using `llm templates edit steampunk`:
```yaml
prompt: >
    Summarize the following text.

    Insert frequent satirical steampunk-themed illustrative anecdotes.
    Really go wild with that.

    Text to summarize: $input
```
The `prompt: >` causes the following indented text to be treated as a single string, with newlines collapsed to spaces. Use `prompt: |` to preserve newlines.

Running that with `llm -t steampunk` against GPT-4o (via [strip-tags](https://github.com/simonw/strip-tags) to remove HTML tags from the input and minify whitespace):
```bash
curl -s 'https://til.simonwillison.net/macos/imovie-slides-and-audio' | \
  strip-tags -m | llm -t steampunk -m gpt-4o
```
Output:
> In a fantastical steampunk world, Simon Willison decided to merge an old MP3 recording with slides from the talk using iMovie. After exporting the slides as images and importing them into iMovie, he had to disable the default Ken Burns effect using the "Crop" tool. Then, Simon manually synchronized the audio by adjusting the duration of each image. Finally, he published the masterpiece to YouTube, with the whimsical magic of steampunk-infused illustrations leaving his viewers in awe.

(prompt-templates-system)=

### System prompts

When working with models that support system prompts you can set a system prompt using a `system:` key like so:

```yaml
system: Summarize this
```
If you specify only a system prompt you don't need to use the `$input` variable - `llm` will use the user's input as the whole of the regular prompt, which will then be processed using the instructions set in that system prompt.

You can combine system and regular prompts like so:

```yaml
system: You speak like an excitable Victorian adventurer
prompt: 'Summarize this: $input'
```

(prompt-templates-fragments)=

### Fragments

Templates can reference {ref}`Fragments <fragments>` using the `fragments:` and `system_fragments:` keys. These should be a list of fragment URLs, filepaths or hashes:

```yaml
fragments:
- https://example.com/robots.txt
- /path/to/file.txt
- 993fd38d898d2b59fd2d16c811da5bdac658faa34f0f4d411edde7c17ebb0680
system_fragments:
- https://example.com/systm-prompt.txt
```

(prompt-templates-options)=

### Options

Default options can be set using the `options:` key:

```yaml
name: wild-french
system: Speak in French
options:
  temperature: 1.8
```

(prompt-templates-tools)=

### Tools

The `tools:` key can provide a list of tool names from other plugins - either function names or toolbox specifiers:
```yaml
name: time-plus
tools:
- llm_time
- Datasette("https://example.com/timezone-lookup")
```
The `functions:` key can provide a multi-line string of Python code defining additional functions:
```yaml
name: my-functions
functions: |
  def reverse_string(s: str):
      return s[::-1]

  def greet(name: str):
      return f"Hello, {name}!"
```
(prompt-templates-schemas)=

### Schemas

Use the `schema_object:` key to embed a JSON schema (as YAML) in your template. The easiest way to create these is with the `llm --schema ... --save name-of-template` command - the result should look something like this:

```yaml
name: dogs
schema_object:
    properties:
        dogs:
            items:
                properties:
                    bio:
                        type: string
                    name:
                        type: string
                type: object
            type: array
    type: object
```

(prompt-templates-variables)=

### Additional template variables

Templates that work against the user's normal prompt input (content that is either piped to the tool via standard input or passed as a command-line argument) can use the `$input` variable.

You can use additional named variables. These will then need to be provided using the `-p/--param` option when executing the template.

Here's an example YAML template called `recipe`, which you can create using `llm templates edit recipe`:

```yaml
prompt: |
    Suggest a recipe using ingredients: $ingredients

    It should be based on cuisine from this country: $country
```
This can be executed like so:

```bash
llm -t recipe -p ingredients 'sausages, milk' -p country Germany
```
My output started like this:
> Recipe: German Sausage and Potato Soup
>
> Ingredients:
> - 4 German sausages
> - 2 cups whole milk

This example combines input piped to the tool with additional parameters. Call this `summarize`:

```yaml
system: Summarize this text in the voice of $voice
```
Then to run it:
```bash
curl -s 'https://til.simonwillison.net/macos/imovie-slides-and-audio' | \
  strip-tags -m | llm -t summarize -p voice GlaDOS
```
I got this:

> My previous test subject seemed to have learned something new about iMovie. They exported keynote slides as individual images [...] Quite impressive for a human.

(prompt-default-parameters)=

### Specifying default parameters

When creating a template using the `--save` option you can pass `-p name value` to store the default values for parameters:
```bash
llm --system 'Summarize this text in the voice of $voice' \
  --model gpt-4o -p voice GlaDOS --save summarize
```

You can specify default values for parameters in the YAML using the `defaults:` key.

```yaml
system: Summarize this text in the voice of $voice
defaults:
  voice: GlaDOS
```

When running without `-p` it will choose the default:

```bash
curl -s 'https://til.simonwillison.net/macos/imovie-slides-and-audio' | \
  strip-tags -m | llm -t summarize
```

But you can override the defaults with `-p`:

```bash
curl -s 'https://til.simonwillison.net/macos/imovie-slides-and-audio' | \
  strip-tags -m | llm -t summarize -p voice Yoda
```

I got this:

> Text, summarize in Yoda's voice, I will: "Hmm, young padawan. Summary of this text, you seek. Hmmm. ...

(prompt-templates-extract)=

### Configuring code extraction

To configure the {ref}`extract first fenced code block <usage-extract-fenced-code>` setting for the template, add this:

```yaml
extract: true
```

(prompt-templates-default-model)=

### Setting a default model for a template

Templates executed using `llm -t template-name` will execute using the default model that the user has configured for the tool - or `gpt-3.5-turbo` if they have not configured their own default.

You can specify a new default model for a template using the `model:` key in the associated YAML. Here's a template called `roast`:

```yaml
model: gpt-4o
system: roast the user at every possible opportunity, be succinct
```
Example:
```bash
llm -t roast 'How are you today?'
```
> I'm doing great but with your boring questions, I must admit, I've seen more life in a cemetery.

(prompt-templates-loaders)=

## Template loaders from plugins

LLM plugins can {ref}`register prefixes <plugin-hooks-register-template-loaders>` that can be used to load templates from external sources.

[llm-templates-github](https://github.com/simonw/llm-templates-github) is an example which adds a `gh:` prefix which can be used to load templates from GitHub.

You can install that plugin like this:
```bash
llm install llm-templates-github
```

Use the `llm templates loaders` command to see details of the registered loaders.

```bash
llm templates loaders
```
Output:
```
gh:
  Load a template from GitHub or local cache if available

  Format: username/repo/template_name (without the .yaml extension)
    or username/template_name which means username/llm-templates/template_name
```

Then you can then use it like this:
```bash
curl -sL 'https://llm.datasette.io/' | llm -t gh:simonw/summarize
```
The `-sL` flags to `curl` are used to follow redirects and suppress progress meters.

This command will fetch the content of the LLM index page and feed it to the template defined by [summarize.yaml](https://github.com/simonw/llm-templates/blob/main/summarize.yaml) in the [simonw/llm-templates](https://github.com/simonw/llm-templates) GitHub repository.

If two template loader plugins attempt to register the same prefix one of them will have `_1` added to the end of their prefix. Use `llm templates loaders` to check if this has occurred.