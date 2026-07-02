// Chapter 0 is always the prologue in this corpus (verified 1:1 against
// chapter_kind in the extraction metadata).
export function chapterLabel(n: number): string {
  return n === 0 ? "Prologue" : `Chapter ${n}`;
}
