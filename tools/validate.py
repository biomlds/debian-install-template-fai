#!/usr/bin/env python3
from __future__ import annotations
import os,re,stat,subprocess,sys
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/'fai/config'
errors=[]; warnings=[]
required=[
'class/10-base-classes','class/20-bootstrap','class/50-host-classes','class/DEBIAN.var','class/TRIXIE.var','class/WORKSTATION.var',
'disk_config/LUKS_BTRFS','debconf/WORKSTATION','hooks/partition.WORKSTATION','hooks/mountdisks.LUKS_BTRFS',
'package_config/DEBIAN','package_config/FAIBASE','package_config/TRIXIE','package_config/AMD64','package_config/GRUB_EFI',
'package_config/LUKS_BTRFS','package_config/WORKSTATION','package_config/SWAY','package_config/BACKUP','package_config/INCUS','package_config/FLATPAK_APPS',
'scripts/LUKS_BTRFS/10-bootstrap-key','scripts/LUKS_BTRFS/20-snapper','scripts/GRUB_EFI/10-setup','scripts/FINAL/99-finalize',
'files/usr/local/lib/workstation-firstboot/workstation_firstboot.py/WORKSTATION',
'assets/disk-selection/disk_selector.py']
for rel in required:
    if not (CFG/rel).is_file(): errors.append(f'missing {rel}')
for p in ROOT.rglob('*'):
    if not p.is_file() or '.git' in p.parts or p.name=='MANIFEST.sha256': continue
    data=p.read_bytes(); rel=p.relative_to(ROOT)
    if b'\r\n' in data: errors.append(f'CRLF {rel}')
    if b'\x00' in data: errors.append(f'NUL {rel}')
    try: text=data.decode()
    except UnicodeDecodeError: continue
    for n,line in enumerate(text.splitlines(),1):
        if line.rstrip(' \t')!=line: errors.append(f'trailing whitespace {rel}:{n}')
shell=[]
for p in ROOT.rglob('*'):
    if not p.is_file(): continue
    first=p.read_bytes().splitlines()[:1]
    if p.suffix=='.sh' or (first and first[0].startswith(b'#!') and b'sh' in first[0]):
        shell.append(p)
        if not p.stat().st_mode & stat.S_IXUSR: errors.append(f'not executable {p.relative_to(ROOT)}')
        q=subprocess.run(['bash','-n',str(p)],capture_output=True,text=True)
        if q.returncode: errors.append(f'bash syntax {p.relative_to(ROOT)}: {q.stderr.strip()}')
pyfiles=[p for p in ROOT.rglob('*.py') if p.is_file()]
pyfiles += [CFG/'files/usr/local/lib/workstation-firstboot/workstation_firstboot.py/WORKSTATION']
for p in pyfiles:
    try:
        compile(p.read_text(), str(p), 'exec')
    except SyntaxError as exc:
        errors.append(f'python syntax {p.relative_to(ROOT)}: {exc}')
for p in list(ROOT.rglob('*.yaml'))+list(ROOT.rglob('*.yml'))+[CFG/'files/etc/workstation-bootstrap/config.yaml.example/WORKSTATION']:
    try: yaml.safe_load(p.read_text())
    except Exception as e: errors.append(f'YAML {p.relative_to(ROOT)}: {e}')
for p in sorted((CFG/'package_config').iterdir()):
    mode=None; seen=set()
    for n,raw in enumerate(p.read_text().splitlines(),1):
        line=raw.strip()
        if not line or line.startswith('#'): continue
        if line.startswith('PACKAGES '): mode=line.split(maxsplit=1)[1]; continue
        if mode not in {'install','remove'}: errors.append(f'package before header {p.name}:{n}')
        if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*',line): errors.append(f'bad package {p.name}:{n}:{line}')
        if (mode,line) in seen: errors.append(f'duplicate package {p.name}:{line}')
        seen.add((mode,line))
secret_patterns=[
 re.compile(r'BEGIN (?:OPENSSH|RSA|EC|DSA) PRIVATE KEY'),
 re.compile(r'(?i)(?:password|passphrase)[ \t]*[:=][ \t]*["\'](?!REPLACE|/media|/run|/var|\$)[^"\'\r\n]{8,}["\']'),
 re.compile(r'\$\{\{\s*secrets\.'),
]
for p in ROOT.rglob('*'):
    if not p.is_file() or p.name in {'validate.py'}: continue
    text=p.read_text(errors='ignore')
    for pat in secret_patterns:
        if pat.search(text): errors.append(f'possible committed secret {p.relative_to(ROOT)}')
setup=shutil_which=''
q=subprocess.run(['bash','-lc','command -v setup-storage || true'],capture_output=True,text=True)
setup=q.stdout.strip()
if setup:
    os.makedirs('/tmp/fai-validate',exist_ok=True)
    q=subprocess.run([setup,'-s','-f',str(CFG/'disk_config/LUKS_BTRFS')],env={**os.environ,'disklist':'/dev/null','LOGDIR':'/tmp/fai-validate'},capture_output=True,text=True)
    if q.returncode: errors.append('setup-storage syntax: '+(q.stderr.strip() or q.stdout.strip()))
else: warnings.append('setup-storage unavailable; static disk validation only')
q=subprocess.run([sys.executable,str(ROOT/'tests/test-consistency.py')],capture_output=True,text=True)
if q.returncode: errors.append('consistency: '+q.stdout.strip()+q.stderr.strip())
for w in warnings: print('WARN:',w)
if errors:
    for e in errors: print('ERROR:',e,file=sys.stderr)
    raise SystemExit(1)
print(f'PASS {len(required)} required files; {len(shell)} shell files; {len(pyfiles)} Python files; {len(list((CFG/"package_config").iterdir()))} package classes')
