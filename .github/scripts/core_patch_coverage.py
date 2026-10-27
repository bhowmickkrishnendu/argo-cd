"""Verify coverage of changed executable blocks in the core-mode client."""
import argparse
import json
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('profile')
parser.add_argument('--allow-missing', action='store_true')
args = parser.parse_args()
target = 'cmd/argocd/commands/headless/headless.go'
diff = subprocess.check_output(['git', 'diff', 'f5967c368cd2a3dd2d74c9a08a347c5ae6a2f522', '--unified=0', '--', target], text=True)
added = set()
line_number = 0
for line in diff.splitlines():
    hunk = re.match(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
    if hunk:
        line_number = int(hunk.group(1))
    elif line.startswith('+') and not line.startswith('+++'):
        added.add(line_number)
        line_number += 1
    elif line.startswith(' ') and not line.startswith('---'):
        line_number += 1
blocks = {}
for entry in Path(args.profile).read_text().splitlines()[1:]:
    match = re.match(r'(.+):(\d+)\.\d+,(\d+)\.\d+ (\d+) (\d+)$', entry)
    if not match or not match[1].endswith(target):
        continue
    start, end, statements, hits = map(int, match.groups()[1:])
    if statements and any(start <= line <= end for line in added):
        blocks[(start, end, statements)] = blocks.get((start, end, statements), 0) + hits
assert blocks, 'No changed executable blocks found'
total = sum(block[2] for block in blocks)
covered = sum(block[2] for block, hits in blocks.items() if hits)
missing = [{'start': block[0], 'end': block[1], 'statements': block[2]} for block, hits in blocks.items() if not hits]
print(json.dumps({'file': target, 'covered_statements': covered, 'total_statements': total,
                  'patch_statement_coverage': round(100 * covered / total, 2), 'uncovered_blocks': missing}, indent=2))
if missing and not args.allow_missing:
    raise SystemExit('Changed core kubeconfig statements are still uncovered')
