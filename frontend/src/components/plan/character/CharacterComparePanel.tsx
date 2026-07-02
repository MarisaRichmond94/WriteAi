import { useState, useEffect } from "react";
import { X, Loader2 } from "lucide-react";
import type { WriterCharacter } from "../../../types";
import { fetchExtractedCharacter } from "../../../api/plan";

interface CharacterComparePanelProps {
  character: WriterCharacter;
  onClose: () => void;
}

export default function CharacterComparePanel({ character, onClose }: CharacterComparePanelProps) {
  const [extractedData, setExtractedData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchExtractedCharacter(character.id)
      .then(setExtractedData)
      .catch(() => setExtractedData({}))
      .finally(() => setLoading(false));
  }, [character.id]);

  const hasExtracted = extractedData && Object.keys(extractedData).length > 0;

  return (
    <div className="flex flex-col h-full border-l border-surface-border bg-surface-card">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-surface-border px-4 py-3 flex-shrink-0">
        <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">
          Compare: {character.name}
        </p>
        <button
          onClick={onClose}
          className="rounded p-1 text-ink-muted hover:text-ink-secondary transition-colors"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {loading && (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-ink-muted" />
        </div>
      )}

      {!loading && (
        <div className="flex flex-1 overflow-hidden">
          {/* Left — writer's vision */}
          <div className="flex-1 overflow-y-auto border-r border-surface-border px-4 py-4 space-y-4">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-accent mb-3">Your Vision</p>

            <Section label="Role">{character.role || <Empty />}</Section>
            <Section label="Traits">
              {character.traits.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {character.traits.map((t) => (
                    <span key={t} className="rounded-full bg-accent/10 px-2 py-0.5 text-[10px] text-accent">
                      {t}
                    </span>
                  ))}
                </div>
              ) : <Empty />}
            </Section>
            <Section label="Goals">{character.goals || <Empty />}</Section>
            <Section label="Arc Notes">{character.arc_notes || <Empty />}</Section>
            <Section label="Relationships">
              {character.relationships.length > 0 ? (
                <ul className="space-y-1">
                  {character.relationships.map((r, i) => (
                    <li key={i} className="text-[11px] text-ink-secondary">
                      <span className="font-medium">{r.target}</span>
                      <span className="text-ink-muted"> — {r.nature}</span>
                    </li>
                  ))}
                </ul>
              ) : <Empty />}
            </Section>
          </div>

          {/* Right — AI extracted */}
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-emerald-400 mb-3">What the Books Show</p>

            {!hasExtracted && (
              <p className="text-[11px] text-ink-muted">
                No extracted data yet — run the pipeline to compare.
              </p>
            )}

            {hasExtracted && (() => {
              const d = extractedData as Record<string, unknown>;
              const aliases = d.aliases as string[] | undefined;
              const role = d.role as string | undefined;
              const traits = d.traits as string[] | undefined;
              const relationships = d.relationships as { target: string; status: string; gendered_status?: string | null; inferred?: boolean }[] | undefined;
              const knowledge = d.knowledge_gained as string | undefined;
              const activeConflicts = d.active_conflicts as string[] | undefined;

              return (
                <>
                  {aliases && aliases.length > 0 && (
                    <Section label="Also Known As">
                      <p className="text-[11px] text-ink-secondary">{aliases.join(", ")}</p>
                    </Section>
                  )}
                  <Section label="Role">{role || <Empty />}</Section>
                  <Section label="Traits">
                    {traits && traits.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {traits.map((t) => (
                          <span key={t} className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-400">
                            {t}
                          </span>
                        ))}
                      </div>
                    ) : <Empty />}
                  </Section>
                  <Section label="Knowledge Gained">{knowledge || <Empty />}</Section>
                  <Section label="Relationships">
                    {relationships && relationships.length > 0 ? (
                      <ul className="space-y-1">
                        {[...relationships].sort((a, b) => (a.inferred ? 1 : 0) - (b.inferred ? 1 : 0)).slice(0, 8).map((r, i) => (
                          <li key={i} className={r.inferred ? "text-[11px] text-ink-secondary/50" : "text-[11px] text-ink-secondary"}>
                            <span className="font-medium">{r.target}</span>
                            <span className={r.inferred ? "text-ink-muted/50" : "text-ink-muted"}> — {r.inferred ? "~ " : ""}{r.gendered_status || r.status}</span>
                          </li>
                        ))}
                      </ul>
                    ) : <Empty />}
                  </Section>
                  <Section label="Active Conflicts">
                    {activeConflicts && activeConflicts.length > 0 ? (
                      <ul className="space-y-1">
                        {activeConflicts.map((c, i) => (
                          <li key={i} className="text-[11px] text-ink-muted">• {c}</li>
                        ))}
                      </ul>
                    ) : <Empty />}
                  </Section>
                </>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] font-medium uppercase tracking-wide text-ink-muted mb-1">{label}</p>
      <div className="text-[11px] text-ink-secondary leading-relaxed">{children}</div>
    </div>
  );
}

function Empty() {
  return <span className="text-ink-muted/50 italic">Not specified</span>;
}
