(embeddings-storage)=
# Embedding storage format

The default output format of the `llm embed` command is a JSON array of floating point numbers.

LLM stores embeddings in space-efficient format: a little-endian binary sequences of 32-bit floating point numbers, each represented using 4 bytes.

These are stored in a `BLOB` column in a SQLite database.

The following Python functions can be used to convert between this format and an array of floating point numbers:

```python
import struct

def encode(values):
    return struct.pack("<" + "f" * len(values), *values)

def decode(binary):
    return struct.unpack("<" + "f" * (len(binary) // 4), binary)
```

These functions are available as `llm.encode()` and `llm.decode()`.

If you are using [NumPy](https://numpy.org/) you can decode one of these binary values like this:

```python
import numpy as np

numpy_array = np.frombuffer(value, "<f4")
```
The `<f4` format string here ensures NumPy will treat the data as a little-endian sequence of 32-bit floats.