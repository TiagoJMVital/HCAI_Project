# WSL2 setup and testing

Use WSL2 Ubuntu, VS Code and a compatible Python 3 interpreter (the current environment uses Python 3.14). From `HCAI_Project/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Put the institutional IAedu key, HTTPS endpoint and channel ID **only** in ignored `.env` via VS Code, or export them in the shell. Never commit or print credentials. `.env.example` lists provider and Ollama alternatives. `LLM_PROVIDER=iaedu` selects IAedu; `LLM_PROVIDER=ollama` selects the local alternative when installed separately. Proposer and Critic can be configured independently through role-specific variables or runner options. Streamlit, validation, import and mocked tests need no IAedu connection. The app serves locally; start it with `streamlit run annotation_app.py --server.address 127.0.0.1`, then open the printed URL in the Windows browser.

## Local checks (no LLM requests)

```bash
python src/benchmark_v2.py validate ../scenario_v2_example.json
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
python eval/run_config_b_v2.py --only working_student_deadline_001 --initial-proposal-from eval/runs/e9052e6757c14820a06b89ddaf9aafe6/B/working_student_deadline_001.json
# This import makes no LLM call:
python src/proposal_catalog_v2.py eval/runs/<run_id>/B/<scenario_id>.json
streamlit run annotation_app.py --server.address 127.0.0.1
python src/gate_dataset_v2.py --split train
```

For an existing B result, use its actual path, including historical `B_v2/` if applicable. Outputs are under `eval/runs/<run_id>/A|B/`, imported artifacts under `data/proposals/`, review forms under `data/annotations/`, and gate exports under `data/gate_datasets/`. An imported proposal appears in Streamlit after a refresh. Import is idempotent for identical result content and rejects changed provenance. A missing provider key, wrong channel/endpoint or exhausted quota affects only explicit real generation; stop and diagnose rather than retrying a full benchmark. No command here writes a real calendar.

The replay option makes a new run and calls the current Critic on the deterministic result calendar. Its first iteration has `proposer_source=replayed`; later revisions, if requested, use the normal Proposer with the original scenario context. `replay_source` records the source path/run ID, source run SHA-256, canonical proposal SHA-256, current scenario SHA-256 and whether the historical first-iteration result calendar matched current simulation. Source artifacts are read-only. Check these fields before comparing runs.
