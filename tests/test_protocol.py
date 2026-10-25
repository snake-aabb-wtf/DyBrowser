import unittest

try:
    from dybrowser.protocol import ToolError, validate_request, failure
except ImportError:
    ToolError = validate_request = failure = None


class ProtocolTests(unittest.TestCase):
    def test_dom_snapshot_options_are_validated_by_mode(self):
        request = {'action':'snapshot', 'mode':'dom', 'css':'#chat',
                   'max_depth':6, 'max_nodes':300, 'include_hidden':False}
        self.assertEqual(validate_request(request), request)
        invalid = [dict(request, mode='unknown'), dict(request, max_depth=-1),
                   dict(request, max_depth=21), dict(request, max_nodes=0),
                   dict(request, max_nodes=2001), dict(request, include_hidden='yes'),
                   dict(request, max_elements=10),
                   {'action':'snapshot', 'max_depth':2},
                   {'action':'click', 'css':'button', 'mode':'dom'}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ToolError):
                validate_request(value)

    def test_invalid_requests_are_rejected_before_actions(self):
        self.assertIsNotNone(validate_request, 'request validation is not implemented')
        for value in [[], None, {}, {'action': 'surprise'},
                      {'action': 'fill', 'text': True, 'css': 'input'},
                      {'action': 'click_xy', 'x': True, 'y': 3},
                      {'action': 'snapshot', 'timeout': 0},
                      {'action': 'snapshot', 'timeout': 120001}]:
            with self.subTest(value=value), self.assertRaises(ToolError):
                validate_request(value)

    def test_empty_explicit_targets_cannot_fall_back_to_current_page(self):
        for request in [
            {'action':'page_close', 'page_id':''},
            {'action':'page_switch', 'page_id':'   '},
            {'action':'fill', 'frame':'', 'css':'input', 'text':'wrong frame'},
            {'action':'click', 'css':''},
            {'action':'snapshot', 'frame':' \t'},
        ]:
            with self.subTest(request=request), self.assertRaises(ToolError):
                validate_request(request)

    def test_text_is_preserved_and_errors_are_structured(self):
        self.assertIsNotNone(validate_request, 'request validation is not implemented')
        for text in ['', '你好 Agent']:
            self.assertEqual(validate_request({'action': 'fill', 'css': 'input', 'text': text})['text'], text)
        result = failure(ToolError('invalid_request', 'bad input'))
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'invalid_request')

    def test_ignored_target_constraints_are_rejected(self):
        for request in [
            {'action':'click', 'css':'button', 'name':'Cancel'},
            {'action':'press', 'key':'Enter', 'name':'Cancel'},
            {'action':'click', 'role':'button', 'url':'https://unused.invalid'},
            {'action':'click', 'ref':'e1', 'snapshot_id':'s1', 'nth':1},
            {'action':'click', 'css':'button', 'exact':False},
            {'action':'click', 'css':'button', 'snapshot_id':'unused'},
            {'action':'wait', 'url':'*', 'state':'hidden'},
            {'action':'screenshot', 'frame':'iframe'},
        ]:
            with self.subTest(request=request), self.assertRaises(ToolError):
                validate_request(request)
