// Shim: mock mode is disabled in this app.
/* eslint-disable @typescript-eslint/no-explicit-any */

export const MOCK_EVENTS: any[] = [];

export function generateMockChapterText(_quote: string, _chapter: number): string {
  return "";
}

export function generateMockCharacterProfile(_name: string, _filterBook?: string): any {
  return null;
}
