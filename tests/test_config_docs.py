"""The documents say what the code does where a reader would act on them (review round 1: M-17, M-31, M-32)."""
import json
import os
import re
import stat
import subprocess
import sys

from cafe.pm import config, credibility, pipeline
from cafe.pm.physics import comms

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
    assert "return None if problems else max(float(d[\"err\"]) for d in recs)" in src[src.index("def stored_wall_error"):]


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
    those alone with --cov-append and the json report; the pins and the seven tests are the ones mutmut deselects."""
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
    # round 10, M-34: said "demo box", pad-agnostic
    assert "About 15 days of the demo mission (its shipped `pad_deg` 2.0, 8 workers) fit 32 GB" in rb and "(`pad_deg`)" in rb
    assert "with the default pad about 10 days do" in rb
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


# ---- review round 8, documents (M-49, M-50, M-53, M-54, M-55, M-56)

def _runbook_section(start, end):
    rb = text("docs", "RUNBOOK.md")
    return rb[rb.index(start):rb.index(end)]


def test_the_runbook_names_every_mission_key_and_says_which_verdicts_to_trust():
    """M-50: BRIEF exit condition 5 asks that the RUNBOOK alone lets a lab member define a mission and know which verdicts to trust; it named neither
    `links`, `required_fraction`, `when`, `shore` nor `verdict`. Every top-level key and every `links` item key of the schema is named in step 3a."""
    import json
    schema = json.loads(text("cafe", "schemas", "mission.json"))
    sec = _runbook_section("### 3a. Write your own mission", "## 4. Measure this machine")
    keys = list(schema["properties"]) + list(schema["properties"]["links"]["items"]["properties"])
    missing = [k for k in keys if f"`{k}`" not in sec and f"`{k}:" not in sec]
    assert not missing, missing
    assert "cafe/schemas/mission.json" in sec and "### 5a. Which verdicts to trust" in text("docs", "RUNBOOK.md")
    trust = _runbook_section("### 5a. Which verdicts to trust", "## 6. With a GPU")
    for phrase in ("GO, MARGINAL, NO-GO", "EMULATED", "rule-of-three", "credibility.html", "assumed"):
        assert phrase in trust, phrase


def test_the_runbook_does_not_say_the_planner_never_overruns_stage_1():
    """M-53: the estimate is a lower bound (the code says so), and q8 ran 2.2 times over it (52.7 s planned, 117 s measured of a 900 s share)."""
    rb = text("docs", "RUNBOOK.md")
    assert "never overruns" not in rb
    assert "q8 ran 2.2 times over it (52.7 s planned, 117 s measured, of a 900 s share)" in rb and "(270 s of 240 s)" in rb


def test_every_package_in_requirements_txt_is_in_the_licence_file():
    """M-54: docs/LICENSES.md left out ten of the fourteen pinned packages, among them pymavlink (LGPL-3.0), which cafe/pm/physics/uas.py imports."""
    lic = text("docs", "LICENSES.md").lower()
    names = [re.split(r"[=<>~]", ln)[0].strip() for ln in text("requirements.txt").splitlines() if ln.strip() and not ln.startswith("#")]
    assert len(names) == 14 and [n for n in names if n.lower() not in lic] == []
    assert "LGPL-3.0" in text("docs", "LICENSES.md") and "from pymavlink import mavutil" in text("cafe", "pm", "physics", "uas.py")


def test_the_runbook_fetches_before_it_benches():
    """M-55: the stage-1 part of `make bench` needs the fetched environment cache and ends in SystemExit without it, so the document fetches first."""
    rb = text("docs", "RUNBOOK.md")
    assert rb.index("## 3. Fetch the mission's data") < rb.index("## 4. Measure this machine")
    assert "no environment cache" in text("bench", "throughput.py") and "pm python -m cafe.pm fetch --mission missions/tepex_c_demo.yaml" in rb
    assert "(step 3 is the\n  fetch)" in rb and "| an input is not cached | step 3 |" in rb and "step 4 is the fetch" not in rb


def test_the_runbook_says_to_commit_the_throughput_file_before_the_golden():
    """M-56: `make bench` rewrites the tracked config/throughput.json, the wrapper then reports a dirty tree, and the golden is refused from one."""
    bench = _runbook_section("## 4. Measure this machine", "## 5. Run the mission")
    assert "**Commit the new `config/throughput.json`**" in bench and "git commit -am 'throughput of this machine'" in bench
    assert "(commit the `config/throughput.json` of step 4 first)" in text("docs", "RUNBOOK.md")
    assert re.search(r"^bench:.*\n(?:\t.*\n)+", text("Makefile"), re.M) and "throughput.json" in text("bench", "throughput.py")


def test_physics_12_1_gives_the_curved_against_plane_earth_difference_at_nulls():
    """M-49: "within 2 km it is the plane-earth result (0.15 dB)" held for single distances and the ship-to-USV geometry; at interference nulls the two
    differ by 26 dB (UAS at 108.1 m over a calm sea), and the code's docstring says so too."""
    sec = text("docs", "PHYSICS.md")
    sec = sec[sec.index("### 12.1 RF: two-ray over the sea"):]
    sec = sec[:sec.index("\n### ", 10)]
    assert "Within 2 km it is the plane-earth result (0.15 dB)" not in sec
    assert "26 dB for the UAS at the top of its profile (ht 2.2 m, hr 108.1 m)" in sec and "0.8 dB for a surface pair" in sec
    doc = text("cafe", "pm", "physics", "comms.py")
    assert "0.15 dB." not in doc and "26 dB" in doc


OWNER_MARKER_RULE = " --exclude=/.pmx.owner"


def test_pm_sh_and_pmx_sh_read_one_filter_list_and_never_delete_what_they_exclude():
    """M-39: pm.sh synced without --delete (a removed test still ran on the server) and each script would have had its own list of the outputs to keep."""
    rules = text("bin", "sync_filters")
    for script in (text("pm.sh"), text("bin", "pmx.sh")):
        assert "--delete" in script and "--filter" in script and "sync_filters" in script
        assert "--delete-excluded" not in script and "--exclude" not in script.replace(OWNER_MARKER_RULE, "")        # but pmx.sh's owner marker (M-33)
    assert text("bin", "pmx.sh").count(OWNER_MARKER_RULE) == 1 and OWNER_MARKER_RULE not in text("pm.sh")
    for out in ("/runs/", "/config/throughput.json", "/config/subgrid.json", "/docs/mutation.json", "/mutants/", "/audit.log",
                "/coverage.json", "/tests/golden/***", "/report/***"):
        assert re.search(rf"^[-P] {re.escape(out)}$", rules, re.M), out
    assert not re.search(r"^P .*/$", rules, re.M), "a P rule on a directory needs the *** form"


def test_pmx_judges_a_detached_job_by_the_exact_session_name_or_an_rc_zero_log():
    """M-34: line 20 was `tmux ls | grep $TM`, a substring match over every session on the box."""
    pmx = text("bin", "pmx.sh")
    assert "grep $TM" not in pmx and "has-session -t =$TM" in pmx and "grep -qx rc=0" in pmx


def test_r11_m32_every_phony_make_target_has_a_rule():
    """Round 11 M-32: `run` and `clean-runs` were listed as phony and defined nowhere, so `make clean-runs` printed "Nothing to be done" and exit 0."""
    mk = text("Makefile")
    names = re.search(r"^\.PHONY:(.*)$", mk, re.M).group(1).split()
    assert names and [n for n in names if not re.search(rf"^{re.escape(n)}:", mk, re.M)] == []


PROOT_STAND_IN = """import os, sys
a = sys.argv[1:]
tmp = next(x.rsplit(":", 1)[0] for i, x in enumerate(a) if a[i - 1] == "-b" and x.endswith(":/tmp"))
job = [x.replace("/tmp/.rc", tmp + "/.rc") for x in a[a.index("/usr/bin/env") + 1:]]
os.execv("/usr/bin/env", ["env", *job])
"""


def run_in_the_proot_runner(tmp_path, command, **host):
    """(exit code, stdout) of `bin/proot_run.sh app <command>` on a worker whose proot is a stand-in that runs the job's own command line (the `env -i ...` that
    bin/proot_run.sh builds) on this host, with the job's /tmp put where the runner expects it. `host` is the environment of the caller."""
    w = tmp_path / "home" / "cafe-worker"
    (w / "bin").mkdir(parents=True)
    (w / "bin" / "proot.py").write_text(PROOT_STAND_IN)
    (w / "bin" / "proot").write_text(f'#!/bin/sh\nexec "{sys.executable}" "{w}/bin/proot.py" "$@"\n')
    (w / "bin" / "proot").chmod(stat.S_IRWXU)
    (w / "root" / "usr" / "bin").mkdir(parents=True)
    (w / "root" / "usr" / "bin" / "env").write_text("")
    (w / "root" / "usr" / "bin" / "env").chmod(stat.S_IRWXU)
    (w / "root.done").write_text("x")
    for d in ("app", "pmdata", "data"):
        (w / "cafe" / d).mkdir(parents=True)
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path / "home"), "CAFE_MIN_FREE_GB": "0", "PM_CPUS": "3", **host}
    r = subprocess.run(["sh", str(ROOT / "bin" / "proot_run.sh"), "app", *command], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout


def test_r11_m29_the_env_form_the_runbook_documents_reaches_the_job_and_a_variable_of_the_host_shell_does_not(tmp_path):
    """Round 11 M-29: the runners start the job with a fixed environment, so `CAFE_OFFLINE=1 pm python ...` never set it; the RUNBOOK says to put
    `env VAR=value` in front of the command. The real runner, with a stand-in proot: the documented form sets the variable (and overrides the CAFE_WORKERS
    the runner derives from PM_CPUS); the same variable in the caller's environment is not there."""
    rb = text("docs", "RUNBOOK.md")
    assert "pm env CAFE_OFFLINE=1 python -m cafe.pm" in rb and "does not pass your shell's environment on" in rb
    assert run_in_the_proot_runner(tmp_path / "a", ["env", "CAFE_OFFLINE=1", "printenv", "CAFE_OFFLINE"]) == (0, "1\n")
    assert run_in_the_proot_runner(tmp_path / "b", ["env", "CAFE_WORKERS=5", "printenv", "CAFE_WORKERS"]) == (0, "5\n")
    assert run_in_the_proot_runner(tmp_path / "c", ["printenv", "CAFE_WORKERS"]) == (0, "3\n")                              # the runner's own: PM_CPUS
    for var in ("CAFE_OFFLINE", "CAFE_NPROC", "CAFE_EMULATOR_TABLE"):
        assert run_in_the_proot_runner(tmp_path / var, ["printenv", var], **{var: "1"}) == (1, "")


# ---- review round 12: documents that quote the code or a measured record (M-12, M-17, M-18, M-20)

def flat(doc):
    return " ".join(doc.split())


def test_r12_m17_the_wave_ages_are_assumptions_yaml_keys_and_no_document_says_they_are_not():
    """Round 12 M-17: PHYSICS 4.1 and CREDIBILITY said `swell_age` and `wind_sea_age` are code defaults that are not keys of config/assumptions.yaml, so the
    credibility report does not list them. waves.py reads them from it, and the report lists both."""
    keys = config.read_yaml(ROOT / "config" / "assumptions.yaml")
    assert keys["waves.swell_age"]["value"] == 1.2 and keys["waves.wind_sea_age"]["value"] == 2.0
    assert {"assumptions.yaml:waves.swell_age", "assumptions.yaml:waves.wind_sea_age"} <= {i["id"] for i in credibility.assumed_inputs()}
    src = text("cafe", "pm", "env", "waves.py")
    assert 'assumption("waves.swell_age")' in src and 'assumption("waves.wind_sea_age")' in src
    phys, cred = flat(text("docs", "PHYSICS.md")), flat(text("docs", "CREDIBILITY.md"))
    for doc in (phys, cred):
        assert "they are not keys in `config/assumptions.yaml`" not in doc and "assumed and are not in `assumptions.yaml`" not in doc
    assert "the keys `waves.swell_age` and `waves.wind_sea_age` of `config/assumptions.yaml`" in phys
    assert "`waves.swell_age` (1.2) and `waves.wind_sea_age` (2.0) are keys of `config/assumptions.yaml`" in cred


def test_r12_m18_the_stokes_figures_in_physics_are_the_recorded_receipt_and_stored_attribute_not_a_lead_s_log():
    """Round 12 M-18: PHYSICS 4.4 gave 38 % and 'under-predicts by about x2.7' as one finding from a log. 38 % is the all-node median of |fit/real - 1|; the
    receipt's median fit/real ratio on the real cache was re-read (review/round_12/m18/, orca, 2026-11-08) and is 0.657. The documents quote those records."""
    rec = ROOT / "review" / "round_12" / "m18"
    rows = json.loads((rec / "wave_direction.json").read_text())
    ctx = [r for r in rows if r["kind"] == "context" and r["name"].startswith("Wave direction (cache tepex_c_demo)")
           and "parametric spectrum / from the real" in r["name"]]
    assert len(ctx) == 1 and f"{ctx[0]['value']:.3f}" == "0.657"
    probe = (rec / "probe2.txt").read_text()
    assert '"fit_only_median_speed_err": 0.3842877802874689' in probe and '"corrected_loo_median_speed_err": 0.05130921006182648' in probe
    phys = flat(text("docs", "PHYSICS.md"))
    assert "the fit under-predicts by about x2.7 at the sample points" not in phys
    assert "**0.657** at 211 points" in phys and "0.3843" in phys and "(0.0513)" in phys and "(3.74)" in phys and "points 211" in probe
    assert "withdrawn" in row(34) and "0.657" in row(34) and "0.657" in row(658)


def test_r12_m20_the_pad_cap_is_said_to_be_reached_at_24_5_days_in_the_runbook_and_the_rows():
    """Round 12 M-20: 'at most 10, reached at about 26 days' in RUNBOOK 3 and rows 190 and 229; pipeline.padding gives 9.5 at 24.4 days and 10 from 24.5."""
    rb = flat(text("docs", "RUNBOOK.md"))
    assert "(at most 10, reached at 24.5 days: 24.4 days gives 9.5)" in rb and "reached at about 26 days" not in rb
    for n in (190, 229):
        assert "24.5 days" in row(n) and "about 26 days" not in row(n)
    assert pipeline.MAX_PAD_DEG == 10.0 and "24.4 days" in str(pipeline.padding.__doc__)


def test_r12_m12_physics_and_the_questions_state_the_fresnel_error_band_the_docstring_states():
    """Round 12 M-12: -1 was said to hold below 1 to 2 deg. PHYSICS 12.1 and QUESTIONS_FOR_LAB 12a carry what the docstring of two_ray_curved_db carries (the
    table itself is recomputed in tests/test_comms.py): within 10 % only below about 0.3 deg, up to 7.6 dB optimistic at a peak, the polarisation question."""
    sec = flat(text("docs", "PHYSICS.md"))
    sec = sec[sec.index("### 12.1 RF: two-ray over the sea"):]
    sec = sec[:sec.index("### 12.2")]
    doc = flat(str(comms.two_ray_curved_db.__doc__))
    for part in ("within 10 % of the magnitude only below about 0.3 deg", "up to 7.6 dB", "7.4 dB lower to 23.6 dB higher", "7.5 dB lower to 34.7 dB higher",
                 "no sample changed"):
        assert part in doc and part in sec, part
    assert "pseudo-Brewster angle 4.85 deg" in sec and "valid for grazing angles below ~1-2 deg" not in doc
    q = flat(text("QUESTIONS_FOR_LAB.md"))
    assert "12a. **Antenna polarisation, and the sea temperature and salinity at the RF link**" in q and "*Default:* vertical polarisation" in q
    assert "Fresnel" in row(652) and "withdrawn" in row(652)



# ---- review round 13 (the document sides of M-10, M-13, M-20, M-22, M-23, M-38, M-44, M-45)

def test_r13_m10_the_sea_water_conductivity_is_the_one_that_gives_the_quoted_eps_c_in_every_place():
    """Round 13 M-10: eps'' = 60 lambda sigma is 116.0 at 915 MHz for the 5.9 S/m the documents printed and 118.9 (the quoted eps_c) for 6.05 S/m."""
    lam = 299792458.0 / 915e6
    assert abs(60 * lam * 6.05 - 118.9) < 0.1 and abs(60 * lam * 5.9 - 118.9) > 2
    places = {"PHYSICS": text("docs", "PHYSICS.md"), "QUESTIONS_FOR_LAB": text("QUESTIONS_FOR_LAB.md"), "row 652": row(652),
              "the two_ray_curved_db docstring": str(comms.two_ray_curved_db.__doc__)}
    for name, doc in places.items():
        assert "sigma 5.9 S/m" not in flat(doc) and "sigma 6.05 S/m" in flat(doc), name


def test_r13_m44_the_draft_that_gives_the_free_surface_hull_the_platforms_displacement_is_0_145_m_with_the_keel_counted():
    """Round 13 M-44: 0.18 m is the half ellipsoid alone; with the 0.14 m3 keel the mesh needs c = (V_platform - V_keel) / (2 pi a b / 3), about 0.145 m."""
    yaml_text = flat(text("config", "assumptions.yaml"))
    assert "about 0.145 m" in yaml_text and "a draft of about 0.18 m" not in yaml_text
    phys = flat(text("docs", "PHYSICS.md"))
    assert "a draft of about 0.18 m would give" not in phys and "about 0.145 m" in phys
    assert "names a draft of about 0.18 m" not in row(407) and "about 0.145 m" in row(407)


def test_r13_m45_six_cores_is_called_a_chosen_cap_not_a_measured_knee():
    """Round 13 M-45: the throughput is measured at 1, 2, 4 and 8 cores only; six is interpolated."""
    assert "measured scaling knee" not in row(297) and "chosen cap" in row(297)
    assert "measured scaling knee" not in text("cafe", "pm", "stage3", "freesurface.py")


def test_r13_m22_the_runbook_states_the_vehicle_limit_the_schema_enforces():
    """Round 13 M-22: 65 vehicles was refused by a limit no document stated."""
    limit = json.loads(text("cafe", "schemas", "mission.json"))["properties"]["vehicles"]["maxItems"]
    assert limit == 64 and f"1 to {limit} vehicles" in flat(text("docs", "RUNBOOK.md"))


def test_r13_m13_the_runbook_names_the_directory_make_receipts_reads_the_stored_results_from():
    """Round 13 M-13: `make receipts` reads the stored CFD and SITL files from $CAFE_APP_RUNS (default /work/runs, read-only under pm.sh and bin/pmx.sh)."""
    assert 'os.environ.get("CAFE_APP_RUNS", "/work/runs")' in text("cafe", "pm", "receipts.py")
    rb = flat(text("docs", "RUNBOOK.md"))
    assert "`$CAFE_APP_RUNS` (default `/work/runs`" in rb and "read-only under `pm.sh` and `bin/pmx.sh`" in rb


def test_r13_m20_the_runbook_and_status_give_the_receipt_counts_measured_in_round_13_not_round_11s():
    """Round 13 M-20: `make receipts` on a clean orca at 939851e printed 273 pass, 30 fail, 32 context (335 rows) in about 12 min; the RUNBOOK said 350 rows,
    287 passing, 33 context and about 17 min. The counts are re-measured at code freeze (the totals move with the stamped files of the app group)."""
    for name, doc in (("RUNBOOK", flat(text("docs", "RUNBOOK.md"))), ("STATUS", flat(text("STATUS.md")))):
        assert "273 pass" in doc and "32 context" in doc and "335 rows" in doc, name
        # round 11's counts stay only as history
        assert "ended with 350 rows" not in doc and "round 11: 350 rows" not in doc and "about 17 min at 2 CPUs" not in doc, name
    assert "about 12 min at 2 CPUs on orca" in flat(text("docs", "RUNBOOK.md"))


def test_r13_m23_the_brief_lists_the_command_that_fetches_data_the_way_the_cli_spells_it():
    """Round 13 M-23: there is no `cafe` script; BRIEF 2.9 and 6 named `cafe fetch`. The brief's text stays as given; its Corrections table has the command."""
    from cafe.pm.env import environment
    table = text("docs", "BRIEF.md").split("## Corrections")[1].split("\n---\n")[0]
    assert environment.FETCH_CMD in table and "cafe fetch" in table


def test_r13_m38_the_questions_and_the_status_say_what_the_stored_fea_utilization_is():
    """Round 13 M-38: the stage-3 FEA stores the larger of the von Mises and the knocked-down buckling utilization (hangar.KNOCKDOWN 0.5)."""
    assert "KNOCKDOWN = 0.5" in text("cafe", "hangar.py")
    q = flat(text("QUESTIONS_FOR_LAB.md"))
    assert "4a. **The default glider hull" in q and "0.367" in q and "0.687" in q and "1.374" in q
    assert "*Default:*" in q.split("4a. **The default glider hull")[1]
    st = flat(text("STATUS.md"))
    assert "knocked-down buckling" in st and "wing and arm root" in st


def test_r14_m8_every_document_that_counts_the_real_time_tests_counts_audit_serial_tests():
    """Round 14, M-8: DECISIONS 334 and STATUS 59 and 103 said five where `audit.SERIAL_TESTS` has seven: the number a document gives is that list's length."""
    from cafe.pm import audit
    words = dict(zip("one two three four five six seven eight nine ten".split(), range(1, 11), strict=True))
    seen = []
    for name in ("STATUS.md", "DECISIONS.md", "README.md", "docs/RUNBOOK.md", "docs/ORCA_RUNNER.md"):
        for m in re.finditer(r"\b(one|two|three|four|five|six|seven|eight|nine|ten) real-time tests\b", text(*name.split("/"))):
            seen.append((name, m.group(1)))
            assert words[m.group(1)] == len(audit.SERIAL_TESTS), (name, m.group(0))
    assert {n for n, _ in seen} >= {"STATUS.md", "DECISIONS.md"}                       # it did find the places


# ---- review round 14 (the document sides of M-3, M-15, M-16, M-33 and M-43)

def test_r14_m15_the_makefile_and_the_runbook_say_that_make_ci_plans_the_glider_fea_out_under_the_floor_the_assumption_file_holds():
    """Round 14, M-15: under `--budget ci` the glider FEA reserve is 9.0 s, under `stage3.fea_min_s`, so `make ci` does not reach the FEA child (the budget
    test `test_r14_m15_*` pins the plan); the Makefile and RUNBOOK 2 said 'every stage' with no exception."""
    floor = config.assumptions()["stage3.fea_min_s"]["value"]
    assert floor == 68.2
    ci_line = next(line for line in text("Makefile").splitlines() if line.startswith("ci:") and "##" in line)
    assert "the glider FEA is planned out" in ci_line and "stage3.fea_min_s" in ci_line
    rb = flat(text("docs", "RUNBOOK.md"))
    assert "except that the glider FEA is planned out under `ci`" in rb and f"`stage3.fea_min_s`, {floor}" in rb
    assert "9.0 s" in row(776) and f"{floor}" in row(776) and "(amends 741)" in row(776)


def test_r14_m16_the_runbook_says_that_a_make_ci_run_audits_clean_only_inside_the_call_because_its_data_is_in_tmp():
    """Round 14, M-16: `CI_DATA` defaults to /tmp/cafe_ci_data, which the container drops; a later audit or `report --run` of runs/ci reports its inputs
    missing. The Makefile default and the sentence stay together (a persistent default would make the sentence false: change both)."""
    assert "ci: CI_DATA ?= /tmp/cafe_ci_data" in text("Makefile")
    rb = flat(text("docs", "RUNBOOK.md"))
    assert "The run's data is in `/tmp/cafe_ci_data` (`CI_DATA`), which the container drops" in rb
    assert "audit passes only inside the `make ci` call" in rb and "nine `AUDIT FAIL` lines" in rb
    assert "_same_place` is not changed" in row(777)


def test_r14_m3_the_readme_and_the_runbook_say_what_python_m_cafe_receipts_takes():
    """Round 14, M-3: `python -m cafe.receipts` takes `stamp FILE...` or one existing results directory; anything else is a usage error before any receipt."""
    assert "`python -m cafe.receipts` takes `stamp FILE...` or one existing results directory" in flat(text("docs", "RUNBOOK.md"))
    assert "the directory must exist" in flat(text("README.md")) and "usage error" in flat(text("README.md"))
    src = text("cafe", "receipts.py")
    assert "RESULTS_DEFAULT" in src and "def main(" in src


def test_r14_m33_every_documented_orca_gate_command_that_names_the_checkout_carries_pm_take():
    """Round 14, M-33: a fresh worktree is another checkout than the one that owns `pm_<you>`, so the gate of a round needs `PM_TAKE=1` once (and `PMX` is
    required). The commands CLAUDE.md and ORCA_RUNNER give, and the gate commands of the newest HANDOFF block, carry it."""
    cmd = "PM_HOST=cafe-orca PMX=pm_<you> bin/orca_gate.sh"
    for name, doc in (("CLAUDE.md", text("CLAUDE.md")), ("docs/ORCA_RUNNER.md", text("docs", "ORCA_RUNNER.md"))):
        assert f"PM_TAKE=1 {cmd}" in doc, name
        assert cmd not in doc.replace(f"PM_TAKE=1 {cmd}", ""), name
    block = text("HANDOFF.md").split("### Round 14 is fixed and merged on `r14-merged`")[1].split("\n### ")[0]
    gates = [m.start() for m in re.finditer(r"bin/orca_gate\.sh 8 proof1", block)]
    assert gates and all("PM_TAKE=1" in block[max(0, g - 60):g] for g in gates)
    assert "`PMX` is required" in text("docs", "ORCA_RUNNER.md")


def test_r14_m43_the_leave_one_out_sd_of_the_wind_fit_is_the_one_measured_and_every_site_that_quotes_it_agrees():
    """Round 14, M-43: PHYSICS 7, CREDIBILITY L19 and row 589 gave 0.155 (from a round 10 log no committed file reproduced) and PHYSICS gave the other
    moorings' mean errors as +0.07 to +1.14. `review/round_14/m43/loo_q14la.txt` is `fit_wind_error` on q14la's hourly residuals without each mooring, run on
    orca on the merged code; its all-14 fit equals the run's `priors_fitted.json`. The places that quote it say what it says."""
    out = (ROOT / "review" / "round_14" / "m43" / "loo_q14la.txt").read_text()
    speed = out.split("=== direction deg")[0]
    sd13 = re.search(r"without T5S165E : persistent ([0-9.]+)", speed).group(1)
    assert sd13 == "0.1545" and "all 14: persistent 0.5689" in speed and "stored wind_speed_bias: value 0.5689" in speed
    means = {m.group(1): float(m.group(2)) for m in re.finditer(r"^  (T\w+)\s+mean\s+([+-][0-9.]+)", speed, re.M)}
    others = [v for k, v in means.items() if k != "T5S165E"]
    assert len(means) == 14 and len(others) == 13 and means["T5S165E"] == -1.4822
    assert f"{min(others):.3f}" == "-0.032" and f"{max(others):.3f}" == "1.142"
    loo = [float(m.group(1)) for m in re.finditer(r"without (?!T5S165E)\w+\s*: persistent ([0-9.]+)", speed.split("leave one out:")[1])]
    assert len(loo) == 13 and f"{min(loo):.3f}" == "0.562" and f"{max(loo):.3f}" == "0.610"
    phys, cred, qs = flat(text("docs", "PHYSICS.md")), flat(text("docs", "CREDIBILITY.md")), flat(text("QUESTIONS_FOR_LAB.md"))
    for name, doc in (("PHYSICS", phys), ("CREDIBILITY L19", cred), ("QUESTIONS_FOR_LAB 7a", qs), ("row 589", row(589))):
        assert sd13 in doc and "0.155 " not in doc.replace("0.1545", ""), name
    assert "-0.03 (T2N170W) to +1.14 (T5N165E)" in phys and "+0.07 to +1.14" not in phys and "0.562 to 0.610" in phys
    assert "-0.032 to +1.142" in cred and "-0.032 to +1.142" in row(589)
