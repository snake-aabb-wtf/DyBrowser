"""Loopback HTTP transport; browser objects stay in one asyncio worker."""
import asyncio
import concurrent.futures
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
from urllib.parse import urlsplit

from .protocol import ToolError, require, success, failure
from .sessions import ROOT, SessionManager

MAX_BODY = 1024 * 1024


class Worker:
    def __init__(self, root):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.run, daemon=True, name='playwright')
        self.root = root
        self.manager = None

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def initialize(self):
        self.manager = SessionManager(self.root)
        await self.manager.start()

    def start(self):
        self.thread.start()
        self.submit(self.initialize(), 30)

    def submit(self, coroutine, timeout=150):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise ToolError('timeout', 'Service operation timed out') from exc

    async def route(self, method, path, payload):
        if path == '/health' and method == 'GET':
            return {'status': 'ready', 'protocol_version': 2, 'persistent_sessions': True}
        if path == '/sessions':
            if method == 'GET':
                return await self.manager.list()
            if method == 'POST':
                return await self.manager.create(payload)
        parts = path.strip('/').split('/')
        if len(parts) in (2, 3) and parts[0] == 'sessions':
            if len(parts) == 2 and method == 'DELETE':
                return await self.manager.close(parts[1])
            if len(parts) == 3 and parts[2] == 'actions' and method == 'POST':
                return await self.manager.action(parts[1], payload)
            if len(parts) == 3 and parts[2] == 'resume' and method == 'POST':
                require(not payload, 'resume does not accept options')
                return await self.manager.resume(parts[1])
            if len(parts) == 3 and parts[2] == 'identity' and method == 'DELETE':
                return await self.manager.forget(parts[1])
        raise ToolError('not_found', 'Unknown endpoint')

    def stop(self):
        try:
            if self.manager:
                self.submit(self.manager.shutdown(), 30)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=10)
            self.loop.close()


class LocalServer(ThreadingHTTPServer):
    daemon_threads = False
    allow_reuse_address = True

    def __init__(self, port, root):
        super().__init__(('127.0.0.1', port), Handler)
        self.worker = Worker(root)


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.0 closes connections, including rejected bodies we intentionally don't read.
    def log_message(self, *_):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def reply(self, status, data):
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)
        self.wfile.flush()
        if status >= 400:
            # Closing a Windows TCP socket with an unread rejected body can
            # reset the connection before the peer reads our JSON. Send FIN
            # after the response, then briefly drain pending input. Limit
            # both bytes and time; rejected input is never parsed/executed.
            try:
                self.connection.shutdown(socket.SHUT_WR)
                self.connection.settimeout(0.2)
                remaining = MAX_BODY * 2
                while remaining > 0:
                    chunk = self.rfile.read1(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except OSError:
                pass

    def handle_request(self):
        try:
            expected = f'127.0.0.1:{self.server.server_port}'
            require(self.headers.get('Host') in (expected, f'localhost:{self.server.server_port}'),
                    'Only local Host headers are accepted', 'forbidden')
            origin = self.headers.get('Origin')
            require(origin is None or origin in (f'http://{expected}', f'http://localhost:{self.server.server_port}'),
                    'Cross-origin requests are not allowed', 'forbidden')
            require(self.headers.get('Sec-Fetch-Site') not in ('cross-site', 'same-site'),
                    'Browser cross-site requests are not allowed', 'forbidden')
            require(not self.headers.get('Transfer-Encoding'), 'Chunked requests are not supported')
            length = self.headers.get('Content-Length', '0')
            require(length.isdigit(), 'Invalid Content-Length')
            length = int(length)
            require(length <= MAX_BODY, 'Request exceeds 1 MiB', 'request_too_large')
            payload = {}
            if self.command == 'POST':
                try:
                    payload = json.loads(self.rfile.read(length).decode('utf-8'),
                        parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v))) if length else {}
                except (ValueError, UnicodeError) as exc:
                    raise ToolError('invalid_json', 'Expected valid UTF-8 JSON') from exc
                require(isinstance(payload, dict), 'Request must be a JSON object')
            path = urlsplit(self.path).path
            if path == '/shutdown' and self.command == 'POST':
                self.reply(200, success({'stopping': True}))
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            result = self.server.worker.submit(self.server.worker.route(self.command, path, payload))
            self.reply(200, success(result))
        except ToolError as exc:
            status = {'forbidden':403, 'not_found':404, 'request_too_large':413,
                      'session_not_found':404, 'page_not_found':404}.get(exc.code, 400)
            self.reply(status, failure(exc))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.reply(500, failure(exc))

    do_GET = do_POST = do_DELETE = do_OPTIONS = do_PUT = handle_request


def serve(port=8765, root=ROOT):
    server = LocalServer(port, Path(root))
    try:
        server.worker.start()
        print(json.dumps(success({'status':'ready', 'host':'127.0.0.1',
                                  'port':server.server_port}), ensure_ascii=False), flush=True)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
    finally:
        # Drain request threads before stopping their event loop.
        server.server_close()
        server.worker.stop()
