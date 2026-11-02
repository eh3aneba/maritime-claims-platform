"""No app imports, DB, scanner or customer data; verify preflight even under -O."""
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
HELPER = HERE / 'hm05_selected_worker_replay.py'
SOURCE = HERE.parent / 'reviewer-packet-hm05-2026-11-01' / 'original.png'
LOAD = '''
import builtins, importlib.util
from types import SimpleNamespace
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name.split('.')[0] in {'app', 'sqlalchemy', 'fastapi', 'starlette'}:
        raise RuntimeError('forbidden_application_import')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
spec = importlib.util.spec_from_file_location('replay', HELPER)
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)
settings = SimpleNamespace(app_env='test', ai_provider='disabled', ocr_enabled=True,
    ocr_languages='eng+fas', malware_scan_enabled=True,
    external_evidence_live_provider_adapters_enabled=False,
    external_evidence_live_sftp_adapters_enabled=False)
'''


class ReplayGuardTests(unittest.TestCase):
    def run_guard(self, code, success=False):
        for flags in ([], ['-O']):
            with self.subTest(flags=flags, code=code):
                script = f'HELPER = {str(HELPER)!r}\nSOURCE = {str(SOURCE)!r}\n' + LOAD + code
                result = subprocess.run([sys.executable, *flags, '-c', script],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0 if success else 1, result.stderr)
                self.assertNotIn('forbidden_application_import', result.stderr)
                self.assertEqual(result.stdout, '')

    def test_import_is_inert_and_valid_synthetic_preflight_does_not_grant_acceptance(self):
        self.run_guard('replay.validate_settings(settings)\n'
                       'replay.validate_empty_counts([0, 0, 0])\n'
                       'replay.validate_database_name("hm05_synthetic")\n'
                       'replay.validate_source(open(SOURCE, "rb").read())\n', success=True)

    def test_each_unsafe_runtime_setting_is_rejected_in_both_modes(self):
        for key, value in dict(app_env='production', ai_provider='external',
                ocr_enabled=False, ocr_languages='eng', malware_scan_enabled=False,
                external_evidence_live_provider_adapters_enabled=True,
                external_evidence_live_sftp_adapters_enabled=True).items():
            self.run_guard(f'settings.{key} = {value!r}\nreplay.validate_settings(settings)\n')

    def test_non_worker_uid_rejected_before_application_import(self):
        self.run_guard('replay.os.getuid = lambda: 0\nreplay.main()\n')

    def test_existing_dataset_rejected_at_each_guarded_model_position(self):
        for counts in ([1, 0, 0], [0, 1, 0], [0, 0, 1]):
            self.run_guard(f'replay.validate_empty_counts({counts!r})\n')

    def test_wrong_database_name_rejected(self):
        for name in ('production', '', None):
            self.run_guard(f'replay.validate_database_name({name!r})\n')

    def test_changed_or_missing_source_bytes_rejected(self):
        for raw in (b'', b'invented changed raster bytes'):
            self.run_guard(f'replay.validate_source({raw!r})\n')


if __name__ == '__main__':
    unittest.main()
