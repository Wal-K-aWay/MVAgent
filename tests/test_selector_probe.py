"""Selector probe inputs, controlled factors, and honest outcome accounting."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from eval.skill_eval.selector_probe import pin_manifest, run_case, summarize, validate_cases, variants
from skill_evolution.configs.manual import ENTRY_STYLES


def definition():
    return {'role': 'video', 'methods': [
        {'key': key, 'strategies': {'concise': f'Observe {key}.', 'procedural': f'Inspect {key} carefully.'},
         'applicability': {style: f'{style} applicability for {key}.' for style in ENTRY_STYLES}}
        for key in ('presence', 'timing')]}


class SelectorProbeTest(unittest.TestCase):
    def test_input_boundaries(self):
        video = {'id': 'v', 'role': 'video', 'task': 'Locate the event.', 'state': {'history': ''}, 'has_evidence': False}
        global_case = {'id': 'g', 'role': 'global', 'task': 'Compare these videos.',
                       'state': {'videos': {'video_1': {'duration_sec': 10}}}, 'has_evidence': False}
        self.assertEqual(validate_cases([video, global_case]), [video, global_case])
        for state in ({'history': 'PRIVATE MEMORY'}, {'history': '', 'videos': {}}, {'question': 'GLOBAL QUESTION'}):
            with self.assertRaises(ValueError): validate_cases([{**video, 'state': state}])
        for metadata in ({'duration_sec': -1}, {'duration_sec': True}, {'duration_sec': 1, 'path': 'SECRET'}):
            with self.assertRaises(ValueError):
                validate_cases([{**global_case, 'state': {'videos': {'video_1': metadata}}}])
        with self.assertRaises(ValueError): validate_cases([video, video])
        with self.assertRaises(ValueError): validate_cases([{**video, 'ground_truth': 'A'}])

    def test_wording_keeps_body_and_reverse_changes_only_ids(self):
        values = variants(definition())
        self.assertEqual(len(values), 6)
        for style in ENTRY_STYLES:
            normal, normal_map = values[style, 'normal']
            reverse, reverse_map = values[style, 'reversed']
            self.assertEqual(normal_map, {'1': 'presence', '2': 'timing'})
            self.assertEqual(reverse_map, {'1': 'timing', '2': 'presence'})
            self.assertEqual(normal.cards[0].strategy, reverse.cards[1].strategy)
            self.assertEqual(normal.cards[0].when_to_use, reverse.cards[1].when_to_use)
            self.assertEqual(normal.cards[0].strategy, 'Observe presence.')
            self.assertEqual(len(normal.sha256), 64)
            self.assertNotEqual(normal.sha256, reverse.sha256)

    def test_errors_are_not_abstentions(self):
        base = {'role': 'video', 'style': 'broad', 'order': 'normal'}
        rows = [{**base, 'status': status, 'selected_methods': methods} for status, methods in
                [('ok', ['timing']), ('ok', []), ('invalid', []), ('error', [])]]
        result = summarize(rows)
        group = result['groups'][0]
        self.assertEqual([group[k] for k in ('selected', 'abstained', 'invalid', 'error')], [1, 1, 1, 1])
        self.assertEqual(group['selected_methods'], {'timing': 1})
        self.assertIn('not selection correctness', result['interpretation'])

    def test_resume_rejects_changed_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            manifest = {'source': 'fixed', 'configuration': 'fixed'}
            first = pin_manifest(output, manifest)
            self.assertEqual(first, pin_manifest(output, deepcopy(manifest)))
            with self.assertRaises(ValueError): pin_manifest(output, {**manifest, 'configuration': 'changed'})

    def test_native_selection_raw_persistence_and_no_call_resume(self):
        class Client:
            calls = 0

            def json_chat(self, **kwargs):
                self.calls += 1
                self.messages = kwargs['messages']
                return {'status': 'ok', 'value': {'selected_skill_ids': ['2']}, 'raw_response': '{"selected_skill_ids":["2"]}'}

        case = {'id': 'v', 'role': 'video', 'task': 'Locate the event.', 'state': {'history': ''}, 'has_evidence': False}
        bank, mapping = variants(definition())['broad', 'normal']
        with tempfile.TemporaryDirectory() as temporary:
            client = Client()
            kwargs = dict(model=client, output=Path(temporary), manifest_hash='fixed', timeout=5)
            row = run_case(case, 'broad', 'normal', bank, mapping, **kwargs)
            self.assertEqual(row['selected_methods'], ['timing'])
            self.assertEqual(row['status'], 'ok')
            self.assertEqual(len(row['artifacts']), 3)
            self.assertEqual(run_case(case, 'broad', 'normal', bank, mapping, **kwargs), row)
            self.assertEqual(client.calls, 1)
            self.assertNotIn('Observe timing.', str(client.messages))


if __name__ == '__main__':
    unittest.main()
