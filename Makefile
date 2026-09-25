# Common tasks. Run `make setup` once.
PY ?= python3
VENV ?= .venv
BIN = $(VENV)/bin

setup:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -U pip
	$(BIN)/pip install -r requirements-lock.txt
	$(BIN)/pip install -e ".[dev]"

demo:            ## replay history end to end and render the dashboard
	$(BIN)/crm-agent simulate
	@echo "Open space/index.html"

demo-live:       ## replay all but the last period, so you can run it live
	$(BIN)/crm-agent simulate --leave-last

a2a:             ## run the three agents as A2A services on :9100
	$(BIN)/crm-agent a2a-serve

cycle-a2a:       ## run the final lead and account cycles over A2A (needs `make a2a` in another terminal)
	$(BIN)/crm-agent cycle lead 2026-09 --transport a2a
	$(BIN)/crm-agent cycle account 2026Q3 --transport a2a

mcp:             ## MCP server on stdio
	$(BIN)/crm-agent mcp

test:
	$(BIN)/pytest -q

sf-deploy:       ## deploy fields, permission set and Apex action to your org (needs the sf CLI)
	cd salesforce && sf project deploy start --source-dir force-app --target-org crm-dev --test-level RunSpecifiedTests --tests ScoreExplainActionTest
	sf org assign permset --name CRM_Score_Agent --target-org crm-dev

space:           ## publish the dashboard to a Hugging Face Space (run `hf auth login` first)
	$(BIN)/pip install -q huggingface_hub
	$(BIN)/python -c "from huggingface_hub import HfApi; import os; api=HfApi(); rid=os.getenv('HF_SPACE','dsoosai/crm-scoring-agents'); api.create_repo(rid, repo_type='space', space_sdk='static', exist_ok=True); api.upload_folder(folder_path='space', repo_id=rid, repo_type='space'); print('https://huggingface.co/spaces/'+rid)"

.PHONY: setup demo demo-live a2a cycle-a2a mcp test sf-deploy space
