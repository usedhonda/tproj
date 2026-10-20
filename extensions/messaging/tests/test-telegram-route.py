"""Real host/hub/MCP projection with synthetic service authentication only."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'unified'))
sys.path.insert(0, str(ROOT / 'external/kai-mcp'))
from host import Host
from hub import Hub
from protocol import HubError
from mailbox_tools import MailboxTools
from telegram_ingress import TelegramOwnerBinding


class RouteTest(unittest.TestCase):
    def test_ingress_atomic_origin_projection_reply_and_revocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            binding = TelegramOwnerBinding('binding-fixture', 'owner-fixture', 101,
                                           202, 202, 'kai', 1, time.time() + 3600)
            owner = asdict(binding)
            config = {'hosts': {'local': 'host-fixture'}, 'admin_token': 'admin-fixture',
                      'telegram_ingress_bindings': {binding.binding_id: {
                          'host_id': 'local', 'participant_id': 'telegram-service',
                          'owner_binding': owner}}}
            hub = Hub(Path(tmp) / 'hub.db', config)
            hub.dispatch({'op': 'directory_import', 'admin_token': 'admin-fixture',
                          'services': [{'participant_id': name + '-service', 'address': name,
                                        'host_id': 'local', 'kind': name}
                                       for name in ('telegram', 'kai')]})
            for name in ('telegram', 'kai'):
                hub.dispatch({'op': 'endpoint_register', 'host_id': 'local',
                              'host_token': 'host-fixture', 'endpoint_id': name + '-ep',
                              'participant_id': name + '-service', 'session': name,
                              'pane': '', 'pid': 0, 'pid_start': '0', 'runtime_id': name,
                              'platform': name})
            host = Host({'journal': str(Path(tmp) / 'host.db'), 'host_id': 'local',
                         'services': {'telegram': {'address': 'telegram',
                            'participant_id': 'telegram-service', 'binding_generation': 'service-one',
                            'allowed_addresses': ['kai'], 'telegram_ingress': {
                               'mode': 'long_poll', 'owner_binding': owner}}}}, recover=False)
            host.hub = lambda op, **args: hub.dispatch(dict(args, op=op,
                                         host_id='local', host_token='host-fixture'))
            # Kernel/launchd authentication has separate existing contract tests.
            host.service = lambda *_: {'endpoint_id': 'telegram-ep'}
            update = {'update_id': 12, 'message': {'message_id': 30,
                'from': {'id': 202, 'is_bot': False},
                'chat': {'id': 202, 'type': 'private'}, 'text': 'ask KAI directly'}}
            req = {'op': 'service_telegram_ingress', 'service_id': 'telegram',
                   'verified_bot_id': 101, 'raw_update': json.dumps(update)}
            accepted = host.dispatch(req, 1, os.getuid())
            mid = accepted['message_id']
            self.assertEqual(host.dispatch(req, 1, os.getuid())['duplicate'], True)
            message = host.hub('query', endpoint_id='kai-ep', message_id=mid)
            projected = MailboxTools._view(message)
            self.assertTrue(projected['origin_binding_active'])
            self.assertEqual(projected['external_origin']['owner_id'], 'owner-fixture')
            self.assertEqual(projected['body'], 'ask KAI directly')
            self.assertEqual(hub.db.execute('SELECT count(*) FROM messages').fetchone()[0], 1)
            with self.assertRaises(HubError):
                host.submit({'endpoint_id': 'telegram-ep'}, {'submission_id': 'forged',
                    'target': 'kai', 'body': 'forged', 'external_origin': projected['external_origin']})
            host.hub('submit', message={'message_id': 'kai-answer', 'in_reply_to': mid,
                     'sender_endpoint': 'kai-ep', 'body': 'direct answer'})
            answer = host.hub('query', endpoint_id='telegram-ep', message_id='kai-answer')
            self.assertEqual(answer['in_reply_to'], mid)
            self.assertEqual(answer['target_address'], 'telegram')
            config['telegram_ingress_bindings'][binding.binding_id]['owner_binding'] = asdict(replace(binding, revoked=True))
            message = host.hub('query', endpoint_id='kai-ep', message_id=mid)
            self.assertFalse(MailboxTools._view(message)['origin_binding_active'])
            self.assertEqual(message['external_origin']['owner_id'], 'owner-fixture')
            with self.assertRaises(HubError): host.dispatch(req, 1, os.getuid())
            host.db.close()
            hub.close()


if __name__ == '__main__':
    unittest.main()
