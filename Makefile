SHELL := /bin/bash

.PHONY: validate test build-tools build-iso manifest manifest-check inventory archive

validate:
	./tools/validate.sh

test:
	python3 tests/test-consistency.py
	python3 tests/test-disk-selector.py
	bash tests/test-firstboot-input.sh
	bash tests/test-luks-rotation-image.sh

build-tools:
	./tools/build-host-tools.sh

build-iso:
	sudo ./tools/build-iso.sh

manifest:
	@set -o pipefail; { git ls-files -z | while IFS= read -r -d '' file; do \
		[ "$$file" = "MANIFEST.sha256" ] || sha256sum -- "$$file"; \
	done; } | LC_ALL=C sort -k2 > MANIFEST.sha256

manifest-check: manifest
	git diff --exit-code -- MANIFEST.sha256

inventory:
	git ls-files

archive: validate manifest
	cd .. && rm -f debian-install-template-fai-interactive-disks.zip && \
		zip -q -r debian-install-template-fai-interactive-disks.zip debian-install-template-fai \
		-x 'debian-install-template-fai/.git/*' \
		-x 'debian-install-template-fai/build/*' \
		-x 'debian-install-template-fai/config/config.yaml' \
		-x 'debian-install-template-fai/*.kdbx' \
		-x 'debian-install-template-fai/*.passphrase' \
		-x 'debian-install-template-fai/*.password' \
		-x 'debian-install-template-fai/*/provision.password.hash' \
		-x 'debian-install-template-fai/*/provision.authorized_keys' \
		-x '*/__pycache__/*' -x '*.pyc'
	./tools/check-archive.sh ../debian-install-template-fai-interactive-disks.zip
