.PHONY: all format help export-requirements run-agent-uv run-agent run-eval-uv run-eval generate-report-uv generate-report

all: help

format:
	uv run ruff format .
	uv run ruff check --select I . --fix
	uv run ruff check .

export-requirements:
	uv export --no-hashes --no-dev > requirements.txt

run-agent-uv:
	uv run python3 single_file_agent.py

run-agent:
	python3 single_file_agent.py

run-eval-uv:
	uv run python3 -m evaluation.main

run-eval:
	python3 -m evaluation.main

generate-report-uv:
	uv run python3 evaluation/components/generate_report.py $(run)

generate-report:
	python3 evaluation/components/generate_report.py $(run)

help:
	@echo '----'
	@echo 'Available commands:'
	@echo ''
	@echo 'Agent Commands:'
	@echo '  run-agent-uv.............. - run agent using uv'
	@echo '  run-agent................. - run agent in current env'
	@echo ''
	@echo 'Evaluation Commands:'
	@echo '  run-eval-uv............... - run evaluation suite using uv'
	@echo '  run-eval.................. - run evaluation suite in current env'
	@echo '  generate-report-uv........ - regenerate report.txt from an eval run using uv'
	@echo '  generate-report........... - regenerate report.txt from an eval run in current env'
	@echo '                            (optional run=<run-directory-name>, defaults to the most recent)'
	@echo ''
	@echo 'Development Commands:'
	@echo '  format.................... - run code formatters (ruff)'
	@echo '  export-requirements....... - export runtime dependencies from uv.lock to requirements.txt'
	@echo ''
	@echo 'Examples:'
	@echo '  make run-agent-uv'
	@echo '  make run-eval-uv'
	@echo '  make generate-report-uv run=eval_run_2026-11-11_16-09-01_ontology'
	@echo '  make export-requirements'
	@echo '----'
