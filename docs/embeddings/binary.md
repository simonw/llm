(embeddings-binary)=
# Binary embedding formats

The default output format of the `llm embed` command is a JSON array of floating point numbers.

LLM stores embeddings in a more space-efficient format: little-endian binary sequences of 32-bit floating point numbers, each represented using 4 bytes.

The following Python functions can be used to convert between the two formats:

```python
import struct

def encode(values):
    return struct.pack("<" + "f" * len(values), *values)

def decode(binary):
    return struct.unpack("<" + "f" * (len(binary) // 4), binary)
```
When using `llm embed` directly, the default output format is JSON.

Use `--format blob` for the binary output, `--format hex` for that binary output as hexadecimal and `--format base64` for that binary output encoded using base64.
