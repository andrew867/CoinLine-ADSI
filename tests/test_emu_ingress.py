import configparser
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from coinline_adsi.asterisk import Gateway


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'deploy/asterisk/config'


class EmulatorIngressTests(unittest.IsolatedAsyncioTestCase):
    async def test_delay_only_changes_emulator_alert(self):
        gateway = Gateway('http://example.test', 'synthetic', AsyncMock(), emu_alert_delay=1.25)
        try:
            self.assertEqual(gateway.first_alert_delay('emu-infoline'), 1.25)
            for route in ('infoline', 'lab', 'resident-lab', 'private-lab-infoline'):
                self.assertEqual(gateway.first_alert_delay(route), 0.25)
        finally:
            await gateway.http.aclose()
        for invalid in (0.249, 5.001, float('nan')):
            with self.assertRaises(ValueError):
                Gateway('http://example.test', 'synthetic', AsyncMock(), emu_alert_delay=invalid)

    async def test_named_endpoint_is_scoped_and_default_stays_authenticated(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read([CONFIG / 'pjsip.conf', CONFIG / 'pjsip-emu.conf'], encoding='utf-8')
        self.assertEqual(config['lab']['auth'], 'lab-auth')
        self.assertNotIn('auth', config['co'])
        self.assertEqual(config['co']['context'], 'coinline-emu')
        self.assertEqual(config['co']['dtmf_mode'], 'inband')
        self.assertEqual(config['co']['allow'], 'ulaw')
        self.assertEqual(config['co']['trust_id_inbound'], 'no')
        self.assertEqual(config['co']['media_address'], '127.0.0.1')
        self.assertEqual(config['emu-transport']['bind'], '0.0.0.0:5069')
        dialplan = [line.strip() for line in (CONFIG / 'extensions-emu.conf').read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith(';')]
        self.assertEqual(dialplan, ['[coinline-emu]', 'exten => 2374,1,Stasis(coinline,emu-infoline)',
                                   'same => n,Hangup()'])

    async def test_separate_loopback_ports_and_database(self):
        overlay = (ROOT / 'compose.emu.yaml').read_text()
        self.assertIn('name: coinline-adsi-emu', overlay)
        self.assertIn('target: gateway-emu', overlay)
        self.assertIn('127.0.0.1:5069:5069/udp', overlay)
        self.assertIn('127.0.0.1:18100-18139:18100-18139/udp', overlay)
        self.assertIn('coinline-adsi-emu_db', overlay)
        self.assertIn('ADSI_LOCAL_PRIVATE_CALLS: "0"', overlay)
        self.assertIn('ADSI_LOCAL_BANK_ENROLLMENT: "0"', overlay)
