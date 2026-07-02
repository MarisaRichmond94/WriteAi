import type { CharacterSummary, CharacterDetail, CharacterBookDetail, CharacterCorrections } from "../types";
import { isMockMode, MOCK_EXTRACTED_CHARACTERS, MOCK_CHARACTER_DETAIL, MOCK_CHARACTER_BOOK_DETAIL } from "../mocks/mockData";

export async function fetchCharacters(
  bookId?: string,
  options?: { raw?: boolean; includeHidden?: boolean }
): Promise<CharacterSummary[]> {
  if (isMockMode()) {
    if (!bookId) return MOCK_EXTRACTED_CHARACTERS;
    return MOCK_EXTRACTED_CHARACTERS.filter((c) => c.books.includes(bookId));
  }
  const params = new URLSearchParams();
  if (bookId) params.set("book", bookId);
  if (options?.raw) params.set("raw", "true");
  if (options?.includeHidden) params.set("include_hidden", "true");
  const query = params.toString();
  const url = query ? `/api/characters?${query}` : "/api/characters";
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch characters: ${res.statusText}`);
  return res.json();
}

export async function fetchCharacterDetail(characterId: string, bookId?: string): Promise<CharacterDetail> {
  if (isMockMode()) return MOCK_CHARACTER_DETAIL;
  const url = bookId
    ? `/api/characters/${characterId}?book=${bookId}`
    : `/api/characters/${characterId}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch character: ${res.statusText}`);
  return res.json();
}

export async function fetchCharacterBookDetail(
  characterId: string,
  bookId: string
): Promise<CharacterBookDetail> {
  if (isMockMode()) return MOCK_CHARACTER_BOOK_DETAIL;
  const res = await fetch(`/api/characters/${characterId}/book/${bookId}`);
  if (!res.ok) throw new Error(`Failed to fetch character book detail: ${res.statusText}`);
  return res.json();
}

export async function invalidateCharactersCache(): Promise<void> {
  const res = await fetch("/api/characters/cache/invalidate", { method: "POST" });
  if (!res.ok) throw new Error(`Failed to invalidate cache: ${res.statusText}`);
}

export async function triggerExtract(): Promise<void> {
  const res = await fetch("/api/characters/extract", { method: "POST" });
  if (!res.ok) throw new Error(`Failed to trigger extraction: ${res.statusText}`);
}

export async function uploadCharacterPhoto(
  characterId: string,
  file: File,
  bookId?: string
): Promise<void> {
  if (isMockMode()) return;
  const url = bookId
    ? `/api/characters/${characterId}/photo?book=${bookId}`
    : `/api/characters/${characterId}/photo`;
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(url, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Failed to upload photo: ${res.statusText}`);
}

// ── Corrections API ───────────────────────────────────────────────────────────

export async function fetchCorrections(): Promise<CharacterCorrections> {
  const res = await fetch('/api/characters/corrections');
  if (!res.ok) throw new Error('Failed to fetch corrections');
  return res.json();
}

export async function patchCharacterName(oldName: string, newName: string, characterId?: string): Promise<void> {
  const res = await fetch('/api/characters/corrections/name', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ old_name: oldName, new_name: newName, character_id: characterId }),
  });
  if (!res.ok) throw new Error('Failed to update character name');
}

export async function deleteCharacterNameCorrection(oldName: string): Promise<void> {
  const res = await fetch(`/api/characters/corrections/name/${encodeURIComponent(oldName)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to delete name correction');
}

export async function addCharacterAlias(character: string, alias: string, context?: string): Promise<void> {
  const res = await fetch('/api/characters/corrections/aliases', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character, alias, context }),
  });
  if (!res.ok) throw new Error('Failed to add alias');
}

export async function removeCharacterAlias(character: string, alias: string): Promise<void> {
  const res = await fetch('/api/characters/corrections/aliases', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character, alias }),
  });
  if (!res.ok) throw new Error('Failed to remove alias');
}

export async function addCharacterRelationship(character: string, target: string, status: string): Promise<void> {
  const res = await fetch('/api/characters/corrections/relationships', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character, target, status }),
  });
  if (!res.ok) throw new Error('Failed to add relationship');
}

export async function updateCharacterRelationship(character: string, target: string, status: string): Promise<void> {
  const res = await fetch('/api/characters/corrections/relationships', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character, target, status }),
  });
  if (!res.ok) throw new Error('Failed to update relationship');
}

export async function removeCharacterRelationship(character: string, target: string): Promise<void> {
  const res = await fetch('/api/characters/corrections/relationships', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character, target }),
  });
  if (!res.ok) throw new Error('Failed to remove relationship');
}

export async function mergeCharacters(fromCharacter: string, intoCharacter: string, asAlias?: string): Promise<void> {
  const res = await fetch('/api/characters/corrections/merge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from_character: fromCharacter, into_character: intoCharacter, as_alias: asAlias }),
  });
  if (!res.ok) throw new Error('Failed to merge characters');
}

export async function hideCharacter(character: string): Promise<void> {
  const res = await fetch('/api/characters/corrections/hide', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character }),
  });
  if (!res.ok) throw new Error('Failed to hide character');
}

export async function unhideCharacter(character: string): Promise<void> {
  const res = await fetch(`/api/characters/corrections/hide/${encodeURIComponent(character)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to unhide character');
}

export async function patchCharacterGender(character: string, gender: string): Promise<void> {
  const res = await fetch('/api/characters/corrections/gender', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character, gender }),
  });
  if (!res.ok) throw new Error('Failed to update gender');
}

export async function deleteCharacterGender(character: string): Promise<void> {
  const res = await fetch(`/api/characters/corrections/gender/${encodeURIComponent(character)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to remove gender override');
}

