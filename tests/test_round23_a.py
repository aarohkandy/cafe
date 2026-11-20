"""Round 23, batch A (M-3, S-9, S-10): the Bellhop label names no cause for a capped sample, and the NOT EXERCISED note no longer says that no number of
members changes the verdict."""
import itertools

from cafe.pm import stage1
from cafe.pm.physics import comms

CAUSE_WORDS = ("ray", "almost", "bound", "no number of members")


def _infos():
    runs_set = ((None, None), (1, 1), (1, 3), (2, 3))
    for done, total, capped, beyond, ran, runs in itertools.product(range(4), range(4), range(4), range(3), (True, False), runs_set):
        if done <= total and capped <= done:
            yield dict(done=done, total=total, capped=capped, beyond=beyond, runs_lo=runs[0], runs_hi=runs[1], ran=ran)


def test_m3_no_label_names_a_cause_and_a_capped_count_says_both_signs_over_the_cap():
    """Before: `capped` > 0 printed 'held at the assumed 60 dB bound ... (no ray reached the receiver, or almost none)', true of the positive side only."""
    n = 0
    for info in _infos():
        label = stage1._bellhop_label(info)
        assert not any(w in label.lower() for w in CAUSE_WORDS), (info, label)
        shows = "had a Bellhop excess beyond" in label
        assert shows == bool(info["capped"] and info["total"] and info["ran"]), (info, label)
        if shows:
            assert f"; {info['capped']} of them had a Bellhop excess beyond +-{comms.BELLHOP_EXCESS_CAP_DB:g} dB (the assumed cap) and were held at it" in label
        n += 1
    assert n == 480


def test_s9_the_not_exercised_note_says_what_the_rule_is_and_no_more():
    """Before: the note ended 'and no number of members changes that' (a larger ensemble draws other members, one of which may need the link)."""
    note = stage1.NOT_EXERCISED_NOTE
    assert note == "the link was required at no moment in any member, so no member could fail it: P(fail) = 0 here counts nothing (round 9, M-17)"
    assert not any(w in note for w in ("no number", "changes that", "any number"))

