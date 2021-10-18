.DEFAULT_GOAL := all

black = black halohome
flake8 = flake8 halohome
isort = isort halohome
install-pip = python -m pip install -U setuptools pip wheel

.PHONY: install
install:
	$(install-pip)
	pip install -e .

.PHONY: install-dev
install-dev:
	$(install-pip)
	pip install -e ".[dev]"

.PHONY: format
format:
	$(isort)
	$(black)

.PHONY: check
check:
	$(isort) --check-only --df
	$(black) --check --diff
	$(flake8)

.PHONY: build
build:
	python setup.py sdist bdist_wheel
	twine check dist/*

.PHONY: clean
clean:
	rm -rf `find . -name __pycache__`
	rm -rf build
	rm -rf dist
	rm -rf *.egg-info
