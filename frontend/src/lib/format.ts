// Chapter 0 is always the prologue in this corpus (verified 1:1 against
// chapter_kind in the extraction metadata).
export function chapterLabel(n: number): string {
  return n === 0 ? "Prologue" : `Chapter ${n}`;
}

// Writer event times are stored as 24h "HH:MM" (native <input type="time">
// value); display them 12h with AM/PM instead of asking writers to convert.
export function formatTime12h(time: string): string {
  const [h, m] = time.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const hour12 = h % 12 || 12;
  return `${hour12}:${String(m).padStart(2, "0")} ${period}`;
}
