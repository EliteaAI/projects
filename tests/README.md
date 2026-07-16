# Projects Plugin Tests

Unit tests for the projects plugin, isolated from Pylon runtime.

## Quick Start

```bash
cd centry/pylon_main/plugins/projects
python3 tests/run_tests.py -v
```

## Test Structure

```
tests/
├── run_tests.py          # Entry point - installs Pylon stubs before pytest
├── pytest.ini            # Pytest configuration
├── conftest.py           # Auto-markers based on directory
├── requirements-dev.txt  # Test dependencies
├── fixtures/
│   └── helpers.py        # Module loading utilities
└── unit/
    ├── test_helpers.py         # ProjectCreationStep ABC tests
    └── test_pydantic_models.py # GroupCreateModel, ProjectCreatePD validation
```

## Running Tests

```bash
# All tests
python3 tests/run_tests.py -v

# Unit tests only
python3 tests/run_tests.py -m unit -v

# Specific file
python3 tests/run_tests.py unit/test_helpers.py -v
```

## Test Count

- **Unit tests**: 25 (ProjectCreationStep, pydantic model validation)
