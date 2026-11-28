import { apiClient } from "@/api/client";
import type { Tier } from "@/api/files";

/** Admin playground API. Exists only when the stack runs in playground mode (404 otherwise). */

export type Engine = "nli" | "llm";
export type Defense = "D1" | "D2" | "D4" | "D6";
export type AttackId = "none" | "A1" | "A2" | "A3" | "A4" | "A5" | "A6" | "A7";
export type Lang = "en" | "uk";
export type Format = "txt" | "docx" | "pdf";

export interface Setup {
  label?: string;
  engine: Engine;
  model: string;
  prompt?: string;
  prompt_text?: string | null;
  seed?: number;
  temperature?: number;
  top_p?: number | null;
  max_tokens?: number;
  thinking?: boolean;
  presidio?: boolean;
  defenses?: Defense[];
  detector?: "pg2" | "protectai";
  expected_tier?: Tier | null;
}

export interface Attack {
  attack: AttackId;
  payload_lang: Lang;
  placement: "start" | "end";
  carrier: string;
  a3_payload: "A1" | "A2";
  payload: string | null;
  output_format: Format;
}

export type Input =
  | { kind: "text"; text: string; text_format: Format; lang: Lang }
  | { kind: "file"; file_id: string; lang: Lang }
  | { kind: "corpus"; corpus_ref: string };

export interface Catalog {
  nli: { id: string; label: string }[];
  nli_server: boolean;
  llm: { id: string; status: string }[];
  llm_error: string;
  prompts: Record<string, string>;
  defenses: Record<Defense, string>;
  detectors: string[];
  defaults: {
    seed: number;
    temperature: number;
    top_p: number | null;
    max_tokens: number;
    thinking: boolean;
    prompt: string;
    presidio: boolean;
  };
  attacks: {
    attacks: AttackId[];
    payloads: Record<string, Record<Lang, string>>;
    docx_carriers: string[];
    pdf_carriers: string[];
    a7_carriers: { docx: string[]; pdf: string[] };
    obfuscations: string[];
  };
  corpus: boolean;
  presets: Preset[];
}

/** A ready-made run: a research file, an attack and setups with the research results. */
export interface Preset {
  id: string;
  title: string;
  summary: string;
  explain: boolean;
  corpus_ref: string;
  attack: Attack;
  setups: Setup[];
}

export interface CorpusDoc {
  ref: string;
  pair_id: string;
  lang: Lang;
  tier: Tier;
  group: string;
  words: string;
  difficulty: string;
}

export interface PickFile {
  id: string;
  filename: string;
  owner: string;
  size_bytes: number;
  uploaded_at: string;
}

export interface DocPayload {
  filename: string;
  content_type: string;
  data_b64: string;
  views: { full: string; visible: string };
}

export interface DocumentResponse {
  input: DocPayload;
  attacked: DocPayload;
  attack_source: "none" | "adapter" | "research-variant";
  info: { lang?: Lang; name?: string; pair_id?: string; tier?: Tier };
}

export interface RowResult {
  final_tier: Tier;
  zero_shot_tier: Tier;
  presidio_tier: Tier;
  categories_triggered: string[];
  raw_scores: Record<string, number>;
  presidio_entities: Record<string, { count?: number }>;
  needs_review: boolean;
  /** LLM rows: what the model returned for each classified view (D2 adds the visible text). */
  llm_output?: { view: "full" | "visible"; raw: string; reasoning: string; truncated: boolean }[];
  config: {
    view_tiers?: { full: Tier; visible: Tier };
    detector_score?: number;
    needs_review?: boolean;
    [k: string]: unknown;
  };
}

export interface Row {
  id: string;
  position: number;
  setup: Setup;
  status: "pending" | "running" | "done" | "failed";
  result: RowResult | null;
  explanation: { tier?: Tier; reason?: string; same_tier?: boolean; error?: string } | null;
  error: string | null;
  latency_ms: number | null;
}

export interface RunSummary {
  id: string;
  title: string;
  created_at: string;
  status: "pending" | "running" | "done" | "failed";
  input_kind: string;
  attack: Attack;
  attack_source: string;
  explain: boolean;
  preset: string | null;
  rows: number;
  done: number;
}

export interface RunDetail extends Omit<RunSummary, "rows"> {
  input_ref: string | null;
  documents: Record<string, { filename: string; content_type: string; size_bytes: number }>;
  rows: Row[];
}

export interface SavedSetup {
  id: string;
  name: string;
  rows: Setup[];
}

const BASE = "/api/admin/playground";

/** True when the stack runs in playground mode (the routes exist only then). */
export async function playgroundEnabled(): Promise<boolean> {
  try {
    await apiClient.get(`${BASE}/status`);
    return true;
  } catch {
    return false;
  }
}

export async function fetchCatalog(): Promise<Catalog> {
  return (await apiClient.get<Catalog>(`${BASE}/catalog`)).data;
}

export async function fetchCorpus(): Promise<CorpusDoc[]> {
  return (await apiClient.get<{ items: CorpusDoc[] }>(`${BASE}/corpus`)).data.items;
}

export async function searchFiles(q: string): Promise<PickFile[]> {
  return (await apiClient.get<{ items: PickFile[] }>(`${BASE}/files`, { params: { q } })).data
    .items;
}

export async function buildDocument(input: Input, attack: Attack): Promise<DocumentResponse> {
  return (await apiClient.post<DocumentResponse>(`${BASE}/document`, { input, attack })).data;
}

export async function createRun(body: {
  input: Input;
  attack: Attack;
  setups: Setup[];
  explain: boolean;
  preset?: string | null;
}): Promise<RunDetail> {
  return (await apiClient.post<RunDetail>(`${BASE}/runs`, body)).data;
}

export async function listRuns(): Promise<RunSummary[]> {
  return (await apiClient.get<{ items: RunSummary[] }>(`${BASE}/runs`)).data.items;
}

export async function fetchRun(id: string): Promise<RunDetail> {
  return (await apiClient.get<RunDetail>(`${BASE}/runs/${id}`)).data;
}

export async function fetchRunDocument(
  id: string,
  which: "input" | "attacked",
): Promise<DocPayload> {
  return (await apiClient.get<DocPayload>(`${BASE}/runs/${id}/document`, { params: { which } }))
    .data;
}

export async function rerun(id: string): Promise<RunDetail> {
  return (await apiClient.post<RunDetail>(`${BASE}/runs/${id}/rerun`)).data;
}

export async function deleteRun(id: string): Promise<void> {
  await apiClient.delete(`${BASE}/runs/${id}`);
}

export async function listSetups(): Promise<SavedSetup[]> {
  return (await apiClient.get<{ items: SavedSetup[] }>(`${BASE}/setups`)).data.items;
}

export async function saveSetup(name: string, rows: Setup[]): Promise<SavedSetup> {
  return (await apiClient.post<SavedSetup>(`${BASE}/setups`, { name, rows })).data;
}

export async function deleteSetup(id: string): Promise<void> {
  await apiClient.delete(`${BASE}/setups/${id}`);
}

export function decodeB64(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

/** The API's error message, or a fallback. */
export function apiMessage(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { message?: string } } };
  return e.response?.data?.message ?? fallback;
}
