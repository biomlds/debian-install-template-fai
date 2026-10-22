SHELL := /bin/bash
MANIFEST := MANIFEST.sha256
MANIFEST_OUT ?= $(MANIFEST)

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
	@set -euo pipefail; { \
		if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
			git ls-files -z; \
		else \
			find . -type f \
				! -path './.git/*' \
				! -name '.git' \
				! -path './build/*' \
				! -path '*/__pycache__/*' \
				! -name '*.pyc' \
				! -path './config/config.yaml' \
				! -name '*.iso' \
				! -name '*.iso.sha256' \
				! -name '*.kdbx' \
				! -name '*.key' \
				! -name '*.passphrase' \
				! -name '*.password' \
				! -name 'MANIFEST.sha256' \
				! -name 'HOST_TOOLS.sha256' \
				! -name 'HOST_TOOLS.versions' \
				! -name 'provision.password.hash' \
				! -name 'provision.authorized_keys' \
				! -path './fai/config/assets/bin/*' \
				! -path './fai/config/assets/vendor/grub-btrfs/*' \
				-print0; \
		fi | while IFS= read -r -d '' file; do \
			file="$${file#./}"; \
			[ "$$file" = "$(MANIFEST)" ] || sha256sum -- "$$file"; \
		done; } | LC_ALL=C sort -k2 > "$(MANIFEST_OUT)"

manifest-check:
	@set -e; tmp=$$(mktemp); \
	trap 'rm -f -- "$$tmp"' EXIT; \
	$(MAKE) --no-print-directory manifest MANIFEST_OUT="$$tmp"; \
	if ! cmp -s -- "$(MANIFEST)" "$$tmp"; then \
		echo "MANIFEST.sha256 is out of date; run 'make manifest'." >&2; \
		diff -u -- "$(MANIFEST)" "$$tmp" >&2 || true; \
		exit 1; \
	fi

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
