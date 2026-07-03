import { useState, useEffect } from "react";
import { X, Plus, Trash2 } from "lucide-react";
import type { WriterCharacter, WriterCharacterRelationship } from "../../../types";
import { slugify } from "../../../api/plan";

interface CharacterEditModalProps {
  open: boolean;
  character: Partial<WriterCharacter> | null;
  onSave: (character: WriterCharacter) => void;
  onCancel: () => void;
}

export default function CharacterEditModal({ open, character, onSave, onCancel }: CharacterEditModalProps) {
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [traits, setTraits] = useState<string[]>([]);
  const [traitInput, setTraitInput] = useState("");
  const [goals, setGoals] = useState("");
  const [arcNotes, setArcNotes] = useState("");
  const [booksInput, setBooksInput] = useState("");
  const [relationships, setRelationships] = useState<WriterCharacterRelationship[]>([]);

  useEffect(() => {
    if (open && character) {
      setName(character.name ?? "");
      setRole(character.role ?? "");
      setTraits(character.traits ?? []);
      setGoals(character.goals ?? "");
      setArcNotes(character.arc_notes ?? "");
      setBooksInput((character.books ?? []).join(", "));
      setRelationships(character.relationships ?? []);
      setTraitInput("");
    }
  }, [open, character]);

  if (!open) return null;

  const isNew = !character?.id;

  const addTrait = () => {
    const t = traitInput.trim();
    if (t && !traits.includes(t)) {
      setTraits([...traits, t]);
    }
    setTraitInput("");
  };

  const removeTrait = (t: string) => setTraits(traits.filter((x) => x !== t));

  const addRelationship = () => {
    setRelationships([...relationships, { target: "", nature: "" }]);
  };

  const updateRelationship = (i: number, key: keyof WriterCharacterRelationship, value: string) => {
    setRelationships(relationships.map((r, idx) => idx === i ? { ...r, [key]: value } : r));
  };

  const removeRelationship = (i: number) => {
    setRelationships(relationships.filter((_, idx) => idx !== i));
  };

  const handleSave = () => {
    if (!name.trim()) return;
    const parsedBooks = booksInput.split(",").map((b) => b.trim()).filter(Boolean);
    onSave({
      id: character?.id ?? slugify(name.trim()),
      name: name.trim(),
      category: character?.category ?? null,
      role: role.trim() || null,
      traits,
      goals: goals.trim() || null,
      arc_notes: arcNotes.trim() || null,
      books: parsedBooks,
      relationships: relationships.filter((r) => r.target.trim()),
      photo_url: character?.photo_url ?? null,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="flex flex-col w-full max-w-lg max-h-[85vh] rounded-xl border border-surface-border bg-surface-card shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-surface-border px-5 py-4 flex-shrink-0">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-primary">
            {isNew ? "New Character" : "Edit Character"}
          </h2>
          <button onClick={onCancel} className="rounded p-1 text-ink-muted hover:text-ink-secondary transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Form */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-medium text-ink-muted mb-1">
                Name <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Character name"
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-ink-muted mb-1">Role</label>
              <input
                type="text"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                placeholder="e.g. Protagonist, antagonist…"
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none"
              />
            </div>
          </div>

          {/* Traits */}
          <div>
            <label className="block text-[11px] font-medium text-ink-muted mb-1">Traits</label>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {traits.map((t) => (
                <span key={t} className="flex items-center gap-1 rounded-full bg-accent/10 px-2 py-0.5 text-[11px] text-accent">
                  {t}
                  <button onClick={() => removeTrait(t)} className="text-accent/60 hover:text-accent">
                    <X className="h-2.5 w-2.5" />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={traitInput}
                onChange={(e) => setTraitInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTrait(); } }}
                placeholder="Add trait and press Enter"
                className="flex-1 rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none"
              />
              <button onClick={addTrait} className="rounded-md border border-surface-border px-3 py-2 text-xs text-ink-muted hover:text-ink-secondary transition-colors">
                Add
              </button>
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-medium text-ink-muted mb-1">Goals</label>
            <textarea
              value={goals}
              onChange={(e) => setGoals(e.target.value)}
              rows={2}
              placeholder="What does this character want? What drives them?"
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none resize-none"
            />
          </div>

          <div>
            <label className="block text-[11px] font-medium text-ink-muted mb-1">Arc Notes</label>
            <textarea
              value={arcNotes}
              onChange={(e) => setArcNotes(e.target.value)}
              rows={3}
              placeholder="How do you intend this character to grow or change throughout the series?"
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none resize-none leading-relaxed"
            />
          </div>

          {/* Relationships */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-[11px] font-medium text-ink-muted">Key Relationships</label>
              <button
                onClick={addRelationship}
                className="flex items-center gap-1 text-[11px] text-ink-muted hover:text-accent transition-colors"
              >
                <Plus className="h-3 w-3" />
                Add
              </button>
            </div>
            <div className="space-y-2">
              {relationships.map((r, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input
                    type="text"
                    value={r.target}
                    onChange={(e) => updateRelationship(i, "target", e.target.value)}
                    placeholder="Character name"
                    className="w-32 rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none"
                  />
                  <input
                    type="text"
                    value={r.nature}
                    onChange={(e) => updateRelationship(i, "nature", e.target.value)}
                    placeholder="Relationship nature"
                    className="flex-1 rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none"
                  />
                  <button
                    onClick={() => removeRelationship(i)}
                    className="text-ink-muted hover:text-red-400 transition-colors"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-medium text-ink-muted mb-1">
              Books (comma-separated)
            </label>
            <input
              type="text"
              value={booksInput}
              onChange={(e) => setBooksInput(e.target.value)}
              placeholder="Book titles, comma-separated"
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary placeholder-ink-muted/50 focus:border-accent focus:outline-none"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-surface-border px-5 py-3 flex-shrink-0">
          <button onClick={onCancel} className="rounded-md px-3 py-1.5 text-xs text-ink-muted hover:text-ink-secondary transition-colors">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!name.trim()}
            className="rounded-md bg-accent px-4 py-1.5 text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {isNew ? "Add Character" : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
