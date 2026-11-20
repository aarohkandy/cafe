"""Round 23, batch E (S-lint): the claims lint. No absolute or sample-figure phrase lands on a user-visible output unreviewed.

Two halves. (1) The product: every non-docstring string constant (the literal pieces of an f-string too) of the files in PRODUCT_FILES and of every file of
`cafe/pm/physics/`, found by the AST, is searched for PRODUCT_PAT. (2) The user documents (DOCUMENTS): the text is searched for DOC_PAT, the narrower phrases
of the claims sweep (review/round_23/merged.md). Every hit must be in the allow-list of its half. The allow-list is an ENUMERATION: a key is (file, scope, the
text around the phrase with its whitespace collapsed) and carries the number of times it occurs, a kind and a one-line reason. A new occurrence, a changed
context or a changed count fails until someone classifies it; an entry that no longer matches fails too (stale), so a deleted claim takes its entry with it.

What the lint proves: that no phrase of the vocabulary lands unreviewed. It does not prove that an allowed sentence is true (the reason says why it is kept),
or that a sentence outside the vocabulary is honest. It reads these files only; the rest of `cafe/pm` (config, acceptance, whatif, stats, env, stage3,
`__main__`) is not swept, and a new file outside `cafe/pm/physics/` is not in scope until it is added to PRODUCT_FILES.

Kinds. KEEP:S-n: a KEEP row of the sweep (true over the whole domain; its test or reason is in the row). definition: the text defines what it names, or states
what the code does with it. message: an error, refusal or note printed only when the condition it names holds. constant: a name, key or format, not a claim.
receipt: the text of a receipt that carries the figure it names. limit: an input limit the code enforces. measured: a named measurement of a named case.
history: a dated record of what an earlier round said or did. OPEN:S-n: a SCOPE or DELETE row of the sweep that is still on the tree;
OPEN:K-n: a sentence the skeptic pass of batch E found false or unscoped and the sweep did not list; both are routed to the lead (the reason is always
OPEN_REASON, and a comment above the row says what it is). A row whose text is edited or deleted goes stale and is removed."""
import ast
import pathlib
import re
from collections import Counter

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The vocabulary. Words at a boundary, case-insensitive. "bound" covers a printed "lower bound", "upper bound", "bounds".
PRODUCT_PAT = re.compile(r"\bup to\b|\bat most\b|\bcannot\b|\bnever\b|\bno ray\b|\bwithin about\b|\bby chance\b|\bfiner\b|\bno number\b|\bworst\b"
                         r"|\beverywhere\b|\bevery\b|\balways\b|\bpure physics\b|\bbounds?\b", re.I)
# The documents: the sweep's narrower phrases. A bare "every", "never" or "bound" is prose (and the statistics' own word) in 2,000 lines; these are the
# phrases the sweep found false: a limit printed as "up to N" or "at most N", a "by chance" or "no number of members" absolute, "within about", the
# worst-case hedge, a finer sampling, "pure physics", and a "lower bound" or "upper bound" (the statistic's name or an estimate's claim: each is read).
DOC_PAT = re.compile(r"\bup to \d|\bat most \d|\bby chance\b|\bno number of members\b|\bwithin about\b|\bworst[- ]case\b|\bfiner sampling\b"
                     r"|\bpure physics\b|\b(?:lower|upper) bound\b", re.I)

PRODUCT_FILES = ["cafe/pm/report.py", "cafe/pm/credibility.py", "cafe/pm/stage1.py", "cafe/pm/budget.py", "cafe/pm/pipeline.py"]
PHYSICS_DIR = "cafe/pm/physics"
DOCUMENTS = ["docs/RUNBOOK.md", "docs/CREDIBILITY.md", "docs/PHYSICS.md", "QUESTIONS_FOR_LAB.md"]
CONTEXT = 60
MAX_CTX = 30 + CONTEXT + 1
KINDS = ("message", "constant", "definition", "receipt", "measured", "history", "limit")
OPEN_REASON = "OPEN: routed to the lead"


def _ctx(text, start):
    """The phrase with 30 characters before it and 60 from its start, whitespace collapsed, a cut first word dropped (a key that survives a re-wrap)."""
    a = max(0, start - 30)
    w = " ".join(text[a:start + CONTEXT].split())
    if a and not text[a - 1].isspace() and " " in w:
        w = w.split(" ", 1)[1]
    return w


def doc_hits(text, pat=DOC_PAT):
    """[(scope, context, line)] for every match of `pat` in the text; a document has no scope (the empty string)."""
    return [("", _ctx(text, m.start()), text.count("\n", 0, m.start()) + 1) for m in pat.finditer(text)]


def _docstring_ids(tree):
    return {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str)}


def string_hits(src, pat=PRODUCT_PAT):
    """[(scope, context, line)] for every non-docstring string constant of the source (the literal pieces of an f-string too) that matches `pat`.
    The scope is the dotted name of the enclosing function or class, plus the name a module- or class-level assignment gives the string: it keeps a
    fragment such as 'bound' apart from another one, and it does not move when a line is added above it."""
    tree = ast.parse(src)
    doc = _docstring_ids(tree)
    out: list[tuple[str, str, int]] = []

    def walk(node, scope, in_func):
        for ch in ast.iter_child_nodes(node):
            sc, fn = scope, in_func
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                sc, fn = scope + [ch.name], in_func or not isinstance(ch, ast.ClassDef)
            elif isinstance(ch, (ast.Assign, ast.AnnAssign)) and not in_func:
                t = ch.targets[0] if isinstance(ch, ast.Assign) else ch.target
                if isinstance(t, ast.Name):
                    sc = scope + [t.id]
            if isinstance(ch, ast.Constant) and isinstance(ch.value, str) and id(ch) not in doc:
                out.extend((".".join(scope), _ctx(ch.value, m.start()), ch.lineno) for m in pat.finditer(ch.value))
            walk(ch, sc, fn)

    walk(tree, [], False)
    return out


def product_files():
    return PRODUCT_FILES + sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / PHYSICS_DIR).glob("*.py"))


def collect(files, hitter):
    """({(file, scope, context): count}, {(file, scope, context): [lines]})."""
    count: Counter = Counter()
    lines: dict[tuple[str, str, str], list[int]] = {}
    for f in files:
        for scope, ctx, line in hitter((ROOT / f).read_text()):
            count[(f, scope, ctx)] += 1
            lines.setdefault((f, scope, ctx), []).append(line)
    return count, lines


def unclassified(count, allow):
    """[(key, found, allowed)] for every key whose count differs from its allow-list entry (a missing entry allows 0)."""
    keys = set(count) | set(allow)
    return sorted((k, count.get(k, 0), allow[k][0] if k in allow else 0) for k in keys if count.get(k, 0) != (allow[k][0] if k in allow else 0))


def _entries(*groups):
    """{(file, scope, context): (count, kind, reason)} from `file, [rows], file, [rows], ...`; a row is (scope, context, count, kind, reason); a duplicate
    key is an error."""
    out = {}
    for f, rows in zip(groups[::2], groups[1::2], strict=True):
        for scope, ctx, n, kind, reason in rows:
            assert (f, scope, ctx) not in out, (f, scope, ctx)
            out[(f, scope, ctx)] = (n, kind, reason)
    return out


# ------------------------------------------------------------------------------------------------------------------------------- the allow-lists
# OPEN rows are the SCOPE or DELETE rows of the sweep still on the tree; a comment above each says which. Each goes stale the moment its text is
# changed, and the stale test then asks for the entry to be deleted. The lead's merge step of round 23 fixed the last eleven (S-3, S-17, S-20, S-41, K-1).
PRODUCT_ALLOW = _entries(
    'cafe/pm/budget.py', [
        ('emulator_plan', 'the emulator cannot train at this budget: one mission variant costs', 1, 'message',
         'the plan note printed when the computed cost of one variant exceeds the share: a condition the code checks'),
        ('describe', 'cannot', 1, 'KEEP:S-13',
         "'can'/'cannot certify P(fail) < 5 %' is certify_possible, n_max against n_certify = 73 (tests/test_stats.py, "
         'tests/test_budget.py)'),
    ],
    'cafe/pm/credibility.py', [
        ('LEVELS', 'review or field evidence (never awarded here)', 1, 'KEEP:S-30',
         "'never awarded here': the rule code awards at most level 3 (credibility.LEVELS and the cap in code)"),
        ('_l23_text', "above Hs 0). The card of every RF link computes the same figures for the link's own p", 1, 'KEEP:S-7',
         "'the card of every RF link ... for any heights from 0.1 m to 1000 m': rfband.valid_height, D_MIN_M "
         '(tests/test_round21_b.py, test_round22_b.py grids)'),
        ('_l23_text', 'airborne; an end whose height cannot be read at reference heights, which the card says are', 1, 'message',
         'the L23 text: an end whose height cannot be read is shown at assumed reference heights, which the card says'),
        ('LIMITATIONS', 'altitudes, is applied to every leg, so a leg flown at another altitude sees the lengt', 1, 'definition',
         'a limitation row (L16-L17 area) that says what the model does at every leg or depth: the description of the code, not a '
         'measured figure'),
        ('LIMITATIONS', 'at the surface and at every depth, come from HYCOM/GOFS with the BRIEF 2.5 literat', 1, 'definition',
         'a limitation row (L16-L17 area) that says what the model does at every leg or depth: the description of the code, not a '
         'measured figure'),
        ('RULES', 'names its inputs; 2 and every ingest self-check passed, the COARE u* is within', 1, 'definition',
         'the text of a factor rule: what level 2 of the ingest factor requires '
         '(tests/test_credibility.py::test_the_rules_text_is_the_documents_text)'),
        ('RULES', '1 a stage ledger exists; 2 every ledger is clean (ok, no failed check, chain intact, ha', 1, 'definition',
         'the text of a factor rule (the same test)'),
        ('RULES', '(a wider uncertainty cannot validate it; a row whose finest grid has not converge', 1, 'KEEP:S-18',
         "'a wider uncertainty cannot validate it': the rule printed beside it (U_val below half the reference) is the definition"),
        ('RULES', 'checks passed; 3 and every vehicle and link that leaves P(fail) < 5 % open (95 %', 1, 'definition',
         'the text of the uncertainty rule: which links it applies to and the Wilson bound it reads (the same test)'),
        ('RULES', '< 5 % open (95 % Wilson lower bound on P(fail) below 5 %; a link with the verdict NOT EXER', 1, 'definition',
         'the text of the uncertainty rule: which links it applies to and the Wilson bound it reads (the same test)'),
        ('RULES', '1 ledgers exist; 2 and every ledger carries a git sha, config hash, versions, and t', 1, 'definition',
         'the text of a factor rule (the same test)'),
        ('wind_prior_fit', '(95 % upper bound', 1, 'definition',
         "'95 % upper bound' names the statistic the prior row prints (TAO between-mooring variance)"),
        ('_dtmb_rows', 'not run: cafe.pm.dtmb5415 cannot be imported (', 1, 'message',
         "'not run: ... cannot be imported' is the reason a V&V row did not run"),
        ('vehicle_replaced', 'task never reads it', 1, 'message',
         "the reason a mission_defaults key is not read in a glider mode: GLIDER_MODE_ONLY, the code's own table"),
        ('counts_rule', 'n >= 1, 0 <= k_fail <= n, n at most', 1, 'limit',
         'the integer bound the counts guard enforces (9007199254740992 = 2**53)'),
        ('check_never_required', 'n - k_fail: a member that never needed the link passes): the summary was edited or is', 1, 'message',
         'the name of the field n_never_required inside a damage message'),
        ('_validation', 'and U_D, so |E| <= U_val cannot be assessed', 1, 'message',
         "a V&V row's note: the condition that U_num, U_input and U_D are missing"),
        ('_validation', ': an uncertainty that wide cannot validate it', 1, 'KEEP:S-18',
         "'an uncertainty that wide cannot validate it': by the rule printed beside it (U_val below half the reference)"),
        ('_uncertainty', 'n_certify: P(fail) < 5 % cannot be certified there', 1, 'KEEP:S-13',
         "'cannot be certified there' for n below n_certify = 73 (the exact receipt, tests/test_stats.py)"),
        ('_robustness', 'no first-order sensitivity (every ensemble is all-pass or all-fail, or n < 16) and no re', 1, 'definition',
         "the text of the robustness row: what 'no first-order sensitivity' means (every ensemble all-pass or all-fail, or n < 16)"),
        ('_ms_management', 'sha, config hash, versions in every ledger; stage-1 seeds recorded', 1, 'definition',
         'the text of the ms_management row: what the check requires of every ledger'),
        ('_render', 'cannot be checked from the verdict', 1, 'message',
         "the receipts-page note for a receipt that is not a verdict (the same text as report.py's)"),
        ('_render', 'and priors</h2><p class=muted>Every assumptions.yaml key, every perturbation prior, every', 1, 'definition',
         'the heading note of the Assumed page: assumed_inputs() builds it from every assumptions.yaml key, every perturbation '
         'prior and every platform leaf marked assumed (read, not enumerated by a test)'),
        ('_render', 'assumptions.yaml key, every perturbation prior, every platform input marked assume', 1, 'definition',
         'the heading note of the Assumed page: assumed_inputs() builds it from every assumptions.yaml key, every perturbation '
         'prior and every platform leaf marked assumed (read, not enumerated by a test)'),
        ('_render', 'every perturbation prior, every platform input marked assumed. A verdict that depends', 1, 'definition',
         'the heading note of the Assumed page: assumed_inputs() builds it from every assumptions.yaml key, every perturbation '
         'prior and every platform leaf marked assumed (read, not enumerated by a test)'),
        ('build', 'was not re-read. Level 4 is never awarded automatically.', 1, 'KEEP:S-30',
         "'Level 4 is never awarded automatically': the rule code awards at most level 3"),
    ],
    'cafe/pm/physics/__init__.py', [
        ('_RULES', 'from 0 up to, not including, 1', 1, 'message',
         "a validation rule's own text: from 0 up to, not including, 1 (the lambda beside it)"),
        ('_rule', 'in every place of a list', 1, 'message',
         "a validation rule's own text (the lambda beside it)"),
        ('_rule', 'and at most', 1, 'message',
         "a validation rule's own text (the lambda beside it)"),
    ],
    'cafe/pm/physics/comms.py', [
        ('THORP_DECIDES_LABEL', 'Thorp budget decides every link', 1, 'definition',
         'THORP_DECIDES_LABEL: the label of a run in which no sample was refined (acoustic_link default, stage1._bellhop_refine); '
         'the S-11 family, tests/test_round22_a.py'),
        ('receipts', '11.5/18.5/24.5 kHz, 0.5-6 km: worst |difference|', 1, 'receipt',
         "the receipt's name for the measured worst |difference| of three frequencies over 0.5-6 km: a measured maximum of a named"
         ' grid, printed with its value'),
    ],
    'cafe/pm/physics/glider.py', [
        ('_receipts', 'gliders at 0.25-0.4 m/s cannot hold station against a jet; swimming 0.3 < current 0.', 1, 'receipt',
         "the receipt's text for BRIEF 1.4: a glider at 0.25-0.4 m/s with a 0.5 m/s current; it carries the figures of the check"),
    ],
    'cafe/pm/physics/uas.py', [
        ('fly_sitl', 'cafe.emulator cannot be imported (', 1, 'message',
         "'cannot be imported': the reason the SITL emulator did not run"),
    ],
    'cafe/pm/physics/usv.py', [
        ('USVSim.__init__', 'a finite number above 0 for every member', 1, 'message',
         'a validation message: the speed factor must be finite and above 0 for every member (the check beside it)'),
        ('USVSim.__init__', 'be finite and above 0 for every member, got', 1, 'message',
         'a validation message (the check beside it)'),
        ('receipts', 'BRIEF 2.4: becalmed when it cannot stem the current for > N h', 1, 'receipt',
         "the receipt's text for BRIEF 2.4: becalmed when the USV cannot stem the current for more than N hours (the rule of the "
         'model)'),
    ],
    'cafe/pm/pipeline.py', [
        ('ocean_box', 'or more; the ocean fetch cannot cut that: narrow the box or lower box.pad_deg', 1, 'message',
         'the ocean-fetch refusal: the box cannot be cut'),
        ('ocean_box', '0 deg E; the GLBy ocean fetch cannot cross it: move the box east or west of 0 deg, or spli', 1, 'message',
         'the ocean-fetch refusal: the box crosses 0 deg E'),
        ('_umwm_depth', 'cannot be read (', 1, 'message',
         'a UMWM depth file that cannot be read'),
        ('s_ingest', 'm/s, at most', 1, 'limit',
         'the bound of an ingest check, printed with its value'),
        ('s_ingest.fetch_ocean', 'HYCOM, which this pipeline cannot download: write it with `python -m cafe.pm ingest-oce', 1, 'message',
         "the refusal to download the lab's HYCOM"),
        ('s_ingest', 'store (tree_sha256 over every file of the store)', 1, 'definition',
         'the ledger note on a store hash: the hash is over every file of the store (ledger.tree_sha256)'),
        ('s_ingest', 'manifest; tree_sha256 over every file of the store)', 1, 'definition',
         'the ledger note on a store hash (ledger.tree_sha256 over every file of the store)'),
        ('s_ingest', 'surface layer (sha256 of every file of the store)', 1, 'definition',
         'the ledger note on a store hash (ledger.tree_sha256 over every file of the store)'),
        ('_forcing_range', ', the worst', 2, 'measured',
         "an ingest check's note: the worst value found, printed with its number"),
        ('_forcing_range', 'every WRF and UMWM field the model reads and the ocean store', 1, 'definition',
         "the ingest self-check's all-clear text: what it checked (every field the model reads, inside the bounds of "
         'assumptions.yaml ingest.*)'),
        ('_forcing_range', 'all finite and inside the bounds of config/assumptions.yaml ingest.*', 1, 'definition',
         "the ingest self-check's all-clear text: what it checked (every field the model reads, inside the bounds of "
         'assumptions.yaml ingest.*)'),
        ('_ingest_checks', 'wave file is zero or was never written, which is no calm', 2, 'message',
         "an ingest check's note on a wave file that is zero or was never written"),
        ('_tao', '95 % upper bound of the between-mooring variance,', 1, 'definition',
         "'95 % upper bound' names the statistic printed beside it (the TAO fit)"),
        ('_stage1_checks', '; the report says it cannot certify < 5 %', 1, 'KEEP:S-13',
         "'the report says it cannot certify < 5 %' for a run whose members are below n_certify = 73"),
        ('_stage1_checks', 'stage 1 used are the same for every vehicle and are member_seed(seed, first member of a ba', 1, 'definition',
         'a ledger note on stream seeds: they are the same for every vehicle (stage-1 seed derivation, tests/test_round21_c.py)'),
        ('_stream_seed_problems', 'so the streams cannot be compared', 1, 'message',
         "the stream-seed check's refusal: no seeds to compare"),
        ('s_emulator', 'emulator misses this by chance with probability', 1, 'KEEP:S-19',
         "'misses this by chance with probability': the number is whatif's computed value, not read against whatif._chance_miss by"
         ' any reviewer (flagged in the hand-back)'),
        ('s_emulator', "a mission 1e6 units from every training row is refused; value is this run's own basel", 1, 'definition',
         'the text of the novelty limit: a mission further than the threshold from every training row is refused'),
        ('run', ': up to date (ledger', 1, 'constant',
         "a log line 'up to date': the stage's ledger is current; not a claim about a figure"),
    ],
    'cafe/pm/report.py', [
        ('_stat', 'interval bound', 1, 'constant',
         'a column header of the verdict table'),
        ('_stat', 'this ensemble (lower 95 % bound', 1, 'KEEP:S-12',
         "'P(fail) < 5 % is excluded by this ensemble (lower 95 % bound ...)': the confidence is printed (batch B deleted 'no "
         "number of members certifies it')"),
        ('_stat', 'P(fail) < 5 % cannot be certified at n =', 1, 'KEEP:S-13',
         "'cannot be certified at n = N ... 73 members are needed (3/n for zero failures)': n_certify exact (tests/test_stats.py)"),
        ('_stat', '(two-sided 95 % Wilson bound) are needed (with zero failures n members only show P(', 1, 'KEEP:S-13',
         "'cannot be certified at n = N ... 73 members are needed (3/n for zero failures)': n_certify exact (tests/test_stats.py)"),
        ('_sens_scope', '(95 % upper bound', 1, 'definition',
         "'95 % upper bound' names the statistic printed beside it"),
        ('_env', 'current along the tracks cannot be queried here; this section shows only the forcing', 1, 'message',
         'the environment section: it was not given an Environment, so it cannot query the forcing along the tracks'),
        ('_env', 'windows stage recorded at the worst moments.', 1, 'definition',
         'the windows stage records the worst moments of forcing; the next sentence of the page says it is not the instant a '
         'member failed'),
        ('_env', ") at up to 24 points of each vehicle's stage1b median track: wind", 1, 'definition',
         "the section's own sampling rule: min(n, 24) points per vehicle (report._env, np.linspace(..., min(n_ok, 24)))"),
        ('_stat_html', ', two-sided 95 % Wilson bound)', 1, 'definition',
         'the verdict-rule header names the Wilson bound'),
        ('_stat_html', 'rule: GO when P(fail) is at most', 1, 'definition',
         'the verdict rule as the code applies it: GO when P(fail) and the Wilson bound are at most the thresholds printed beside '
         'it'),
        ('_stat_html', '% Wilson upper bound on P(fail) is at most', 1, 'definition',
         'the verdict rule as the code applies it: GO when P(fail) and the Wilson bound are at most the thresholds printed beside '
         'it'),
        ('_stat_html', 'upper bound on P(fail) is at most', 1, 'definition',
         'the verdict rule as the code applies it: GO when P(fail) and the Wilson bound are at most the thresholds printed beside '
         'it'),
        ('_stat_html', 'bound', 1, 'constant',
         'a column header of the verdict table'),
        ('_top3_html', '(it is the same number in every one), so there is nothing to rank and no noise floor w', 1, 'message',
         'printed only when the ranked outcome is the same in every member (the condition is checked before it prints)'),
        ('_fix_html', 'that cannot (off the window, the box or the data)</summary><div c', 1, 'definition',
         'the summary line of the what-if table: changes the run cannot answer (off the window, the box or the data)'),
        ('_speed_html', 'flown sorties that reached every waypoint:', 1, 'definition',
         'the label of a computed share: the sorties that reached every waypoint'),
        ('_speed_html', '; with every launch scrubbed:', 1, 'definition',
         'the label of a computed share: with every launch scrubbed'),
        ('_granularity_samples_html', 'the required fraction from every sample).', 1, 'definition',
         "granularity's own explanation: too few samples to tell the required fraction from every sample"),
        ('IRIDIUM_NOTE', 'p_success and is retried up to the assumed max_attempts, the same in any sea state, w', 1, 'KEEP:S-2',
         "Iridium note: 'retried up to the assumed max_attempts, the same in any sea state' is the code path (iridium_session "
         'takes bytes, an rng, a count; tests/test_round16_report.py:107-110)'),
        ('_env_html', '<p class=warn>Forcing at the worst windows is not shown:', 1, 'definition',
         "the environment section's label: the forcing recorded at the windows stage's worst windows (each window is the strongest"
         ' analysis-field forcing; the next sentence says it is not the instant a member failed)'),
        ('_env_html', 'at the worst windows (each window is the record of the strongest an', 1, 'definition',
         'the same label, with the same disclaimer'),
        ('_env_html', 'guide to the forcing, not the worst case for the glider.</p>', 1, 'message',
         "'not the worst case for the glider' narrows the claim (the window is ranked by surface current, the glider's loss "
         "follows the flow over its dive); batch B's hand-back asked for this row; not in the sweep"),
        ('_chance', 'calibrated emulator misses it by chance with probability', 1, 'KEEP:S-19',
         "'misses it by chance with probability': whatif's computed value, not read against whatif._chance_miss by any reviewer "
         '(flagged)'),
        ('_emulator_html', 'a target of exactly 0 or 1 cannot be inside the interval', 1, 'definition',
         'on the raw P scale a target of exactly 0 or 1 cannot be inside an interval that is the inverse logit of a finite '
         'interval (mathematics, not a measurement)'),
        ('_emulator_html', 'rows the table already holds. Every EMULATED answer comes from a trained emulator, so none', 1, 'definition',
         "'EMULATED' is set only by the stage-3 emulator path (report.py:424, 1555); read, not enumerated by a test"),
        ('_sanity_html', 'cannot be checked from the verdict', 1, 'message',
         'the receipts-page note for a receipt that is not a verdict'),
        ('_render', 'check: every number links to a receipt, which is a hashed ledger ou', 1, 'KEEP:S-31',
         "'every number links to a receipt': the render-time self-check (_PATHS, report.py:2213-2222)"),
    ],
    'cafe/pm/stage1.py', [
        ('link_acts', 'always', 1, 'constant',
         "the YAML value 'always' of a link's `when` key"),
        ('_uas_hours', 'bounds', 1, 'constant',
         'the attribute name `bounds` of an Environment'),
        ('_bellhop_label', ', so it cannot change which they are', 2, 'KEEP:S-11',
         "'the Bellhop excess is held within 60 dB, so it cannot change which they are': clipped to +-60, sign-preserving "
         '(tests/test_round22_a.py)'),
        ('_sensitivity', 'Every member that needed the link', 1, 'definition',
         'the sensitivity text when every member failed: it says so and says there is nothing to compare'),
        ('_sensitivity', 'Every member', 1, 'definition',
         'the sensitivity text when every member failed: it says so and says there is nothing to compare'),
        ('_sensitivity', 'in every one of the', 1, 'definition',
         'the sensitivity text when the outcome is constant over the members it is read from (min == max is checked before it '
         'prints)'),
        ('_sensitivity', '): the sample cannot rank them, which is not the same as none mattering.', 1, 'message',
         'the sensitivity text: the sample cannot rank them, which is not the same as none mattering (printed only when the '
         'ranking has no signal)'),
    ],
)
DOC_ALLOW = _entries(
    'QUESTIONS_FOR_LAB.md', [
        # QUESTIONS 21a and 21d (the documents step of round 23, merged after the lint was written): records of the choice, not claims
        ('', 'say no more about what a finer sampling would find. **This takes away the only senten', 1, 'history',
         'a record of a round 23 choice (QUESTIONS 21): it names the deleted sentence or the lint\'s own word list, not a claim about the output'),
        ('', "of a UAS-pair card that a finer sampling finds larger errors** (for the demo's pair of", 1, 'history',
         'a record of a round 23 choice (QUESTIONS 21): it names the deleted sentence or the lint\'s own word list, not a claim about the output'),
        ('', '`pair_band` call at a finer sampling per card); (c) the old hedge back (it over-wa', 1, 'history',
         'a record of a round 23 choice (QUESTIONS 21): it names the deleted sentence or the lint\'s own word list, not a claim about the output'),
        ('', 'most`, `cannot`, `never`, `by chance`, `finer`, `no number`, `worst`, `every`, `always`', 1, 'definition',
         'a record of a round 23 choice (QUESTIONS 21): it names the deleted sentence or the lint\'s own word list, not a claim about the output'),
        ('', 'above 0 and at most 1000, `wp_radius_m` above 0, `roll_limit_deg` above', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', 'above 0 and at most 180; glider `dive_depth_m`, `station_tol_m` and `wp_', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', '1 (GO also needs the Wilson lower bound on success >= min(0.75, go), and `validate` prin', 1, 'definition',
         'names the statistic or the prior it discusses (a Wilson or 95 % bound), not a claim about the output'),
        ('', 'wind prior be its 95 % upper bound?** The TAO fit gives a persistent wind-speed sd', 1, 'definition',
         'names the statistic or the prior it discusses (a Wilson or 95 % bound), not a claim about the output'),
        ('', 'fit gives 0.569 m/s (95 % upper bound 0.957; direction 5.25 deg, bound 12.15): the fig', 1, 'definition',
         'names the statistic or the prior it discusses (a Wilson or 95 % bound), not a claim about the output'),
        ('', '804). Its one-sided 95 % upper bound is about 0.5 m/s (`value_hi95` in `ingest/priors', 1, 'definition',
         'names the statistic or the prior it discusses (a Wilson or 95 % bound), not a claim about the output'),
        ('', 'moves by 0.1 dB); an end up to 0.55 m triggers the card; a height off every row says', 1, 'history',
         'row 17e, marked SUPERSEDED by the live band (DECISIONS 1045): its text is history'),
        ('', 'speaks for every RF end up to 2.2 m; for an end of 0.55 to 2.2 m with a 10 to 15 m p', 1, 'history',
         'row 18b, marked SUPERSEDED by the live band (DECISIONS 1045): its text is history'),
        ('', 'Fresnel, Hs 0: too high by up to 5.1 dB, too low by up to 2.2 dB), for any other partne', 1, 'history',
         'row 18b, marked SUPERSEDED by the live band (DECISIONS 1045): its text is history'),
        ('', "by up to 5.1 dB, too low by up to 2.2 dB), for any other partner 'no error band is state", 1, 'history',
         'row 18b, marked SUPERSEDED by the live band (DECISIONS 1045): its text is history'),
        ('', '`batch` and `n_max` at most 10**6 and `budget` a known budget name. *Alternative', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', '1040) The excess moves by up to 4.6 dB with `nbeams` (reviewer B). `comms.bellhop_tl`', 1, 'measured',
         "'the excess moves by up to 4.6 dB with nbeams (reviewer B)': a named measurement by a named reviewer, not a limit of the"
         ' card'),
        ('', "per statistics guard and a lower bound on `pair_band`'s frequency. 20g. **The shape", 1, 'definition',
         'names the statistic or the prior it discusses (a Wilson or 95 % bound), not a claim about the output'),
    ],
    'docs/CREDIBILITY.md', [
        ('', '< 5 % open (95 % Wilson lower bound on P(fail) below 5 %; a link with the verdict NO', 1, 'definition',
         "names the Wilson bound the Uncertainty rule reads and the budget table's cap of 64 members for quick (n below n_certify "
         '= 73)'),
        ('', 'i.e. whose 95 % Wilson lower bound on P(fail) is below 5 % (an ensemble above that', 1, 'definition',
         "names the Wilson bound the Uncertainty rule reads and the budget table's cap of 64 members for quick (n below n_certify "
         '= 73)'),
        ('', '`assumed`. Budget `quick` (at most 64 members) cannot reach it; `battery_capacity_scale', 1, 'definition',
         "names the Wilson bound the Uncertainty rule reads and the budget table's cap of 64 members for quick (n below n_certify "
         '= 73)'),
        ('', 'The 95 % one-sided upper bound of the between-mooring variance with 10 degrees', 1, 'definition',
         'names the 95 % upper bound of the between-mooring variance (the TAO fit): a statistic, with its degrees of freedom'),
        ('', 'asks whether the upper bound should replace it. The number is not stable unde', 1, 'definition',
         'names the 95 % upper bound of the between-mooring variance (the TAO fit): a statistic, with its degrees of freedom'),
        ('', '1057 and 1062; the card up to 2.2 m and the envelope for 0.55 to 2.2 m added in roun', 1, 'history',
         'a dated record of what rounds 20 and 22 printed (the card up to 2.2 m)'),
        ('', 'on P(fail) lies inside GO (at most 0.10) or inside NO-GO (above 0.40), the interval the', 1, 'definition',
         "the verdict thresholds (GO at most 0.10): the rule's own numbers"),
    ],
    'docs/PHYSICS.md', [
        ('', 'the COARE profile is used up to 100 m. - 3-D hours are only the launch hour and the ne', 1, 'definition',
         'the height to which the profile code is applied when there is no 3-D field (a stated modelling limit of that fallback, not an accuracy)'),
        ('', "at one speed gave a step of up to 2.6 times in Cd; the demo's smallest `dcp` is 3.93 m/s", 1, 'definition',
         "measured: a step of 2.6 times in Cd (3.07e-3 against 1.19e-3 at U 8 m/s, sigH 1.5; review round 12, M-13, DECISIONS 653) that "
         "the hard switch at one dcp gave, which the fade removes; a named case, not a bound on any other"),
        ('', 'about 1.5 at the median and at most 2.2. (This section used to say "under-predicts by ab', 1, 'measured',
         'a named measurement of a named case, or a named limit of a test (the round, pair or probe is on the line); not a bound '
         'on the card'),
        ('', 'below and 5000 m is a lower bound (review round 9, M-35, DECISIONS 495) | 0.08 x 0', 1, 'definition',
         'a stated modelling limit or the name of a statistic in its own section (COARE up to 100 m, a step in Cd, a 95 % bound of'
         ' a prior), with the number it is for'),
        ('', '0.569) m/s 95 % upper bound of the persistent sd 0.957 wind_direction_bias', 1, 'definition',
         'a stated modelling limit or the name of a statistic in its own section (COARE up to 100 m, a step in Cd, a 95 % bound of'
         ' a prior), with the number it is for'),
        ('', '5.25) deg 95 % upper bound 12.15 wind_speed_noise sd 1.461 m/s, tau 5.', 1, 'definition',
         'a stated modelling limit or the name of a statistic in its own section (COARE up to 100 m, a step in Cd, a 95 % bound of'
         ' a prior), with the number it is for'),
        ('', '27 to 30 m/s of wind off by up to 1.5 m/s; 48 agrees with 200 to 0.025 m/s) ``` - The s', 1, 'measured',
         'a named measurement of a named case, or a named limit of a test (the round, pair or probe is on the line); not a bound '
         'on the card'),
        ('', 'with a gap above 0.2 m/s to at most 0.25 % (0.1 % measured; review round 8, M-8). A `stw', 1, 'measured',
         'a named measurement of a named case, or a named limit of a test (the round, pair or probe is on the line); not a bound '
         'on the card'),
        ('', 'the interference nulls, by up to 20 dB at ht 15 m and hr 60 m, and lowers the peaks), s', 1, 'measured',
         'a named measurement of a named case, or a named limit of a test (the round, pair or probe is on the line); not a bound '
         'on the card'),
        ('', 'On the demo the change is at most 5.3e-4 dB in any sample of the usv-uas-rf margin (an', 1, 'measured',
         'a named measurement of a named case, or a named limit of a test (the round, pair or probe is on the line); not a bound '
         'on the card'),
        ('', 'the loss was overstated by up to 39.2 dB: those were the extremes of the 400 sampled ra', 1, 'history',
         'a dated record of what round 22 said and why it was wrong (the extremes of the 400 sampled ranges)'),
        ('', 'for 2.2 m with 108.1 m a finer sampling gives -14.7 / +48.7 at 4,000 ranges and -14.9', 1, 'KEEP:S-22',
         'a named pair (2.2 m with 108.1 m) and named samplings (4,000 and 40,000 ranges)'),
        ('', "is no longer 'too high' by up to 2.9 dB (its minimum is -0.3 dB), the 0.1 m minimum is", 1, 'history',
         'a dated record of rounds 19 and 20 (the envelope and the row tolerance the live band superseded, DECISIONS 1045): '
         'history'),
        ('', 'by 0.45 dB, over 0.01 m by up to 0.97 dB at 0.1 m, 0.31 dB at 0.3 m, 0.135 dB at 0.5 m', 1, 'history',
         'a dated record of rounds 19 and 20 (the envelope and the row tolerance the live band superseded, DECISIONS 1045): '
         'history'),
        ('', 'then spoke for every RF end up to 2.2 m (plus the 0.001 m row tolerance), the highest he', 1, 'history',
         'a dated record of rounds 19 and 20 (the envelope and the row tolerance the live band superseded, DECISIONS 1045): '
         'history'),
        ('', 'its margin is too high by up to 5 dB. For such an end with a partner of 10 to 15 m (th', 1, 'history',
         'a dated record of rounds 19 and 20 (the envelope and the row tolerance the live band superseded, DECISIONS 1045): '
         'history'),
        ('', 'to +2.2 dB, margin too low by up to 2.2 dB and too high by up to 5.1 dB. The coarser 0.05', 1, 'history',
         'a dated record of rounds 19 and 20 (the envelope and the row tolerance the live band superseded, DECISIONS 1045): '
         'history'),
        ('', 'to 2.2 dB and too high by up to 5.1 dB. The coarser 0.05 m grid gives -5.133 and +2.13', 1, 'history',
         'a dated record of rounds 19 and 20 (the envelope and the row tolerance the live band superseded, DECISIONS 1045): '
         'history'),
        ('', 'for the 2.2 m partner gave up to 2.39 dB too high and up to 3.3 dB too low, outside the', 1, 'history',
         'a dated record of rounds 19 and 20 (the envelope and the row tolerance the live band superseded, DECISIONS 1045): '
         'history'),
        ('', 'up to 2.39 dB too high and up to 3.3 dB too low, outside the envelope. Against a Fresne', 1, 'history',
         'a dated record of rounds 19 and 20 (the envelope and the row tolerance the live band superseded, DECISIONS 1045): '
         'history'),
        ('', "about the extremes and a finer sampling; it is deleted); no extreme, no 'bound', 'up", 1, 'history',
         'the record of what round 22 and 23 deleted from the card (quotes the deleted words)'),
        ('', 'gave for how far a finer sampling moves the median, the counts, the extremes an', 1, 'history',
         'the record of what round 22 and 23 deleted from the card (quotes the deleted words)'),
        ('', 'the card or L23 says what a finer sampling does to an extreme, which is false for the pa', 1, 'history',
         'the record of what round 22 and 23 deleted from the card (quotes the deleted words)'),
        ('', "range gave another margin, by up to 26.5 dB in round 20's probes (27 of 2,496 ambiguous sa", 1, 'measured',
         'a named measurement of a named case, or a named limit of a test (the round, pair or probe is on the line); not a bound '
         'on the card'),
        ('', '1 to 2 m, batch A measured it up to 4 m); it is not a shadow and not the beam count, and a', 1, 'measured',
         'a named measurement of a named case, or a named limit of a test (the round, pair or probe is on the line); not a bound '
         'on the card'),
        ('', 'the excess moves by up to 4.6 dB with it, reviewer B), because the right count i', 1, 'measured',
         'a named measurement of a named case, or a named limit of a test (the round, pair or probe is on the line); not a bound '
         'on the card'),
        ('', 'each session retried up to 3 times; per-attempt success 0.95; set-up time log-nor', 1, 'definition',
         "the Iridium session's own rule: each session retried up to the assumed max_attempts (3 in radios.yaml; assumed, S-2)"),
        ('', 'p >= go (0.90) and the lower bound on success >= min(0.75, go); NO-GO if p < nogo', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', '%, 95 % (zero-failure Wilson upper bound below 5 %); one-sided (1 - 0.05)^n <= 0.05 ->', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', 'one `n_certify` solves: its upper bound is 0.0500. With zero failures and n below 73 the', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', 'the two-sided 95% Wilson upper bound." (the 60-member clause only below 60 members; f', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', 'an ensemble whose 95 % Wilson lower bound on P(fail) is below 5 %; one above it says "P(fa', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', 'by this ensemble" with the lower bound and no more (round 23, S-12), and the credibilit', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', 'threshold and the 90 % Wilson upper bound on P(fail) is at most 1 - `LO_SUCCESS_GO` (0.25', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', 'upper bound on P(fail) is at most 1 - `LO_SUCCESS_GO` (0.25 in the demo), NO-GO when P', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', '248). Budget `quick` (at most 64 members) cannot certify. ### 13.2 Latin hypercub', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', "if the predicted P(fail) is at most 0.10 and the upper end of the emulator's conformal 9", 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', 'conformal 90 % band is at most 0.25, the rule of Stage 1 (`intervals.verdict_band`;', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', '| |---|---| | `wilson lower bound k=3 n=30 vs statsmodels` (upper; and `agresti_co', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', '95 % (zero-failure Wilson upper bound)` | exactly 73 | | `zero-failure Wilson upper bo', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', '73 | | `zero-failure Wilson upper bound at n=73 is just under 5 %` | 1e-3 | | `one-sided', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', '/ calibrated threshold` at most 1. **These are scored on a synthetic table** (`synth', 1, 'definition',
         'names the Wilson bound a verdict rule or a test reads (n_certify = 73: S-13), or a threshold of the rule'),
        ('', 'needs all): `mach_max` (at most 0.1), `courant_max` (0.3), `yplus_in_30_300_fraction', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', 'constraints on a sample of at most 600 nodes: sum m_i u_i = 0 and sum m_i r_i x u_i = 0', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
    ],
    'docs/RUNBOOK.md', [
        ('', 'every one, not only a link within about 6 dB of its margin) is judged on Thorp absorpti', 1, 'history',
         "describes what round 20 and before sampled ('not only a link within about 6 dB'): a past rule, not a claim"),
        ('', 'above 0 and at most 60, `no_gust_front_within_min` 0 to 1440, `radius_km', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', '`lost_after_h` above 0 and at most 720, `dive_depth_m` 1 to 2000 and, for a glider, bet', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', 'above 0 and at most 1000, `ship.antenna_height_m` 0.5 to 100, `ship.tran', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', 'letters, digits, `_` and `-`, at most 64 characters (it is a directory name). The mission', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', 'times 0.5 m/s rounded up to 0.5 deg), must not cross 0 deg E: the ocean fetch take', 1, 'definition',
         'a rounding rule of pad_deg (rounded up to 0.5 deg), not a claim'),
        ('', '`go` and the 90 % Wilson lower bound on success at least 0.75, so 9 members without a', 1, 'KEEP:S-39',
         '9 members without a failure are GO whatever `go` is: the 90 % Wilson lower bound of 9 of 9 is 0.769 (8 of 8: 0.747), '
         'arithmetic of sweep row S-39, not recomputed here; the point estimate 1.0 meets any `go` <= 1'),
        ('', '`required_fraction` (above 0, at most 1) is the share of those moments the link must work', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', '`go` and the 90 % Wilson lower bound on success at least `min(0.75, go)`; below `nogo', 1, 'definition',
         "the verdict rule's own text: the Wilson bound the rule reads (the same rule as RUNBOOK 104)"),
        ('', 'at least 1 in plain digits, at most 9 of them (round 18, M-11, DECISIONS 961); an empty', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', 'x 0.5 m/s in degrees (at most 10, reached at 24.5 days: 24.4 days gives 9.5); set', 1, 'definition',
         '`pipeline.MAX_PAD_DEG` = 10 caps the default pad; the day figures are arithmetic (24.4 d x 86400 x 0.5 m/s / 111,195 m per deg = 9.48,'
         ' up to 9.5; 24.5 d = 9.52, up to 10)'),
        ('', 'it), not only the samples within about 6 dB of the margin as in round 20 and before: a', 1, 'history',
         "describes what round 20 and before refined ('within about 6 dB of the margin'): a past rule"),
        ('', "to 20 printed a card only up to 2.2 m and none, or 'no error band is stated', above it", 1, 'history',
         'a dated record of what rounds 17 to 20 printed'),
        ('', '<= N_MAX`: for quick batch at most 32 and not above n_max, n_max at most 64), so `batch', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', '32 and not above n_max, n_max at most 64), so `batch: 1000000`, `batch: 1000` beside `n_ma', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', '`... has batch ..., n_max at most 64 and batch at least 1, at most 32 and not above n_', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', 'most 64 and batch at least 1, at most 32 and not above n_max, for budget quick`, and a pla', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', "n >= 1, 0 <= k_fail <= n, n at most 9007199254740992)` (and a link's `n_never_required`", 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
        ('', 'sea point has no wind (at most 0.2 m/s) and no waves (UMWM `ust` or `swh` at or bel', 1, 'definition',
         'the ingest calm test: `pipeline.CALM_WIND_MS` = 0.2 m/s and `CALM_SWH_M` = 1e-3 m, the thresholds the code applies;'
         ' a definition of "a calm", not an input limit'),
        ('', 'is plain digits only, and at most 9 of them (review round 17, M-11, DECISIONS 931; rou', 1, 'limit',
         'an input limit the code enforces (the validation table of the mission, assumptions or budget check named on the line); a'
         ' limit, not an accuracy'),
    ],
)



# --------------------------------------------------------------------------------------------------------------------------------- the lint itself
CLASSIFY = "delete the claim, or classify it (a row with its kind and a one-line reason):\n"


def _report(count, lines, allow):
    return "\n".join(f"{k[0]}:{lines.get(k, ['stale'])[0]}: [{k[1]}] {k[2]!r}: found {found}, allowed {ok}" for k, found, ok in unclassified(count, allow))


def test_s_lint_product_every_phrase_is_classified():
    count, lines = collect(product_files(), string_hits)
    assert not unclassified(count, PRODUCT_ALLOW), CLASSIFY + _report(count, lines, PRODUCT_ALLOW)


def test_s_lint_documents_every_phrase_is_classified():
    count, lines = collect(DOCUMENTS, doc_hits)
    assert not unclassified(count, DOC_ALLOW), CLASSIFY + _report(count, lines, DOC_ALLOW)


@pytest.mark.parametrize("allow", [PRODUCT_ALLOW, DOC_ALLOW], ids=["product", "documents"])
def test_s_lint_every_entry_has_a_kind_and_a_reason(allow):
    for (f, scope, ctx), (n, kind, reason) in allow.items():
        assert n >= 1 and reason.strip() and ctx == " ".join(ctx.split()) and 0 < len(ctx) <= MAX_CTX, (f, scope, ctx)
        assert kind in KINDS or re.fullmatch(r"(KEEP|OPEN):S-\d+|OPEN:K-\d+", kind), (f, scope, ctx, kind)
        assert (kind.startswith("OPEN")) == (reason == OPEN_REASON), (f, scope, ctx)      # the one reason of a routed item; no other row may use it


def _sweep():
    """The verdict column of the claims sweep: {n: 'KEEP' | 'SCOPE' | 'DELETE'} from the table rows of review/round_23/merged.md."""
    rows = re.findall(r"^\| S-(\d+) \|.*\| (KEEP|SCOPE|DELETE)\b[^|]*\|\s*$", (ROOT / "review/round_23/merged.md").read_text(encoding="utf-8"), re.M)
    return {int(n): v for n, v in rows}


# A KEEP row whose sweep verdict is SCOPE because a batch applied the scope (the lint holds the sentence as it now reads): S-12 (batch B printed
# the confidence).
SCOPE_APPLIED = {12}


def test_s_lint_a_keep_row_names_its_sweep_row():
    """KEEP:S-n is a KEEP row of the claims sweep (review/round_23/merged.md) and OPEN:S-n a SCOPE or DELETE row of it: the number is read there, not only
    range-checked. A KEEP of a SCOPE row is allowed only when a batch applied the scope (SCOPE_APPLIED)."""
    sweep = _sweep()
    assert sorted(sweep) == list(range(1, 44)), sorted(sweep)
    for allow in (PRODUCT_ALLOW, DOC_ALLOW):
        for key, (_, kind, _) in allow.items():
            if kind.startswith("KEEP:S-"):
                n = int(kind.split("-")[1])
                assert sweep[n] == "KEEP" or n in SCOPE_APPLIED, (key, kind, sweep[n])
            elif kind.startswith("OPEN:S-"):
                assert sweep[int(kind.split("-")[1])] in ("SCOPE", "DELETE"), (key, kind)
    assert not {k for allow in (PRODUCT_ALLOW, DOC_ALLOW) for _, k, _ in allow.values() if k in ("KEEP", "OPEN")}


# What the lint's own machinery does: the self-tests that make "a new occurrence fails" a measured fact, not a promise.
def test_s_lint_a_new_phrase_fails_and_a_stale_entry_fails():
    src = 'def f():\n    """A docstring that never matters."""\n    return "the margin is up to 9 dB high"\n'
    ((scope, ctx, line),) = string_hits(src)
    assert (scope, ctx, line) == ("f", "the margin is up to 9 dB high", 3)                     # the docstring's "never" is not a string of the output
    key = ("x.py", scope, ctx)
    row = {key: (1, "KEEP:S-1", "r")}
    assert unclassified(Counter({key: 1}), {}) == [(key, 1, 0)]                                  # a new occurrence
    assert unclassified(Counter({key: 1}), row) == []
    assert unclassified(Counter({key: 2}), row) == [(key, 2, 1)]                                 # a second occurrence of an allowed one
    assert unclassified(Counter({key: 1}), {key: (2, "KEEP:S-1", "r")}) == [(key, 1, 2)]
    assert unclassified(Counter(), row) == [(key, 0, 1)]                                         # stale: the text is gone
    assert unclassified(Counter({("x.py", "g", ctx): 1}), row) == [(key, 0, 1), (("x.py", "g", ctx), 1, 0)]   # the same words in another scope are new


@pytest.mark.parametrize("src,found", [
    ('x = f"a {n} cannot {m} be"', ["cannot"]),                         # the literal pieces of an f-string are string constants
    ('x = "a " "worst case"', ["a worst case"]),                        # implicit concatenation is one constant
    ('x = "a lower BOUND"', ["a lower BOUND"]),
    ('x = "unbounded, bounded, boundary"', []),                         # a word boundary: only the words "bound" and "bounds"
    ('x = "up\\n  to this"', []),                                       # "up to" is two words and one space
    ('class C:\n    "never"\n    y = "pure physics"', ["pure physics"]),   # a docstring is not output; a class-level string is
    ('x = 1  # never', []),                                             # a comment is not a string constant
    ('def f():\n    pass\n    "always"', ["always"]),                    # only the FIRST statement is a docstring
])
def test_s_lint_scanner_cases(src, found):
    assert [c for _, c, _ in string_hits(src)] == found


def test_s_lint_scanner_scope_context_and_line():
    src = 'A = "x at most y"\nclass C:\n    B = "never"\n    def m(self):\n        t = "every a"\n        return ["bound"]\n'
    assert [(s, c, ln) for s, c, ln in string_hits(src)] == [("A", "x at most y", 1), ("C.B", "never", 3), ("C.m", "every a", 5), ("C.m", "bound", 6)]
    ((_, c, line),) = string_hits('x = 1\ny = "at most   one\\n   of ' + "z" * 100 + '"')
    assert c == "at most one of " + "z" * 40 and line == 2                     # 60 characters from the phrase, then the whitespace collapsed
    assert [(c, ln) for _, c, ln in doc_hits("a\nb at most 5\nmembers   of the run\n")] == [("a b at most 5 members of the run", 2)]
    hits = doc_hits("it was up to date; up to 3 m; up to\n4 m")
    assert [c for _, c, _ in hits] == ["it was up to date; up to 3 m; up to 4 m"]   # one hit, "up to" and a digit


def test_s_lint_dropping_any_entry_fails_the_lint():
    for allow, files, hitter in ((PRODUCT_ALLOW, product_files(), string_hits), (DOC_ALLOW, DOCUMENTS, doc_hits)):
        count, _ = collect(files, hitter)
        for key in allow:
            assert unclassified(count, {k: v for k, v in allow.items() if k != key}), key


def test_s_lint_the_scope_is_what_it_says():
    files = product_files()
    assert all((ROOT / f).is_file() for f in files + DOCUMENTS)
    assert set(PRODUCT_FILES) <= set(files) and sum(f.startswith(PHYSICS_DIR) for f in files) >= 7
    assert {"cafe/pm/physics/comms.py", "cafe/pm/physics/rfband.py", "cafe/pm/physics/uas.py"} <= set(files)
    assert {f for f, _, _ in PRODUCT_ALLOW} <= set(files) and {f for f, _, _ in DOC_ALLOW} <= set(DOCUMENTS)
