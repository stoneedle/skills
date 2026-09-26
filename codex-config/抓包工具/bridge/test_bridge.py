import asyncio
import gzip
import json
import tempfile
from pathlib import Path
import aiohttp
from aiohttp import web
from backports import zstd
from claude_tap.trace_store import TraceStore
from bridge import Relay


async def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        seen = []
        sent = asyncio.Event()
        release = asyncio.Event()
        async def upstream(request):
            raw = await request.read()
            seen.append((raw, request.headers.get('Content-Encoding'), request.query_string))
            if request.query.get('error'):
                return web.json_response({'error': 'synthetic'}, status=429)
            if request.method == 'GET':
                return web.Response(status=426)
            response = web.StreamResponse(headers={'content-type': 'text/event-stream', 'Set-Cookie': 'synthetic-secret'})
            await response.prepare(request)
            await response.write(b'event: response.created\ndata: {"type":"response.created","response":{"id":"resp_test","output":[]}}\n\n')
            if request.query.get('slow'):
                sent.set()
                await release.wait()
            await response.write(b'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp_test","status":"completed","output":[],"usage":{"input_tokens":2,"output_tokens":1}}}\n\n')
            return response
        app = web.Application()
        app.router.add_route('*', '/{path:.*}', upstream)
        ur = web.AppRunner(app, auto_decompress=False, handler_cancellation=True)
        await ur.setup()
        us = web.TCPSite(ur, '127.0.0.1', 0)
        await us.start()
        port = us._server.sockets[0].getsockname()[1]
        relay = Relay(f'http://127.0.0.1:{port}', root/'state.json', root/'traces.sqlite3')
        rr = web.AppRunner(relay.app(), auto_decompress=False, handler_cancellation=True)
        await rr.setup()
        rs = web.TCPSite(rr, '127.0.0.1', 0)
        await rs.start()
        base = f'http://127.0.0.1:{rs._server.sockets[0].getsockname()[1]}'
        def recording(value):
            relay.state_file.write_text(json.dumps({'enabled': value, 'session': 'test'}))
        raw = b'{"model":"synthetic","stream":true,"input":[]}'
        async with aiohttp.ClientSession() as client:
            async def send(body=raw, encoding=None, query=''):
                h = {'Content-Type':'application/json','Authorization':'Bearer synthetic-secret'}
                if encoding:
                    h['content-encoding'] = encoding
                async with client.post(base+'/v1/responses'+query, data=body, headers=h) as r:
                    return r.status, await r.read()
            assert (await send())[0] == 200
            assert relay.saved == 0 and not relay.db.exists()
            recording(True)
            for encoding, body in [('gzip',gzip.compress(raw)), ('zstd',zstd.compress(raw))]:
                status, response = await send(body, encoding, '?a=1')
                assert status == 200 and b'response.completed' in response
                assert seen[-1] == (body, encoding, 'a=1')
            await relay.queue.join()
            assert relay.saved == 2
            task = asyncio.create_task(send(query='?slow=1'))
            await sent.wait()
            recording(False)
            release.set()
            assert (await task)[0] == 200
            await relay.queue.join()
            assert relay.saved == 3  # A request begun during recording finishes intact.
            assert (await send())[0] == 200
            await relay.queue.join()
            assert relay.saved == 3
            writer = relay.writers['test']
            store = TraceStore(relay.db)
            records = store.load_records(writer.session_id)
            store.close()
            assert len(records) == 3
            assert records[0]['request']['body']['model'] == 'synthetic'
            assert records[0]['response']['body']['status'] == 'completed'
            assert 'synthetic-secret' not in json.dumps(records)
            assert (await send(query='?error=1'))[0] == 429
            async with client.get(base+'/v1/responses',headers={'Upgrade':'websocket','Connection':'Upgrade'}) as r:
                assert r.status == 426
            original = relay.persist
            def broken(item):
                raise OSError('synthetic storage failure')
            relay.persist = broken
            recording(True)
            assert (await send())[0] == 200
            await relay.queue.join()
            assert relay.errors == 1
            relay.persist = original
            recording(False)
            sent.clear()
            release.clear()
            response = await client.post(base+'/v1/responses?slow=1',data=raw)
            await sent.wait()
            response.close()
            for _ in range(50):
                if relay.active == 0:
                    break
                await asyncio.sleep(.02)
            assert relay.active == 0, 'Client cancellation must release the upstream request'
            release.set()
            await ur.cleanup()
            assert (await send())[0] == 502
        await rr.cleanup()
        print('PASS: off/on; gzip/zstd byte fidelity; SSE; mid-stream stop; secret removal; 429; WS 426; storage failure isolation; client cancellation; upstream failure')


if __name__ == '__main__':
    asyncio.run(main())
