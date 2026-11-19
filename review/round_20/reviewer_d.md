# Round 20, reviewer D: robustness and operations of round 19's changes with hostile inputs

Tree: detached copy of 67aa547 (code 979e37a's), orca, `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev20_d PM_CPUS=2`; probe scripts were in my scratch worktree `../cafe-rev20-d/rev/p1.py` to `p9.py` (not committed, removed at the end). No finding gives wrong data to act on; none is major or critical.

## What I attacked and found holding (so a reader knows what "clean" means here)

- `cfd._literals` (1006), 33 constructs (functions and classes under top-level `if`, each part of `try`, `with`, `for`, `while`, `match`, `async def`, a def in a def, a method under an `if`, decorator, default, keyword-only default, annotation, return annotation, f-string, lambda in a def, walrus, assert, slice, dict key): all move the key; bare module-level `lambda`, comprehension and constants are not keyed (the shipped file has none: its only top-level non-def, non-SETTINGS statements are the module docstring and `if __name__`). `cfd.recipe()` = `a091d933b7537473`, `_code_literals()` = `9a7181651627013ab5dbd3c6e78f833a798f6aac`, unmoved. On the real `cafe/cfd.py`, every one of the 582 numeric, string and bool constants inside keyed functions was changed one at a time (AST, `ast.unparse`): 0 holes (key moved each time, apart from the documented exemptions); all 10 signed literals moved the key when the sign was flipped.
- `intervals._count` and its users: numpy `uint8, int8, uint16, int16, uint32, int32, int64, uint64` give the Python-int answers (0.2189, 0.3958) in `wilson`, `newcombe_diff`, `agresti_coull`, `verdict`; `np.bool_`, 0-d and 1-element arrays, `float`, `np.float64` are refused with the count message; `sprt_decide` refuses `k > n` and `k < 0`, accepts `k = n = 0` (returns "continue").
- `_seed._checked` / `main`: not UTF-8, empty file, a directory at the file's name, list, wrong fluid, speed as text, NaN, Infinity, empty `dirs`, bad direction key, speeds of another case, speed key text or `nan`, no `speeds`, resistance as text, read-only cache: each is `NOT seeded <file> - <reason>`, rc 1, cache empty (nothing written for the other two good files); all good: 3 seeded, rerun "already there".
- `remote.store_lock`: directory, FIFO, symlink, dangling symlink (target not created), missing parent (create True and False), `sub/x.lock`, empty name, hard link to a data file, nested via a second hard link, second thread waits then gets, body raises then re-take, `wait` raising then later take: all behave as the docstring says (a name with a NUL byte is a ValueError, not an OSError: callers pass fixed names). A lock file unlinked while held lets a second process take the new file at once (inherent to `flock` by path; the RUNBOOK says to delete no lock file while a run is going).
- `hycom.write_store` with real SIGKILLs (a probe child, fake one-group stores of 60 chunk files, with and without the lock file): before the first rename (store whole, `.<12 hex>.tmp` build left), between the renames (store absent, `.old.tmp` whole, `leftover_note` and `open_store` name it with the `mv`; the next locked write sweeps it), after the second rename (aside whole beside a present store; swept by the next locked write only), during the delete (a half-deleted `.dead.tmp`, not in `asides`, never offered for `mv`; swept by the next write locked or not). All as DECISIONS 1011 says.
- Hull reader (`fea.hull_elements_along`): differential fuzz of the WHOLE `config/assumptions.yaml` against PyYAML (CSafeLoader), 31,295 mutated files (character, token, line, indent and swap edits near the entry and anywhere, LF and CRLF, tab, NUL, BOM, U+2028, anchors, `? `, `---`, merge keys, duplicate keys): 11,613 returned a number, all equal to PyYAML's; 19,682 refused; 0 disagreements.
- `__main__._plan_sizes` for bool, 12.0, string, null, negative, 0 `batch` and `n_min > n_max`: exit 2 with the "damaged or incomplete" message each time. A non-object plan.json and a plan.json without `budget` are exit 2 with a message.
- RUNBOOK rows 298 and 299 (the leftover note, the `.dead.tmp` text, the emulator lock error text, the `warning: <lock> is not locked` text) match the code.

## Findings

### D-1. `plan.json` batch and n_max have no upper bound: `batch` 10**30 is a traceback, `n_max` 10**30 starts the what-if
severity: minor
lane: robustness
where: cafe/pm/__main__.py:312 (`_plan_sizes`), :345 (`ctx.plan.update`)
reproduction: on orca, a run directory whose `plan.json` is `{"budget": "quick", "batch": 1000000000000000000000000000000, "n_min": 8, "n_max": 64}` then `python -m cafe.pm whatif --mission missions/tepex_c_demo.yaml --run <dir> --shift 1h`: exit 1, `OverflowError: Python int too large to convert to C ssize_t` (a traceback, not the exit-2 "damaged or incomplete" message that every other bad size gets). Same file with `"batch": 8, "n_max": 10**30`: passes the check and the what-if starts (loads the 5 GB environment, still running at 60 s; I stopped it by pid). The docstring says "whole numbers ... in range" but only the lower bounds are checked.
why it matters: a damaged plan.json with a huge whole number is not the message round 19's M-10 set out to give; a huge `n_max` asks Stage 1 for as many members as it takes.
wrong data: no

### D-2. `plan.json`'s `budget` is not checked: a list is a traceback, null runs the what-if with no plan, an int is blamed on `--budget`
severity: minor
lane: robustness
where: cafe/pm/__main__.py:328-330 (`bud = run_plan["budget"]` is read before `_plan_sizes`, and not checked), :342 (`pipeline.Context(a.mission, bud, ...)`)
reproduction: same harness with `{"budget": ["quick"], "batch": 8, "n_min": 8, "n_max": 64}`: exit 1, `TypeError: unhashable type: 'list'`. With `"budget": null`: no error, the what-if goes on (Context gets `budget_name=None`, which is the "no plan" mode that `fetch` uses; the three sizes are copied into an empty plan; stopped at 60 s, so I did not see the answer). With `"budget": 5`: `error: --budget 5: choose one of [...]`, although the user gave no `--budget`.
why it matters: `_plan_sizes` was added so a damaged plan.json ends as one message; the field next to the three it checks is the one that is not.
wrong data: no (what the null case prints was not observed)

### D-3. `python -m cafe._seed` on a deeply nested JSON file is a traceback, not `NOT seeded <file> - <reason>`
severity: minor
lane: robustness
where: cafe/_seed.py:79-84 (`except (OSError, ValueError)`)
reproduction: `runs/t1/torpedo.external.json` holding `[` x 100000 then `]` x 100000, the other two files good: `_seed.main()` raises `RecursionError: maximum recursion depth exceeded while decoding a JSON array` (RecursionError is not a ValueError); nothing is written (the read comes first), but no `NOT seeded` line and no "nothing was seeded" line, against the docstring's "one that cannot be read, is not JSON ... is `NOT seeded <file> - <reason>`, exit 1".
why it matters: the all-or-nothing check is the point of M-14; this one input escapes its message (the effect, nothing written, is right).
wrong data: no

### D-4. `_seed._checked` accepts an external result with any non-empty subset of the six directions and no `gci`
severity: minor
lane: data
where: cafe/_seed.py:48-53; read by cafe/vehicle.py:284-300 and :389
reproduction: `torpedo.external.json` with `dirs` holding only `+x` (force, moment, viscous of three numbers): `_seed.main()` prints `seeded torpedo ('external', 'water', 1.5)` rc 0. `vehicle.py` then takes the one direction from the "cfd" and fills the other five from the Newtonian estimate, yet sets `sources["drag"] = "cfd"` (line 291) and `setdefault`s the estimate label (line 301) only if unset, so the drag table is called CFD while five of six directions are the estimate. `_site_data.py:186` reads `v["gci"]` of every direction (KeyError without it).
why it matters: the check says it holds a seeded file to "a result of its case", and one with one direction in six passes. Real files have six, so this needs a truncated or hand-edited file.
wrong data: no

### D-5. `hycom.leftover_note` offers the `mv` of the first leftover by random name, not the newest
severity: minor
lane: operations
where: cafe/pm/env/hycom.py:329-343 (`left[0]`), `_leftovers` sorts by name, which is a random uuid
reproduction: two asides `.<16 hex>.ffffffffffff.old.tmp` (mtime one hour ago) and `.<16 hex>.000000000000.old.tmp` (now) beside a missing `lab_x.zarr`: the note lists both and says "`mv ...000000000000.old.tmp ... lab_x.zarr` puts it back"; with the two names swapped it offers the older one. More than one aside is possible for a lab store, which nothing sweeps (RUNBOOK 298 (3)): each killed `ingest-ocean` after the second rename leaves one, and a later kill between the renames leaves the store absent.
why it matters: the advice restores a store of unknown generation, and for a lab store the older data would pass the window check silently if it covers the window.
wrong data: no (a user is told to `mv`; which one is not stated to be the newest)

### D-6. A half-deleted `.dead.tmp` is never reported by anything
severity: minor
lane: operations
where: cafe/pm/env/hycom.py:247-250 (`dead`, called only at :321), cafe/pm/__main__.py:263 (reports `asides` only), docs/RUNBOOK.md:298
reproduction: the kill-during-delete probe leaves `.<16 hex>.<12 hex>.dead.tmp` (half the files) beside a present store: `asides` is empty, `leftover_note` is "" (the store exists), `ingest-ocean` prints no note, and `pipeline._need` never meets a missing store. It goes at the next `write_store` of that name only. The RUNBOOK row says it "is safe to delete by hand" but no symptom or command leads a user to it, and the box's disk is 97 % full (a whole store's worth, up to the 20 GB the owner expects).
why it matters: the round's own point (M-11) was that a kill during the delete should leave nothing confusing; it leaves nothing that is found.
wrong data: no

### D-7. Statistics: `verdict()` returns the caller's numpy scalars, huge ints are an OverflowError, `sprt_decide`'s alpha and beta are unchecked
severity: minor
lane: statistics
where: cafe/pm/stats/intervals.py:183-184 (`verdict` returns `n=n, k_fail=k_fail` as given), :88-95 (`wilson`: `z * z / n` with a Python int above 1e308), cafe/pm/stats/sequential.py:34-38
reproduction: `intervals.verdict(np.uint8(30), np.uint8(100))` gives `n: np.uint8(100), k_fail: np.uint8(30)` in its dict (`_count` converts inside `_check`, but `verdict` keeps the originals); `json.dumps` of a numpy integer is a TypeError (by reasoning, not run: no caller of the repo is known to pass one). `wilson(1, 10**400)` is `OverflowError: int too large to convert to float`, not the ValueError of the module. `sprt_decide(1, 3, .1, .2, alpha=0)` is `ZeroDivisionError`, `alpha=-1` and `beta=1` are `ValueError: math domain error`.
why it matters: round 19's M-8 made the counts Python ints for the arithmetic; the dict `verdict` returns still carries the original type, and the error classes at the edges are not the module's.
wrong data: no

## Not run (needs more than the allowance, or not reachable from here)

- `write_store` on a real zarr and the delete time of a 20 GB store; two concurrent runs of one mission and of two missions on one box; a kill in the middle of an append to the emulator table (the table's write is `atomic.write_with` under `emulator.locked`; read, not killed); the TAO download lock (read `remote.download`, not run); a real Stage-1 what-if against a rerun.
- RUNBOOK Troubleshooting: I read rows 294 to 300 against the code. A crude grep of the backticked symptoms of the other rows against `cafe/` and `bin/` matched about half; the rest did not match only because the text is split across f-strings or placeholders, and I did not check them one by one. Not a finding, not verified.
- The whole `whatif` with a valid plan: `--run` of a plan.json with sound sizes goes straight into a Stage-1 what-if on the orca copy of the demo environment (5 GB resident), so I did not let any such case finish; the damaged-plan cases that end before it are above.

Cleanup: my orca directory `~/cafe-worker/cafe/pm_rev20_d` and `pmdata/runs/rev20_d_*` (wi, ws, seed, two, lk, fz.yaml) and the worktree `../cafe-rev20-d` are removed by the last step of this session; stray process: none (the one `whatif` I started was stopped by its exact pid).

total: 7 findings (0 critical, 0 major, 7 minor)
