"""Offline checks: importing the uploader does not start an upload."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import runpy
import sys
import unittest
import pandas as pd

SCRIPT = Path(__file__).resolve().parents[1] / 'upload_to_supabase.py'
select = runpy.run_path(str(SCRIPT))['select_new_rows']

def database(pages):
    db = Mock()
    db.table.return_value.select.return_value.order.return_value.range.return_value.execute.side_effect = pages
    return db

class SelectionTests(unittest.TestCase):
    def run_uploader(self, fail_insert=False):
        db = database([SimpleNamespace(data=[], count=0)])
        if fail_insert:
            db.table.return_value.insert.return_value.execute.side_effect = RuntimeError('private details')
        ai = Mock()
        ai.models.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1] * 768)])
        df = pd.DataFrame({'thai_text': [f'text-{i}' for i in range(8)], 'label': ['ham'] * 8})
        with patch.object(sys, 'argv', ['upload_to_supabase.py', '--limit', '5']), patch('dotenv.load_dotenv'), patch('supabase.create_client', return_value=db), patch('google.genai.Client', return_value=ai), patch('pandas.read_csv', return_value=df), patch('time.sleep'), patch('builtins.print'):
            if fail_insert:
                with self.assertRaises(SystemExit) as error:
                    runpy.run_path(str(SCRIPT), run_name='__main__')
                self.assertEqual(error.exception.code, 1)
            else:
                with self.assertRaises(SystemExit) as error:
                    runpy.run_path(str(SCRIPT), run_name='__main__')
                self.assertEqual(error.exception.code, 0)
        self.assertEqual(ai.models.embed_content.call_count, 5)
        db.table.return_value.insert.assert_called_once()
        self.assertEqual(len(db.table.return_value.insert.call_args.args[0]), 5)
        db.table.return_value.insert.return_value.execute.assert_called_once()

    def test_limit_five_flushes_final_batch(self):
        self.run_uploader()

    def test_insert_error_does_not_retry(self):
        self.run_uploader(fail_insert=True)

    def test_pages_duplicates_and_original_indices(self):
        df = pd.DataFrame({'thai_text': ['new', 'old', 'new', 'last'], 'label': ['ham'] * 4})
        db = database([SimpleNamespace(data=[{'thai_text': 'old', 'label': 'ham'}], count=2), SimpleNamespace(data=[{'thai_text': 'last', 'label': 'ham'}], count=2)])
        self.assertEqual(select(df, db).index.tolist(), [0])
        db.table.return_value.select.return_value.order.return_value.range.assert_any_call(1, 500)

    def test_unrelated_existing_rows_do_not_skip_csv(self):
        df = pd.DataFrame({'thai_text': ['new'], 'label': ['spam']})
        db = database([SimpleNamespace(data=[{'thai_text': 'other', 'label': 'ham'}], count=1)])
        self.assertEqual(len(select(df, db)), 1)

    def test_read_failure_stops(self):
        with self.assertRaises(RuntimeError):
            select(pd.DataFrame({'thai_text': ['new'], 'label': ['ham']}), database([RuntimeError()]))

    def test_conflict_stops(self):
        with self.assertRaises(ValueError):
            select(pd.DataFrame({'thai_text': ['same'], 'label': ['ham']}), database([SimpleNamespace(data=[{'thai_text': 'same', 'label': 'spam'}], count=1)]))

    def test_all_existing_and_empty_database(self):
        df = pd.DataFrame({'thai_text': ['same'], 'label': ['ham']})
        self.assertTrue(select(df, database([SimpleNamespace(data=[{'thai_text': 'same', 'label': 'ham'}], count=1)])).empty)
        self.assertEqual(len(select(df, database([SimpleNamespace(data=[], count=0)]))), 1)

if __name__ == '__main__':
    unittest.main()
