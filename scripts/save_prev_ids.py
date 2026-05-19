#!/usr/bin/env python3
"""Save current job IDs to /tmp/prev_ids.txt before the scraper runs."""
import json
import sys

try:
    data = json.load(open('docs/data/jobs.json'))
    ids  = {j['id'] for j in data.get('jobs', [])}
    open('/tmp/prev_ids.txt', 'w').write('\n'.join(ids))
    print(f'Saved {len(ids)} previous job IDs')
except FileNotFoundError:
    open('/tmp/prev_ids.txt', 'w').write('')
    print('No previous jobs.json — starting fresh')
except Exception as e:
    print(f'Warning: {e}', file=sys.stderr)
    open('/tmp/prev_ids.txt', 'w').write('')
