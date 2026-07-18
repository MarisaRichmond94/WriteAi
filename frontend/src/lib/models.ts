// Single source of truth for the Claude models the UI exposes in its model
// dropdowns. Previously this list was copy-pasted across ChatInput, ReviewPane,
// CharacterReviewPanel, and SettingsPane; edit it here only.
//
// Keep these IDs in sync with PRICING_PER_MTOK in src/extractor.py — the backend
// imposes no model allowlist (it passes whatever ID it's given straight to the
// Anthropic SDK), but an ID missing from the pricing table silently logs cost at
// the default $3/$15 fallback rate.

export interface ModelOption {
  id: string;
  label: string;
}

export const CHAT_MODELS: ModelOption[] = [
  { id: "claude-opus-4-8", label: "Opus 4.8" },
  { id: "claude-sonnet-5", label: "Sonnet 5" },
  { id: "claude-haiku-4-5", label: "Haiku 4.5" },
];

export const MODEL_IDS = CHAT_MODELS.map((m) => m.id);

export const DEFAULT_QUERY_MODEL = "claude-sonnet-5";
export const DEFAULT_EXTRACTION_MODEL = "claude-haiku-4-5";

export function modelLabel(id: string): string {
  return CHAT_MODELS.find((m) => m.id === id)?.label ?? id;
}

// Coerce a stored/config model ID to one the dropdowns actually offer, so a
// previously-saved model that's no longer listed falls back to the default
// instead of rendering as a raw ID (or being sent through as a stale model).
export function resolveModel(stored?: string | null): string {
  return stored && MODEL_IDS.includes(stored) ? stored : DEFAULT_QUERY_MODEL;
}
