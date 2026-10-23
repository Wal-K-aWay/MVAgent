"""Bounded, event-preserving Train feedback. Chinese mirror: docs/skill-feedback-prompts.md."""
from copy import deepcopy
import json
import re


_EVENT_FIELDS = ('history', 'actions', 'request_feedback')
_VIEW_FIELDS = {
    'global': {'question', 'videos', 'history', 'answer', 'selected_cards'},
    'video': {'instruction', 'duration_sec', 'prior_memory', 'actions', 'report',
              'status', 'selected_cards', 'request_feedback', 'error'},
}


def _size(value):
    return len(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def _events(field, value):
    if field != 'history':
        if not isinstance(value, list):
            raise ValueError(f'{field} must be an array of public events')
        return value
    if not isinstance(value, str):
        raise ValueError('history must be rendered public text')
    if not value.strip() or value.strip() == '(none)':
        return []
    # Runtime uses Event N — action; older explicit Step headings are also whole blocks.
    starts = list(re.finditer(r'(?m)^(?:Event|Step) [1-9]\d*[ \t]*(?:—|–|-|:)[ \t]*\S[^\n]*$', value))
    if not starts or value[:starts[0].start()].strip():
        return [value]
    return [value[start.start():end].rstrip('\n') for start, end in
            zip(starts, [item.start() for item in starts[1:]] + [len(value)])]


def _omitted(indices):
    ranges = []
    for index in indices:
        if ranges and index == ranges[-1][1] + 1:
            ranges[-1][1] = index
        else:
            ranges.append([index, index])
    return ranges


def format_feedback(example: dict, max_chars: int) -> dict:
    """Format already-projected, untruncated views; never sample, score or summarize.

    The budget is this result's JSON length with ensure_ascii=False and indent=2.
    Identical fields and exact event prefixes occur once. Each arm's remaining
    events keep their original order and index; equal indices do not imply pairing.
    """
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError('max_chars must be a positive integer')
    if not isinstance(example, dict) or not isinstance(example.get('parent'), dict):
        raise ValueError('A complete public parent view is required')
    if not isinstance(example.get('feedback'), dict):
        raise ValueError('Whole-question feedback is required')
    allowed = {'parent', 'candidate', 'candidate_same_local_context', 'candidate_context_changed', 'feedback'}
    if set(example) - allowed:
        raise ValueError('Unknown feedback fields; project role-visible data first')
    candidate_keys = [key for key in ('candidate', 'candidate_same_local_context') if key in example]
    if len(candidate_keys) > 1:
        raise ValueError('Provide only one candidate view')
    candidate_key = candidate_keys[0] if candidate_keys else None
    views = {key: deepcopy(example[key]) for key in ('parent', *candidate_keys)}
    role = 'global' if 'question' in views['parent'] else 'video'
    identifying_field = 'question' if role == 'global' else 'instruction'
    for view in views.values():
        if (not isinstance(view, dict) or identifying_field not in view
                or set(view) - _VIEW_FIELDS[role]):
            raise ValueError('Expected an untruncated public view of the same role')
        for field in _EVENT_FIELDS:
            if field in view:
                _events(field, view[field])
    output = {key: deepcopy(value) for key, value in example.items() if key not in views}
    output['shared'] = {}
    output['parent'] = views['parent']
    if candidate_key:
        output[candidate_key] = views[candidate_key]
        output['visible_views_identical'] = views['parent'] == views[candidate_key]

    streams = []

    def pack(events, offset=0):
        records = [{'index': offset + index + 1, 'event': event} for index, event in enumerate(events)]
        result = {'event_count': len(records), 'events': records, 'omitted_ranges': []}
        streams.append((result, records))
        return result

    if candidate_key:
        parent, candidate = views['parent'], views[candidate_key]
        for field in list(parent):
            if field in candidate and parent[field] == candidate[field]:
                output['shared'][field] = parent.pop(field)
                candidate.pop(field)
        for field in _EVENT_FIELDS:
            if field not in parent or field not in candidate:
                continue
            before, after = _events(field, parent[field]), _events(field, candidate[field])
            prefix = 0
            while prefix < min(len(before), len(after)) and before[prefix] == after[prefix]:
                prefix += 1
            parent[field] = pack(before[prefix:], prefix)
            candidate[field] = pack(after[prefix:], prefix)
            if prefix:
                output.setdefault('shared_event_prefixes', {})[field] = pack(before[:prefix])

    for view in (output['shared'], *views.values()):
        for field in _EVENT_FIELDS:
            if field in view and not isinstance(view[field], dict):
                view[field] = pack(_events(field, view[field]))
    if _size(output) <= max_chars:
        return output

    def retain(destination, records, kept):
        destination['events'] = [record for index, record in enumerate(records) if index in kept]
        destination['omitted_ranges'] = _omitted(
            record['index'] for index, record in enumerate(records) if index not in kept)

    kept = [set() for _ in streams]
    for destination, records in streams:
        retain(destination, records, set())
    if _size(output) > max_chars:
        raise ValueError('Protected public fields and omission metadata exceed max_chars')

    # Preserve final evidence and the first divergent event before interior events.
    priorities = [list(dict.fromkeys([len(records) - 1, 0, *range(1, len(records) - 1)]))
                  if records else [] for _, records in streams]
    for rank in range(max(map(len, priorities), default=0)):
        for number, (destination, records) in enumerate(streams):
            if rank >= len(priorities[number]):
                continue
            index = priorities[number][rank]
            kept[number].add(index)
            retain(destination, records, kept[number])
            if _size(output) > max_chars:
                kept[number].remove(index)
                retain(destination, records, kept[number])
    return output
