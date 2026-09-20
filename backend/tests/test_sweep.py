"""The adoption rule and the report. The sweep's IO — re-indexing and
searching — is not tested here; what must not be allowed to drift is the rule
that decides whether a difference is real."""

from sweep_retrieval import GRID, SweepRow, adoption_verdict, render_sweep


def test_the_grid_is_the_nine_pre_registered_configurations():
    """Pinned so the grid cannot quietly grow after the results are in —
    adding a tenth configuration post hoc is exactly the fishing D46 forbids."""
    assert len(GRID) == 9
    assert set(GRID) == {(chars, over) for chars in (600, 1000, 1500) for over in (2, 4, 8)}
    assert (1000, 4) in GRID  # the baseline must be measured alongside the rest


def test_a_difference_inside_two_standard_errors_is_not_adopted():
    assert adoption_verdict(delta=0.04, stderr=0.03) is False


def test_a_difference_beyond_two_standard_errors_is_adopted():
    assert adoption_verdict(delta=0.10, stderr=0.03) is True


def test_a_difference_exactly_at_two_standard_errors_is_not_adopted():
    """Strictly greater. The boundary goes to the incumbent — a tie is not
    evidence for changing a shipped default."""
    assert adoption_verdict(delta=0.06, stderr=0.03) is False


def test_a_worse_configuration_is_never_adopted():
    assert adoption_verdict(delta=-0.20, stderr=0.01) is False


def test_an_infinite_standard_error_is_never_adopted():
    """paired_mrr_delta returns inf for n < 2 — an unmeasurable difference
    must not read as a significant one."""
    assert adoption_verdict(delta=0.5, stderr=float("inf")) is False


def test_the_report_states_the_adoption_rule_and_the_outcome():
    rows = [
        SweepRow(1000, 4, mrr=0.62, delta=0.0, stderr=0.0, adopt=False),
        SweepRow(600, 8, mrr=0.71, delta=0.09, stderr=0.03, adopt=True),
    ]
    report = render_sweep(rows, baseline_mrr=0.62)
    assert "two standard errors" in report
    assert "0.09" in report and "0.03" in report
    assert "600" in report


def test_the_report_says_so_when_nothing_clears_the_bar():
    """The likeliest outcome, and the one a reader most needs stated plainly —
    silence would read as an unfinished sweep."""
    rows = [SweepRow(600, 2, mrr=0.64, delta=0.02, stderr=0.04, adopt=False)]
    report = render_sweep(rows, baseline_mrr=0.62)
    assert "no configuration" in report.lower()
