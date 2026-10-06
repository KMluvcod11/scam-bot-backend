"""Offline checks; no credentials, API requests, or user datasets."""
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch
import pandas as pd

ENGINE = Path(__file__).resolve().parents[1]


class ScriptSafetyTests(unittest.TestCase):
    def test_imports_do_not_start_work(self):
        scripts = [ENGINE / 'upload_to_supabase.py', ENGINE / 'translate_phishing.py']
        scripts += list((ENGINE.parent / 'scam-bot-backend' / 'scripts').glob('smoke_*.py'))
        with patch('dotenv.load_dotenv') as env, patch('pandas.read_csv') as read, patch('supabase.create_client') as db, patch('google.genai.Client') as ai:
            for script in scripts:
                runpy.run_path(str(script))
            for operation in (env, read, db, ai):
                operation.assert_not_called()

    def test_translation_separates_failure_and_saves_before_interrupt(self):
        module = runpy.run_path(str(ENGINE / 'translate_phishing.py'))
        df = pd.DataFrame({'label': ['Safe Email'] * 3, 'text': ['a', 'b', 'c']})
        for last, expected_code in [('ไทย', 1), (KeyboardInterrupt(), 130)]:
            with self.subTest(last=last), tempfile.TemporaryDirectory() as folder:
                output, failed = Path(folder) / 'ok.csv', Path(folder) / 'failed.csv'
                function = module['translate_rows']
                with patch.dict(function.__globals__, translate_to_line=Mock(side_effect=['สวัสดี', ValueError('PRIVATE'), last])), patch('builtins.print') as logs:
                    code = function(df, Mock(), output, failed)
                self.assertEqual(code, expected_code)
                success = pd.read_csv(output)
                errors = pd.read_csv(failed)
                self.assertEqual(success['thai_text'].tolist(), ['สวัสดี', 'ไทย'] if expected_code == 1 else ['สวัสดี'])
                self.assertEqual(errors['source_row'].tolist(), [2])
                self.assertEqual(errors['error_type'].tolist(), ['ValueError'])
                self.assertNotIn('PRIVATE', str(logs.call_args_list))

    def test_translation_retries_empty_results_then_raises(self):
        module = runpy.run_path(str(ENGINE / 'translate_phishing.py'))
        model = Mock()
        model.generate_content.return_value.text = ''
        with patch('time.sleep'), patch('builtins.print'), self.assertRaises(ValueError):
            module['translate_to_line']({'label': 'Safe Email', 'text': 'example'}, model)
        self.assertEqual(model.generate_content.call_count, 3)

    def test_translation_refuses_to_overwrite(self):
        module = runpy.run_path(str(ENGINE / 'translate_phishing.py'))
        with patch.object(Path, 'exists', return_value=True), patch('pandas.read_csv') as read, patch('builtins.print'):
            self.assertEqual(module['main'](), 1)
            read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
