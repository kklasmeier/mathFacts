"""Number specs for Operand A and Operand B (spec 5.1).

"0-3, 5, 10" becomes [0, 1, 2, 3, 5, 10]. Errors are plain sentences that the
builder shows next to the field.
"""

import re

TOKEN = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")

# Default largest operand value by operation (spec 5.1). Account settings can
# raise this later, up to 100.
OPERAND_LIMIT = {"add": 20, "sub": 20, "mul": 12, "div": 12}


class SpecError(ValueError):
    """Raised with a message a parent can act on."""


def parse_spec(text, limit):
    """Return the sorted, unique values in a spec. Raises SpecError if invalid."""
    if text is None or not text.strip():
        raise SpecError("Enter at least one number, such as 2 or 1-9.")

    values = set()
    for part in text.split(","):
        piece = part.strip()
        if not piece:
            raise SpecError("Remove the extra comma. Use forms like 2, 1-9, or 2,4,6.")
        match = TOKEN.match(part)
        if not match:
            raise SpecError(
                f"'{piece}' is not a number or a range. Use forms like 2, 1-9, or 2,4,6."
            )
        low = int(match.group(1))
        high = int(match.group(2)) if match.group(2) else low
        if high < low:
            raise SpecError(f"'{piece}' runs backwards. Put the smaller number first.")
        if high > limit:
            raise SpecError(f"Use numbers up to {limit} for this operation.")
        values.update(range(low, high + 1))
    return sorted(values)
