import datetime
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from src import telemetry


class TestTelemetry(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temp)
        self.env = self.enterContext(patch.dict(os.environ, XJTU_WW_TELEMETRY_FORCE='1',
            XJTU_WW_TELEMETRY_DISABLED='0', XJTU_WW_TELEMETRY_URL='https://example.invalid/v1/ping'))
        self.sender = self.enterContext(patch.object(telemetry, '_send', return_value=True))
        self.now = datetime.datetime(2026, 11, 27, 15, 59, tzinfo=datetime.timezone.utc)

    def report(self, version='v1.4.0', prior=False):
        return telemetry.report_startup_telemetry(self.root, version, prior, now=self.now)

    def test_first_id_and_classification_survive_network_failure(self):
        self.sender.side_effect = TimeoutError()
        self.assertFalse(self.report())
        first = self.sender.call_args.args[1]
        self.assertEqual(first['upgrade_via'], 'new_install')
        self.assertEqual(str(uuid.UUID(first['cid'])), first['cid'])
        self.assertFalse(telemetry.has_prior_configs(self.root))
        self.sender.side_effect = None
        self.assertTrue(self.report(prior=True))
        self.assertEqual(first, self.sender.call_args.args[1])
        self.assertFalse(self.report())
        self.now += datetime.timedelta(minutes=2)
        self.assertTrue(self.report())
        self.assertEqual(self.sender.call_args.args[1]['event'], 'active')

    def test_confirmed_upgrade_manual_change_rollback_and_migration(self):
        (self.root / 'configs').mkdir()
        (self.root / 'configs/settings.json').write_text('{}')
        self.assertTrue(self.report(prior=telemetry.has_prior_configs(self.root)))
        self.assertEqual(self.sender.call_args.args[1]['upgrade_via'], 'legacy_migration')
        telemetry.write_update_receipt(self.root, {'version':'v1.10.0','from_version':'v1.4.0','id':uuid.uuid4().hex})
        self.sender.return_value = False
        self.assertFalse(self.report('v1.10.0'))
        self.assertTrue((self.root / telemetry.RECEIPT).is_file())
        self.sender.return_value = True
        for ver, via in [('v1.10.0','in_app_update'),('v1.11.0','manual_upgrade'),('v1.4.0','rollback')]:
            self.assertTrue(self.report(ver))
            self.assertEqual(self.sender.call_args.args[1]['upgrade_via'], via)
        self.assertFalse((self.root / telemetry.RECEIPT).exists())

    def test_disabled_source_and_preview_do_not_send_or_allocate_id(self):
        with patch.dict(os.environ, XJTU_WW_TELEMETRY_DISABLED='1'):
            self.assertFalse(self.report())
        with patch.dict(os.environ, XJTU_WW_TELEMETRY_FORCE='0'), patch.object(sys,'frozen',False,create=True):
            self.assertFalse(self.report())
        self.assertFalse(self.report('dev-abcd'))
        (self.root / 'configs').mkdir()
        (self.root / 'configs/Basic Options.json').write_text(json.dumps({telemetry.TELEMETRY_OPTION:False}))
        self.assertFalse(self.report())
        self.sender.assert_not_called()
        self.assertFalse((self.root / 'configs/telemetry.json').exists())
