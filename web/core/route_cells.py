"""Bounded routing for interchangeable implementations of a single contract."""


def eligible_mask(contract: int, policy: int, ready: int, domains: int, resources: int) -> int:
    return contract & policy & ready & domains & resources


def pick_index(eligible: int, cursor: int) -> int | None:
    if not eligible:
        return None
    suffix = eligible >> cursor
    if suffix:
        return cursor + (suffix & -suffix).bit_length() - 1
    return (eligible & -eligible).bit_length() - 1


def domain_mask(dependencies: tuple[frozenset[str], ...], blocked: frozenset[str]) -> int:
    return sum(1 << index for index, required in enumerate(dependencies) if required.isdisjoint(blocked))


class Rotation:
    """Round robin over weighted slots, with two positive probes after a refusal."""

    def __init__(self, schedule: tuple[int, ...]):
        self.schedule = schedule
        self.cursor = 0
        self._healthy = [2] * (max(schedule) + 1)

    def recovering(self, index: int) -> bool:
        return self._healthy[index] < 2

    def observe(self, index: int, healthy: bool) -> None:
        self._healthy[index] = min(2, self._healthy[index] + 1) if healthy else 0

    def choose(self, eligible: int) -> int | None:
        slots = sum(
            1 << slot for slot, index in enumerate(self.schedule)
            if eligible & (1 << index) and not self.recovering(index)
        )
        slot = pick_index(slots, self.cursor)
        if slot is None:
            return None
        self.cursor = (slot + 1) % len(self.schedule)
        return self.schedule[slot]
