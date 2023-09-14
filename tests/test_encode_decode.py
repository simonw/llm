import llm
import pytest
import numpy as np


@pytest.mark.parametrize(
    "array",
    (
        (0.0, 1.0, 1.5),
        (3423.0, 222.0, -1234.5),
    ),
)
def test_roundtrip(array):
    encoded = llm.encode(array)
    decoded = llm.decode(encoded)
    assert decoded == array
    # Try with numpy as well
    numpy_decoded = np.frombuffer(encoded, "<f4")
    assert tuple(numpy_decoded.tolist()) == array
