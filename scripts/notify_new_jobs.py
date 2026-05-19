#!/usr/bin/env python3
"""Compare new jobs.json against saved IDs and open a GitHub issue if new jobs found."""
import json
import os
import subprocess
import sys

prev_ids = set(open('/tmp/prev_ids.txt').read().splitlines()) - {''}

try:
    data = json.load(open('docs/data/jobs.json'))
except Exception as e:
    print(f'Could not read jobs.json: {e}')
    sys.exit(0)

jobs     = data.get('jobs', [])
new_jobs = [j for j in jobs if j['id'] not in prev_ids]

if not new_jobs:
    print('No new positions — skipping issue.')
    sys.exit(0)

print(f'{len(new_jobs)} new position(s) found — opening GitHub issue.')

lines = [f"**{len(new_jobs)} new position(s) found** — {data.get('last_updated', '')[:10]}\n"]
for j in new_jobs:
    badge = '★ stats/quant · ' if j.get('stats_highlight') else ''
    inst  = f" @ {j['institution']}" if j.get('institution') else ''
    loc   = f", {j['location']}" if j.get('location') else ''
    dl    = f" · deadline {j['deadline']}" if j.get('deadline') else ''
    lines.append(f"- [{j['title']}{inst}{loc}]({j['url']})  ")
    lines.append(f"  {badge}{j['type']}{dl}")
    lines.append("")

body  = '\n'.join(lines)
repo  = os.environ['REPO']
title = f"[Jobs] {len(new_jobs)} new ecology/statistics position(s)"

result = subprocess.run(
    ['gh', 'issue', 'create', '--repo', repo,
     '--title', title, '--body', body, '--label', 'jobs'],
    capture_output=True, text=True
)
if result.returncode == 0:
    print(f'Issue created: {result.stdout.strip()}')
else:
    # Label may not exist — retry without it
    result2 = subprocess.run(
        ['gh', 'issue', 'create', '--repo', repo,
         '--title', title, '--body', body],
        capture_output=True, text=True
    )
    if result2.returncode == 0:
        print(f'Issue created: {result2.stdout.strip()}')
    else:
        print(f'Failed: {result2.stderr}', file=sys.stderr)
        sys.exit(1)
