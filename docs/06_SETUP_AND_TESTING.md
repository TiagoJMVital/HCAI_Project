# Setup and testing on WSL2 Ubuntu

## Current v2 path

From `HCAI_Project/` in the virtual environment: `python src/benchmark_v2.py validate ../scenario_v2_example.json` validates the reference, and `python src/benchmark_v2.py import ../scenario_v2_example.json --split train` imports it only after the family split is chosen. `python src/benchmark_v2.py validate` checks all imported v2 scenarios. `streamlit run annotation_app.py --server.address 127.0.0.1` opens the local interface; use the printed localhost URL in Windows. **Propostas v2** and **Consenso v2** are the active pages; old pages remain under **Arquivo**. `python src/proposal_catalog_v2.py eval/runs/<run_id>/B_v2/<scenario_id>.json` imports a previous result without a model call. `python eval/run_config_a_v2.py --only <scenario_id>` and `python eval/run_config_b_v2.py --only <scenario_id>` explicitly generate a single A or B result and **call the configured LLM**. `python src/gate_dataset_v2.py --split train` exports eligible examples; test export needs `--unlock-test` only after freeze. `python -m pytest -q` uses mocked providers and makes no IAedu calls. Legacy commands below remain valid for the older corpus; see [the active protocol](04_ANNOTATION_PROTOCOL.md).

## Local environment

Open `HCAI_Project` as the VS Code WSL workspace. From that repository root, use Python **3.12 or newer**; the inspected local environment uses Python 3.14.4. `requirements.txt` specifies compatible ranges for Pydantic v2, Requests, python-dotenv, pytest and Streamlit, not a fully pinned lockfile. [Streamlit's installation documentation](https://docs.streamlit.io/get-started/installation/command-line) lists Python 3.14 as supported. `git` is needed to inspect working-tree state. Ollama, n8n and Google credentials are **not** required for local tests or annotation. Do not install or run them merely to reproduce the automated suite.

```bash
cd /home/cfaeatb/projetos/HCAI-Project/HCAI_Project
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If this Ubuntu Python lacks `ensurepip`/`pip`, use the already documented `uv` alternative (if installed):

```bash
uv venv --python /usr/bin/python3 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

After setup, use `.venv/bin/python` in commands if the shell is not activated. `requirements.txt` is the dependency source of truth. The `.venv/`, `.env`, `data/annotation_work/`, `data/gate_datasets/` and `eval/runs/` paths are ignored by Git; `.env.example` is deliberately tracked. Check with `git check-ignore .env .venv/`. Never commit keys or private calendar exports.

## Local annotation app

From the WSL2 repository root, after installing dependencies:

```bash
source .venv/bin/activate
streamlit run annotation_app.py --server.address 127.0.0.1
```

Open the local URL shown by Streamlit, usually `http://localhost:8501`, in the Windows browser. The app uses the existing JSON packets/forms, requires no IAedu call and does not access Google Calendar. It prepares missing blank forms without replacing existing ones. The selected author sees only their forms until the paired comparison area is unlocked for a completed item. See [Annotation protocol](04_ANNOTATION_PROTOCOL.md) for draft saving, completion, defer reasons and adjudication. Stop the local server with `Ctrl+C` in the WSL terminal.

The weekly calendar uses Streamlit's built-in [`st.html`](https://docs.streamlit.io/develop/api-reference/text/st.html) with escaped, sanitized HTML/CSS and **no JavaScript or additional calendar dependency**. Previous/Next week controls and the Original/Proposed switch are native Streamlit widgets. The calendar is read-only and highlights only intervals identified by the limited deterministic parser described in the annotation protocol.

## IAedu configuration

Copy `.env.example` to `.env` and fill `.env` locally in VS Code. Set `LLM_PROVIDER=iaedu`, `PROPOSER_LLM_PROVIDER=iaedu`, `CRITIC_LLM_PROVIDER=iaedu`, `IAEDU_API_KEY`, `IAEDU_API_ENDPOINT` (portal-provided HTTPS `/stream` URL), `IAEDU_CHANNEL_ID` (portal's GPT-5.5 channel) and model labels. **Do not paste secrets into a chat, terminal output, issue or committed file.** The model label does not select the deployed model; the channel does. The provider sends `x-api-key` and multipart form fields, reconstructs streamed tokens and validates JSON locally. Each request gets a fresh thread ID.

`LLM_PROVIDER=ollama` plus role-specific `PROPOSER_LLM_PROVIDER=ollama` and `CRITIC_LLM_PROVIDER=ollama` selects the alternative. Configure `OLLAMA_URL` and `OLLAMA_MODEL` for an existing local Ollama service/model; the code defaults to `http://localhost:11434` and `llama3.2:3b`. Ollama was not installed as part of the IAedu setup and is unnecessary for mock tests. `--provider`, `--model`, `--critic-provider` and `--critic-model` may override provider/model selection on runners; keep them matched to the experimental protocol.

## Offline generation and verification

These commands do not call IAedu or any calendar service:

```bash
python src/make_benchmark.py
python src/validate_data.py
python -m pytest -q tests
```

Expected validator summary for the current benchmark: valid profile, **41 scenarios**, **20 bases**, **41 variants**, three training-only grouped folds and family split OK. `make_benchmark.py` regenerates synthetic files, so avoid it if you are examining uncommitted scenario edits; inspect `git status` first. The current local suite passes 54 tests. Its provider tests use mocked responses and do not prove live API availability.

## Live synthetic checks and individual A/B runs

The following commands **do consume IAedu calls** when IAedu is selected. Use only synthetic scenarios and a configured private `.env`; no real calendar is contacted. Run connectivity before structured generation, then one scenario at a time:

```bash
python src/check_iaedu.py --mode connectivity
python src/check_iaedu.py --mode structured
python eval/run_config_a.py --only soft_gym_01 --experiment-id demo-pair --repeat-index 0
python eval/run_config_b.py --only soft_gym_01 --experiment-id demo-pair --repeat-index 0 --critic-threshold 4.0 --max-refinements 3 --min-dimension-score 1
```

Omitting `--only` runs the whole benchmark and can consume many tokens; do not do that for a smoke test. A/B write unique `eval/runs/<run_id>/A|B/<scenario_id>.json` records. Match `experiment_id` and `repeat_index` for comparison, but verify provider/model and generation settings too. The offline command `python eval/compare_runs.py --experiment-id demo-pair` prints paired records; it is a grouping aid, not a significance test. The command `python eval/evaluate_run.py eval/runs/<run_id>/B/soft_gym_01.json` prints partial objective quality checks. A `status=proposal_ready` with `decision=act` means only a simulated decision. `deferred_critic_threshold` and `deferred_invalid_proposal` are distinct from `critic_error`/`proposer_error`; technical errors are not successful deferrals.

The earlier fixed A samples are in `eval/results/A/`; new unique runs do not overwrite them. `data/proposal_sources/` stores archived imported B proposals. The v2 workflow uses separate `data/proposal_sources_v2/`, `data/annotation_work_v2/` and `data/gate_datasets_v2/` paths. These paths are not automatically ignored by Git; review generated artifacts and privacy before any future commit. See [the active protocol](04_ANNOTATION_PROTOCOL.md).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `ModuleNotFoundError` or wrong Pydantic API | Activate `.venv`, inspect `python --version`, reinstall from `requirements.txt` in that environment. |
| IAedu HTTP 401/403 | Recheck key, endpoint and channel in the portal locally; stop live tests on authentication/permission errors. Do not print the values. |
| Empty stream or invalid JSON | The endpoint must be the portal `/stream` endpoint; the client assembles `token` events and retries a bounded number of malformed structured replies. Inspect sanitized status, not raw payloads containing sensitive context. |
| IAedu quota/timeout | Stop the run; keep the error record. Do not automatically execute the full benchmark or infer a human `defer`. |
| Legacy `prepare-proposals` refuses to run | The archived two-stage path requires scenario adjudication first; v2 direct proposal review does not. |
| Legacy `gate_dataset.py` refuses export | The archived path requires both old stages. For v2 use `gate_dataset_v2.py`; test export still requires explicit unlock after freezing the model. |
| A/B decisions differ | Inspect both proposals, violations, Critic history and model settings; one isolated pair is not a causal estimate. |

No configuration writes to Google Calendar. `find_violations` is partial and its absence of reported violations is not proof of full request satisfaction.
