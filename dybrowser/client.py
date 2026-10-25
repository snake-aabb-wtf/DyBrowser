"""Standard-library-only client, suitable for embedding in an AI Agent."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener


class Client:
    def __init__(self, base_url='http://127.0.0.1:8765'):
        self.base_url = base_url.rstrip('/')
        self.opener = build_opener(ProxyHandler({}))

    def call(self, path, payload=None, method=None):
        method = method or ('GET' if payload is None else 'POST')
        raw = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        request = Request(self.base_url + path, data=raw, method=method,
                          headers={'Content-Type':'application/json'})
        try:
            with self.opener.open(request, timeout=150) as response:
                return json.load(response)
        except HTTPError as exc:
            with exc:
                return json.load(exc)
        except (URLError, TimeoutError, OSError) as exc:
            return {'ok':False, 'error':{'code':'service_unavailable',
                'message':f'{exc}; start dybrowser.py serve first'}}

    def create(self, **options):
        return self.call('/sessions', options)

    def action(self, session_id, action, **options):
        return self.call(f'/sessions/{session_id}/actions', {'action':action, **options})

    def close(self, session_id):
        return self.call(f'/sessions/{session_id}', method='DELETE')
