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
FORBIDDEN_STATE = {'provider.json','activation.dpapi','nas-drives.json','codextools-nas-guide.json'}
# Digests identify retired private share labels without republishing the labels.
SHARE_DIGESTS = {'f4469c16c0f0b1d8c051a0fd9bb58a853a76cd39c0407eda74a5822ac4a95773', '661668b740a6fcbc32b584a044389b5794bf6fff1a8e91c631b926254d704a1e', '4ef14b4bf3de5020bf8e0a19dac95b6797aa60a4d9cafdc16e3fbe8f64559308', 'ba5fcd120f9fb3fd5191f7e490100e19bdad5ba5a4151caaf06076f0abb85102'}

def problems(name, content):
    issues = []
    if Path(name).name.casefold() in FORBIDDEN_STATE or 'PrivatePlugins' in Path(name).parts or 'CompanyAccess' in Path(name).parts:
        issues.append('company/private state')
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
            entries=((item.filename,archive.read(item)) for item in archive.infolist() if not item.is_dir())
            for name,body in entries:
                count+=1
                issues=problems(name,body)
                if issues: failures.append({'path':name,'issues':issues})
    else:
        for name in source_files():
            path=ROOT/name
            if not path.is_file(): continue
            count+=1
            issues=problems(name,path.read_bytes())
            if issues: failures.append({'path':name,'issues':issues})
    print(json.dumps({'ok':not failures,'filesChecked':count,'failures':failures},ensure_ascii=False))
    return 1 if failures else 0

if __name__=='__main__': raise SystemExit(main())
