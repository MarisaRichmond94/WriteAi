import { useEffect, useState } from "react";
import clsx from "clsx";
import { CheckCircle2, ShieldCheck, XCircle } from "lucide-react";
import { useApp } from "../../store";
import type { SettingsField } from "../../types";
import { api } from "../../lib/api";
import { Button, SectionLabel, Spinner } from "../ui";

interface SettingsData {
  fields: SettingsField[];
  profile: { writer_name: string; site_name: string };
  store_counts: Record<string, number>;
}

export function SettingsPane() {
  const { toast, loadProfile } = useApp();
  const [data, setData] = useState<SettingsData | null>(null);
  const [changes, setChanges] = useState<Record<string, string>>({});
  const [profile, setProfile] = useState({ writer_name: "", site_name: "" });
  const [saving, setSaving] = useState(false);
  const [validation, setValidation] = useState<{ ok: boolean; problems: string[]; books: string[] } | null>(null);
  const [validating, setValidating] = useState(false);

  useEffect(() => {
    api<SettingsData>("/api/settings")
      .then((d) => {
        setData(d);
        setProfile(d.profile);
      })
      .catch((e) => toast(String(e), "error"));
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ values: changes, profile }),
      });
      toast("Settings saved", "success");
      setChanges({});
      loadProfile();
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

  const field = "w-full rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-xs text-ink-primary outline-none focus:border-accent";

  return (
    <div className="h-full overflow-y-auto px-8 py-6">
      <div className="mx-auto flex max-w-3xl flex-col gap-8">
        {/* profile */}
        <section>
          <SectionLabel>Writer profile</SectionLabel>
          <div className="grid grid-cols-2 gap-3 rounded-lg border border-surface-border bg-surface-card p-4">
            <div>
              <div className="mb-1 text-[11px] text-ink-secondary">Your name</div>
              <input
                value={profile.writer_name}
                onChange={(e) => setProfile({ ...profile, writer_name: e.target.value })}
                className={field}
              />
            </div>
            <div>
              <div className="mb-1 text-[11px] text-ink-secondary">Site name</div>
              <input
                value={profile.site_name}
                onChange={(e) => setProfile({ ...profile, site_name: e.target.value })}
                className={field}
              />
            </div>
          </div>
        </section>

        {/* env settings */}
        <section>
          <SectionLabel>System configuration (.env)</SectionLabel>
          <div className="flex flex-col gap-3 rounded-lg border border-surface-border bg-surface-card p-4">
            {data.fields.map((f) => (
              <div key={f.key} className="grid grid-cols-[220px_1fr] items-center gap-3">
                <div>
                  <div className="font-mono text-[11px] text-ink-primary">{f.key}</div>
                  <div className="text-[10px] leading-tight text-ink-muted">{f.prompt}</div>
                </div>
                {f.kind === "bool" ? (
                  <select
                    value={changes[f.key] ?? f.value}
                    onChange={(e) => setChanges({ ...changes, [f.key]: e.target.value })}
                    className={field}
                  >
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : f.kind.startsWith("choice:") ? (
                  <select
                    value={changes[f.key] ?? f.value}
                    onChange={(e) => setChanges({ ...changes, [f.key]: e.target.value })}
                    className={field}
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
                    className={clsx(field, f.secret && "font-mono")}
                  />
                )}
              </div>
            ))}
            <p className="text-[10px] text-ink-muted">
              Secrets show masked previews — type a full new value to replace one. Values are validated the
              same way as <code>settings.py</code>.
            </p>
          </div>
        </section>

        {/* store stats */}
        <section>
          <SectionLabel>Store</SectionLabel>
          <div className="flex flex-wrap gap-4 rounded-lg border border-surface-border bg-surface-card px-4 py-3 text-[11px] text-ink-secondary">
            {Object.entries(data.store_counts).map(([k, v]) => (
              <span key={k}>
                <span className="font-medium text-ink-primary">{v.toLocaleString()}</span> {k.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        </section>

        {/* validation */}
        {validation && (
          <section
            className={clsx(
              "rounded-lg border px-4 py-3 text-xs",
              validation.ok ? "border-emerald-400/30 bg-emerald-400/10" : "border-rose-400/30 bg-rose-400/10",
            )}
          >
            {validation.ok ? (
              <div className="flex items-center gap-2 text-emerald-300">
                <CheckCircle2 className="h-4 w-4" strokeWidth={1.5} />
                All checks passed — found {validation.books.length} books: {validation.books.join(", ")}
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
          </section>
        )}

        <div className="flex gap-2">
          <Button onClick={save} disabled={saving || (Object.keys(changes).length === 0 && !profile)}>
            {saving && <Spinner className="h-3.5 w-3.5" />} Save changes
          </Button>
          <Button variant="secondary" onClick={validate} disabled={validating}>
            {validating ? <Spinner className="h-3.5 w-3.5" /> : <ShieldCheck className="h-3.5 w-3.5" strokeWidth={1.5} />}
            Validate configuration
          </Button>
        </div>
      </div>
    </div>
  );
}
