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
     '--title', title, '--body', body, '--label', 'jobs',
    '--assignee', 'BertvanderVeen'],
    capture_output=True, text=True
)
if result.returncode == 0:
    issue_url = result.stdout.strip()
    print(f'Issue created: {issue_url}')
    # Extract issue number and close it immediately — GitHub emails on create,
    # closing keeps the repo's issue list clean
    import re
    m = re.search(r'/issues/(\d+)', issue_url)
    if m:
        issue_number = m.group(1)
        close = subprocess.run(
            ['gh', 'issue', 'close', issue_number, '--repo', repo,
             '--comment', 'Closing automatically — notification sent by email.'],
            capture_output=True, text=True
        )
        if close.returncode == 0:
            print(f'Issue #{issue_number} closed.')
        else:
            print(f'Could not close issue: {close.stderr}')
else:
    # Label may not exist — retry without it
    result2 = subprocess.run(
        ['gh', 'issue', 'create', '--repo', repo,
         '--title', title, '--body', body,
        '--assignee', 'BertvanderVeen'],
        capture_output=True, text=True
    )
    if result2.returncode == 0:
        issue_url = result2.stdout.strip()
        print(f'Issue created: {issue_url}')
        import re
        m = re.search(r'/issues/(\d+)', issue_url)
        if m:
            subprocess.run(
                ['gh', 'issue', 'close', m.group(1), '--repo', repo,
                 '--comment', 'Closing automatically — notification sent by email.'],
                capture_output=True, text=True
            )
    else:
        print(f'Failed: {result2.stderr}', file=sys.stderr)
        sys.exit(1)
