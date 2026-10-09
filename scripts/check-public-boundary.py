"""Reject company state and concrete private network addresses in public distributions."""
from __future__ import annotations
import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_STATE = {'provider.json','activation.dpapi','nas-drives.json','codextools-nas-guide.json',
    'credentials.json','custom-domains.json','cookies','login data','web data','installer-source.txt','settings.json','prefs.json','progress.json','preferences','local state','accounts.json','tokens.json','auth.json'}
PUBLIC_TOP = {'apps','helpers','scripts','system','docs','tests','public-hub','third_party','assets','templates'}
PUBLIC_FILES = {'AGENTS.md','README.md','.gitignore','start-plugin-station.vbs','start-plugin-station.cmd','ONLINE-RELEASE.json','LICENSE','NOTICE','.gitattributes'}
PRIVATE_DIRS = {'.runtime','privateplugins','companyaccess','webview2-data','backups','migration-backups','artifacts','.venv'}

def path_problems(name):
    if name == 'artifacts/.gitkeep': return []
    parts = name.replace('\\', '/').split('/')
    if any(part.casefold() in PRIVATE_DIRS for part in parts) or any(part.casefold() in FORBIDDEN_STATE for part in parts):
        return ['private state path']
    if Path(name).suffix.casefold() in {'.db','.sqlite','.sqlite3','.dpapi','.log','.bak','.ldb','.lock'}: return ['state file extension']
    if any(part in {'..', ''} for part in parts): return ['invalid package path']
    if parts[0] not in PUBLIC_TOP and name not in PUBLIC_FILES:
        return ['outside public source allowlist']
    return []

# Digests identify retired private share labels without republishing the labels.
SHARE_DIGESTS = {'f4469c16c0f0b1d8c051a0fd9bb58a853a76cd39c0407eda74a5822ac4a95773', '661668b740a6fcbc32b584a044389b5794bf6fff1a8e91c631b926254d704a1e', '4ef14b4bf3de5020bf8e0a19dac95b6797aa60a4d9cafdc16e3fbe8f64559308', 'ba5fcd120f9fb3fd5191f7e490100e19bdad5ba5a4151caaf06076f0abb85102'}

def problems(name, content):
    issues = path_problems(name)
    if issues: return issues
    text = content.decode('utf-8', errors='ignore') + content.decode('utf-16le', errors='ignore')
    for address in re.findall(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])',text):
        try: ip=ipaddress.ip_address(address)
        except ValueError: continue
        octets = tuple(int(part) for part in address.split('.'))
        if octets[:2] == (192,168) or octets[0] == 10 or (octets[0] == 172 and 16 <= octets[1] <= 31) or (octets[0] == 100 and 64 <= octets[1] <= 127):
            issues.append('concrete private network address')
            break
    for word in re.findall(r'(?=([\u4e00-\u9fff]{4}))',text):
        if hashlib.sha256(word.encode()).hexdigest() in SHARE_DIGESTS:
            issues.append('private share label')
            break
    return list(set(issues))

def source_files():
    result=subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT,capture_output=True,check=True)
    return sorted(set(result.stdout.decode().split('\0'))-{''})

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--package',type=Path)
    args=parser.parse_args()
    failures=[]; count=0
    if args.package:
        with zipfile.ZipFile(args.package) as archive:
            for item in archive.infolist():
                if item.is_dir(): continue
                count+=1
                name=item.filename
                # Source ZIPs may have a single distribution wrapper directory.
                parts=name.split('/')
                if len(parts)>1 and parts[0].casefold().startswith('codextools'):
                    name='/'.join(parts[1:])
                issues=path_problems(name)
                if not issues: issues=problems(name,archive.read(item))
                if issues: failures.append({'path':'<rejected-entry>' if path_problems(name) else name,'issues':issues})
    else:
        for name in source_files():
            issues=path_problems(name)
            if issues:
                count+=1
                failures.append({"path":"<rejected-entry>","issues":issues})
                continue
            path=ROOT/name
            if not path.is_file(): continue
            count+=1
            if not issues: issues=problems(name,path.read_bytes())
            if issues: failures.append({'path':'<rejected-entry>' if path_problems(name) else name,'issues':issues})
    print(json.dumps({'ok':not failures,'filesChecked':count,'failures':failures},ensure_ascii=False))
    return 1 if failures else 0

if __name__=='__main__': raise SystemExit(main())
