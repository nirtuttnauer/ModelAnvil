"""Replay a saved decision report and fail when a declared regression is missed."""


def gate_status(report, *, max_regression=0.0, require_decisive=True):
    """Return a process status: 0 passes, 1 misses the gate, 2 is an unusable report."""
    if not isinstance(report, dict):
        return 2
    if report.get('production_qualified') is not False:
        return 2
    candidate = report.get('candidate_accuracy')
    baseline = report.get('baseline_accuracy')
    if type(candidate) is not float and type(candidate) is not int:
        return 2
    if type(baseline) is not float and type(baseline) is not int:
        return 2
    if type(max_regression) is not float and type(max_regression) is not int or max_regression < 0:
        return 2
    if require_decisive and report.get('decisive') is not True:
        return 1
    if float(candidate) + float(max_regression) < float(baseline):
        return 1
    return 0
