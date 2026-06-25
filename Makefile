.PHONY: lint test validate

lint:
	uv run --extra dev ruff check .

test:
	uv run --extra dev pytest

validate: lint test
