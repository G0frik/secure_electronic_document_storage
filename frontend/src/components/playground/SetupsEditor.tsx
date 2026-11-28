import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Copy, Trash2 } from "@/components/icons";
import type { Catalog, Defense, Setup } from "@/api/playground";
import { defaultSetup, setupName } from "@/components/playground/setups";

const DEFENSES: Defense[] = ["D1", "D2", "D4", "D6"];

interface Props {
  catalog: Catalog;
  setups: Setup[];
  onChange: (setups: Setup[]) => void;
}

export default function SetupsEditor({ catalog, setups, onChange }: Props) {
  const [open, setOpen] = useState<number | null>(null);

  function update(i: number, patch: Partial<Setup>) {
    onChange(setups.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  }

  function toggleDefense(i: number, d: Defense) {
    const cur = setups[i]?.defenses ?? [];
    const on = !cur.includes(d);
    update(i, {
      defenses: on ? [...cur, d].sort() : cur.filter((x) => x !== d),
      ...(d === "D1" && on ? { prompt_text: null } : {}), // D1 runs the hardened prompt as is
    });
  }

  return (
    <div className="stack stack-2">
      {setups.map((s, i) => (
        <div key={i} className="pg-setup">
          <div className="pg-setup-main">
            <span className="pg-setup-index">{i + 1}</span>
            <select
              className="select"
              aria-label="Engine"
              value={s.engine}
              onChange={(e) => {
                const next = defaultSetup(catalog, e.target.value as "nli" | "llm");
                onChange(setups.map((x, j) => (j === i ? next : x)));
              }}
            >
              <option value="nli">NLI</option>
              <option value="llm">LLM</option>
            </select>
            <select
              className="select"
              aria-label="Model"
              value={s.model}
              onChange={(e) => update(i, { model: e.target.value })}
            >
              {s.engine === "nli"
                ? catalog.nli.map((m) => (
                    <option key={m.id} value={m.id} title={m.label}>
                      {m.id}
                    </option>
                  ))
                : catalog.llm.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.id}
                      {m.status === "loaded" ? " (loaded)" : ""}
                    </option>
                  ))}
            </select>
            <div className="pg-defenses" role="group" aria-label="Defenses">
              {DEFENSES.map((d) => {
                const off = d === "D1" && s.engine !== "llm";
                return (
                  <label key={d} className="pg-chip" title={catalog.defenses[d]} data-off={off}>
                    <input
                      type="checkbox"
                      disabled={off}
                      checked={(s.defenses ?? []).includes(d)}
                      onChange={() => toggleDefense(i, d)}
                    />
                    {d}
                  </label>
                );
              })}
              <label
                className="pg-chip"
                title="Presidio identifier scan, max with the semantic tier"
              >
                <input
                  type="checkbox"
                  checked={s.presidio !== false}
                  onChange={(e) => update(i, { presidio: e.target.checked })}
                />
                Presidio
              </label>
            </div>
            <div className="row row-2" style={{ marginLeft: "auto" }}>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                aria-expanded={open === i}
                onClick={() => setOpen(open === i ? null : i)}
              >
                {open === i ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Settings
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost btn-icon"
                title="Duplicate"
                aria-label={`Duplicate setup ${i + 1}`}
                onClick={() => {
                  setOpen(null);
                  onChange([...setups.slice(0, i + 1), { ...s }, ...setups.slice(i + 1)]);
                }}
              >
                <Copy size={14} />
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost btn-icon"
                title="Remove"
                aria-label={`Remove setup ${i + 1}`}
                disabled={setups.length === 1}
                onClick={() => {
                  setOpen(null);
                  onChange(setups.filter((_, j) => j !== i));
                }}
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
          {open === i && (
            <SetupSettings catalog={catalog} setup={s} onChange={(p) => update(i, p)} />
          )}
        </div>
      ))}
    </div>
  );
}

function SetupSettings({
  catalog,
  setup: s,
  onChange,
}: {
  catalog: Catalog;
  setup: Setup;
  onChange: (p: Partial<Setup>) => void;
}) {
  const d1 = !!s.defenses?.includes("D1");
  const prompt = d1 ? "classify_hardened_v1" : (s.prompt ?? "classify_v1");
  const promptText = (!d1 && s.prompt_text) || catalog.prompts[prompt] || "";
  return (
    <div className="pg-settings">
      <label className="field">
        <span className="field-label">Label (optional)</span>
        <input
          className="input"
          value={s.label ?? ""}
          placeholder={setupName({ ...s, label: "" })}
          onChange={(e) => onChange({ label: e.target.value })}
        />
      </label>
      {s.defenses?.includes("D4") && (
        <label className="field">
          <span className="field-label">Injection detector (D4)</span>
          <select
            className="select"
            value={s.detector ?? "pg2"}
            onChange={(e) => onChange({ detector: e.target.value as "pg2" | "protectai" })}
          >
            {catalog.detectors.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </label>
      )}
      {s.engine === "nli" ? (
        <p className="text-small text-muted" style={{ gridColumn: "1 / -1", margin: 0 }}>
          {catalog.nli.find((m) => m.id === s.model)?.label}. Runs on the host GPU like the research
          runs; thresholds and tier mapping as in the service.
        </p>
      ) : (
        <>
          <label className="field">
            <span className="field-label">Prompt</span>
            <select
              className="select"
              value={prompt}
              disabled={d1}
              onChange={(e) => onChange({ prompt: e.target.value, prompt_text: null })}
            >
              {Object.keys(catalog.prompts).map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
          </label>
          <NumberField
            label="Seed"
            value={s.seed ?? 42}
            step={1}
            onChange={(v) => onChange({ seed: v ?? 42 })}
          />
          <NumberField
            label="Temperature"
            value={s.temperature ?? 0}
            step={0.1}
            min={0}
            max={2}
            onChange={(v) => onChange({ temperature: v ?? 0 })}
          />
          <NumberField
            label="Top-p (empty = server default)"
            value={s.top_p ?? null}
            step={0.05}
            min={0.05}
            max={1}
            onChange={(v) => onChange({ top_p: v })}
          />
          <NumberField
            label="Max tokens"
            value={s.max_tokens ?? 256}
            step={64}
            min={16}
            max={4096}
            onChange={(v) => onChange({ max_tokens: v ?? 256 })}
          />
          <label className="pg-chip" style={{ alignSelf: "end" }}>
            <input
              type="checkbox"
              checked={!!s.thinking}
              onChange={(e) => onChange({ thinking: e.target.checked })}
            />
            Thinking (reasoning before the answer)
          </label>
          <label className="field" style={{ gridColumn: "1 / -1" }}>
            <span className="field-label">
              Prompt text{" "}
              {d1 ? "— locked: D1 uses the hardened prompt" : s.prompt_text ? "(edited)" : ""}
            </span>
            <textarea
              className="textarea pg-prompt"
              value={promptText}
              readOnly={d1}
              onChange={(e) => onChange({ prompt_text: e.target.value })}
            />
            {!d1 && s.prompt_text && (
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                style={{ alignSelf: "start" }}
                onClick={() => onChange({ prompt_text: null })}
              >
                Reset to {s.prompt}
              </button>
            )}
          </label>
        </>
      )}
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step,
  min,
  max,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  step: number;
  min?: number;
  max?: number;
}) {
  // keep the typed text while editing; the setup gets a number (or null when left empty)
  const [raw, setRaw] = useState(value == null ? "" : String(value));
  useEffect(() => {
    setRaw((cur) =>
      cur !== "" && Number(cur) === value ? cur : value == null ? "" : String(value),
    );
  }, [value]);
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <input
        className="input"
        type="number"
        step={step}
        min={min}
        max={max}
        value={raw}
        onChange={(e) => {
          setRaw(e.target.value);
          if (e.target.value !== "" && !Number.isNaN(Number(e.target.value))) {
            onChange(Number(e.target.value));
          }
        }}
        onBlur={() => {
          if (raw === "") onChange(null);
        }}
      />
    </label>
  );
}
