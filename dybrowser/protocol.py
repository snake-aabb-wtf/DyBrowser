"""Validation and transport-independent JSON errors."""
import math


class ToolError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.details = code, details


def success(data):
    return {'ok': True, 'data': data}


def failure(error):
    result = {'code': getattr(error, 'code', 'internal_error'), 'message': str(error)}
    if getattr(error, 'details', None) is not None:
        result['details'] = error.details
    return {'ok': False, 'error': result}


def require(condition, message, code='invalid_request'):
    if not condition:
        raise ToolError(code, message)


# Required fields and accepted types. bool is deliberately not accepted as int.
FIELDS = {
    'goto': {'url': str}, 'back': {}, 'forward': {}, 'reload': {},
    'snapshot': {}, 'inspect': {}, 'text': {}, 'screenshot': {},
    'click': {}, 'fill': {'text': str}, 'type': {'text': str},
    'press': {'key': str}, 'hover': {}, 'select_option': {'value': str},
    'check': {}, 'uncheck': {}, 'wait': {}, 'scroll': {},
    'click_xy': {'x': (int, float), 'y': (int, float)},
    'evaluate': {'expression': str},
    'pages': {}, 'page_new': {}, 'page_switch': {'page_id': str},
    'page_close': {},
}
OPTIONAL = {
    'page_id': str, 'frame': str, 'timeout': int, 'snapshot_id': str,
    'ref': str, 'role': str, 'name': str, 'label': str, 'text': str,
    'css': str, 'exact': bool, 'nth': int, 'full_page': bool,
    'max_elements': int, 'max_chars': int, 'state': str, 'url': str,
    'ms': int, 'x': (int, float), 'y': (int, float), 'button': str,
    'value': str, 'key': str, 'expression': str, 'arg': object,
    'wait_until': str,
    'mode': str, 'max_depth': int, 'max_nodes': int, 'include_hidden': bool,
}
ELEMENT_ACTIONS = {'click', 'fill', 'type', 'hover', 'select_option', 'check',
                   'uncheck', 'inspect', 'text'}
LOCATOR_FIELDS = {'ref', 'snapshot_id', 'role', 'name', 'label', 'css',
                  'text', 'nth', 'exact', 'frame'}
ACTION_FIELDS = {
    'goto': {'url', 'wait_until'}, 'back': {'wait_until'},
    'forward': {'wait_until'}, 'reload': {'wait_until'},
    'snapshot': {'frame', 'css', 'mode', 'max_elements', 'max_chars',
                 'max_depth', 'max_nodes', 'include_hidden'},
    'inspect': {'max_chars'}, 'text': {'max_chars'},
    'screenshot': {'full_page'}, 'click': {'button'},
    'fill': {'text'}, 'type': {'text'}, 'press': {'key'}, 'hover': set(),
    'select_option': {'value'}, 'check': set(), 'uncheck': set(),
    'wait': {'url', 'ms', 'state'}, 'scroll': {'x', 'y'},
    'click_xy': {'x', 'y', 'button'}, 'evaluate': {'expression', 'arg'},
    'pages': set(), 'page_new': {'url'}, 'page_switch': set(), 'page_close': set(),
}


def validate_request(payload):
    require(isinstance(payload, dict), 'Request must be a JSON object')
    action = payload.get('action')
    require(isinstance(action, str) and action in FIELDS, 'Unknown or missing action')
    schema = OPTIONAL | FIELDS[action]
    for key, kind in FIELDS[action].items():
        require(key in payload, f'Missing field: {key}')
    for key, value in payload.items():
        if key == 'action':
            continue
        require(key in schema, f'Unknown field: {key}')
        kind = schema[key]
        require(isinstance(value, kind) and not
                (isinstance(value, bool) and kind != bool and kind != object),
                f'Invalid type for {key}')
        if type(value) in (int, float):
            require(math.isfinite(value), f'{key} must be finite')
    for key in ('page_id', 'frame', 'css', 'role', 'ref', 'snapshot_id'):
        if key in payload:
            require(bool(payload[key].strip()), f'{key} must not be empty')
    for key, low, high in [('timeout', 1, 120000), ('nth', 0, 100000),
                            ('max_elements', 1, 1000), ('max_chars', 100, 100000),
                            ('ms', 0, 10000), ('max_depth', 0, 20), ('max_nodes', 1, 2000)]:
        if key in payload:
            require(low <= payload[key] <= high, f'{key} must be in {low}..{high}')
    for key, choices in [('button', ('left', 'middle', 'right')),
                         ('state', ('attached', 'detached', 'visible', 'hidden')),
                         ('wait_until', ('commit', 'domcontentloaded', 'load', 'networkidle'))]:
        if key in payload:
            require(payload[key] in choices, f'Invalid {key}')
    locators = [k for k in ('ref', 'role', 'label', 'css') if k in payload]
    # text is a locator except when it is the payload of fill/type.
    if 'text' in payload and action not in ('fill', 'type'):
        locators.append('text')
    allowed = {'action', 'page_id', 'timeout'} | ACTION_FIELDS[action]
    if action in ELEMENT_ACTIONS | {'press', 'wait'}:
        allowed |= LOCATOR_FIELDS
    require(not (set(payload) - allowed), f'Unsupported fields for {action}: {sorted(set(payload) - allowed)}')
    require('name' not in payload or 'role' in payload, 'name requires role')
    require('snapshot_id' not in payload or 'ref' in payload, 'snapshot_id requires ref')
    require('exact' not in payload or any(k in locators for k in ('role', 'label', 'text')),
            'exact requires a role, label or text locator')
    require('nth' not in payload or (bool(locators) and 'ref' not in payload),
            'nth requires a locator other than ref')
    require('frame' not in payload or action == 'snapshot' or bool(locators),
            'frame requires an element locator or snapshot')
    require(len(locators) <= 1, 'Choose one locator: ref/role/label/text/css')
    if action in ELEMENT_ACTIONS:
        require(bool(locators), 'An element locator is required')
    if 'ref' in payload:
        require(bool(payload.get('snapshot_id')), 'ref requires snapshot_id')
        require('frame' not in payload, 'ref already identifies its frame')
    if action == 'wait':
        require(sum([bool(locators), 'url' in payload, 'ms' in payload]) == 1,
                'wait requires exactly one locator, url or ms')
        require('state' not in payload or bool(locators), 'state requires an element locator')
    if action == 'goto':
        require(bool(payload['url'].strip()), 'url must not be empty')
    if action == 'snapshot':
        mode = payload.get('mode', 'interactive')
        require(mode in ('interactive', 'dom'), 'mode must be interactive or dom')
        require(mode == 'dom' or not any(k in payload for k in ('max_depth', 'max_nodes', 'include_hidden')),
                'max_depth/max_nodes/include_hidden require mode=dom')
        require(mode != 'dom' or 'max_elements' not in payload,
                'mode=dom uses max_nodes instead of max_elements')
    return dict(payload)
