# Round 18, reviewer D (robustness and operations)

Scope: round 17's CFD and store fixes with hostile inputs (DECISIONS 929 to 937), the RUNBOOK's step 6, step 7 and Troubleshooting table followed as a lab
user (the RUNBOOK has no section 8: sections 6 and 7 and the Troubleshooting table hold the round 17 sentences), and `whatif`. All runs were on orca at
2 CPUs from a detached worktree (`cafe-rev18-d` at 08a2f23, code as d631e32), directory `pm_rev18_d`; scripts were `r18d/t1.py` to `t5.py`, `cli.sh`,
`w.sh`, `s.sh`, `m.sh`, `m2.sh` (in the scratch worktree only).

What was checked and held (no finding): `cfd.dvec` (19 labels incl. `x+z90.0000001`, `x+z.5`, `x+z1e1`, full-width digits, trailing newline: all refused, `x+z90`
and `x+z00010` accepted as the row says); `cfd.cached` with nan, inf, numpy array and scalar, set, bytes, tuple keys, complex, circular list (warning, result
returned, next call recomputes), read-only cache dir (warning names PermissionError), `CACHE` a file (warning), missing stl and an unserialisable key (loud, before
any compute); `par.env_count` (`1_0`, `" 4"`, `4_0` refused with the variable named); five concurrent `remote.download` of one file and a SIGKILLed first one (all
others finish with the right sha-256, only `f.nc` and `f.nc.lock` left); the lock name planted as a symbolic link (downloads on parts of their own, the link's
target not created); `atomic` write over a 0000 file, mode 2775 -> 0775, umask 077 existing 0664 kept, loop and chain of links, link in the directory part, fifo, a
directory as target (clean IsADirectoryError, no temporary left); `whatif` argument errors (`--drop nosuch`, drop all, `--vehicle nosuch`, `--shift 5h --shift=-5h`,
`1e30h`, a move not smaller than the box, `--vehicle usv` alone) all exit 2 with a one-line message; step 6's commands (`bin/run_premission` exists and takes
`--budget 4h`, `run --gpus 1` stops with the quoted error, `plan --gpus 1 --gpu-mem-gb nan` begins "no GPU found on this machine" and refuses nan,
`promote-calibration --run /data/runs/q18` says "did not calibrate the sub-grid layer" and changes nothing, exit 2); step 7's usage-error claims (`audit` with a
bad path or option, `--pytest-done`/`--pytest-receipt` with another option, `receipts --slow --only ,` and `--only nosuchgroup`, `cafe.receipts stamp` with no file or
an option or two words, a sphere Reynolds number of 7 for `nest slow` and `lbm slow`: each exits 2 as written); `make` exists in the image and `make -n audit` /
`acceptance GPUS=1` print what the RUNBOOK says.

### D-1. The CFD cache key does not see the sign of a negative literal, so the `locationInMesh` fractions the row names as keyed are keyed only by magnitude
severity: minor
lane: reproducibility
where: `cafe/cfd.py:53-63` (`_text_and_numbers` yields `repr(c.value)` of `ast.Constant` nodes only; `-0.71` is `UnaryOp(USub, Constant(0.71))`, so the sign is dropped), the sites at `cafe/cfd.py:636` (`loc=(-0.71 * L, -0.83 * L, -0.37 * L)`), `:127`, `:190`, `:402`, `:419`, `:470`, `:713`, `:724`; DECISIONS 929 and RUNBOOK Troubleshooting row "CFD: reusing an identical earlier run" (both say the `locationInMesh` fractions are in the key)
reproduction: on orca (or anywhere): parse `cafe/cfd.py`, run `_literals(src)` and `_literals(src.replace("loc=(-0.71 * L, -0.83 * L, -0.37 * L)", "loc=(0.71 * L, 0.83 * L, 0.37 * L)", 1))`. The two sha-1 values are equal (`True`), so `recipe()` and every cache file name are unchanged; the seed point of the free-surface mesh moves from the lower back corner to the opposite one (a different region, possibly inside the hull) and the Hangar's `fs` table comes back as 'an identical earlier run'. The sweep test of row 929 raises each number by one, which never turns a minus into a plus. The same holds for `-1` in the direction-vector, `-3000` and the other eight negative literals.
why it matters: the fix for M-4 claims that every number written in the keyed functions is in the key; a sign edit is the same silent stale-cache failure M-4 was filed for. The row's list of what is outside the key names 'an operator', which a reader would not take to include the minus of a number.
wrong data: yes (conditional on someone editing a sign): the Hangar's `fs`, `cfd` and `cfd_aoa` tables are returned from a cache made with the other seed point, labelled 'reusing an identical earlier run'.

### D-2. The emulator table's `.lock` file takes none of M-13's rules: made 0600 under umask 077, and a link at its name is followed
severity: minor
lane: robustness / operations
where: `cafe/pm/emulator.py:106-116` (`locked`: `open(path.with_name(path.name + ".lock"), "a")`); `cafe/pm/env/remote.py:238` (`store_lock`: `os.open(..., 0o644)` then `O_RDWR`); DECISIONS 934
reproduction: `r18d/t5.py` on orca: `os.umask(0o077); with emulator.locked(Path("train.parquet")): pass` then `stat train.parquet.lock` gives `0o600`. With a dangling link planted at `t2.parquet.lock` pointing to `/app/r18d/scratch5/victim`, `locked()` creates `victim` (printed `victim created through link: True`). Row 934 fixed the mode and the link rule of `train.parquet` itself ('a run under umask 077 made the shared table 0o600, unreadable to the others') but the lock beside it is opened `"a"` by every run: a second Unix user's run gets `PermissionError` on the 0600 lock (the same failure the row set out to remove, one file over). `store_lock` creates its lock 0644 and opens it O_RDWR, so a second user gets EACCES there too and the block silently runs unlocked (`yield False`, no log line; the ingest's `_shared_store` has no way to say so). The second user part is reasoned from the code, not run (one account).
why it matters: the shared table is written by several people (row 934's own premise); the lock is what stops two runs losing each other's rows, and it is either unopenable or silently absent for the second person.
wrong data: no (a crash with a traceback at the table write, or a silently unlocked store write)

### D-3. `atomic.replace_from` does not refuse a symbolic link as the source when the target name is new (row 937 says ELOOP)
severity: minor
lane: robustness / security
where: `cafe/atomic.py:121-124` (the `O_NOFOLLOW` open is inside `if mode is not None:`), DECISIONS 937 ('a link as the source is ELOOP'), docstring at `cafe/atomic.py:105-113`
reproduction: `r18d/t3.py`: `(t/"s.part").symlink_to(t/"secret.txt"); atomic.replace_from(t/"s.part", t/"final")` returns None; `final` is then a symbolic link (`is_symlink() True`) to `secret.txt`. The same call with `p` an existing regular file raises `OSError [Errno 40]` as claimed. The two real callers (`remote.download` for a first download of a TAO file, `hycom._fetch_part` for a first part) always have a new target, so the guard never applies on the first fetch.
why it matters: the claim in the row and the docstring is wrong for the common case; a `.part` planted as a link in a shared download directory becomes the file the cache then reads. The row itself says the race around `src` is open, but this is not a race, it is the branch.
wrong data: no

### D-4. `python -m cafe._seed` prints `seeded <key>` whether or not anything was written, and leaks a temporary directory per sample
severity: minor
lane: documentation / honesty
where: `cafe/_seed.py:21` (`tempfile.mkdtemp()` never removed), `cafe/_seed.py:30-31` (`cfd.cached(k, stl, print, ...)` then an unconditional `print("seeded", ...)`)
reproduction: `r18d/s.sh` on orca: the second `python -m cafe._seed` prints `CFD: reusing an identical earlier run (4b8beed18f55f2fe.json)` and then `seeded quad ...` for all three samples: `cached` found the key and wrote nothing, the line says seeded. With a read-only cache the log is `warning: the CFD result was not cached ...` followed by `seeded ...` and exit 0 (read from the code, not run: orca's `/work` is writable under proot). Each call also leaves a `tmp*/mesh.stl` directory per sample.
why it matters: the RUNBOOK says the command 'seeds the cache'; a user on the docker runners (read-only `/work`, step 1's `pm()` mounts none) reads `seeded` and exit 0 for a seed that did not happen, which is the symptom M-12 was about.
wrong data: no

### D-5. `fea.hull_elements_along` still returns a number for layouts PyYAML refuses (tab after `value:`, a vertical tab or form feed, a second colon in a sibling's plain text)
severity: minor
lane: robustness
where: `cafe/fea.py:91-95` (`(\w+):(?:[ \t]+(.*))?` takes a tab after the child's colon; `str.splitlines()` at `cafe/fea.py:62` splits on `\x0b`, `\x0c` and `\x85`), DECISIONS 935 ('refuses ... a tab after the key's colon', 'the file is one mapping')
reproduction: `r18d/t2.py` (a differential fuzz of 11,515 mutated files, the reader against `yaml.safe_load`): 180 mismatches, all in four forms, each of which the reader returns 70 for and `yaml.safe_load` raises on: `  value:\t70` (tab after the value's colon), `  value: 70\x0c`, `  value: 70\x0b`, and a sibling line `  unit: a: b` ahead of `value: 70`. The row closes the tab after the key's own colon but not after `value:`. With any of the four the FEA meshes at L/70 while the PyYAML read in `pipeline_windows` of the same file fails, so the two readers the row says 'agree' do not.
why it matters: the reader's stated contract is never to return what PyYAML would not; the stage-3 window and the Hangar then run on a file the rest of the pipeline refuses.
wrong data: no

### D-6. `whatif --shift` of a UAS by an absurd number of hours is accepted and gives an arbitrary launch time
severity: minor
lane: robustness
where: `cafe/pm/whatif.py:141-146` (`tot = (hh*60 + mm + int(round(h*60))) % 1440` has no bound on `h`, while the glider and USV branch at `:148-151` refuses a shift outside the window)
reproduction: `r18d/t5.py` on orca: `whatif.apply(m, {"uas": dict(shift_h=1e20)})` and `shift_h=1e300` return a mission (`OK`) where `glider_eq`, `glider_2n` and `usv` raise `Invalid ... outside the window`. The launch time of day of the UAS is then the float rounding residue of `1e20 * 60` modulo 1440. The command line cannot spell 1e20 (`--shift` takes digits only) but `--shift 99999999999999999999h` can.
why it matters: the other vehicles get a clear refusal; the UAS gets an answer for a shift no one meant, with no note.
wrong data: no (a typo input; no real use gives it)

### D-7. Not read or not run (listed, not run anyway)
- two concurrent ingests, two concurrent runs of one mission or of two names with one box, kill and resume of a real ingest, a killed GOFS or TAO fetch: each needs an ingest or a run (hours, the network, or the CI budget), which the rules forbid. What could be read: no run-level lock exists (`grep` of `pipeline.py` and `__main__.py` finds `store_lock` only on the mission cache, the ocean store, the GEBCO cut and the TAO files), so two `run` of one `--out` interleave their stage files and ledgers; I did not run it and make no claim about the result.
- `bin/orca_gate.sh`, `make receipts`, `make broken`, `make audit` (full), `make acceptance`: not run (budget). `make -n` only.
- a CFD case (no OpenFOAM exercised): the cache key was exercised on module text and `cached` with stand-in computes only; `free_surface`/`external` validation was read, not run through a mesh. A hostile `draft` far above the hull's height (`free_surface(draft=1e6)`) and a boolean or string `speed` pass `_finite_positive` (read, not run).
- `whatif` with a finished run for a changed vehicle (the Stage-1 answers, the 'becomes' line): not run, reviewer C's lane and a Stage-1 batch per vehicle.
- a `whatif --run` that names a run that does not exist starts Stage 1 for the baseline and every vehicle (a note says so; `/data/runs/nosuch_r18d` ran until my own 150 s `timeout` inside the job ended it): by design in the RUNBOOK, listed because a mistyped path costs a quick-budget Stage 1.

### Side effects I caused on orca (for the lead)
- `python -m cafe._seed` (D-4) was run twice by me with `CAFE_WORK` unset; on orca `/work` is `~/cafe-worker/cafe/data` and is writable under proot, so it wrote three small JSON files (3.3 kB, 0.9 kB, 3.4 kB) into `~/cafe-worker/cafe/data/cfdcache`: `4b8beed18f55f2fe.json`, `8fb35e6de7519e98.json`, `7421244e25a437fc.json` (created 07:35 on 2026-11-17). They are old validation results seeded under the present key, i.e. the thing the row says to do only for runs made with the present settings. I did not delete them (not my directory by the rules); remove them if the Hangar is run on orca.
- `/data/runs/rev18_d_empty` (empty, made by me) and `~/cafe-worker/cafe/pm_rev18_d` are the only other things I left; both are removed at the end by exact name (see below).

total: 6 findings (0 critical, 0 major, 6 minor); one (D-1) gives wrong data to act on (conditional on a sign edit), D-2 to D-6 do not.
