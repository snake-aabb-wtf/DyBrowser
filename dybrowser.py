"""DyBrowser command line. stdout is machine-readable JSON."""
import argparse
import json
from pathlib import Path
import sys

from dybrowser.client import Client
from dybrowser.protocol import ToolError, failure, require


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Persistent local CfT control for AI agents')
    parser.add_argument('--port', type=int, default=8765, help='local service port (default 8765)')
    sub = parser.add_subparsers(dest='command', required=True)
    server = sub.add_parser('serve', help='run foreground service until stop or Ctrl+C')
    server.add_argument('--port', type=int, default=argparse.SUPPRESS)
    server.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parent)
    sub.add_parser('status')
    sub.add_parser('stop')
    sessions = sub.add_parser('session').add_subparsers(dest='session_command', required=True)
    create = sessions.add_parser('create')
    create.add_argument('--profile-id')
    create.add_argument('--headless', action='store_true')
    sessions.add_parser('list')
    sessions.add_parser('close').add_argument('session_id')
    request = sub.add_parser('request', help='JSON request from argument, --file, or UTF-8 stdin')
    request.add_argument('session_id')
    request.add_argument('payload', nargs='?')
    source = request.add_mutually_exclusive_group()
    source.add_argument('--json', dest='json_payload')
    source.add_argument('--file', type=Path)
    args = parser.parse_args()
    try:
        require(0 <= args.port <= 65535, 'port must be 0..65535')
        if args.command == 'serve':
            from dybrowser.server import serve
            serve(args.port, args.data_dir)
            return 0
        client = Client(f'http://127.0.0.1:{args.port}')
        if args.command == 'status':
            result = client.call('/health')
        elif args.command == 'stop':
            result = client.call('/shutdown', {})
        elif args.command == 'session':
            if args.session_command == 'create':
                options = {'headless':args.headless}
                if args.profile_id:
                    options['profile_id'] = args.profile_id
                result = client.create(**options)
            elif args.session_command == 'list':
                result = client.call('/sessions')
            else:
                result = client.close(args.session_id)
        else:
            require(not args.payload or not (args.json_payload or args.file), 'Choose one JSON input source')
            if args.file:
                raw = args.file.read_text(encoding='utf-8-sig')
            elif args.json_payload is not None:
                raw = args.json_payload
            elif args.payload is not None:
                raw = args.payload
            else:
                require(not sys.stdin.isatty(), 'Provide JSON argument, --file or stdin')
                raw = sys.stdin.buffer.read().decode('utf-8-sig')
            try:
                payload = json.loads(raw)
            except ValueError as exc:
                raise ToolError('invalid_json', str(exc)) from exc
            result = client.call(f'/sessions/{args.session_id}/actions', payload)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0 if result['ok'] else 1
    except Exception as exc:
        print(json.dumps(failure(exc), ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
