"""
Keep numbers that are not numbers out of JSON.

Python writes NaN and infinity into JSON as bare words, which browsers
refuse to read: one of them anywhere in an answer makes the whole answer
unreadable. They are sent as null instead, which the pages show as a dash.
"""

import math


def finite(value):
    """A copy of a value with every NaN and infinity replaced by None."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(item) for item in value]
    return value
