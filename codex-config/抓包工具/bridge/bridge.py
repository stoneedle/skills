"""Loopback HTTP relay with opt-in Claude tap recording. No client launch/config writes."""
import argparse
import asyncio
import gzip
import json
import logging
import os
import time
import uuid
import zlib
from pathlib import Path

import aiohttp
from aiohttp import web
from backports import zstd
from claude_tap.proxy import HOP_BY_HOP, SENSITIVE_HEADER_KEYS, _build_record
from claude_tap.sse import SSEReassembler
from claude_tap.trace import TraceWriter
from claude_tap.trace_store import TraceStore
from claude_tap.trace_encoding import parse_request_body_for_trace

ROOT = Path(__file__).resolve().parent
LIMIT = 32 * 1024 * 1024


def header(headers, name):
    return next((v for k, v in headers.items() if k.lower() == name.lower()), '')


def decode(body, headers):
    encoding = header(headers, 'Content-Encoding').lower()
    if encoding == 'zstd':
        body = zstd.decompress(body)
    elif encoding == 'gzip':
        body = gzip.decompress(body)
    elif encoding == 'deflate':
        body = zlib.decompress(body)
    return body


def headers_for_relay(headers):
    excluded = set(HOP_BY_HOP) | {'host', 'content-length'}
    excluded.update(x.strip().lower() for x in headers.get('Connection', '').split(','))
    return [(k, v) for k, v in headers.items() if k.lower() not in excluded]


class Relay:
    def __init__(self, upstream, state_file, db):
        self.upstream = upstream.rstrip('/')
        self.state_file = Path(state_file)
        self.db = Path(db)
        self.queue = asyncio.Queue(maxsize=8)
        self.saved = self.dropped = self.errors = self.requests = 0
        self.active = 0
        self.last_path = None
        self.writers = {}

    def capture_id(self):
        try:
            state = json.loads(self.state_file.read_text(encoding='utf-8'))
            return state.get('session') if state.get('enabled') else None
        except (OSError, ValueError):
            return None

    async def lifecycle(self, app):
        # Restart always comes up with capture off, including after Windows login.
        self.state_file.write_text('{"enabled":false}', encoding='utf-8')
        self.client = aiohttp.ClientSession(auto_decompress=False, trust_env=False,
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=None))
        worker = asyncio.create_task(self.worker())
        yield
        await self.queue.join()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await self.client.close()

    async def worker(self):
        while True:
            item = await self.queue.get()
            try:
                await asyncio.to_thread(self.persist, item)
                self.saved += 1
            except Exception as exc:
                self.errors += 1
                logging.error('recording failed (%s); relay unaffected', type(exc).__name__)
            finally:
                self.queue.task_done()

    def persist(self, item):
        session, raw, request_headers, response_headers, payload, meta = item
        request_body = parse_request_body_for_trace(decode(raw, request_headers), request_headers)
        response_body = decode(payload, response_headers)
        events = None
        if 'text/event-stream' in header(response_headers, 'Content-Type'):
            parser = SSEReassembler(store_events=True)
            parser.feed_bytes(response_body + b'\n\n')
            response_body, events = parser.reconstruct(), parser.events
        else:
            response_body = parse_request_body_for_trace(response_body, response_headers)
        if session not in self.writers:
            store = TraceStore(self.db)
            sid = store.create_session(client='codex', proxy_mode='reverse')
            self.writers[session] = TraceWriter(sid, store=store,
                metadata={'integration': 'codex-tap-bridge', 'capture_group': session})
        writer = self.writers[session]
        record = _build_record(req_id=meta['id'], turn=writer.count + 1,
            duration_ms=meta['duration'], method=meta['method'], path_qs=meta['path'],
            req_headers={}, req_body=request_body, status=meta['status'],
            resp_headers={}, resp_body=response_body, sse_events=events,
            upstream_base_url=self.upstream)
        # Full removal, rather than Claude tap's default partial bearer prefix.
        record['request']['headers'] = {k: v for k, v in request_headers.items()
            if k.lower() not in SENSITIVE_HEADER_KEYS}
        record['response']['headers'] = {k: v for k, v in response_headers.items()
            if k.lower() not in SENSITIVE_HEADER_KEYS}
        try:
            writer._write_locked(record)
            if writer.storage_error_count:
                raise RuntimeError('trace storage reported an error')
            writer.close()
        finally:
            writer._store.close()

    async def status(self, request):
        return web.json_response({'service': 'codex-tap-bridge-v1',
            'pid': os.getpid(),
            'recording': bool(self.capture_id()), 'upstream': self.upstream,
            'requests': self.requests, 'active': self.active, 'saved': self.saved,
            'dropped': self.dropped, 'recording_errors': self.errors,
            'last_path': self.last_path, 'pending_records': self.queue.qsize()})

    async def handle(self, request):
        if not request.path.startswith('/v1/'):
            return web.Response(status=404)
        session = self.capture_id() if request.path.startswith('/v1/responses') else None
        started = time.monotonic()
        self.requests += 1
        self.active += 1
        self.last_path = request.path
        downstream = None
        try:
            raw = await request.read()
            async with self.client.request(request.method, self.upstream + request.raw_path,
                    headers=headers_for_relay(request.headers), data=raw,
                    allow_redirects=False) as upstream:
                downstream = web.StreamResponse(status=upstream.status,
                    headers=headers_for_relay(upstream.headers))
                await downstream.prepare(request)
                payload = bytearray()
                async for chunk in upstream.content.iter_any():
                    await downstream.write(chunk)
                    if session:
                        if len(payload) + len(chunk) <= LIMIT and len(raw) <= LIMIT:
                            payload.extend(chunk)
                        else:
                            session = None
                            payload.clear()
                            self.dropped += 1
                await downstream.write_eof()
                if session:
                    item = (session, raw, dict(request.headers), dict(upstream.headers), bytes(payload),
                        {'id': 'req_' + uuid.uuid4().hex, 'duration': int((time.monotonic()-started)*1000),
                         'method': request.method, 'path': request.raw_path, 'status': upstream.status})
                    try:
                        self.queue.put_nowait(item)
                    except asyncio.QueueFull:
                        self.dropped += 1
                return downstream
        except (aiohttp.ClientError, ConnectionError, asyncio.TimeoutError):
            if downstream is not None and downstream.prepared:
                if request.transport:
                    request.transport.close()
                return downstream
            return web.json_response({'error': {'message': 'Local Web GPT upstream unavailable'}}, status=502)
        finally:
            self.active -= 1

    def app(self):
        app = web.Application(client_max_size=128*1024*1024)
        app.cleanup_ctx.append(self.lifecycle)
        app.router.add_get('/bridge/status', self.status)
        app.router.add_route('*', '/{path:.*}', self.handle)
        return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=17842)
    parser.add_argument('--upstream', default='http://127.0.0.1:17841')
    parser.add_argument('--state', type=Path, default=ROOT/'capture-state.json')
    parser.add_argument('--db', type=Path, default=Path.home()/'.local/share/claude-tap/traces.sqlite3')
    args = parser.parse_args()
    logging.basicConfig(filename=ROOT/'service.log', level=logging.ERROR,
                        format='%(asctime)s %(levelname)s %(message)s')
    relay = Relay(args.upstream, args.state, args.db)
    web.run_app(relay.app(), host='127.0.0.1', port=args.port, access_log=None,
                auto_decompress=False, handler_cancellation=True, print=None)
