# WSL2 setup and testing

Use WSL2 Ubuntu, VS Code and a compatible Python 3 interpreter (the current environment uses Python 3.14). From `HCAI_Project/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Put the institutional IAedu key, HTTPS endpoint and channel ID **only** in ignored `.env` via VS Code, or export them in the shell. Never commit or print credentials. `.env.example` lists provider and Ollama alternatives. `LLM_PROVIDER=iaedu` selects IAedu; `LLM_PROVIDER=ollama` selects the local alternative when installed separately. Proposer and Critic can be configured independently through role-specific variables or runner options. Streamlit, validation, import and mocked tests need no IAedu connection. The app serves locally; start it with `streamlit run annotation_app.py --server.address 127.0.0.1`, then open the printed URL in the Windows browser.

IAedu rate limits are handled in the shared provider for both agents. `Retry-After`
is respected when present; otherwise bounded exponential backoff with jitter uses
`IAEDU_RATE_LIMIT_MAX_RETRIES`, `IAEDU_RATE_LIMIT_BASE_DELAY`,
`IAEDU_RATE_LIMIT_MAX_DELAY`, and `IAEDU_RATE_LIMIT_JITTER`. The resumable pilot
adds `PILOT_REQUEST_DELAY_SECONDS` between new A/B configurations and stops after
a rate-limit failure instead of advancing through the remaining scenarios.

Structured-output retries are separate from HTTP rate-limit retries.
`IAEDU_STRUCTURED_MAX_RETRIES` sets the total number of attempts (default `2`,
minimum `1`) used when a response is truncated, has invalid JSON, or fails the
local Pydantic schema. Run diagnostics record only the failure category, output
length and affected schema fields; raw failed outputs remain in the existing
`failed_llm_outputs` field for traceability. The official IAedu Python API example
documents only the multipart fields `channel_id`, `thread_id`, `user_info`, and
`message`. It does not document an output-token parameter, so this client does
not send an unsupported `max_tokens` field. Any provider-side generation limit
is therefore outside the controls documented for this client.

The Proposer uses the versioned `compact_proposal_v1` wire schema to reduce
model output size. The stored run still contains the canonical `Proposal` used
by deterministic validation. Use `prompt_versions.proposer_wire_schema_version`
and `prompt_versions.proposer_wire_schema_sha256` when comparing runs; older
runs without these fields predate the compact generation contract.

## Local checks (no LLM requests)

```bash
python src/benchmark_v2.py validate data/scenarios/working_student_deadline_001.json
python src/benchmark_v2.py validate
python -m pytest -q
```

`validate` without a path checks the imported manifest and scenarios. The full test suite uses synthetic fixtures and mocked LLM responses. The legacy 41-case validator is archived and does not define the active corpus. Tests may use temporary directories; do not point them at live author forms.

## Official operations

```bash
python src/benchmark_v2.py import /path/to/new_scenario.json --split train
# The following two commands make explicit LLM calls when configured:
python eval/run_config_a_v2.py --only <scenario_id>
python eval/run_config_b_v2.py --only <scenario_id> --critic-threshold 4.0 --max-refinements 3
# Optional: reuse the first proposal of a prior B run and start at the Critic.
python eval/run_config_b_v2.py --only <scenario_id> --initial-proposal-from eval/runs/treino/<family>/<scenario_id>/<run_id>/B/<scenario_id>.json
# This import makes no LLM call:
python src/proposal_catalog_v2.py eval/runs/treino/<family>/<scenario_id>/<run_id>/B/<scenario_id>.json
streamlit run annotation_app.py --server.address 127.0.0.1
python src/gate_dataset_v2.py --split train
```

For an existing B result, use its actual path, including historical layouts if applicable. New outputs are separated under `eval/runs/treino/<family>/...`, `eval/runs/avaliacao/desenvolvimento/<family>/...`, or `eval/runs/avaliacao/teste/<family>/...`; imported artifacts remain under `data/proposals/`, review forms under `data/annotations/`, and gate exports under `data/gate_datasets/`. Import is idempotent for identical result content and rejects changed provenance. No command here writes a real calendar.

The final training batch preserves the pilot provider configuration and makes no provider call in dry-run mode:

```bash
python eval/run_training_b_v2.py --dry-run --resume
python eval/run_training_b_v2.py --resume
```

The default is already resumable; `--resume` makes that intent explicit. `--only`, `--family`, and `--limit` narrow the eligible training selection. Only `--force` deliberately repeats an experimentally compatible completed run. Provider/parsing failures receive only the bounded shared-provider retries; authentication, quota, rate-limit and token failures stop the batch.

The replay option makes a new run and calls the current Critic on the deterministic result calendar. Its first iteration has `proposer_source=replayed`; later revisions, if requested, use the normal Proposer with the original scenario context. `replay_source` records the source path/run ID, source run SHA-256, canonical proposal SHA-256, current scenario SHA-256 and whether the historical first-iteration result calendar matched current simulation. Source artifacts are read-only. Check these fields before comparing runs.
