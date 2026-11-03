"""The documents say what the code does where a reader would act on them (review round 1: M-17, M-31, M-32)."""
import re

from cafe.pm import config, credibility

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


def test_credibility_doc_limitation_table_is_the_code_s_list():
    """Round 2 integration: docs/CREDIBILITY.md section 5 carries every LIMITATIONS text of credibility.py, character for character, and L13 (run time)."""
    doc = text("docs", "CREDIBILITY.md")
    for x in credibility.LIMITATIONS:
        assert f"| {x['id']} | {x['text']} |" in doc, x["id"]
    assert "| L13 | sub-grid layer uncalibrated:" in doc


def test_credibility_doc_quotes_the_rules_verbatim():
    doc = text("docs", "CREDIBILITY.md").replace("\\|", "|")
    for k, v in credibility.RULES.items():
        assert v in doc, k


# ---- review round 3 (M-24, M-25, M-26)

def test_readme_quick_start_runs_every_python_command_inside_the_image_with_the_runbook_wrapper():
    """M-26: `make install` only builds the images; the fetch and the run need numpy, jax, xlb, gsw, so they go through pm()."""
    block = re.search(r"```bash\n(make install.*?)```", text("README.md"), re.S).group(1)
    wrapper = lambda t: re.search(r"pm\(\) \{ docker run.*?\"\$@\"; \}", t, re.S).group(0)  # noqa: E731
    assert wrapper(block) == wrapper(text("docs", "RUNBOOK.md"))
    cmds = [ln.split("#")[0].strip() for ln in block.splitlines() if ln and not ln.startswith(("export", "pm()", "       -"))]
    assert cmds[0] == "make install" and all(c.startswith("pm ") for c in cmds[1:]) and len(cmds) == 3
    assert "pm python -m cafe.pm fetch --mission missions/tepex_c_demo.yaml" in cmds and "make fetch" not in block
    mk = text("Makefile")
    assert re.search(r"^install:", mk, re.M) and (ROOT / "bin" / "run_premission").is_file()


def test_the_brief_and_decisions_33_do_not_claim_an_unconditional_mss_match():
    """M-25: the run's ledger (`spectrum_mss_vs_file`) says 35 % at the 90th percentile with 31 % of the points clipped."""
    for t in (text("docs", "BRIEF.md").split("| 2.3 |")[1].split("\n")[0], row(33)):
        assert "0.0 % where the short-wave share is not clipped" in t and "35 %" in t and "31 %" in t and "spectrum_mss_vs_file" in t


def test_runbook_says_which_run_directories_make_audit_checks_and_what_make_ci_ends_with():
    """M-24."""
    rb = text("docs", "RUNBOOK.md")
    assert "ledgers of runs/quick, runs/overnight and runs/4h (those that exist)" in rb and "audit --ledgers-only runs/ci" in rb


# ---- review round 4 (M-24)

def test_the_runbook_and_readme_wrappers_pass_the_commit_and_the_clean_tree_flag_because_the_image_has_no_git():
    """M-24: `ledger.git_dirty` falls back to $CAFE_GIT_DIRTY, which only pm.sh set, so a lab user's golden always had `dirty: null`."""
    flag = 'CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain)" ]; then echo 1; else echo 0; fi)'
    for t in (text("docs", "RUNBOOK.md"), text("README.md")):
        wrapper = re.search(r"pm\(\) \{ docker run.*?\"\$@\"; \}", t, re.S).group(0)
        assert "CAFE_GIT_SHA=" in wrapper and flag in wrapper
    assert "CAFE_GIT_DIRTY" in text("pm.sh") and "git" not in text("Dockerfile.pm").lower().replace("github", "")
    rb = text("docs", "RUNBOOK.md")
    assert "dirty: null" in rb and "git status --porcelain" in rb


def test_the_ci_workflow_can_reach_its_evidence_steps_and_finish():
    """Review round 5, M-16: the fast `make ci` and `make broken` come before `make audit` (red until the mutation record exists, and a serial full
    suite), every later step runs even after a red one, and the job timeout is longer than the audit."""
    import yaml
    job = yaml.safe_load(text(".github", "workflows", "premission.yml"))["jobs"]["audit-and-ci"]
    steps = job["steps"]
    ci, broken, audit = (next(i for i, s in enumerate(steps) if f"cafe-pm make {t}" in s.get("run", "")) for t in ("ci", "broken", "audit"))
    assert ci < broken < audit
    assert all(steps[i].get("if") == "always()" for i in (broken, audit)) and job["timeout-minutes"] >= 150
