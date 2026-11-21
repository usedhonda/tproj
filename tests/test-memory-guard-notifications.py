#!/usr/bin/env python3
"""Exercise aggregate notification episodes without processes or OS notifications."""
import pathlib
import subprocess

source = (pathlib.Path(__file__).resolve().parents[1] / 'extensions/memory/memory-guard').read_text()
aggregate = source.split('# --- Claude aggregate check ---\n', 1)[1].split('# --- Main loop ---', 1)[0]
harness = '''
WARN_MB=100
CRIT_MB=150
notices=0
calc_total_mb() { echo "$usage"; }
sleep() { :; }
log() { :; }
logger() { :; }
osascript() { notices=$((notices + 1)); }
get_killable_agents() { :; }
'''
harness += aggregate + '''
for usage in 110 120 160 170 120 160; do
  check_claude_aggregate
done
[[ "$notices" == 2 ]] || exit 1
usage=90
check_claude_aggregate
usage=120
check_claude_aggregate
[[ "$notices" == 3 ]] || exit 3
'''
subprocess.run(['/bin/bash', '-c', harness], check=True)
print('PASS: warning, escalation, oscillation suppression and recovery re-arm')
