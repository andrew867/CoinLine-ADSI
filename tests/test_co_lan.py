import configparser
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from coinline_adsi.asterisk import CO_LAN_ROUTES, Gateway
from coinline_adsi.link import CONTINUOUS_DATA, VOICE_BETWEEN_SCREENS


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'deploy/asterisk/config'


class CoLanTests(unittest.IsolatedAsyncioTestCase):
    def test_exact_source_and_dialplan(self):
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(CONFIG / 'pjsip-co-lan.conf', encoding='utf-8')
        self.assertEqual(ini['co']['identify_by'], 'ip')
        self.assertNotIn('auth', ini['co'])
        self.assertEqual(ini['co']['context'], 'coinline-co-lan')
        self.assertEqual(ini['co-lan-identify']['match'], '@PEER_IP@/32')
        self.assertEqual(ini['co-lan-identify']['endpoint'], 'co')
        self.assertEqual(ini['co']['allow'], 'ulaw')
        self.assertEqual(ini['co']['dtmf_mode'], 'inband')
        self.assertEqual(ini['co']['media_address'], '@HOST_IP@')
        self.assertEqual(ini['co-lan-transport']['external_signaling_address'], '@HOST_IP@')
        self.assertEqual(ini['co-lan-transport']['external_media_address'], '@HOST_IP@')
        dialplan = (CONFIG / 'extensions-co-lan.conf').read_text()
        self.assertEqual(set(re.findall(r'^exten => (\d+),', dialplan, re.M)),
                         {'2374', '6500', '6501', '6502', '6503', '6505', '6506', '6507', '6508'})
        self.assertEqual(set(re.findall(r'Stasis\(coinline,([^)]*)\)', dialplan)), set(CO_LAN_ROUTES))
        self.assertNotIn('include =>', dialplan)
        self.assertNotIn('exten => _', dialplan)

    def test_separate_ports_and_synthetic_banking(self):
        overlay = (ROOT / 'compose.co-lan.yaml').read_text()
        for expected in ('name: coinline-adsi-co-lan', 'target: gateway-co-lan', 'ADSI_NATIVE_MAIL: "1"',
                         ':5070:5070/udp', ':18200-18239:18200-18239/udp', 'coinline-adsi-co-lan_db',
                         'ADSI_SHADYBANK_MODE: "demo"', 'ADSI_SHADYBANK_SERVICE_KEY: ""',
                         'ADSI_LOCAL_BANK_ENROLLMENT: "0"', 'ADSI_LOCAL_PRIVATE_CALLS: "0"',
                         'ADSI_PRIVATE_BALANCES: "0"', 'ADSI_OIDC_DISCOVERY: ""'):
            self.assertIn(expected, overlay)
        self.assertNotIn('0.0.0.0:5070:', overlay)

    async def test_lan_profile_does_not_change_existing_routes(self):
        gateway = Gateway('http://example.test', 'fixture', AsyncMock(), co_lan_alert_delay=1.5)
        try:
            for route in CO_LAN_ROUTES:
                self.assertEqual(gateway.first_alert_delay(route), 1.5)
                self.assertEqual(gateway.interaction_profile(route),
                                 CONTINUOUS_DATA if route == 'co-lan-resident-lab' else VOICE_BETWEEN_SCREENS)
            for route in ('lab', 'infoline', 'balance-demo', 'private-lab-infoline', 'resident-lab'):
                self.assertEqual(gateway.first_alert_delay(route), .25)
                self.assertEqual(gateway.interaction_profile(route), CONTINUOUS_DATA)
            self.assertEqual(gateway.interaction_profile('emu-infoline'), CONTINUOUS_DATA)
        finally:
            await gateway.http.aclose()
