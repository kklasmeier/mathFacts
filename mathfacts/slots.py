"""Slot filler (spec 5.1 "Pool vs. slots", 8 algorithms 3 and 10).

Given a pool of facts and a page of rows × columns, choose which fact goes in
each cell, then rearrange so two cells that share a side never hold the same
fact. All randomness comes from one seeded RNG, so the same seed always gives
the same page.
"""

from dataclasses import dataclass

ORDERS = ("sequential", "shuffled", "random")

ATTEMPTS = 4  # restarts of the separation step before giving up
STEPS = 3000  # local-search swaps per attempt


@dataclass
class Arrangement:
    cells: list  # one Problem per cell, row-major (left to right, top to bottom)
    pool_size: int
    slots: int
    repeats: bool  # pool smaller than the page, so facts repeat
    all_same: bool  # the page is one fact repeated
    separated: bool  # no two neighbouring cells share a fact


def choose(facts, slots, order, rng):
    """Pick the multiset of facts for the page, in an order that depends on `order`."""
    n = len(facts)
    if order == "random" and n >= slots:
        # Plenty of facts: each cell is an independent draw, so a page can
        # use a fact more than once only by chance.
        return [rng.choice(facts) for _ in range(slots)]

    if n >= slots:
        if order == "sequential":
            picked = sorted(rng.sample(range(n), slots))
            return [facts[i] for i in picked]
        return rng.sample(facts, slots)

    # Fewer facts than cells: each fact appears floor(slots / n) times, and the
    # leftover cells take a random extra copy of some facts (extra practice).
    if order == "sequential":
        # Walk the facts in A-then-B order and start again, so copies are spread.
        return [facts[i % n] for i in range(slots)]
    copies, extra = divmod(slots, n)
    return facts * copies + rng.sample(facts, extra)


def neighbours(index, rows, cols):
    """Cell indexes that share a side with `index`."""
    row, col = divmod(index, cols)
    out = []
    if col > 0:
        out.append(index - 1)
    if col < cols - 1:
        out.append(index + 1)
    if row > 0:
        out.append(index - cols)
    if row < rows - 1:
        out.append(index + cols)
    return out


def separate(cells, rows, cols, rng):
    """Swap cells until no two side-neighbours match. Returns True on success.

    Each swap is kept only if it does not increase the number of clashing cells
    in the affected area, so the search moves toward a valid page.
    """
    n = len(cells)
    nb = [neighbours(i, rows, cols) for i in range(n)]

    def clash(i):
        return any(cells[j] == cells[i] for j in nb[i])

    for _ in range(STEPS):
        start = rng.randrange(n)
        bad = None
        for offset in range(n):
            candidate = (start + offset) % n
            if clash(candidate):
                bad = candidate
                break
        if bad is None:
            return True
        j = rng.randrange(n)
        if j == bad or cells[j] == cells[bad]:
            continue
        zone = {bad, j, *nb[bad], *nb[j]}
        before = sum(1 for x in zone if clash(x))
        cells[bad], cells[j] = cells[j], cells[bad]
        after = sum(1 for x in zone if clash(x))
        if after > before:
            cells[bad], cells[j] = cells[j], cells[bad]

    return not any(clash(i) for i in range(n))


def build_greedy(cells, rows, cols, rng):
    """Place the same multiset of facts again, one cell at a time, with no clashes.

    Each cell takes a fact that is not already left or above it. Among those,
    it takes a fact with the most copies still to place, so tight pages (a few
    facts with many copies each) still get a valid checkerboard-like layout.
    Returns the new cell list, or None if the greedy pass gets stuck.
    """
    counts = {}
    for fact in cells:
        counts[fact] = counts.get(fact, 0) + 1

    grid = []
    for index in range(len(cells)):
        row, col = divmod(index, cols)
        forbidden = set()
        if col > 0:
            forbidden.add(grid[index - 1])
        if row > 0:
            forbidden.add(grid[index - cols])
        options = [f for f, k in counts.items() if k > 0 and f not in forbidden]
        if not options:
            return None
        best = max(counts[f] for f in options)
        pick = rng.choice([f for f in options if counts[f] == best])
        grid.append(pick)
        counts[pick] -= 1
    return grid


def arrange(facts, rows, cols, order, rng):
    """Fill a rows × cols page from the pool. Returns an Arrangement."""
    if order not in ORDERS:
        raise ValueError(f"unknown order: {order}")
    if not facts:
        raise ValueError("the pool is empty")

    slots = rows * cols
    unique = len(set(facts))
    separated = False
    cells = []
    for _ in range(ATTEMPTS):
        cells = choose(facts, slots, order, rng)
        if order == "shuffled":
            rng.shuffle(cells)
        if unique == 1:
            # One fact only: no arrangement can separate it, so skip the search.
            break
        separated = separate(cells, rows, cols, rng)
        if not separated:
            # Local search keeps the chosen order where it can. When it stalls on
            # tight pages, rebuild the same facts greedily instead.
            rebuilt = build_greedy(cells, rows, cols, rng)
            if rebuilt is not None:
                cells = rebuilt
                separated = True
        if separated:
            break

    return Arrangement(
        cells=cells,
        pool_size=len(facts),
        slots=slots,
        repeats=len(facts) < slots,
        all_same=unique == 1,
        separated=separated or slots == 1,
    )
