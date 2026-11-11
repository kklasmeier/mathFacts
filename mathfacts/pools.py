"""Facts and fact pools (spec 4.5, 5.1, 8 algorithm 2).

For division the fields are named divisor (a) and quotient (b). The problem is
(a × b) ÷ a = b, so the dividend is a × b.
"""

from dataclasses import dataclass

OPERATIONS = {"add": "Addition", "sub": "Subtraction", "mul": "Multiplication", "div": "Division"}
SYMBOL = {"add": "+", "sub": "−", "mul": "×", "div": "÷"}


@dataclass(frozen=True)
class Problem:
    op: str
    a: int
    b: int

    @property
    def answer(self):
        if self.op == "add":
            return self.a + self.b
        if self.op == "sub":
            return self.a - self.b
        if self.op == "mul":
            return self.a * self.b
        return self.b  # division: the quotient

    @property
    def dividend(self):
        return self.a * self.b if self.op == "div" else None


@dataclass
class Pool:
    facts: list
    dropped_zero: int = 0  # divisor-0 combinations removed (division)
    dropped_negative: int = 0  # a < b combinations removed (subtraction)


def build_pool(op, a_values, b_values, include_reverse=False, allow_negatives=False):
    """Cross the two operand lists, apply operation rules, and sort A-then-B."""
    seen = set()
    facts = []
    dropped_zero = 0
    dropped_negative = 0

    def add(problem):
        if problem not in seen:
            seen.add(problem)
            facts.append(problem)

    for a in a_values:
        for b in b_values:
            if op == "div" and a == 0:
                dropped_zero += 1
                continue
            if op == "sub" and a < b and not allow_negatives:
                dropped_negative += 1
                continue
            add(Problem(op, a, b))
            if include_reverse and op in ("add", "mul"):
                add(Problem(op, b, a))

    facts.sort(key=lambda p: (p.a, p.b))
    return Pool(facts, dropped_zero, dropped_negative)
