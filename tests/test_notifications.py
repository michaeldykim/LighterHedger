import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from hedger.state import State
from hedger.discord import Discord, RateLimited, validate_webhook_url
from hedger.notifications import periodic_status
from hedger.telegram import Telegram

URL = 'https://discord.com/api/webhooks/123/test-token'


class NotificationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'state.sqlite3'
        self.state = State(self.path, {'test': True})

    def tearDown(self):
        self.state.close()
        self.temp.cleanup()

    def reopen(self, enabled=True):
        self.state.close()
        self.state = State(self.path, {'test': True}, discord_enabled=enabled)

    async def test_migration_new_only_and_disabled_backlog(self):
        self.state.event('old')
        self.state.data.update(stopped=True, paused='review', watch={'order_index': 42})
        self.state.data.pop('discord_outbox')  # Actual legacy shape.
        self.state.save()
        self.reopen()
        self.assertEqual(self.state.data['discord_outbox'], [])
        self.assertEqual(self.state.data['watch'], {'order_index': 42})
        self.assertTrue(self.state.data['stopped'])
        self.assertEqual(self.state.data['paused'], 'review')
        self.state.event('new')
        self.reopen(False)
        self.state.event('disabled')
        self.assertEqual(self.state.data['outbox'], ['old', 'new', 'disabled'])
        self.assertEqual(self.state.data['discord_outbox'], ['new'])

    async def test_shared_status_timer(self):
        self.reopen()
        engine = Mock()
        engine.summary.return_value = 'Stopped: True'
        with patch('hedger.notifications.asyncio.sleep', new=AsyncMock(
                side_effect=[None, None, asyncio.CancelledError])) as sleep:
            with self.assertRaises(asyncio.CancelledError):
                await periodic_status(self.state, engine)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [300, 300, 300])
        self.assertEqual(self.state.data['outbox'], ['Stopped: True'] * 2)
        self.assertEqual(self.state.data['discord_outbox'], self.state.data['outbox'])

    async def test_failure_independence_and_restart(self):
        self.reopen()
        self.state.event('alert')
        discord = Discord(None, URL, self.state)
        discord.send = AsyncMock(side_effect=RuntimeError('secret'))
        with patch('hedger.discord.asyncio.sleep', new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await discord.deliver()
        telegram = Telegram(None, 'token', 55, self.state, None)
        telegram.call = AsyncMock()
        with patch('hedger.telegram.asyncio.sleep', new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await telegram.deliver()
        self.reopen()
        self.assertEqual(self.state.data['outbox'], [])
        self.assertEqual(self.state.data['discord_outbox'], ['alert'])
        discord = Discord(None, URL, self.state)
        discord.send = AsyncMock()
        with patch('hedger.discord.asyncio.sleep', new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await discord.deliver()
        self.reopen()
        self.assertEqual(self.state.data['discord_outbox'], [])

    async def test_chunk_acknowledgments_survive_restart(self):
        self.reopen()
        self.state.event('a' * 2000 + 'b' * 2000 + 'truncated')
        discord = Discord(None, URL, self.state)
        discord.send = AsyncMock(side_effect=[None, RuntimeError()])
        with patch('hedger.discord.asyncio.sleep', new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await discord.deliver()
        self.reopen()
        self.assertEqual(self.state.data['discord_outbox'], ['b' * 2000])

    async def test_http_confirmation_mentions_and_rate_limits(self):
        response = Mock(status=200)
        response.json = AsyncMock(return_value={'id': '123'})
        context = AsyncMock()
        context.__aenter__.return_value = response
        session = Mock()
        session.post.return_value = context
        discord = Discord(session, URL, self.state)
        await discord.send('@everyone')
        self.assertEqual(session.post.call_args.kwargs['json']['allowed_mentions'], {'parse': []})
        self.assertEqual(session.post.call_args.kwargs['params'], {'wait': 'true'})
        response.status = 429
        response.json.return_value = {'retry_after': 7.5}
        with self.assertRaises(RateLimited) as caught:
            await discord.send('test')
        self.assertEqual(caught.exception.seconds, 7.5)
        self.state.data['discord_outbox'] = ['test']
        with patch('hedger.discord.asyncio.sleep', new=AsyncMock(side_effect=asyncio.CancelledError)) as sleep:
            with self.assertRaises(asyncio.CancelledError):
                await discord.deliver()
        sleep.assert_awaited_once_with(7.5)
        response.status = 200
        response.json.return_value = {}
        with self.assertRaises(RuntimeError):
            await discord.send('test')

    def test_url_validation(self):
        validate_webhook_url(URL)
        for url in ['http://discord.com/api/webhooks/1/token',
                    'https://example.com/api/webhooks/1/token', URL + '?wait=false']:
            with self.assertRaises(ValueError):
                validate_webhook_url(url)
