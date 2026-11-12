# Research harness

Experiments on how well NLI and LLM classifiers assign sensitivity tiers to
English and Ukrainian documents, and how easily hidden instructions lower that tier.

The code imports `app.classifier_core` and never touches Postgres or MinIO. It runs inside the
worker image, so the NLI configs use the same torch/transformers as the service.

## Layout

| Path | What |
|---|---|
| `classify_dir.py` | Classify a folder with the chosen configs → `predictions.csv` + `manifest.json` |
| `engines.py` | NLI, LLM (llama-server) and Presidio engines |
| `cache.py` | Result cache keyed by `(sha256(text), engine, model, prompt_version)` |
| `manifest.py` | Run manifest: git commit, package versions, GGUF sha256, server build, seed |
| `prompts/` | Versioned LLM prompts (`classify_v1.txt` = baseline, no defenses) |
| `smoke/` | 10 EN/UK pairs used only to choose models; not part of the corpus, not reviewed |
| `results/` | Run outputs and the cache. Git-ignored except `results/<run_id>/summary/` |

## Configs

| config_id | Semantic layer |
|---|---|
| `nli_en` | `MoritzLaurer/deberta-v3-large-zeroshot-v2.0`, first 400 words |
| `nli_ml` | `MoritzLaurer/bge-m3-zeroshot-v2.0-c`, first 6000 words |
| `nli_mdeberta` | `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`, first 400 words |
| `llm` | Whatever model `llama-server` is serving; reported as `llm:<label>` |

Every config also gets a `<config>+presidio` row: `max_tier(semantic, presidio)`.

## 1. Start the LLM server (Windows host)

llama.cpp build `b12317`, Vulkan, Windows x64 (`llama-b12317-bin-win-vulkan-x64.zip` from the
ggml-org/llama.cpp releases). GGUFs live outside the repo in `%USERPROFILE%\llm\models`.

```sh
~/llm/llama.cpp/b12317/llama-server.exe -m ~/llm/models/<file>.gguf \
  -ngl 999 -c 8192 -np 1 --host 127.0.0.1 --port 8080
```

- `-ngl 999` puts all layers on the GPU; `--list-devices` should show `Vulkan0: AMD Radeon RX 6700 XT`.
- `-np 1`: one slot, so requests run one at a time.
- `127.0.0.1` is enough: Docker Desktop forwards `host.docker.internal` to the host's loopback,
  and the server stays off the LAN.
- Temperature 0, the seed, the JSON schema and `enable_thinking: false` are sent per request.

| label | GGUF | sha256 (first 12) |
|---|---|---|
| `gemma4-12b` | `gemma-4-12b-it-qat-q4_0.gguf` (google, QAT Q4_0) | `93567e57a8fe` |
| `qwen35-9b` | `Qwen3.5-9B-Q4_K_M.gguf` (unsloth) | `03b74727a860` |
| `gemma4-e4b` | `gemma-4-E4B_q4_0-it.gguf` (google, QAT Q4_0) | `676c35070db6` |
| `mamaylm-12b` | `MamayLM-Gemma-3-12B-IT-v2.0-Q4_K_M.gguf` (INSAIT) | `aeb8e3676b5a` |
| `qwen35-2b` | `Qwen3.5-2B-Q4_K_M.gguf` (unsloth) | `aaf42c8b7c3c` |

## 2. Run

From the repo root (Git Bash), with Docker Desktop running:

```sh
make research MOD=classify_dir ARGS="research/smoke/docs \
  --configs nli_en,nli_ml,llm --labels research/smoke/labels.csv \
  --llm-label gemma4-e4b --gguf gemma-4-E4B_q4_0-it.gguf"
```

- `--gguf` is a file name, not a path: `make research` mounts `~/llm/models` read-only at
  `/models` (override with `LLM_MODELS_DIR=...`), and the file is hashed into the manifest.
- `make research` passes `GIT_COMMIT` because `.git` is not mounted into the container.
- `LLM_BASE_URL` overrides the default `http://host.docker.internal:8080`.
- NLI models download into the `hf-cache` volume on first use; they run on CPU.
- Reruns are cheap: unchanged `(text, engine, model, prompt)` combinations come from the cache.

Output: `results/<run_id>/predictions.csv` (columns listed in `classify_dir.FIELDS`)
and `manifest.json`. With `--labels` the run also prints accuracy, under-classification rate,
invalid answers and median latency per config and language.
