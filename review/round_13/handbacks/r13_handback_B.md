# Round 13, batch B handback (acceptance): M-17, M-11, M-7

Branch `r13-b`, worktree `cafe-r13b`. Files changed: `cafe/pm/acceptance.py`, `tests/test_acceptance.py`. `cafe/pm/__main__.py` and `tests/test_cli.py` were read, not edited (the new tests feed the printed command to `__main__.main`, the real parser, with `acceptance.main` replaced).
No docs were edited. Numbers of the demo: none moves. The shipped `tests/golden/tepex_c_demo_quick.json` is byte for byte unchanged (a test compares its `command` with `_base_command(...)`).

## What changed in the code (one shared place each)

- `_base_command(mission, gpus)`: the one copy of `python -m cafe.pm acceptance --mission M --gpus N --update-golden` (mission shlex-quoted). `_golden_record` stores it as it is; `update_command` prints it and adds ` --out FRESH` and then the golden flags.
- `update_command(golden, mission, gpus, name, out)`: new fifth parameter, the directory of the run being judged (`r["dir"].parent` in `check_golden`; its only caller outside tests). `--out` is `out.parent / (out.name + "_golden")`, shlex-quoted: a fresh sibling, since the judged run's own directory is marked and its runs are replaced on every run. The old prefix (`... --gpus N --update-golden`) is unchanged and `--out` comes straight after it. `--golden-mission NAME` is now added only when the flag can mend the refusal (`golden_refusal(g, name)` and not `golden_refusal(g, name, name)`).
- `golden_refusal`: before the mission test, and for `allowed` too, it refuses what no flag can mend: the path exists and is not a file (a directory); the nearest existing ancestor of the golden is not a directory; that directory is not writable by this user (`os.access(W_OK|X_OK)`). `run()` calls it before any run, `check_golden(update=True)` again, so M-17's twenty-minute run followed by IsADirectoryError cannot happen.
- `check_golden` without `--update-golden`: a golden path that exists and is not a file says "is not a file: name a file with `--golden`" and prints no command (the command would be refused too). Before, it said "no golden file" and printed a command.
- `_write_atomic(path, text)`: sibling `.tmp` then `os.replace`, writes through a symlink to the file it names (`resolve()`), removes the temporary if the write fails. Used for the golden (M-17), and for `acceptance.json` and `acceptance.txt` in `main` (the sibling bare `write_text` at the old acceptance.py:568 named in the finding).
- Chosen not to use `config.write_json`: it appends no trailing newline, and the golden's bytes (and the "byte for byte" claim of 685) need the newline. See "needs from other batches".

## Per finding

### M-17 (--update-golden with a directory golden; non-atomic golden write)

DECISIONS row text (new row, number after the last, amends 673, 680):
> `acceptance.golden_refusal` refuses what no flag can mend before it looks at the mission, and for `--golden-mission` too: the golden path exists and is not a file; its nearest existing ancestor is not a directory; that directory is not writable by this user. `run()` and `check_golden(update=True)` therefore refuse a directory before the first quick run, not after it, and `update_command` offers `--golden-mission NAME` only when it can mend the refusal. The golden, `acceptance.json` and `acceptance.txt` are written through `acceptance._write_atomic` (a sibling `.tmp`, then `os.replace`, through a symlink to the file it names), so a write cut short leaves the old file and no temporary. (amends 673 and 680)
> Why: review round 13, M-17 (B-7). `--golden DIR --golden-mission NAME` passed the early refusal, ran the first quick run (about 20 min), then `write_text` raised IsADirectoryError with the remaining checks and `acceptance.json` unwritten; a full disk left a truncated golden that reads as "not a golden file". Tests: `tests/test_acceptance.py::test_r13_m17_*`.

Amends: 673 (the refusal is no longer only about the mission), 680 (when `--golden-mission` is printed).
CHANGELOG line: `acceptance --update-golden: a golden path that is a directory, below a file or in an unwritable directory is refused before any run starts (also with --golden-mission); the golden, acceptance.json and acceptance.txt are written through a temporary and os.replace (round 13, M-17).`
Doc sentences: RUNBOOK.md:256 (the paragraph that lists what `--update-golden` refuses): add "A path that is a directory, sits below a file or is in a directory this user cannot write is refused the same way, with or without `--golden-mission`; the golden is written through a temporary file, so a full disk leaves the old golden."

### M-11 (printed command lacks --out)

DECISIONS row text (new row, amends 680 and 685):
> The command that `check_golden` prints for writing a golden is accepted by the real parser: `acceptance.update_command(golden, mission, gpus, name, out)` adds `--out FRESH` after `--update-golden` and before the golden flags, FRESH being a new sibling of the judged run's directory (`<out>_golden`), shlex-quoted. The judged run's own directory is not named: acceptance marks it and replaces the runs in it. The test shlex-splits the printed command of every message (missing, damaged, another mission's golden, spaces, `;`, a quote, `$(`) and feeds it to `__main__.main`, which must accept it and give the mission, `--golden`, `--golden-mission` and `--out` back. (amends 680 and 685)
> Why: review round 13, M-11 (B-1). `python -m cafe.pm acceptance --mission M --gpus N --update-golden` exits 2 with "the following arguments are required: --out"; 680 and 685 said it could not be refused and tested the words through `check_golden`, never through the parser. Tests: `tests/test_acceptance.py::test_r13_m11_*`, `test_a_missing_golden_fails_and_names_the_command_that_writes_it`, `test_an_unprovenanced_golden_fails_and_names_the_command_that_writes_a_new_one`.

Amends: 680 (its sentence "with `--update-golden` first so the old prefix is unchanged" stays true: `--out` follows it), 685 (the "cannot be refused" claim now holds for `--out` too).
CHANGELOG line: `acceptance: the command printed for writing a golden carries --out (a fresh <out>_golden sibling), so it is accepted by the parser; the tests feed it to __main__.main (round 13, M-11).`
Doc sentences: RUNBOOK.md:256, after "the command the failed check prints carries `--golden FILE` and `--golden-mission NAME` where they are needed": add "and `--out DIR_golden`, a new directory next to the judged run's".

### M-7 (stored command not tested to be quoted)

DECISIONS row text (new row, amends 685):
> The `command` field of a written golden and the printed command come from one builder, `acceptance._base_command(mission, gpus)`; the stored form is the base (no `--out`, which belongs to one machine), so the shipped golden's bytes do not move and the stored command is a prefix of the printed one. The test splits the stored command with `shlex.split` and requires the mission as one word after `--mission` and nothing else, compares it with the printed command, and compares the shipped golden's `command` with `_base_command`. (amends 685)
> Why: review round 13, M-7 (A-6). 685 named the test as proof of the quoted field, but it read `summary.mission` only, and dropping `shlex.quote(mission)` from `_golden_record` survived all of `tests/test_acceptance.py`. Test: `tests/test_acceptance.py::test_r13_m7_*`.

Amends: 685.
CHANGELOG line: `acceptance: the golden's stored command and the printed one are built by one function and the stored one is tested to be one word per argument (round 13, M-7).`
Doc sentences: none.

## What I checked could break, and how

- Callers of `update_command`: only `check_golden` (grep over cafe, tests, bin, Makefile, *.sh). Callers of `golden_refusal`: `run()`, `check_golden`, `update_command`, tests. `_golden_record`: `check_golden` only. `check_golden`: `run()` and tests. The new `out` parameter has no default on purpose (a caller that forgot it would print a command without `--out`).
- Tests that pin strings: `tests/test_acceptance.py` the missing-golden test, the unprovenanced test, `test_r12_l0_m33_*` (three), updated to feed the parser or to the new order; the `ci` fixture test (`"--update-golden" in detail`) is unchanged and passes. `tests/test_cli.py` builds a real argv with `--out` and is unaffected.
- The shipped golden: its `command` equals `_base_command("missions/tepex_c_demo.yaml", 0)` (asserted), so `provenance_problems`, `compare` and the digest checks see no difference. Nothing else reads the field.
- `golden_refusal` is now stricter in one way that can matter: an existing golden in a directory this user cannot write is refused (the temporary needs the directory), where `write_text` would have written into the file. `tests/golden/` is writable in the checkout and in the cafe-pm image. `os.access` says yes for root, so under root only the directory and ancestor tests refuse.
- A symlinked golden is still written through (the link stays a link); a dangling link is written at its target if the target's directory exists, else `mkdir(parents=True)` makes it, as before.
- Repeated `--update-golden` with `--out` = the printed `<out>_golden`: that directory gets the acceptance marker on first use and is replaced on the next run, so pasting the command twice works (not run end to end: the quick run takes 20 min; the parser, the refusal and the write are tested, `acceptance.run` is replaced in the m11 test by `acceptance.main`).
- Not checked: a real `make acceptance` (about an hour on orca, not asked); real disk-full (simulated with a `write_text` that writes part and raises ENOSPC).

## Needs from other batches

- Batch A (config.py): `config.write_json` takes no trailing-newline option, so I used a 10-line `_write_atomic` in acceptance.py. If A makes `write_json` accept a text/newline option (and resolves symlinks, M-14), acceptance can drop `_write_atomic` for it; not needed for correctness. The same bare `Path.write_text(json.dumps(...))` as M-17 remains at audit.py:433 and :490, credibility.py:973, report.py:1805 (A's files) and pipeline.py:266, :1402 and stage1.py:915 (outside the finding; E and A own them): root cause 4 of merged.md, listed here so F/lead can decide.
- Batch F: the three DECISIONS rows above (numbers after the last), CHANGELOG lines, RUNBOOK.md:256 sentences, and DECISIONS 680's text ("the existing test that pins the prefix ... is unchanged" is no longer true of the test file, true of the prefix of the text).

## Verified (orca, proot, 2 CPUs)

- `tests/test_acceptance.py`, `tests/test_cli.py`, `tests/test_audit.py` whole: exit 0. `ruff check cafe/pm tests` and `mypy cafe/pm` (strict): clean. The 11 new test cases (`-k r13`) pass.
- Each new test fails on a one-edit mutant of the final code (detached worktree, removed): no `--out` in the printed command (the m11 cases and the m7 test fail); `shlex.quote(mission)` dropped from `_base_command` (m11 mission-with-quote cases and m7); the is-a-file refusal removed (m17 refusal test); `_write_atomic` writing in place (m17 cut-write test); the directory/writable check removed (m17 refusal test); `--golden-mission` printed whenever the refusal is not None (m17 refusal test). On HEAD 810ecdb the tests cannot run as written (`update_command` has no `out` parameter), so the mutants are the failing-before evidence.
- Orca cleanup: `pm_r13b`, `pm_r13b_mut` and the three `r13b_*` logs removed; nothing else touched there. The worktree `cafe-r13b-mut` is removed; `cafe-r13b` stays for the merge.
