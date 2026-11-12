#!/bin/zsh
# The four paths are environment variables here; the run used fixed paths with the same meaning.
# ANVIL-025, one hold of the host test lock: unit tests; if they pass, the code commit, the 0.1.1 build and the live run.
set -u
WT=${WT:?worktree}
T=${SCRATCH:?private scratch directory}
VPY=${VENV_PYTHON:?python 3.12 venv}
REL0=${RELEASES:?}/0.1.0
REL1=${RELEASES:?}/0.1.1
echo "lock acquired $(date -u +%FT%TZ)"
cd $WT
env -u DATABASE_ENGINE DJANGO_SETTINGS_MODULE=modelanvil.settings PYTHONPATH=$WT DATABASE_NAME=$T/db.sqlite3 DATABASE_TEST_NAME=$T/test.sqlite3 \
  $VPY manage.py test modelanvil.core.test_selfhost_drills modelanvil.core.test_selfhost --noinput -v 2 > $T/unit-3.log 2>&1
CODE=$?; echo "unit tests exit $CODE $(date -u +%FT%TZ)"; grep -E '^(Ran|OK|FAILED)' $T/unit-3.log
[ $CODE -eq 0 ] || exit 1
git add scripts/drill_selfhost.py modelanvil/core/test_selfhost_drills.py docs/engineering/self-host-drills.md
git commit -q -F $T/tools/commit-message.txt; echo "commit exit $? $(git rev-parse HEAD)"
echo "porcelain lines: $(git status --porcelain | wc -l | tr -d ' ')"
[ -z "$(git status --porcelain)" ] || exit 1
echo "build start $(date -u +%FT%TZ)"
$VPY scripts/build_selfhost_release.py --output $REL1 --version 0.1.1 > $T/build-0.1.1.json 2> $T/build-0.1.1-stderr.txt
echo "build exit $? end $(date -u +%FT%TZ)"; tail -c 2000 $T/build-0.1.1.json
[ -f $REL1/release.json ] || exit 1
$T/tools/run-all.sh $WT $REL0 $REL1 $T/live
echo "gate-build-live end $(date -u +%FT%TZ)"
