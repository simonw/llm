from typing import List, Dict


def dicts_to_table_string(
    headings: List[str], dicts: List[Dict[str, str]]
) -> List[str]:
    max_lengths = [len(h) for h in headings]

    # Compute maximum length for each column
    for d in dicts:
        for i, h in enumerate(headings):
            if h in d and len(str(d[h])) > max_lengths[i]:
                max_lengths[i] = len(str(d[h]))

    # Generate formatted table strings
    res = []
    res.append("    ".join(h.ljust(max_lengths[i]) for i, h in enumerate(headings)))

    for d in dicts:
        row = []
        for i, h in enumerate(headings):
            row.append(str(d.get(h, "")).ljust(max_lengths[i]))
        res.append("    ".join(row))

    return res
