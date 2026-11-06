# Round 9, batch L2 handback (branch r9-merged, worktree cafe-r9m)

One look-ahead problem, fixed at the shared place. DECISIONS and CHANGELOG were not edited; the number below is a suggestion for the lead to renumber
(the file ends at 469 here; the other L handbacks suggest 470 to 478).

## L2-1: `P /tests/golden/` and `P /report/` matched the directory entry only, so server-written files inside them were deleted by every sync

Root cause: in `bin/sync_filters`, a `P` rule with a trailing slash protects the directory entry, not what is in it. When the checkout also has the directory
(it does: `tests/golden/` and `report/` are tracked), the sender sends it, the receiver recurses, and a file inside that exists only on the server matches no rule
and is deleted by `--delete`. Only the named files (`config/throughput.json`, `config/subgrid.json`, `docs/mutation.json`) were really protected. So a golden file
with a new name written by `acceptance --update-golden`, or a page in `report/`, was erased by the next `./pm.sh` or `bin/pmx.sh` sync before `--pull`.

DECISIONS row (suggested 479): the two directories the server rewrites, `tests/golden/` and `report/`, are protected in `bin/sync_filters` as `P /tests/golden/***`
and `P /report/***` (the directory and everything under it). A directory in a `P` rule is always written in this form. A copy that exists in the checkout still goes
over the server's, as before; a file that exists only on the server inside them is kept, so a golden file deleted from the tree stays on the server until it is
removed there by hand. Amends the round 9 M-39 row (one filter list for pm.sh and pmx.sh). The `-` rules on directories (`/runs/`, `/mutants/`, `/.work/`, ...) were
checked and are not affected: an excluded directory is neither sent nor recursed into.

CHANGELOG: the sync filter protects everything the server wrote inside `tests/golden/` and `report/` (`P ...***`), not only the directory entry, so a new golden file
or a report page no longer vanishes at the next `./pm.sh` or `bin/pmx.sh`; DECISIONS 479, round 9 L2.

Tests:
- `tests/test_runners.py::test_l2_a_file_the_server_wrote_inside_a_protected_directory_survives_when_the_checkout_has_that_directory_too` (both `pm.sh` and
  `bin/pmx.sh`, real rsync 3.2.7 on cafe-burst, checkout with both directories). Failed on the unfixed filter (both parameters, `from_server.txt` gone), passes now.
- `tests/test_config_docs.py::test_pm_sh_and_pmx_sh_read_one_filter_list_and_never_delete_what_they_exclude` now names the `***` forms and refuses any `P` rule that ends
  in `/`, so a third directory cannot be added in the broken form.
- The old `test_a_file_removed_from_the_tree_is_removed_on_the_server_and_what_the_server_wrote_stays` missed this because its checkout had no `tests/golden/` or
  `report/`; it still passes unchanged.

Callers checked: `bin/sync_filters` is read only by `pm.sh` and `bin/pmx.sh` (`--filter`, both with `--delete`, neither with `--delete-excluded`). The change only
widens what is kept on the server; nothing is sent differently. Verified on cafe-burst: the two tests above, all of `tests/test_runners.py` and
`tests/test_config_docs.py`, `ruff check cafe/pm tests`, `mypy cafe/pm`. The full suite was not run (the change touches no code under cafe/pm).
