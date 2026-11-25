"""Run speech alignment and automated review on the testimony portion of a job."""
from copy import deepcopy
from dataclasses import replace
import re
from types import SimpleNamespace

from app.src.casecat.anchors import Revision
from app.src.casecat.elements import BYLINE_STYLE, CENTERED_STYLE, examination_style


def split_revision(revision, start):
    head, body, offset = [], [], 0
    for span in revision.spans:
        end = offset + len(span.content)
        if end <= start:
            head.append(span)
        elif offset >= start:
            body.append(span)
        else:
            cut = start - offset
            head.append(replace(span, content=span.content[:cut]))
            body.append(replace(span, identity=span.identity + '/body', content=span.content[cut:]))
        offset = end
    left = tuple(e for e in revision.elements if e.end <= start)
    right = tuple(replace(e, start=e.start-start, end=e.end-start)
                  for e in revision.elements if e.start >= start and e not in left)
    if len(left) + len(right) != len(revision.elements):
        raise ValueError('The start of testimony falls inside a native field.')
    return replace(revision, spans=tuple(head), elements=left), replace(revision, spans=tuple(body), elements=right)


def join_revision(head, body):
    values = dict(head.definitions)
    body_values = dict(body.definitions)
    conflicts = {e.name for e in head.elements if e.kind == 'field' and e.name in values
                 and body_values.get(e.name) != values[e.name]}
    if conflicts:
        # Keep the proposed wording as literal testimony where a body edit
        # would otherwise rename an unrelated occurrence on the cover.
        body_values.update((name, values[name]) for name in conflicts)
        body = replace(body, definitions=tuple(sorted(body_values.items())),
                       elements=tuple(e for e in body.elements if e.kind != 'field' or e.name not in conflicts))
    offset = len(head.text)
    spans = list(head.spans)
    tail = body.spans
    if spans and tail and tail[0].identity == spans[-1].identity + '/body':
        spans[-1] = replace(spans[-1], content=spans[-1].content + tail[0].content)
        tail = tail[1:]
    return Revision((*spans, *tail), (*head.elements, *(replace(e, start=e.start+offset, end=e.end+offset)
                    for e in body.elements)), body.all_caps, body.definitions)


def remap_review(review, original, incoming):
    if review is None:
        return None
    result = deepcopy(review)
    for decision in result.get('pending_decisions', ()):
        for key in ('ranges', 'highlights'):
            decision[key] = [[original(a), original(b), incoming(c), incoming(d)]
                             for a, b, c, d in decision[key]]
    for row in (*result.get('locations', ()), *result.get('evidence', {}).get('occurrences', ())):
        row['start'], row['end'] = incoming(row['start']), incoming(row['end'])
    for row in (*result.get('automatic_changes', ()), *result.get('off_record_changes', ())):
        if 'ranges' in row:
            row['ranges'] = [[original(a), original(b), incoming(c), incoming(d)] for a, b, c, d in row['ranges']]
        for key, mapper in (('original_range', original), ('incoming_range', incoming),
                            ('range', original if row.get('side') == 'original' else incoming)):
            if key in row:
                row[key] = [mapper(p) for p in row[key]]
    return result


def joined_snapshot(original_head, incoming_head, snapshot):
    if snapshot is None:
        return None
    original, incoming, review = snapshot
    left = join_revision(original_head, original)
    right = left if original == incoming and original_head == incoming_head else join_revision(incoming_head, incoming)
    return left, right, remap_review(review, lambda p: p+len(original_head.text), lambda p: p+len(incoming_head.text))


_WORDS = re.compile(r"\w+(?:['’]\w+)*")
_REPORTER = re.compile(r'(?im)^[ \t]*(?:(?:MR\.|THE)\s+)?REPORTER:[ \t]*')
_LABEL = re.compile(r'^[ \t]*(?:(?:THE |MR\. )?REPORTER|SPEAKER \d+):[ \t]*', re.I)


def response_body(prefix, text):
    reporters = list(_REPORTER.finditer(prefix))
    if not reporters:
        return text
    oath_end = re.search(r'\bexamined\s+and\s+testified\s+as\s+follows\s*[:.]?[ \t]*(?:\r?\n)?',
                         text[:450], re.I)
    if oath_end:
        recorded = [m[0].casefold() for m in _WORDS.finditer(text[:oath_end.end()])]
        printed = [m[0].casefold() for m in _WORDS.finditer(prefix[:reporters[-1].start()])]
        if len(recorded) >= 10 and printed[-len(recorded):] == recorded:
            text = text[oath_end.end():].lstrip('\r\n')
    script = prefix[reporters[-1].end():].strip()
    reference = list(_WORDS.finditer(script))
    count = 0
    cut = 0
    speaker = ''
    # Drop only completed sentences matched from the start of the script.
    # Keeping the last sentence boundary preserves a corrected name or license.
    for line in re.finditer(r'[^\r\n]+', text):
        label = _LABEL.match(line[0])
        offset = label.end() if label else 0
        different = False
        for word in _WORDS.finditer(line[0], offset):
            if count >= len(reference) or word[0].casefold() != reference[count][0].casefold():
                different = True
                break
            expected = reference[count]
            count += 1
            if count >= 4 and (count == len(reference) or re.match(r'[.!?](?:\s|$)', script[expected.end():])):
                end = line.start() + word.end()
                tail = re.match(r'[.,!?]*[ \t]*', text[end:])
                cut = end + tail.end()
                speaker = label[0] if label and cut < line.end() else ''
        if different or count == len(reference):
            break
    return speaker + text[cut:].lstrip('\r\n') if cut else text


def _format_examinations(text):
    """Put the numbered blank line in the proposal before speaker offsets are recorded."""
    lines = []
    for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        stripped = line.lstrip(' \t')
        style = examination_style(stripped)
        if style:
            line = stripped
        if style == BYLINE_STYLE:
            last = len(lines)
            while last and not lines[last - 1].strip():
                last -= 1
            if last and examination_style(lines[last - 1]) == CENTERED_STYLE:
                lines[last:] = ['']
        lines.append(line)
    return '\n'.join(lines)


def begin_body_review(state, text, bundle, job, *, head=None, exclude_off_record=True):
    from app.src.casecat.presentation import apply_continuation_layout
    from app.src.suggestion_filter import begin_review, index_speaker_fields

    def normalize_continuations(revision, candidates):
        full = join_revision(head, revision) if head is not None else revision
        offset = len(head.text) if head is not None else 0
        return apply_continuation_layout(job.with_revision(full), bundle, revision, offset, candidates)

    return begin_review(state, _format_examinations(text), exclude_off_record=exclude_off_record,
                        index_fields=index_speaker_fields(head) if head is not None else None,
                        normalize_continuations=normalize_continuations if job and bundle else None)


def begin_document_review(state, text, *, exclude_off_record=True, full_document=False):
    start = state.body_position(state.original)
    if not start:
        return begin_body_review(state, text, state.bundle, state.job, exclude_off_record=exclude_off_record)
    head, body = split_revision(state.original, start)
    draft = SimpleNamespace(original=body)
    text = text[state.body_position(state.incoming):] if full_document else response_body(head.text, text)
    undo = begin_body_review(draft, text, state.bundle, state.job, head=head, exclude_off_record=exclude_off_record)
    _, state.incoming, state.review = joined_snapshot(head, head, (body, draft.incoming, draft.review))
    return joined_snapshot(head, head, undo)


def auto_accept_document(state, *, disabled_rules, remember_undo=None):
    from app.src.suggestion_filter import auto_accept
    from app.src.suggestions import GROUPING_VERSION
    review = state.review or {}
    filtered = review.get('automatic_filter') == 1
    if (filtered and review.get('grouping_version', 1) < GROUPING_VERSION
            or not filtered and 'pending_decisions' in review):
        from app.src.review_upgrade import upgrade_automatic
        return upgrade_automatic(state, disabled_rules, remember_undo)
    if filtered:
        return []
    a = state.body_position(state.original)
    if not a:
        return auto_accept(state, disabled_rules=disabled_rules)
    b = state.body_position(state.incoming)
    left, original = split_revision(state.original, a)
    right, incoming = split_revision(state.incoming, b)
    local = SimpleNamespace(original=original, incoming=incoming,
                            review=remap_review(state.review, lambda p: max(0, p-a), lambda p: max(0, p-b)))
    auto_accept(local, disabled_rules=disabled_rules)
    state.original, state.incoming, state.review = joined_snapshot(left, right, (local.original, local.incoming, local.review))
    return state.review['automatic_changes']
