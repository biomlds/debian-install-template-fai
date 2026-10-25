SHELL := /bin/bash
MANIFEST_OUT ?= MANIFEST.sha256

.PHONY: validate test build-tools build-iso manifest manifest-check inventory archive
validate:
	./tools/validate.sh
test:
	python3 tests/test-consistency.py
	python3 tests/test-disk-selector.py
	python3 tests/test-workstation.py
	bash tests/test-luks-rotation-image.sh
build-tools:
	./tools/build-host-tools.sh
build-iso:
	sudo ./tools/build-iso.sh
manifest:
	python3 tools/manifest.py --output "$(MANIFEST_OUT)"
manifest-check:
	python3 tools/manifest.py --check
inventory:
	git ls-files
archive: validate manifest
	python3 tools/archive.py
