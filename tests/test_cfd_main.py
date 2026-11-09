"""`python -m cafe.cfd WHAT SAMPLE WORKDIR`: the argument check of the old app's smoke-run entry point (round 13, M-9)."""
import pytest

from cafe import cfd


def no_study(monkeypatch):
    """Every study stands in as a call that fails the test: a refused command must not start one (the free-surface study is an OpenFOAM run)."""
    def started(*a, **k):
        raise AssertionError("a study was started")
    for fn in ("characterize_external", "characterize_incidence", "characterize_free_surface"):
        monkeypatch.setattr(cfd, fn, started)


@pytest.mark.parametrize("argv", [[], ["external"], ["external", "torpedo"], ["externel", "torpedo", "W"], ["", "torpedo", "W"], ["surfaces", "wigley", "W"],
                                  ["surface", "nosuch", "W"], ["external", "", "W"]])
def test_a_wrong_what_a_wrong_sample_or_missing_arguments_are_a_usage_line_and_exit_2_before_anything_is_written(argv, tmp_path, monkeypatch, capsys):
    """"externel" fell to the last branch and started the free-surface study, writing a stamped *.externel.json; no arguments were an IndexError and an
    unknown sample a KeyError after the work directory was made."""
    no_study(monkeypatch)
    argv = [str(tmp_path / "W") if a == "W" else a for a in argv]
    with pytest.raises(SystemExit) as e:
        cfd.main(argv)
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("usage: python -m cafe.cfd external|incidence|surface SAMPLE WORKDIR [...]; SAMPLE is one of ") and "wigley" in err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("what, sample, study", [("external", "torpedo", "characterize_external"), ("incidence", "suboff", "characterize_incidence"),
                                                 ("surface", "wigley", "characterize_free_surface")])
def test_each_valid_what_still_runs_exactly_its_own_study(what, sample, study, tmp_path, monkeypatch):
    called = []
    no_study(monkeypatch)
    monkeypatch.setattr(cfd, study, lambda *a, **k: called.append(study) or dict(rho=1.0, speeds={}, dirs={}))
    assert cfd.main([what, sample, str(tmp_path / "W")]) == tmp_path / "W" / f"{sample}.{what}.json" and called == [study]
