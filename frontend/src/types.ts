// ── API data shapes (mirrors server/routers/*) ──────────────────────────────

export interface ChapterSummary {
  chapter: number;
  kind: string;
  pov: string | null;
  date: string | null;
  word_count: number;
  chunk_count: number;
}

export interface Book {
  id: number;
  name: string;
  chapter_count: number;
  chunk_count: number;
  word_count: number;
  povs: string[];
  stats: Record<string, number>;
  chapters: ChapterSummary[];
}

export interface Citation {
  chunk_id: string;
  book_number: number | null;
  book_title: string | null;
  chapter_number: number | null;
  pov_character: string | null;
  distance: number | null;
  preview: string;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  streaming?: boolean;
  cost_usd?: number;
}

export type QueryMode = "general" | "plot_hole" | "timeline" | "character" | "alternate";

export interface Relationship {
  name: string;
  shared_scenes: number;
  nature: string | null;
}

export interface CharacterSummary {
  id: string;
  name: string;
  aliases: string[];
  kind: "character" | "descriptor";
  books: number[];
  chunk_count: number;
  chapter_count: number;
  is_pov: boolean;
  pov_chunk_count: number;
  traits: string[];
  relationships: Relationship[];
}

export interface CharacterDetail extends CharacterSummary {
  arcs: Record<string, string>;
  knowledge_by_book: Record<string, { chapter: number; learns: string }[]>;
  appearances_by_book: Record<string, number[]>;
}

export interface QuarantinedName {
  name: string;
  chunk_count: number;
  reason: string;
}

export interface TimelineEvent {
  id: number;
  book_number: number;
  chapter_number: number;
  position: number;
  title: string;
  type: string;
  granularity: "major" | "moderate" | "minor";
  date: string | null;
  summary: string | null;
  location: string | null;
  participants: string[];
  knowledge_impact: { character: string; learns: string }[];
  source_chunk_ids: string[];
}

export interface OutlineChapter {
  id: string;
  book: number;
  chapter: number | null;
  position: number;
  status: "planned" | "synced";
  heading: string;
  pov: string;
  date: string | null;
  writer_summary: string;
  extracted_bullets: string[];
  notes: string | null;
}

export interface WriterCharacter {
  id: string;
  name: string;
  category: "main" | "secondary" | "tertiary" | null;
  role: string | null;
  aliases: string | null;
  traits: string[];
  arc_notes: string | null;
  goals: string | null;
  relationships: { target: string; nature: string }[];
  books: number[];
}

export interface ResyncDiff {
  id: string;
  chapter: number;
  field: string;
  outline_value: unknown;
  extracted_value: unknown;
}

export interface SettingsField {
  key: string;
  prompt: string;
  kind: string;
  value: string;
  secret: boolean;
}

export type ReviewFocus =
  | "Rough Draft"
  | "Continuity"
  | "Character Voice"
  | "Line Edit"
  | "Pacing";

export type Pane =
  | "plan"
  | "review"
  | "explore"
  | "timeline"
  | "books"
  | "characters"
  | "settings";
