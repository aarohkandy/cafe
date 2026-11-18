# Round 19, reviewer D: robustness and operations of round 18 and its addendum

Checkout `/Users/aaroh/Downloads/everything/cafe_main`, head 51150e7 (code of 7260ebb), scratch worktree `../cafe-rev19-d` (detached, removed at the end).
All probes ran on orca at 2 CPUs under `PM_HOST=cafe-orca PM_RUNTIME=proot` in my own `pm_rev19_d`, `pm_rev19_d_b` and `pm_rev19_d_c` directories, scratch data only
under `/data/rev19_d` and `/data/runs/rev19_d_v` (a copy of q20). Nothing in the repo was edited. At the end the three `pm_rev19_d*` directories, `pmdata/rev19_d`,
`pmdata/runs/rev19_d_v` and the `.pmx.job.pm_rev19_d*` markers were removed; no process of mine remains (one early probe that outran its window was stopped by
its exact pids, 2620530, 2620526, 2620493 and 2620484). The shared emulator table, the shared mission cache and `pmdata/cache` were never written.

## What held (read and tried, no finding)

- `cfd._literals` and the signs (960): `-1`, `+1`, `~1`, `--1`, `-0.0` against `0.0`, `(-1, 2)` against `(1, 2)`, `-1j`, `-True` each move the digest; `-(1)` equals `-1` (same AST,
  correct); a literal inside an f-string, its format spec, a lambda default, a method, a nested function named `main`, an `assert` message all move it; `log(...)`, `print(...)`,
  `raise` and a bare string statement do not (as the comment says). `-x` and `x`, `1 - 2` and `1 + 2`, `x < 0.5` and `x > 0.5` give one key, which row 978 states.
  `import ... as _par` leaves the key as 971 says.
- `par.env_count` over 20 spellings (empty, `0`, ` 4`, `1_0`, full-width and Arabic digits, `+3`, `007`, `000000009`, ten digits, 5,000 digits, `0x10`, `4\n`): each is
  the documented count or a `ConfigError` naming the variable with at most 40 characters of it. `cfd.dvec` over 23 labels (True, None, 1.5, bytes, list, dict, `x+z1e1`,
  `x+z10\n`, a full-width digit, 5,000 digits, `x+z90.0001`): a `ValueError` naming the label, never a `TypeError`.
- `atomic.replace_from`: a link at the source (new target or existing) is ELOOP and leaves both names; a link at the target is refused; a missing source is
  `FileNotFoundError`; a target's mode is kept (a setuid target comes out 0755, as the docstring says); a cross-device target is EXDEV with the source left.
- The emulator table's lock under `umask 022`, `077` and `002` (0644, 0600, 0664, and the `flock` is really held); a link at its name and a directory at its name are a
  `ConfigError` that names the file, and the link's target is not created. `store_lock` with a link or a directory at its name yields False and logs the one warning;
  its target is not created. Three processes appending 40 rows each to one table through `whatif.add_rows`: 120 of 120 rows, no lock left behind.
- `hycom.write_store` with real SIGKILLs at the four points (before the first rename, between the two, after the second, during the delete after half the files had gone), with
  and without the lock file: the name holds the old store, nothing, the new store and the new store as the row says; the next write works; with the lock the aside is deleted,
  without it it stays (969, P-R18M2: as stated).
- The hull reader against PyYAML: 80 targeted layouts (octal, sexagesimal, `_`, hex, sign, quoted, tagged, anchored, NBSP, BOM, CRLF, CR, U+2028, directives, duplicates, odd
  children, key-line variants) and 2,500 seeded character mutations of a 41-line excerpt that holds the entry (1,301 accepted by the reader): 0 cases where the reader returns
  a number PyYAML does not. The messages of the RUNBOOK's hull row (tab, four-space indent, block scalar, 5000, `070`) read as the row says.
- `whatif`: the `--budget` refusal text is the RUNBOOK's word for word, exit 2; the UAS shift bound over 20 shifts of the demo (143.99 h, 144 h, 144.0001 h, 144.5 h, 6.01 d,
  1e20 h, 0.0083 h, 23.9999 h ...): each is a time of day or an `Invalid` that says why. `CAFE_WORKERS=abc` and a 12-digit value give the RUNBOOK's two messages, exit 2.
- `report.json` `same_members` for q20's flip.json as it is (flags: `available` true, `measured` false, `source` the flags text; batch: true), with `source` removed
  (`measured` null, `source` null), `base_same` null (`available` false, `measured` false) and `base_same` missing (`same_members` None): as 993 says; the page text
  for each is the 'not run on the Stage-1 rows' members' paragraph or the 'compared with' one.

## Findings

### D-1. The count rule admits narrow numpy integers, and the interval arithmetic then overflows to a wrong interval or a math-domain error
severity: minor
lane: statistics, robustness
where: cafe/pm/stats/intervals.py:55 (`_count`), :86 (`wilson`'s `4 * n * n`), the same arithmetic in `agresti_coull`, `newcombe_diff`, `interval`; cafe/pm/stats/sequential.py (`sprt_decide`, 972)
reproduction: on orca, `iv.wilson(np.uint8(30), np.uint8(100))` returns `(0.0, 0.7778)` and the same with Python ints `(0.2189, 0.3958)`; `np.uint8(3), np.uint8(10)` gives
`(0.0463, 0.6647)` against `(0.1078, 0.6032)` (RuntimeWarning only); `np.int8(3), np.int8(10)` raises `ValueError: math domain error`; `np.int16(300), np.int16(1000)` gives
`(0.2162, 0.3854)` against `(0.2724, 0.3291)`; `np.int32(3000000), np.int32(7000000)` and `np.uint32` are wrong too (4 n^2 overflows at n = 23,170 for int32). `agresti_coull`, `newcombe_diff`
and `interval` go wrong with them. `sprt_decide` has no range check, so `sprt_decide(5, 3, .1, .3)` returns `accept_nogo` and `sprt_decide(-2, 10, .1, .3)` `accept_go`;
`sprt_decide(np.uint8(5), np.uint8(3), .1, .3)` returns `accept_go` where the Python ints give `accept_nogo` (the `n - k` wraps).
why it matters: rows 967 and 972 say 'numpy integers pass' and 'the sum of flags a simulation loop builds is one', and give that as the reason a numpy count is safe; for a width below int64 it is
not, and the failure is silent (a warning that a run's log does not show). Every caller found by grep passes `int(f.sum())` or a JSON int, so no printed number is affected today.
wrong data: no (no caller passes a narrow integer); a future caller that does gets a wrong interval or a wrong sequential decision without an error. The one-line cure is `int(k)`, `int(n)` after `_count`.

### D-2. The link card's pair lookup is an exact float match behind a step trigger, so 0.5000001 m prints nothing and 0.30000000000000004 m (or 0.31 m) prints 'not measured'
severity: minor
lane: honesty, robustness
where: cafe/pm/report.py:762 (trigger `h <= RF_LOW_ANTENNA_M`), :776-778 (`pair not in comms.LOW_ANTENNA_PAIR_BAND`), cafe/pm/physics/comms.py:104
reproduction: drive `report._low_antenna_note` (patching the two `load_platform` readers) for a glider end and a USV end of 2.2 m. Glider 0.5: the sentence with the pair's figures,
'+1.8 to +2.7 dB (median +2.6) ... the loss is overstated by 1.8 to 2.7 dB'. Glider 0.5000001: `None`, no sentence. Glider 0.30000000000000004 with 15 m (and, by the same code path, any height below 0.5 m that is not a row's): 'is not among those
measured ... no error band is stated'. 1 m with 15 m: `None`. The platform loaders accept all of these (0.5000001, 0.1000001, 0.30000000000000004, an integer, `!!float 0.5`; a quoted `"0.5"`, `.nan`,
`.inf`, `0`, `-1`, `true` and a list are refused, as they should be, so the lookup never sees text, NaN or a negative height from a file). Both platform files say of the three
placeholders (0.3, 0.5, 2.2) 'the lab's CAD replaces it'.
why it matters: the ten measured pairs are exactly the placeholder heights. The moment the lab enters a CAD height (0.51 m for the Seaglider tail mast, 2.25 m for the whip) the card falls from a
stated +1.8 to +2.7 dB overstatement to silence (above 0.5 m) or to 'not measured' (below it), though the antenna and its error are the same to a fraction of a decibel; the step at 0.5 m is
a threshold of the schema (944), not of the physics. L23 on the credibility page still lists the table, so this is an omission on the card, not a false statement.
wrong data: yes, by omission: the link card of a link whose margin is biased low by about 2 dB prints no warning once the height is 0.5000001 m. Severity minor because 991 decided 'exactly a row's
heights' and 944 the 0.5 m trigger; the finding is the cliff those two make together.

### D-3. RUNBOOK's lock-error symptom is not the text the code prints
severity: minor
lane: documentation
where: docs/RUNBOOK.md:299 (the first cell), cafe/pm/emulator.py:130
reproduction: the row says the symptom is ``error: the lock file <table>.lock ... cannot be opened``. The code raises `ConfigError("cannot open the emulator table's lock file <path>
(IsADirectoryError: Is a directory); something that is not a file stands at that name: remove it (...). The lock stops two runs ...")` (reproduced with a link and with a directory at the lock's
name; the CLI prints it after `error: `). A lab user who searches the RUNBOOK for the words on the screen finds no row. The second symptom of the row (`warning: <lock> is not locked (...); this block runs
without the lock`) is word for word.
why it matters: the row exists to be found by its symptom text.
wrong data: no.

### D-4. The leftover's `mv` advice cannot appear in the commands that meet a missing store, and a lab store's leftover is never swept
severity: minor
lane: operations, documentation
where: cafe/pm/pipeline.py:365 (`_ocean_cached`: `if not path.exists(): return False`), cafe/pm/pipeline.py:318 (`_need`'s note), cafe/pm/pipeline.py:525 (a lab store is not locked), cafe/pm/env/hycom.py:305-311, docs/RUNBOOK.md:298
reproduction: kill `write_store` between its two renames (SIGKILL at the second `os.replace`): the directory holds `.<16 hex>.<12 hex>.old.tmp` (the old store, whole) and a `.<12 hex>.tmp` (the new
one) and no store. `pipeline._ocean_cached(<store>, box, steps)` returns False without opening it, so `s_ingest` reports `ocean_store_present` failed with `_need`'s text and, for a lab store,
the hint `python -m cafe.pm ingest-ocean --mission ... --path <lab HYCOM dir> ...`; neither names the leftover. Only `hycom.open_store` of the missing name prints 'BUT the store as it was before ... mv ...',
and the commands that reach it are those that load the environment after the ingest stage (read from the code, not run: `report` prints a `Context.env` failure as 'note: environment not loaded'), after an ingest that has already refused the run. For a GOFS
store the next ingest reassembles from `<store>.parts` (no download) and deletes the leftover itself (verified: the next write leaves no aside with the lock file present), so the `mv` is a saving of
minutes. For a lab store nothing locks (`lock = nullcontext()` for `lab`), so `write_store` sweeps nothing: the leftover and the new store's `.tmp` stay on a disk that is 98 % full (measured on orca
today) until someone finds them.
why it matters: the RUNBOOK row tells a lab user to look for an `environment cache file ... cannot be read` message after a killed ingest; in the commands a lab user runs first (`run`, `fetch`,
`ingest-ocean`) it does not occur, and the advice that would save the lab's only ingested copy of its HYCOM is in a message nothing prints there.
wrong data: no.

### D-5. `unreadable` calls a half-deleted leftover 'the older data' and advises `mv`ing it back
severity: minor
lane: robustness
where: cafe/pm/env/hycom.py:307-312 (`unreadable`), :229 (`asides` matches by name only), :288-289 (the delete: `shutil.rmtree(old, ignore_errors=True)`)
reproduction: `write_store` of a store of 11 files with the delete killed (SIGKILL) after 5 of them were unlinked, no lock file. The store is NEW and whole and the aside holds 6 of the 11 files. Remove
the store (what the RUNBOOK's 'delete X and run fetch' row tells a GOFS user, and what a lab user does with a store they think is damaged) and `hycom.open_store(<store>)` raises ConfigError ending
'is beside it: .<16 hex>.<12 hex>.old.tmp (0.0 GB): `mv ... <store>` puts it back without a download'. The size is printed, but nothing says that this tree was being deleted when the process died, and a store
with missing chunks reads them as the fill value; `ocean_store_nan_mask` would then fail the ingest check on the NaN pattern (it checks a pattern, not that every chunk exists).
why it matters: the claim 'whole' in the docstring and the row is true for a kill between the renames or after the second and false for a kill during the delete, which is the same name and the same message.
wrong data: no (a later ingest check is likely to catch the holes); the advice is wrong for one of the four kill points.

### D-6. A plan.json with a bad value is a traceback or a silent answer; only a missing key is the 'damaged' message
severity: minor
lane: robustness
where: cafe/pm/__main__.py:312-330 (`ctx.plan.update({k: run_plan[k] ...})`), cafe/pm/stage1.py:1039 and :1065, cafe/pm/budget.py:538
reproduction: copy q20 to a private directory and edit `plan.json` (`batch`, `n_min`, `n_max` are read and used as they stand): `whatif --mission missions/tepex_c_demo.yaml --run <copy> --shift 6h --vehicle glider_eq`
with `batch: 0` ends in `ZeroDivisionError: integer division or modulo by zero` from `stage1.wave` (24 s in, a raw traceback); `batch: "32"` in `TypeError: can't multiply sequence by non-int of type 'float'` (budget.py:538);
`batch: 32.5` in `TypeError: 'float' object cannot be interpreted as an integer`; `n_min: 500, n_max: 10` runs to the end (rc 0, 85 s) and prints an answer. Row 953 says a damaged plan.json is the usual
'damaged or incomplete' message; the wrapper `_run_files` covers a missing key and a wrong type read inside it, but `ctx.plan.update` copies the values unchecked and they fail later, outside it.
why it matters: a hand-edited or truncated-and-patched plan.json (the commands tell a lab user to copy run directories) gives a traceback, or an answer on member counts the run never had.
wrong data: no (a hand-damaged file only); the `n_min > n_max` case answers silently and is the one to look at.

### D-7. `store_lock` keys its re-entrancy by the text of the path, so the same thread locking one file under two spellings deadlocks for good
severity: minor
lane: robustness
where: cafe/pm/env/remote.py:239-243 (`held: set[Path]`, `if path in held`)
reproduction: `with store_lock(M, "re.lock"): with store_lock(R/"Mlink", "re.lock"): ...` where `Mlink` is a symlink to `M` (a symlinked cache directory): the second call takes a second descriptor on the same file, `flock` blocks on
the first, and the thread never returns (5 s timeout in the probe; the `wait` callback fired once). `M` against `str(M) + "/"` and against `M / "."` is fine (pathlib normalises them); a symlinked directory, or `..` components, are not.
`emulator.locked` is not re-entrant at all (nested on one table: deadlock; no caller nests).
why it matters: a mission cache or `CAFE_DATA` reached through a symlink in one place and by its real path in another (the ingest holds the ocean lock and `write_store` takes the same lock) hangs the ingest with no message.
No present caller spells one path two ways (`fetch_gofs` builds `out_zarr` from the same `store.parent`), so this is latent.
wrong data: no.

### D-8. `cfd._literals` keys only top-level `def` and `class` statements: a function under a top-level `if`, `try` or `with`, or an `async def`, is outside the key
severity: minor
lane: reproducibility
where: cafe/cfd.py:78-80 (`ast.parse(src).body` filtered to `FunctionDef` and `ClassDef`)
reproduction: `cfd._literals("if True:\n    def f():\n        return 1\n") == cfd._literals("if True:\n    def f():\n        return 2\n")` is True, and the same for `async def f(): return 1` against `return 2`. A method, a nested function
and a lambda default are keyed (they sit under a keyed top-level node). The comment says 'every number and every text written in the functions and classes of this file ... a new function is keyed unless it is named'.
No function of cfd.py is of this shape today (`if __name__ == "__main__"` only), and the SETTINGS test holds module constants.
why it matters: the 'an edit cannot miss it' claim of row 929 has a hole that the next refactor (a function defined under `try: import x` for an optional solver) walks through.
wrong data: no (latent): a Hangar CFD table from the cache after such an edit.

### D-9. The `source` of `same_members` is compared as a display phrase, and an unknown phrase is 'not measured' rather than 'unknown'
severity: minor
lane: documentation, reproducibility
where: cafe/pm/report.py:435, cafe/pm/whatif.py:67
reproduction: the q20 copy re-rendered with `base_same.source` set to `"<b>weird</b> & \"x\""`: `same_members` is `available: true, source: <that text>, measured: false`. 993 defines false for the base run's flags, true for a batch, null where 'it is not known'; a
source this code does not know is not known. `measured` is `source == BASE_SAME_RUN`, where `BASE_SAME_RUN = "a batch run for it"` is also prose, so rewording that phrase turns every earlier flip.json's `measured` from true to false.
A non-string `source` (5) makes the report's own `report_traceable` check fail ('the number 5 is outside a traced value node') and `report --run` exits 1 with 'the new files are in ... but the report ledger still records the old ones'; a list and a dict were not run.
why it matters: nothing prints `measured` or `source` (the page reads `available`), so no sentence is wrong; the key is a machine-readable one that a later consumer would trust.
wrong data: no.

### D-10. `python -m cafe._seed` does not look at what it seeds
severity: minor
lane: robustness, honesty
where: cafe/_seed.py:25-45
reproduction: `$CAFE_WORK/runs/q1/quad.external.json` containing `[1,2]` prints `seeded quad ('external', 'air', 10.0)` and exits 0: the list is now the cached CFD result under that case's key. A corrupt file (`{not json`) is a raw
`json.decoder.JSONDecodeError` traceback with no file name, exit 1, after earlier samples were already seeded. With the cache directory read-only: `NOT seeded ... - warning: the CFD result was not cached ... PermissionError`, exit 1, as 962 says;
`already there` on a second run, as it says; no run found: the one-line message, exit 1. The temporary directories are removed.
why it matters: the RUNBOOK row says to run it only for results made with the present settings; a result of another shape is cached under the real key without a word and the Hangar reads it as a result.
wrong data: no (an operator-supplied file; the shape of a result is not checked, the settings it was made with are the operator's word).

## Not run, and why

- A full run, a kill and resume of one, and two concurrent runs of one mission or of two missions on one box: the allowance forbids a demo run. What ran instead is the lock and store code across processes (three appenders on one emulator table;
  `store_lock` and `flock` held by another descriptor; `write_store` with four real kill points); the kill during an emulator-table append did not land mid-write (the killed child had already finished its 40 rows), so the atomic replace is argued
  from `atomic.write_with`, not shown by a kill.
- `hycom.write_store` and the sweep on a real zarr (stand-in `_append` wrote a `.zgroup` and ten chunk files; the renames, the lock and the sweep are the real code). A real 20-GB store's delete time was not measured.
- The hull reader fuzz ran on a 41-line excerpt (PyYAML on the whole 37 KB file is about 0.3 s a call), not on the whole file; the shipped file is pure ASCII.
- The `cfd` key was exercised on source snippets of my own and on `cfd._literals` of small functions, not by recomputing `recipe()` on the real file before and after an edit of each signed literal (no CFD was run; the `external` and
  `free_surface` sites `lvl - 2`, `lvl - 4`, `4 * b + 8`, `4 * b + 4`, `4 + level_offset` and `ittc57`'s `- 2` are binary operators, outside the key by 978).
- `whatif` with a real Stage-1 answer was run only for the plan.json probes (one vehicle, 24 to 85 s each); no what-if answer was compared with a rerun (C's scope).
- The RUNBOOK rows I followed word for word: 294 (not reproduced: needs two real ingests), 297, 298 (kill points reproduced, message reproduced through `open_store`), 299, 300, 301, 302 (`_seed`), 315. Row 296 (the TAO download lock) was not run (no network, no server).

total: 10 findings (0 critical, 0 major, 10 minor)
