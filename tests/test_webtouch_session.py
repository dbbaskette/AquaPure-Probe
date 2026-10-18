"""Exercise the real WebTouch reader without HA or live vendor access."""
import ast
import __future__
import asyncio
from collections.abc import Mapping
from http.cookies import SimpleCookie
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse, parse_qs, quote
import unittest

SOURCE = Path(__file__).parents[1] / 'custom_components/aquapure_probe/coordinator.py'
TREE = ast.parse(SOURCE.read_text())
NODES = [node for node in TREE.body if (
    isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id.startswith(('_WEBTOUCH_', '_PORTAL_', '_SALT_', '_OFFLINE_', '_ACTION_'))
        for t in node.targets
    )
) or isinstance(node, ast.AsyncFunctionDef) and node.name in ('_read_webtouch_salt', '_read_webtouch_salt_session')]

async def no_delay(_):
    pass

class Response:
    def __init__(self, payload=None, status=200, cookie=None, content=None):
        self.payload, self.status = payload, status
        self.cookies = SimpleCookie()
        if cookie:
            self.cookies['newIOSession'] = cookie
        self.content = content
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def json(self, **kwargs): return self.payload
    async def text(self): return ''

class Display:
    def __init__(self, session): self.session = session
    async def iter_any(self):
        yield b"<script>parent.printNL('screen','Home');</script>"
        await self.session.status_opened.wait()
        for chunk in self.session.salt_chunks:
            yield chunk

class Session:
    """Require explicit cookies instead of relying on a shared cookie jar."""
    def __init__(self, protocol='v2', stream_url='https://webtouch.iaqualink.net/display'):
        self.protocol, self.stream_url = protocol, stream_url
        self.salt_chunks = [b"<script>parent.printNL('text','Salt 2700 PPM');</script>"]
        self.calls = []
        self.closed = False
        self.fail_start = False
        self.status_opened = asyncio.Event()
    def detach(self): self.closed = True
    def get(self, url, **kwargs):
        self.calls.append(('GET', url, kwargs))
        if url.endswith('/userId'): return Response({'id': 'test-user'})
        if url.endswith('/locations'): return Response([{'name': 'Talokan', 'touchLink': 'pool-link'}])
        if url.endswith('/init'):
            if self.protocol == 'v1' and '/v2/' in url: return Response(status=401)
            return Response({'label': 'Talokan', 'serverConnection': self.stream_url,
                             'actionIdMasterStart': 'start', 'actionIdMasterId': 'status'},
                            cookie='display-session')
        if url == self.stream_url:
            self.check_cookie(kwargs)
            assert kwargs['allow_redirects'] is False
            assert 'headers' not in kwargs
            return Response(content=Display(self))
        if url.endswith('/command'):
            self.command(kwargs, kwargs['params']['command'])
            return Response(status=500 if self.fail_start else 200)
        raise AssertionError('Unexpected URL')
    def post(self, url, **kwargs):
        self.calls.append(('POST', url, kwargs))
        self.command(kwargs, kwargs['json']['command'])
        return Response(status=500 if self.fail_start else 200)
    def check_cookie(self, kwargs):
        assert kwargs.get('cookies') == {'newIOSession': 'display-session'}, 'Display session cookie missing'
    def command(self, kwargs, command):
        self.check_cookie(kwargs)
        assert command in ('1', '6'), 'Equipment command must never be sent'
        if command == '6': self.status_opened.set()

class WebTouchTests(unittest.IsolatedAsyncioTestCase):
    async def read(self, session):
        names = {'Mapping': Mapping, 'Any': Any, 'HomeAssistant': Any, 're': re,
                 'parse_qs': parse_qs, 'urlparse': urlparse, 'quote': quote,
                 'time': __import__('time'),
                 'async_create_clientsession': session if callable(session) else lambda _, **kwargs: session,
                 'asyncio': SimpleNamespace(sleep=no_delay, Event=asyncio.Event,
                     create_task=asyncio.create_task, wait_for=asyncio.wait_for,
                     gather=asyncio.gather, TimeoutError=asyncio.TimeoutError)}
        exec(compile(ast.Module(body=NODES, type_ignores=[]), str(SOURCE), 'exec', flags=__future__.annotations.compiler_flag), names)
        return await names['_read_webtouch_salt'](None,
            SimpleNamespace(id_token='test-token', client_id='test-client'),
            SimpleNamespace(serial='test-pool', name='Talokan', data={}))
    async def test_v2_cookie_reaches_stream_and_display_commands(self):
        session = Session()
        self.assertEqual(await self.read(session), (2700, 'connected'))
        commands = [kw['json']['command'] for method, _, kw in session.calls if method == 'POST']
        self.assertEqual(commands, ['1', '6'])
        self.assertTrue(session.closed)
    async def test_v1_cookie_reaches_stream_and_display_commands(self):
        self.assertEqual(await self.read(Session(protocol='v1')), (2700, 'connected'))
    async def test_large_display_flush_does_not_trim_salt_before_parsing(self):
        session = Session()
        session.salt_chunks = [b"<script>parent.printNL('25','3||Salt 2700 PPM');</script>" + b' ' * 65536]
        self.assertEqual(await self.read(session), (2700, 'connected'))

    async def test_fragmented_salt_line_followed_by_large_padding(self):
        session = Session()
        session.salt_chunks = [b"<script>parent.printNL('25','3||Salt 27", b"00 PPM');</script>" + b' ' * 65536]
        self.assertEqual(await self.read(session), (2700, 'connected'))

    async def test_failed_display_retries_with_fresh_session_and_restart(self):
        sessions = []
        def create_session(_, **kwargs):
            session = Session()
            session.fail_start = not sessions
            sessions.append(session)
            return session
        self.assertEqual(await self.read(create_session), (2700, 'connected'))
        self.assertEqual(len(sessions), 2)
        self.assertTrue(all(session.closed for session in sessions))
        inits = [kw for _, url, kw in sessions[1].calls if url.endswith('/init')]
        self.assertTrue(all(kw['params']['restart'] == 'true' for kw in inits))

    async def test_controller_offline_is_reported_and_not_retried(self):
        session = Session()
        session.salt_chunks = [b"<script>parent.printNL('OFFLINE','');</script>"]
        self.assertEqual(await self.read(session), (None, 'controller offline'))
        self.assertTrue(session.closed)

    async def test_consecutive_polls_create_and_close_separate_sessions(self):
        created = []
        def create_session(_, **kwargs):
            self.assertFalse(kwargs['auto_cleanup'])
            session = Session()
            created.append(session)
            return session
        for _ in range(2):
            self.assertEqual(await self.read(create_session), (2700, 'connected'))
            self.assertTrue(created[-1].closed)
        self.assertEqual(len(created), 2)
        self.assertIsNot(created[0], created[1])

    async def test_session_cookie_never_sent_to_untrusted_stream(self):
        for url in ('https://example.com/display', 'http://webtouch.iaqualink.net/display',
                    'https://webtouch.iaqualink.net:444/display',
                    'https://user@webtouch.iaqualink.net/display'):
            session = Session(stream_url=url)
            self.assertEqual(await self.read(session), (None, 'not available'))
            self.assertFalse(any(call_url == url for _, call_url, _ in session.calls))

if __name__ == '__main__': unittest.main()
