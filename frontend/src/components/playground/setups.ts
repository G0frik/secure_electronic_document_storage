import type { Catalog, Setup } from "@/api/playground";

export function defaultSetup(catalog: Catalog, engine: "nli" | "llm", model?: string): Setup {
  const d = catalog.defaults;
  if (engine === "nli") {
    return { engine, model: model ?? "nli_en", presidio: d.presidio, defenses: [] };
  }
  const llm =
    model ?? catalog.llm.find((m) => m.id === "gemma4-12b")?.id ?? catalog.llm[0]?.id ?? "";
  return {
    engine,
    model: llm,
    prompt: d.prompt,
    prompt_text: null,
    seed: d.seed,
    temperature: d.temperature,
    top_p: d.top_p,
    max_tokens: d.max_tokens,
    thinking: d.thinking,
    presidio: d.presidio,
    defenses: [],
    detector: "pg2",
  };
}

/** Short name for a setup: model + defenses + changed settings. */
export function setupName(s: Setup): string {
  if (s.label) return s.label;
  const parts = [s.model];
  if (s.engine === "llm") {
    if (s.prompt && s.prompt !== "classify_v1") parts.push(s.prompt.replace("classify_", ""));
    if (s.prompt_text) parts.push("edited prompt");
    if (s.temperature) parts.push(`t=${s.temperature}`);
    if (s.thinking) parts.push("thinking");
  }
  if (s.defenses?.length) parts.push(s.defenses.join("+"));
  if (s.presidio === false) parts.push("no Presidio");
  return parts.join(" · ");
}
