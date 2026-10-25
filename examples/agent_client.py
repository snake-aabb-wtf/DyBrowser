"""Standard-library client example. Start dybrowser.py serve first."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dybrowser.client import Client


def unwrap(response):
    if not response['ok']:
        raise RuntimeError(json.dumps(response['error'], ensure_ascii=False))
    return response['data']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='about:blank')
    parser.add_argument('--close', action='store_true')
    parser.add_argument('--session-id', help='reuse an existing persistent Session ID')
    args = parser.parse_args()
    client = Client()
    info = unwrap(client.resume(args.session_id) if args.session_id else client.create())
    sid = info['session_id']
    try:
        unwrap(client.action(sid, 'goto', url=args.url))
        snapshot = unwrap(client.action(sid, 'snapshot'))
        shot = unwrap(client.action(sid, 'screenshot'))
        print(json.dumps({'session': info, 'snapshot': snapshot, 'screenshot': shot},
                         ensure_ascii=False, indent=2))
        # Choose a relevant element after inspecting snapshot; for example:
        # node = next(n for n in snapshot['elements'] if n['text'] == 'Continue')
        # unwrap(client.action(sid, 'click', snapshot_id=snapshot['snapshot_id'], ref=node['ref']))
    finally:
        if args.close:
            unwrap(client.close(sid))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
