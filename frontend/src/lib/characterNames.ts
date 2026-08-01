import type { WriterCharacter } from "../types";

// Resolving a stored character reference to something displayable (LOOM-45).
//
// `events[].characters` and `relationships[].target` used to store display
// NAMES. Renaming a character silently orphaned every one of them — nothing
// errored, the links just stopped resolving — which is why the name field in
// Loom's character modal stayed read-only. They now store `wc-` ids, and the
// name is derived here, at read time, from the character record itself.
//
// Everything display-related goes through this module so there is one answer
// to "what is this reference called", rather than three components each
// resolving it slightly differently.

export type CharacterIndex = {
  byId: Map<string, WriterCharacter>;
  byName: Map<string, WriterCharacter>;
};

export function indexCharacters(characters: WriterCharacter[]): CharacterIndex {
  return {
    byId: new Map(characters.map((c) => [c.id, c])),
    byName: new Map(characters.map((c) => [c.name.trim(), c])),
  };
}

/**
 * The character a stored reference points at, or null.
 *
 * Tries the id first, then falls back to matching a name. The fallback is not
 * decoration: it makes the read path total across a partially-applied
 * migration, so shipping this code and running the migration do not have to be
 * the same instant. It also absorbs any record written by an older client.
 * Nothing WRITES a name any more — the fallback is read-only, so it cannot
 * quietly keep the old format alive.
 */
export function resolveCharacter(
  ref: string,
  index: CharacterIndex,
): WriterCharacter | null {
  return index.byId.get(ref) ?? index.byName.get((ref ?? "").trim()) ?? null;
}

/**
 * What to show for a reference.
 *
 * An unresolvable reference renders as an explicit unknown rather than being
 * dropped: the reference is real data, and hiding it loses the fact that the
 * event had a cast member at all — which is the exact silent-omission failure
 * this ticket exists to end. Callers style it with `isUnknown`.
 */
export function characterLabel(ref: string, index: CharacterIndex): string {
  return resolveCharacter(ref, index)?.name ?? "Unknown character";
}

export function isUnknown(ref: string, index: CharacterIndex): boolean {
  return resolveCharacter(ref, index) === null;
}
