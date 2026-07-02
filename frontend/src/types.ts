export type QueryMode = "plot_hole" | "timeline" | "character" | "alternate";

export interface Citation {
  book: string;
  chapter: number;
  chapter_heading: string;
  pov: string;
  date?: string | null;
  chunk_index: number;
  snippet: string;
  distance: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  mode?: QueryMode;
  citations?: Citation[];
  timestamp: Date;
  isStreaming?: boolean;
}

export interface ChapterSummary {
  chapter: number;
  chapter_heading: string;
  pov: string;
  date?: string | null;
  filename: string;
}

export interface BookResponse {
  id: string;
  name: string;
  chapter_count: number;
  chapters: ChapterSummary[];
  povs: string[];
}

export interface IndexStatus {
  total_chunks: number;
  books_indexed: string[];
  last_built?: string | null;
  book_last_indexed: Record<string, string | null>;
  collection_name: string;
  is_ready: boolean;
}

export interface ChatSession {
  id: string;
  question: string;
  messages: Message[];
  timestamp: Date;
  mode?: QueryMode;
  selectedBooks?: string[];
  selectedPovs?: string[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface CharacterRelationship {
  target: string;
  character_id: string;
  status: string;
  gendered_status?: string | null;
  inferred?: boolean;
  appearance_count?: number;
  photo_url?: string | null;
}

export interface AliasWithProvenance {
  alias: string;
  book: string | null;
  chapter: number | null;
  context: string | null;
  count?: number;
}

export interface CharacterSummary {
  id: string;
  name: string;
  aliases: AliasWithProvenance[];
  traits: string[];
  relationships: CharacterRelationship[];
  books: string[];
  is_pov: boolean;
  pov_chapter_count: number;
  photo_url: string | null;
  hidden?: boolean;
  gender?: string | null;
}

export type CharacterCorrections = {
  name_overrides: Record<string, string>;
  alias_removals: Record<string, string[]>;
  alias_additions: Record<string, AliasWithProvenance[]>;
  relationship_overrides: Record<string, Record<string, { status: string }>>;
  relationship_removals: Record<string, string[]>;
  relationship_additions: Record<string, Record<string, { status: string }>>;
  merges: Array<{ from: string; into: string; as_alias?: string }>;
  hidden_characters: string[];
  gender_overrides: Record<string, string>;
};

export interface ArcEntry {
  chapter: number;
  insight: string;
  source_quote: string | null;
}

export interface CharacterDetail extends CharacterSummary {
  arc: Record<string, ArcEntry[] | null>;
}

export interface KnowledgeItem {
  text: string;
  first_revealed_chapter: number | null;
  source_quote: string | null;
}

export interface CharacterBookDetail {
  id: string;
  name: string;
  traits: string[];
  relationships: CharacterRelationship[];
  knowledge: KnowledgeItem[];
  does_not_know: KnowledgeItem[];
  active_conflicts: KnowledgeItem[];
  chapter_appearances: number[];
  photo_url: string | null;
}

export interface DateSpan {
  first: string | null;
  last: string | null;
}

export interface PovBreakdown {
  pov: string;
  chapter_count: number;
}

export interface BookSummary {
  date_span: DateSpan;
  pov_breakdown: PovBreakdown[];
  character_count: number;
  location_count: number;
  event_count: number;
  fact_count: number;
}

export interface BookBreakdown {
  book: string;
  chapter_count: number;
  event_count: number;
}

export interface SeriesSummary extends BookSummary {
  book_breakdown: BookBreakdown[];
}

export interface ExtractedKnowledgeItem {
  insight: string;
  source_quote: string | null;
}

export interface ExtractedCharacter {
  name: string;
  aliases: string[] | null;
  role: string;
  knowledge_gained: ExtractedKnowledgeItem[] | null;
}

export interface ExtractedSourceQuote {
  quote: string;
  book: string | null;
  chapter: number | null;
}

export interface ExtractedEvent {
  title: string;
  type: string;
  participants: string[];
  location: string;
  summary: string;
  source_quotes: ExtractedSourceQuote[] | null;
}

export interface ExtractedFact {
  statement: string;
  characters: string[];
  category: string;
  source_quote: string | null;
}

export interface ExtractedLocation {
  name: string;
  type: string;
}

export interface AppSettings {
  site_name: string;
  source_books_dir: string;
  books_dir: string;
  data_dir: string;
  backup_retention_days: number;
  sync_time: string;
  auto_sync_enabled: boolean;
  book_order: string[];
  query_model: string;
  extraction_model: string;
  odv_model: string;
  discovered_books: string[];
  anthropic_api_key_preview: string;
  openai_api_key_preview: string;
  writer_name: string;
  writer_photo_url: string | null;
  viewer_light_mode: boolean;
}

export type NotificationType =
  | "extraction_ready"
  | "extraction_complete"
  | "sync_complete"
  | "error";

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  body: string;
  book: string | null;
  created_at: string;
  read: boolean;
  action_url: string | null;
}

export interface IngestChapter {
  index: number;
  heading: string;
  pov: string;
  pov_ai_suggested: boolean;
  date: string;
  date_ai_suggested: boolean;
  confirmed: boolean;
  text_preview: string;
  start_char: number;
  end_char: number;
}

export interface IngestManifest {
  source_file: string;
  source_hash: string;
  split_confirmed: boolean;
  chapters: IngestChapter[];
}

export type EventGranularity = "major" | "moderate" | "minor";

export type EventType =
  | "discovery"
  | "confrontation"
  | "revelation"
  | "death"
  | "betrayal"
  | "reconciliation"
  | "other";

export interface EventSourceQuote {
  book: string;
  chapter: number;
  quote: string;
}

export interface EventKnowledgeImpact {
  character: string;
  learns: string;
}

export interface TimelineEvent {
  id: string;
  title: string;
  book: string;
  chapter: number;
  date: string | null;
  participants: string[];
  location: string | null;
  type: EventType;
  summary: string;
  granularity: EventGranularity;
  source_quotes: EventSourceQuote[];
  knowledge_impact: EventKnowledgeImpact[];
  cross_book_setup: string | null;
  cross_book_payoff: string | null;
  internal_year: number | null;
  date_source: "extracted" | "user" | null;
}

export type ReviewFocus = "Literary Agent" | "Casual Reader" | "Hard-Core Reader" | "Philosopher" | "What-If Explorer";

export interface ReviewMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  focus?: ReviewFocus;
  citations?: Citation[];
  timestamp: Date;
  isStreaming?: boolean;
}

export interface ReviewSession {
  id: string;
  label: string;
  book: string;
  chapter: number | "new";
  focus: ReviewFocus;
  messages: ReviewMessage[];
  timestamp: Date;
}

export type PhaseStatus = "idle" | "running" | "success" | "failed" | "skipped";

export interface PhaseInfo {
  status: PhaseStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  error: string | null;
  tokens_used: number | null;
  cost_usd: number | null;
}

export interface PipelineState {
  running: boolean;
  current_phase: string | null;
  phases: Record<string, PhaseInfo>;
  started_at: string | null;
  finished_at: string | null;
  backup_timestamp: string | null;
  paused_for_review: boolean;
  review_item_count: number;
}

export interface BookExtractionStatus {
  book: string;
  version: number | null;
  extracted_at: string | null;
  is_complete: boolean;
  is_stale: boolean;
  stale_because: string | null;
}

export interface ReviewItem {
  a: string;
  b: string;
  a_to_b: string;
  b_to_a: string;
  established_book: string;
  established_chapter: number;
  confidence: string;
  evidence: string;
  needs_review: boolean;
  review_data: {
    type: string;
    character: string;
    target: string;
    old_status: string;
    new_status: string;
    established_book: string;
    established_chapter: number;
    book: string;
    chapter: number;
  } | null;
}

export interface BackupInfo {
  timestamp: string;
  created_at: string;
  phases: string[];
  total_files: number;
  size_bytes: number;
  size_human: string;
}

export interface PipelineCostEstimate {
  phases: Record<string, {
    input_tokens_est: number;
    output_tokens_est: number;
    cost_usd_est: number;
  }>;
  total_cost_usd_est: number;
}

export interface ExtractedChapter {
  chapter: number;
  pov: string;
  date: string | null;
  summary: string[];
  characters: ExtractedCharacter[];
  events: ExtractedEvent[];
  facts: ExtractedFact[];
  locations: ExtractedLocation[];
}

// ── Plan page ─────────────────────────────────────────────────────────────────

export type PlanView = "outline" | "character";

export type OutlineChapterStatus = "planned" | "synced";

export interface OutlineChapter {
  id: string;
  book: string;
  chapter: number | null;
  position: number;
  status: OutlineChapterStatus;
  heading: string;
  pov: string;
  date: string | null;
  writer_summary: string;
  extracted_bullets: string[];
  notes: string | null;
}

export interface OutlineBook {
  book: string;
  chapters: OutlineChapter[];
}

export interface ChapterNumberAssignment {
  outline_id: string;
  outline_heading: string;
  old_chapter: number | null;
  new_chapter: number;
  is_renumbered: boolean;
}

export interface ChapterFieldDiff {
  field: "pov" | "date" | "extracted_bullets" | "heading";
  old: string | null;
  new: string | null;
}

export interface OutlineChapterDiff {
  chapter_id: string;
  chapter: number;
  heading: string;
  diffs: ChapterFieldDiff[];
}

export interface ResyncPreviewResponse {
  book: string;
  status: "ready" | "partial" | "conflict";
  conflict_reason: string | null;
  numbering: ChapterNumberAssignment[];
  field_diffs: OutlineChapterDiff[];
  unmatched_outline_count: number;
}

export interface WriterCharacterRelationship {
  target: string;
  nature: string;
}

export type CharacterCategory = "main" | "secondary" | "tertiary";

export interface WriterCharacter {
  id: string;
  name: string;
  category: CharacterCategory | null;
  role: string | null;
  aliases?: string | null;
  traits: string[];
  arc_notes: string | null;
  goals: string | null;
  relationships: WriterCharacterRelationship[];
  books: string[];
  photo_url: string | null;
}

// ── Character event sourcing ──────────────────────────────────────────────────

export interface CharacterEvent {
  type: string;
  subtype?: string;
  value?: string;
  attribute?: string;
  target?: string;
  status?: string;
  confidence?: 'tentative' | 'confirmed';
  resolved?: boolean;
  departed?: boolean;
  needs_review?: boolean;
  reader_time: { chapter: number; line_start: number; line_end: number };
  story_time: { chapter: number | null; era: string | null };
  source_text: string;
}

export interface CharacterState {
  canonical_name: string;
  known_as: string;
  status: string;
  location: string | null;
  physical_stable: string[];
  physical_dynamic: string[];
  personality_traits: string[];
  relationships: Record<string, string>;
  knowledge: string[];
  does_not_know: string[];
  role: string | null;
  actions: string[];
}

// ── Offline Data Verification (ODV) ───────────────────────────────────────

export interface OdvQueueEntry {
  book: string;
  chapter: number;
  status: "pending" | "running" | "done" | "failed";
  added_at: string;
  alias_count: number;
  completed_at: string | null;
  dropped_count: number | null;
  error: string | null;
  task_type: "alias_verification" | "gender_inference" | "relationship_verification" | "name_merge" | "relationship_resolution";
  character: string | null;
}

export interface OdvQueueStatus {
  pending: OdvQueueEntry[];
  running: OdvQueueEntry | null;
  done: OdvQueueEntry[];
  failed: OdvQueueEntry[];
}

// ── ODV Lab ───────────────────────────────────────────────────────────────

export interface OdvLabRun {
  run_id: string;
  books: Record<string, number[]>;
}

export interface OdvLabTestMeta {
  test_id: string;
  run_id: string;
  book: string;
  scope: "chapter" | "book";
  chapters: number[];
  task_types: string[];
  status: "pending" | "running" | "done" | "failed";
  created_at: string;
  finished_at?: string | null;
  error?: string | null;
  parent_test_id?: string | null;
  variant_version_id?: string | null;
}

export interface OdvLabTestResult extends OdvLabTestMeta {
  verifications: OdvVerificationEntry[];
}

export type OdvGroundTruthExpected = Record<string, string>;

export interface OdvGroundTruthEntry {
  task_type: string;
  book: string;
  chapter?: number | null;
  alias?: string;
  attributed_to?: string;
  character?: string;
  target?: string;
  partial_name?: string;
  descriptor?: string;
  expected: OdvGroundTruthExpected;
}

export interface OdvComparisonResult {
  entry: OdvVerificationEntry;
  ground_truth: OdvGroundTruthExpected | null;
  is_correct: boolean | null;
  wrong_fields: string[];
}

export interface OdvPromptVersion {
  version_id: string;
  saved_at: string;
  source: "original" | "variant" | "archived" | "manual";
  label: string;
  accuracy: number | null;
  test_id: string | null;
  is_active: boolean;
}

export interface OdvPromptVariant {
  version_id: string | null;
  label: "A" | "B" | "C";
  prompt: string;
  what_it_addresses: string;
  accuracy: number | null;
}

export interface OdvImproveResult {
  what_went_wrong: string[];
  variants: OdvPromptVariant[];
}

export interface OdvVariantRunResult {
  test_id: string;
  version_id: string;
  accuracy: number | null;
  comparison: OdvComparisonResult[];
}

export interface OdvCompareResult {
  test_id: string;
  accuracy: number | null;
  comparison: OdvComparisonResult[];
}

export interface OdvVerificationEntry {
  task_type: "alias_verification" | "gender_inference" | "relationship_verification" | "name_merge" | "relationship_resolution";
  book: string;
  chapter: number;
  // alias_verification fields
  alias?: string;
  attributed_to?: string;
  resolved_to?: string | string[];
  outcome?: "confirmed" | "reassigned" | "dropped" | "corrected" | "merged" | "rejected" | "resolved" | "unresolved";
  context?: string;
  // gender_inference fields
  character?: string;
  gender?: string;
  snippet_count?: number;
  // relationship_verification fields
  target?: string;
  original_status?: string;
  resolved_status?: string;
  raw_response?: string;
  // name_merge fields
  partial_name?: string;
  prompt_sent?: string;
  reasoning?: string;
  sub_type?: string;
  // relationship_resolution fields
  descriptor?: string;
  verified_at: string;
}

// ── Quality Review ────────────────────────────────────────────────────────────

export interface CharacterFlag {
  name: string;
  books: string[];
  aliases: string[];
  is_full_name: boolean;
}

export interface SharedAliasFlag {
  alias: string;
  characters: { name: string; books: string[] }[];
}

export interface OrphanedAliasFlag {
  alias: string;
  book: string;
  count: number;
}

export interface RelationshipFlag {
  char_a: string;
  char_b: string;
  status_a_to_b: string;
  status_b_to_a: string | null;
  expected_b_to_a: string;
}

export interface DataQualityFlags {
  unnamed_flags: CharacterFlag[];
  shared_first_name_flags: CharacterFlag[][];
  shared_alias_flags: SharedAliasFlag[];
  orphaned_alias_flags: OrphanedAliasFlag[];
  relationship_flags: RelationshipFlag[];
}
