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


def test_the_runbook_says_what_budget_ci_does_on_the_demo_and_how_to_build_bellhop():
    """Review round 5, M-24 and M-25: nothing refuses `--budget ci` on the demo mission, and `make install` builds no Bellhop (an ambiguous acoustic link is
    judged on Thorp absorption alone without it), so the RUNBOOK names the script that builds it."""
    rb = text("docs", "RUNBOOK.md")
    assert "refused by design" not in rb and "plans and runs on any mission, including the demo" in rb
    assert "install_bellhop.sh" in rb and (ROOT / "bench" / "install_bellhop.sh").is_file() and "Thorp absorption alone" in rb
    # the script installs where the RUNBOOK's pm() mounts /data, so no copy step is needed (it wrote into homebase's ~/work/cafe/pmdata only)
    script = (ROOT / "bench" / "install_bellhop.sh").read_text()
    assert 'OUT="${CAFE_HOST_DATA:-$HOME/work/cafe/pmdata}/bin"' in script and "cp $HOME/work/cafe/pmdata" not in rb


# ---- review round 6 (M-19, M-21, L-W1)

def test_pmx_passes_the_commit_and_the_clean_tree_flag_exactly_as_pm_sh_does():
    """M-19: the image has no git, so a run through bin/pmx.sh recorded `git_dirty: null` and could back no golden or provenance claim."""
    flag = '-e CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi)'
    assert "-e CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null)" in text("bin", "pmx.sh") and flag in text("bin", "pmx.sh") and flag in text("pm.sh")


def test_make_acceptance_writes_into_its_own_directory_and_make_audit_checks_its_quick_run():
    """M-21: `--out $(RUNS)` made acceptance remove the user's reviewed runs/quick (run_one rmtree's out/<name>) before its own run."""
    mk = text("Makefile")
    recipe = re.search(r"^acceptance:.*\n\t(.*)$", mk, re.M).group(1)
    assert re.search(r"--out \$\(RUNS\)/acceptance$", recipe) and "--out $(RUNS) " not in recipe + " "
    assert "$(RUNS)/acceptance/quick" in re.search(r"^audit:.*\n\t(.*)$", mk, re.M).group(1)


def test_the_audit_spreads_the_suite_over_the_cpus_and_runs_the_real_time_tests_alone_in_the_same_coverage_record():
    """L-W1: the serial audit was killed at the 180 min job timeout on the hosted runner. Pass 1 is xdist by file without the real-time tests, pass 2
    those alone with --cov-append and the json report; the pins and the five tests are the ones mutmut deselects."""
    import tomllib
    from cafe.pm import audit
    one, two = audit.pytest_passes(4)
    assert one[one.index("-n") + 1] == "4" and one[one.index("--dist") + 1] == "loadfile"
    assert "--cov-append" not in one and "--cov-report=json:coverage.json" not in one
    assert {a for a in one if a.startswith("--deselect=")} == {f"--deselect={t}" for t in audit.SERIAL_TESTS} and len(audit.SERIAL_TESTS) == 7
    assert "--cov-append" in two and "--cov-report=json:coverage.json" in two and set(audit.SERIAL_TESTS) <= set(two) and "-n" not in two
    py = tomllib.loads(text("pyproject.toml"))["tool"]["mutmut"]["pytest_add_cli_args"]
    assert {a for a in py if a.startswith("tests/")} == set(audit.SERIAL_TESTS)
    slow = {"tests/test_emulator.py::test_query_under_10_ms_and_format", "tests/test_emulator.py::test_receipts_pass_and_fail_when_calibration_is_wrong"}
    assert slow <= set(audit.SERIAL_TESTS)                                           # round 8 M-5: the two tests that measure the query time run alone
    assert "pip install --no-cache-dir pytest-xdist==3.6.1 execnet==2.1.1" in text("Dockerfile.pm") and "--cov=cafe/pm" in one
    wf = text(".github", "workflows", "premission.yml")
    assert "no xdist" not in wf and "make audit" in wf and "$(PY) -m cafe.pm.audit" in text("Makefile")


def test_ci_and_the_runbook_install_the_same_pinned_arducopter_the_receipts_fly():
    """Round 6 integration (L-W2): the UAS SITL receipt test fails without the ArduCopter binary, and neither image nor the CI job installed it, so the
    hosted audit could not pass whatever its timing. bench/install_sitl.sh fetches ArduPilot's stable-4.7.1 SITL build and its two parameter files,
    pinned to the sha-256 of the files homebase runs (README); CI runs it and mounts the result at /work, and RUNBOOK 1 does the same for a lab."""
    import re
    sh, readme, rb = text("bench", "install_sitl.sh"), text("README.md"), text("docs", "RUNBOOK.md")
    pins = dict(re.findall(r"^get \"\$\S+\" (\S+) ([0-9a-f]{64})$", sh, re.M))
    assert set(pins) == {"arducopter", "copter.parm", "copter-X.parm"} and pins["arducopter"].startswith("011627d4") and "011627d4" in readme
    assert "firmware.ardupilot.org/Copter/stable-4.7.1/SITL_x86_64_linux_gnu/arducopter" in sh and "dbe792162d06cab66c3475fd5556bf7a120f119e" in sh
    wf = text(".github", "workflows", "premission.yml")
    assert wf.index("sh bench/install_sitl.sh $PWD/.work/sitl") < wf.index("make audit (code") and "-v $PWD/.work:/work:ro" in wf
    assert "sh bench/install_sitl.sh $CAFE_HOST_DATA/work/sitl" in rb and "-e CAFE_WORK=/data/work" in rb
    assert "-e CAFE_WORK=/data/work" in readme                                          # the README wrapper is the RUNBOOK one


# ---- review round 6, documents (M-21, M-25)

def test_the_runbook_names_the_directory_make_acceptance_writes_into():
    """M-21: `make acceptance` removed the user's runs/quick; the RUNBOOK says where its runs and tables are now."""
    rb = text("docs", "RUNBOOK.md")
    assert "runs/acceptance/<name>" in rb and "runs/acceptance/acceptance.json" in rb and "your `runs/quick` is not touched" in rb


def test_three_statements_the_code_outlived_do_not_come_back():
    """M-25: the pipeline passes theta_e (stage1 does), the UAS verdict is not the battery alone (q6: 55 of 64 members profile_incomplete), and
    env/wrf.py does not exist."""
    physics = text("docs", "PHYSICS.md")
    assert "does not pass `theta_e`" not in physics and "decided by the battery alone" not in physics and "The pipeline passes `theta_e`" in physics
    assert "theta_e_K=te" in text("cafe", "pm", "stage1.py") and "since then it passes `theta_e`" in row(37)
    assert not (ROOT / "cafe" / "pm" / "env" / "wrf.py").exists() and "env/wrf.py" not in text("requirements-pm.txt")
    assert "rotate_grid_to_earth" in text("requirements-pm.txt") and "def rotate_grid_to_earth" in text("cafe", "pm", "env", "conventions.py")


def test_the_ci_containers_run_as_the_runner_and_the_audit_log_is_uploaded():
    """Round 7 integration: as root, OpenFOAM's mpirun refused to start and both OpenFOAM tests failed on the hosted runner (they pass as uid 1000 on
    homebase, the RUNBOOK's pm() user); and the audit's whole output, the only place a hosted traceback is, was not kept."""
    wf = text(".github", "workflows", "premission.yml")
    runs = [ln for ln in wf.splitlines() if "docker run" in ln]
    assert len(runs) == 3 and all("-u $(id -u):$(id -g) -e HOME=/tmp" in ln for ln in runs)
    up = wf.split("- name: audit log")[1]
    assert "uses: actions/upload-artifact@v4" in up and "if: always()" in up
    assert "path: |" in up and "            audit.log\n" in up and "            coverage.json\n" in up  # round 8 M-40: the missed lines are in the upload
    assert "audit.log" in text(".gitignore")


def test_the_usv_speed_prior_says_its_width_is_not_an_uncertainty_of_this_model():
    """Round 7 M-15: the +-1.4 % prior read as the model's uncertainty; the platform source and the perturbation citation both say what it is."""
    import yaml
    plat = yaml.safe_load(text("platforms", "saildrone_explorer.yaml"))
    src = next(v["source"] for blk in plat.values() if isinstance(blk, dict) for k, v in blk.items() if k == "vpp_bias_sd")
    pert = yaml.safe_load(text("config", "perturbations.yaml"))["usv_vpp_bias"]
    assert "not an uncertainty of this model" in src and "not an uncertainty of this model" in str(pert)


# ---- review round 7, documents (M-38, M-45, M-46)

def test_the_runbook_says_what_fits_in_memory_and_that_the_figure_is_the_models():
    """M-38: a 30-day window is refused on a 32 GB machine on a figure that rests on one measured 6-day point; the RUNBOOK says so."""
    rb = text("docs", "RUNBOOK.md")
    assert "About 15 days of the demo box fit 32 GB" in rb and "(`pad_deg`)" in rb
    assert "The memory figure is the model's (linear from one measured 6-day point), not a measurement." in rb


def test_the_runbook_names_the_last_line_make_ci_prints():
    """M-45: the `ci` target ends with the ledger audit, whose last print is `audit: N problem(s)`, not the run's `report:` line."""
    recipe = re.search(r"^ci:.*\n((?:\t.*\n)+)", text("Makefile"), re.M).group(1).splitlines()
    assert recipe[-1].strip().startswith("$(PY) -m cafe.pm.audit --ledgers-only")
    assert 'print(f"audit: {len(problems)} problem(s)")' in text("cafe", "pm", "audit.py")
    assert "then `audit: 0 problem(s)` as the last line, and exit code 0" in text("docs", "RUNBOOK.md")


def test_the_round_7_corrections_of_rows_213_and_281_are_in_the_rows():
    """M-7 and M-46: row 213 named the member blocks the code does not build, and row 281 dated a measurement after the commit that carries it."""
    assert "the block of batch members after the ones stage 1b used" in row(213) and "(k + 1) x batch" in row(213) and "(amended by 346 and 347)" in row(213)
    assert "2026-11-05" not in row(281).split(" | ")[1] and "the date is not recorded" in row(281)
