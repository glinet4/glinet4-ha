"""Dynamic entity discovery shared across platforms.

Every platform used to build its entities once in ``async_setup_entry`` and add
only those whose backing data was present at that instant -- so a capability
that appeared later (AdGuard enabled, a USB disk plugged in, a cellular profile
landing) had no entity until the config entry was reloaded.

``add_entities_when_available`` generalises the pattern ``device_tracker``
already used: candidate entities are added as soon as their data is available
and re-checked on every coordinator update, so late-arriving capabilities get
their entities with no reload.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import callback

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from homeassistant.helpers.entity import Entity
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GlinetConfigEntry, GLinetCoordinator


def add_entities_when_available(
    entry: GlinetConfigEntry,
    async_add_entities: AddEntitiesCallback,
    candidates: Sequence[tuple[Entity, Callable[[], bool]]],
    coordinators: Iterable[GLinetCoordinator],
) -> None:
    """Add each candidate entity as soon as its availability predicate is true.

    ``candidates`` are ``(entity, is_available)`` pairs. Available candidates are
    added now; the rest are added on a later coordinator update once available.
    A listener is registered on each coordinator in ``coordinators`` (they share
    one snapshot, so any of them firing re-checks everything) and torn down with
    the entry. Each candidate is added at most once; entities that later lose
    their data are left in place (removing them is the job of registry GC, and
    only for capabilities that are permanently gone, not transiently down).
    """
    added: set[int] = set()

    @callback
    def _add_available() -> None:
        new = []
        for entity, is_available in candidates:
            if id(entity) in added or not is_available():
                continue
            new.append(entity)
            added.add(id(entity))
        if new:
            async_add_entities(new)

    for coordinator in coordinators:
        entry.async_on_unload(coordinator.async_add_listener(_add_available))
    _add_available()
