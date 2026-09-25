import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import installer


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.squad = {'uuid': 'squad-id', 'name': 'Default-Squad', 'inbounds': [{'uuid': 'existing-id'}]}

    def request(self, method, path, data=None):
        self.calls.append((method, path, data))
        if method == 'GET':
            return {'response': {'internalSquads': [self.squad]}}
        return {'response': {'uuid': 'squad-id'}}


class InstallerTests(unittest.TestCase):
    def test_profile_keeps_routing_and_fills_reality_values(self):
        config = installer.profile_for('node.example.com', 'VLESS-123', 'private-key')
        inbound = config['inbounds'][0]
        reality = inbound['streamSettings']['realitySettings']
        self.assertEqual(inbound['tag'], 'VLESS-123')
        self.assertEqual(reality['serverNames'], ['node.example.com'])
        self.assertEqual(reality['privateKey'], 'private-key')
        self.assertEqual(reality['target'], '/dev/shm/nginx.sock')
        self.assertEqual(config['routing']['rules'][0]['outboundTag'], 'BLOCK')
        self.assertEqual(config['routing']['rules'][1]['outboundTag'], 'warp')
        self.assertEqual(config['outbounds'][2]['settings']['servers'][0]['port'], 40000)

    def test_squad_preserves_previous_inbounds(self):
        api = FakeAPI()
        state = {'inbound_uuid': 'new-id'}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(installer, 'STATE', Path(directory) / 'state.json'), patch.object(installer, 'ask', return_value='1'):
                installer.configure_squad(api, state, 'en')
                self.assertEqual(state['squad_uuid'], 'squad-id')
                self.assertEqual(api.calls[1][2]['inbounds'], ['existing-id', 'new-id'])
                installer.configure_squad(api, state, 'en')
                self.assertEqual(len(api.calls), 2)

    def test_domains_reject_injection(self):
        self.assertTrue(installer.valid_domain('node.example.com'))
        self.assertFalse(installer.valid_domain('node.example.com;rm -rf /'))
        self.assertFalse(installer.valid_domain('localhost'))

    def test_certificate_hook_keeps_certbot_variable(self):
        hook = installer.renewal_hook('node.example.com')
        self.assertIn('$RENEWED_DOMAINS', hook)
        self.assertIn('/etc/letsencrypt/live/node.example.com/fullchain.pem', hook)
        self.assertNotIn('__NODE_DOMAIN__', hook)


if __name__ == '__main__':
    unittest.main()
