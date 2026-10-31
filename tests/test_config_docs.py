"""The documents say what the code does where a reader would act on them (review round 1: M-17, M-31, M-32)."""
import re

from cafe.pm import config

ROOT = config.ROOT


def text(*parts):
    return ROOT.joinpath(*parts).read_text()


def row(n):
    return next(line for line in text("DECISIONS.md").splitlines() if line.startswith(f"| {n} |"))


def test_runbook_pm_wrapper_turns_core_dumps_off_like_pm_sh():
    """M-31: pm.sh runs with --ulimit core=0 and the RUNBOOK wrapper did not."""
    wrapper = re.search(r"pm\(\) \{ docker run[^\n]*", text("docs", "RUNBOOK.md")).group(0)
    assert "--ulimit core=0" in wrapper and "--ulimit core=0" in text("pm.sh")


def test_runbook_says_how_the_slow_receipts_are_stored_and_which_failures_are_open_limitations():
    rb = text("docs", "RUNBOOK.md")
    assert "receipts --slow" in rb and ":not_run" in rb and "about 100 minutes" in rb
    for group in ("app.fea", "pm.emulator", "pm.physics.uas.slow"):
        assert group in rb
    assert "L08" in rb and "L09" in rb


def test_decisions_row_21_says_fetch_downloads_all_four_inputs():
    """M-32: row 21 said `make fetch` does not download the ocean or TAO data; s_ingest downloads orca, TAO, GEBCO and GOFS."""
    r = row(21)
    assert "does not download" not in r and "not yet called" not in r
    for name in ("orca.ingest", "tao.fetch_tao", "bathy.fetch_gebco", "hycom.fetch_gofs", "CAFE_OFFLINE"):
        assert name in r


def test_decisions_80_and_104_agree_on_the_worse_wall_model_error():
    assert "smaller stored error." not in row(80) and "larger (worse)" in row(80) and "worse of the two" in row(104)


def test_credibility_doc_has_no_claim_the_code_contradicts():
    """M-17: the wall-model check takes the worse error (wallmodel.stored_wall_error is a max); the sub-grid switches and bulk_stress_scale are used."""
    doc = text("docs", "CREDIBILITY.md")
    assert "takes the better" not in doc and "are not read" not in doc and "applied by nothing" not in doc
    src = text("cafe", "pm", "stage3", "wallmodel.py")
    assert "return max(float(json.loads(f.read_text())[\"err\"]) for f in fs)" in src[src.index("def stored_wall_error"):]


def test_decisions_rows_are_numbered_without_gaps_or_repeats():
    nums = [int(m.group(1)) for line in text("DECISIONS.md").splitlines() if (m := re.match(r"\| (\d+) \|", line))]
    assert nums == list(range(1, len(nums) + 1)) and nums[-1] >= 162
