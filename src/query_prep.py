"""Query-time character alias expansion (ENABLE_ALIAS_RESOLUTION).

Questions name characters the way people talk ("Emma", "Cat", "Bri");
extraction tags mostly carry full names ("Emma Mendoza", "Cat Kissinger",
"Brielle Draper"). This module bridges the two by reusing the server's
Canonicalizer — the one audited alias system — instead of inventing a
second one: each input name resolves to its entity and expands to the
entity's grounded alias set, so a SQL OR-of-LIKEs can match every spelling.

The input name always stays first in its alias list, so expanded matching
is a strict superset of the literal match; names the canonicalizer can't
resolve fall back to [name] (literal behavior).
"""

from __future__ import annotations

import sqlite3

from .canonical import Canonicalizer

# The Canonicalizer's build phase scans the prose for every name variant —
# too costly to redo per query — but it self-invalidates cheaply on each
# resolve() (row count + user-map state), so one instance per connection is
# both fast and always current. sqlite3.Connection is neither weakref-able
# nor attribute-assignable, so the cache keys on id() and pins the
# connection (preventing id reuse); callers pass one long-lived connection
# per process, so this holds a single entry in practice.
_canonicalizers: dict[int, tuple[sqlite3.Connection, Canonicalizer]] = {}


def _canonicalizer(db: sqlite3.Connection) -> Canonicalizer:
    entry = _canonicalizers.get(id(db))
    if entry is None or entry[0] is not db:
        entry = (db, Canonicalizer(db))
        _canonicalizers[id(db)] = entry
    return entry[1]


def expand_characters(db: sqlite3.Connection,
                      names: list[str]) -> dict[str, list[str]]:
    """Map each input name to a grounded alias list.

    "Cat" -> ["Cat", "Cat Kissinger", ...]; unresolved names -> [name].
    Aliases shorter than 3 characters ("B", "Em", "Q") are excluded: the
    consumers wrap each alias in %…% LIKE wildcards, where a one-letter
    alias would match nearly every row.
    """
    canon = _canonicalizer(db)
    expanded: dict[str, list[str]] = {}
    for name in names:
        aliases = [name]
        entity_name = canon.resolve(name)
        if entity_name is None:
            # user-merged nicknames ("Cap" -> "Noah Gatlin") may exist only
            # as entity aliases, never as raw extraction tags, so resolve()
            # can't see them; accept an alias match when it's unambiguous
            matches = [e.name for e in canon.entities.values()
                       if name == e.name or name in e.aliases]
            if len(matches) == 1:
                entity_name = matches[0]
        entity = canon.entities.get(entity_name) if entity_name else None
        if entity is not None:
            for alias in (entity.name, *entity.aliases):
                if len(alias.strip()) >= 3 and alias not in aliases:
                    aliases.append(alias)
        expanded[name] = aliases
    return expanded
