#!/usr/bin/env python3
"""Verify source -> bundled seed -> optional staged runtime, without mutations."""
from pathlib import Path
import hashlib
import json
import sys
import tarfile

app = Path(sys.argv[1])
root = Path(__file__).resolve().parents[2]
seed = app / 'Contents/Resources/tproj-runtime-seed.tar.gz'
manifest = json.loads((app/'Contents/Resources/tproj-runtime-critical.json').read_text())
with tarfile.open(seed, 'r:gz') as archive:
    for name in ['tproj', 'tproj-remote-client', 'tproj-remote-host', 'tproj-respawn-guard']:
        expected = (root/'bin'/name).read_bytes()
        if manifest.get('bin/'+name) != hashlib.sha256(expected).hexdigest():
            raise SystemExit('Runtime manifest mismatch: '+name)
        member = archive.extractfile('tproj-runtime/bin/'+name)
        if member is None or member.read() != expected:
            raise SystemExit('Bundled runtime mismatch: '+name)
        if len(sys.argv) == 3 and (Path(sys.argv[2])/'bin'/name).read_bytes() != expected:
            raise SystemExit('Staged runtime mismatch: '+name)
if len(sys.argv) == 3:
    digest = hashlib.sha256(seed.read_bytes()).hexdigest()
    if (Path(sys.argv[2])/'.seed-sha256').read_text().strip() != digest:
        raise SystemExit('Staged runtime seed revision mismatch')
print('Runtime chain verified: source / bundle' + (' / staged' if len(sys.argv) == 3 else ''))
