import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { CheckCircle2, Settings as SettingsIcon, XCircle } from "lucide-react";
import { useApp } from "../../store";
import type { SettingsField } from "../../types";
import { api } from "../../lib/api";
import { Spinner } from "../ui";
import { PaneHeader } from "../shared";

interface SettingsData {
  fields: SettingsField[];
  profile: { writer_name: string; site_name: string };
  store_counts: Record<string, number>;
}

const TABS = ["General", "Profile", "API Keys", "Sync", "Books", "AI Models"] as const;
type Tab = (typeof TABS)[number];

// which .env keys appear on which tab
const TAB_KEYS: Record<Tab, string[]> = {
  General: ["BOOKS_DIR", "TEXT_EXPORT_DIR", "DATA_DIR", "LOG_LEVEL"],
  Profile: [],
  "API Keys": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"],
  Sync: ["MAX_CHUNK_TOKENS", "TOP_K_RESULTS", "CONFIRM_BEFORE_INGEST"],
  Books: ["SERIES_NAME", "BOOK_PREFIX_PATTERN"],
  "AI Models": ["QUERY_MODEL", "EXTRACTION_MODEL", "EMBEDDING_PROVIDER", "EMBEDDING_MODEL"],
};

export function SettingsPane() {
  const { toast, loadProfile } = useApp();
  const [data, setData] = useState<SettingsData | null>(null);
  const [tab, setTab] = useState<Tab>("General");
  const [changes, setChanges] = useState<Record<string, string>>({});
  const [profile, setProfile] = useState({ writer_name: "", site_name: "" });
  const [profileDirty, setProfileDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validation, setValidation] = useState<{ ok: boolean; problems: string[]; books: string[] } | null>(null);
  const [validating, setValidating] = useState(false);

  const load = () =>
    api<SettingsData>("/api/settings")
      .then((d) => {
        setData(d);
        setProfile(d.profile);
        setChanges({});
        setProfileDirty(false);
      })
      .catch((e) => toast(String(e), "error"));

  useEffect(() => {
    load();
  }, []);

  const fields = useMemo(() => {
    if (!data) return [];
    const wanted = TAB_KEYS[tab];
    return wanted
      .map((k) => data.fields.find((f) => f.key === k))
      .filter((f): f is SettingsField => Boolean(f));
  }, [data, tab]);

  const dirty = Object.keys(changes).length > 0 || profileDirty;

  const save = async () => {
    setSaving(true);
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ values: changes, profile: profileDirty ? profile : null }),
      });
      toast("Settings saved", "success");
      loadProfile();
      load();
    } catch (e) {
      toast(String(e), "error");
    } finally {
      setSaving(false);
    }
  };

  const validate = async () => {
    setValidating(true);
    try {
      setValidation(await api("/api/settings/validate", { method: "POST" }));
    } catch (e) {
      toast(String(e), "error");
    } finally {
      setValidating(false);
    }
  };

  if (!data) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="h-5 w-5" />
      </div>
    );
  }

  const inputCls =
    "w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-ink-primary outline-none transition-colors focus:border-accent";

  return (
    <div className="flex h-full flex-col">
      <PaneHeader icon={SettingsIcon} title="Settings" subtitle="Configure your installation" />

      {/* tabs */}
      <div className="flex flex-shrink-0 items-center gap-1.5 px-6 pb-4">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              "rounded-full px-3 py-1 text-[11px] font-medium transition-colors",
              tab === t ? "bg-accent text-white" : "text-ink-secondary hover:bg-surface-hover hover:text-ink-primary",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {/* content */}
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-4">
        <p className="mb-4 text-[10px] font-bold uppercase tracking-widest text-ink-primary">{tab}</p>
        <div className="flex max-w-3xl flex-col gap-5">
          {tab === "General" && (
            <Field label="Site name" description="The title of the app, used throughout the interface">
              <input
                value={profile.site_name}
                onChange={(e) => {
                  setProfile({ ...profile, site_name: e.target.value });
                  setProfileDirty(true);
                }}
                className={inputCls}
              />
            </Field>
          )}
          {tab === "Profile" && (
            <Field label="Writer name" description="Used for the greeting and your avatar initials">
              <input
                value={profile.writer_name}
                onChange={(e) => {
                  setProfile({ ...profile, writer_name: e.target.value });
                  setProfileDirty(true);
                }}
                className={inputCls}
              />
            </Field>
          )}

          {fields.map((f) => (
            <Field key={f.key} label={f.key.replace(/_/g, " ").toLowerCase()} description={f.prompt}>
              {f.kind === "bool" ? (
                <select
                  value={changes[f.key] ?? f.value}
                  onChange={(e) => setChanges({ ...changes, [f.key]: e.target.value })}
                  className={inputCls}
                >
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              ) : f.kind.startsWith("choice:") ? (
                <select
                  value={changes[f.key] ?? f.value}
                  onChange={(e) => setChanges({ ...changes, [f.key]: e.target.value })}
                  className={inputCls}
                >
                  {f.kind
                    .split(":")[1]
                    .split(",")
                    .map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                </select>
              ) : (
                <input
                  value={changes[f.key] ?? f.value}
                  onChange={(e) => setChanges({ ...changes, [f.key]: e.target.value })}
                  placeholder={f.secret ? "(unchanged)" : ""}
                  className={clsx(inputCls, f.secret && "font-mono")}
                />
              )}
            </Field>
          ))}

          {tab === "API Keys" && (
            <p className="text-[10px] text-ink-muted">
              Keys show masked previews — type a full new value to replace one. Keys are tested with a free
              API call when you validate.
            </p>
          )}

          {tab === "Sync" && (
            <div className="rounded-md border border-surface-border bg-surface-card px-4 py-3 text-[11px] leading-relaxed text-ink-secondary">
              Nightly sync runs via cron: <code className="text-accent">ingest.py --yes</code> re-processes
              only chapters that changed. See the README for the crontab line.
            </div>
          )}

          {tab === "Books" && (
            <div>
              <button
                onClick={validate}
                disabled={validating}
                className="flex items-center gap-2 rounded border border-surface-border px-4 py-1.5 text-[11px] text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary disabled:opacity-40"
              >
                {validating && <Spinner className="h-3 w-3" />} Validate configuration
              </button>
              {validation && (
                <div
                  className={clsx(
                    "mt-3 rounded-lg border px-4 py-3 text-xs",
                    validation.ok ? "border-emerald-400/30 bg-emerald-400/10" : "border-rose-400/30 bg-rose-400/10",
                  )}
                >
                  {validation.ok ? (
                    <div className="flex items-start gap-2 text-emerald-300">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" strokeWidth={1.5} />
                      <span>
                        All checks passed — found {validation.books.length} books:{" "}
                        {validation.books.join(", ")}
                      </span>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-1 text-rose-300">
                      {validation.problems.map((p, i) => (
                        <div key={i} className="flex items-center gap-2">
                          <XCircle className="h-3.5 w-3.5 shrink-0" strokeWidth={1.5} /> {p}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {tab === "General" && (
            <div className="flex flex-wrap gap-4 rounded-lg border border-surface-border bg-surface-card px-4 py-3 text-[11px] text-ink-secondary">
              {Object.entries(data.store_counts).map(([k, v]) => (
                <span key={k}>
                  <span className="font-medium text-ink-primary">{v.toLocaleString()}</span> {k.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* footer */}
      <div className="flex flex-shrink-0 items-center justify-end gap-2 border-t border-surface-border px-6 py-3">
        <button
          onClick={load}
          disabled={!dirty || saving}
          className="rounded-md px-4 py-1.5 text-xs text-ink-secondary transition-colors hover:text-ink-primary disabled:opacity-40"
        >
          Reset
        </button>
        <button
          onClick={save}
          disabled={!dirty || saving}
          className="flex items-center gap-1.5 rounded-md bg-accent px-4 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-40"
        >
          {saving && <Spinner className="h-3 w-3" />} Save Settings
        </button>
      </div>
    </div>
  );
}

function Field({ label, description, children }: { label: string; description: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] font-bold uppercase tracking-wider text-ink-primary">{label}</p>
      <p className="mb-1.5 mt-0.5 text-[10px] text-ink-muted">{description}</p>
      {children}
    </div>
  );
}
