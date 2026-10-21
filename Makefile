.PHONY: validate test build-tools build-iso manifest inventory archive
validate:
	./tools/validate.sh

test: validate

build-tools:
	./tools/build-host-tools.sh

build-iso:
	sudo ./tools/build-iso.sh

manifest:
	find . -type f ! -path './.git/*' ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256

inventory:
	find . -type f ! -path './.git/*' -print | sort

archive: validate manifest
	cd .. && zip -q -r debian-install-template-fai-interactive-disks.zip debian-install-template
	./tools/check-archive.sh ../debian-install-template-fai-interactive-disks.zip
