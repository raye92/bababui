from app.src.casecat.anchors import Revision, AnchoredSpan
from app.src.suggestions import suggestions, resolve


def speakers(names):
    old = Revision((AnchoredSpan('root', (), (), ''),))
    for i, name in enumerate(names):
        old = old._replace(len(old.text), len(old.text), '     ')
        old = old.insert_field(len(old.text), name, name)
        old = old._replace(len(old.text), len(old.text), f':  Passage number {i} has unique testimony.\n')
    return old


def test_majority_normalizes_matches_and_repoints_only_mismatched_occurrences():
    from app.src.suggestion_filter import prepare
    old = speakers(['MS. SIEMENS'] * 8 + ['MR. LEISER'] * 2)
    text = old.text.replace('MS. SIEMENS:', 'SPEAKER 3:').replace('MR. LEISER:', 'SPEAKER 3:')
    incoming, evidence = prepare(old, text)
    summary = evidence['speakers']['SPEAKER 3']
    assert summary['mapped'] == 'MS. SIEMENS'
    assert summary['counts'] == {'MS. SIEMENS': 8, 'MR. LEISER': 2}
    changes = suggestions(old, incoming)
    assert len(changes) == 2
    accepted, pending = resolve(old, incoming, changes[0], True)
    assert accepted.text.count('MR. LEISER:') == 1
    assert dict(accepted.definitions)['MR. LEISER'] == 'MR. LEISER'
    assert len(suggestions(accepted, pending)) == 1


def test_ties_and_single_votes_remain_unresolved():
    from app.src.suggestion_filter import prepare
    for names in (['MS. SIEMENS'], ['MS. SIEMENS', 'MR. LEISER']):
        old = speakers(names)
        incoming, evidence = prepare(old, old.text.replace('MS. SIEMENS:', 'SPEAKER 3:').replace('MR. LEISER:', 'SPEAKER 3:'))
        assert evidence['speakers']['SPEAKER 3']['mapped'] is None
        assert 'SPEAKER 3:' in incoming.text


def test_trailing_whitespace_is_restored_but_newlines_and_internal_spaces_remain():
    from app.src.suggestion_filter import prepare
    old = Revision((AnchoredSpan('root', (), (), 'First words.  \nSecond line. \nThird.'),))
    incoming, _ = prepare(old, 'First  words.\nSecond line.\n\nThird.')
    assert incoming.text == 'First  words.  \nSecond line. \n\nThird.'
    changes = suggestions(old, incoming)
    assert len(changes) == 2
    assert any(c.kind == 'structure' for c in changes)

def test_trailing_whitespace_is_restored_after_paragraph_split():
    from app.src.suggestion_filter import prepare
    old = Revision((AnchoredSpan('root', (), (),
                                'Q First sentence.  Would that be correct?  \nA Yes.'),))
    incoming, _ = prepare(old, 'Q First sentence.\nQ Would that be correct?\nA Yes.')
    assert incoming.text == 'Q First sentence.\nQ Would that be correct?  \nA Yes.'


def test_override_keeps_completed_decisions_and_frozen_evidence():
    from copy import deepcopy
    from types import SimpleNamespace
    from app.src.suggestion_filter import begin_review, override_speaker, track_decision
    old = speakers(['MS. SIEMENS']*8 + ['MR. LEISER']*2)
    state = SimpleNamespace(original=old, incoming=old, review=None)
    begin_review(state,old.text.replace('MS. SIEMENS:', 'SPEAKER 3:').replace('MR. LEISER:', 'SPEAKER 3:'))
    evidence = deepcopy(state.review['evidence'])
    c = suggestions(state.original,state.incoming)[0]
    before = state.incoming.text
    state.original,state.incoming=resolve(state.original,state.incoming,c,False)
    track_decision(state.review,c,before,state.incoming.text)
    override_speaker(state,'SPEAKER 3','MR. LEISER')
    assert state.review['evidence']==evidence
    assert len(suggestions(state.original,state.incoming))==8
    assert state.incoming.text.count('MR. LEISER:')==10
    override_speaker(state,'SPEAKER 3','MS. SIEMENS')
    assert state.incoming.text.count('MR. LEISER:')==1
    assert len(suggestions(state.original,state.incoming))==1


def test_names_inside_testimony_do_not_vote_and_multiple_labels_can_share_identity():
    from app.src.suggestion_filter import prepare
    old=speakers(['MS. SIEMENS']*4)
    lines=old.text.splitlines(keepends=True)
    text=''.join(p.replace('MS. SIEMENS:',f'SPEAKER {1 if i<2 else 2}:') for i,p in enumerate(lines))
    incoming,evidence=prepare(old,text)
    assert len(evidence['speakers'])==2
    assert all(s['mapped']=='MS. SIEMENS' for s in evidence['speakers'].values())
    assert not suggestions(old,incoming)
    _,evidence=prepare(old,old.text+'     Q    Did SPEAKER 5: say MS. SIEMENS?')
    assert not evidence['speakers']


def test_repeated_ambiguous_paragraphs_do_not_vote():
    from app.src.suggestion_filter import prepare
    old=speakers(['MS. SIEMENS']*2)
    old=old.revise(old.text.replace('number 1','number 0'))
    _,evidence=prepare(old,old.text.replace('MS. SIEMENS:','SPEAKER 3:'))
    assert evidence['speakers']['SPEAKER 3']['counts']=={}


def test_bylines_use_following_wording_without_inventing_qa_votes():
    from app.src.suggestion_filter import prepare
    old=speakers(['MS. SIEMENS']*2)
    old=old.revise(old.text.replace('     MS.', 'BY MS.').replace(':  Passage', ':\n     Q    Passage'))
    _,evidence=prepare(old,old.text.replace('MS. SIEMENS:', 'SPEAKER 3:'))
    assert evidence['speakers']['SPEAKER 3']['counts']=={'MS. SIEMENS':2}

def test_matching_native_speakers_keep_reference_identity_and_crlf_offsets():
    from app.tests.test_native_fields import field_job
    from app.src.casecat.project import NativeState
    from app.src.suggestion_filter import begin_review
    bundle,job=field_job()
    state=NativeState.load(bundle,job.key)
    begin_review(state,job.text.replace('MS. OLD','SPEAKER 3').replace('\n','\r\n'))
    assert not suggestions(state.original,state.incoming)
    assert state.original.elements==state.incoming.elements
    assert len(state.review['locations'])==2
    assert Revision.from_dict(state.incoming.to_dict())==state.incoming
