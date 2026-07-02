// Shim: mock mode is disabled in this app. The character-profile builder
// returns a safe empty profile; the panel hydrates real data on top.
/* eslint-disable @typescript-eslint/no-explicit-any */

export const MOCK_EVENTS: any[] = [];

export function generateMockChapterText(_quote: string, _chapter: number): string {
  return "";
}

export function generateMockCharacterProfile(name: string, _filterBook?: string): any {
  return {
    name,
    role: "",
    description: "",
    aliases: [],
    traits: [],
    relationships: [],
    books: [],
  };
}
