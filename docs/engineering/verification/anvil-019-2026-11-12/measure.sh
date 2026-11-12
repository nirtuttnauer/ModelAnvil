#!/bin/zsh
# ANVIL-019 measurement: two actual PostgreSQL-tagged runs at the code commit, inside the host test lock.
set -u
WT=/Users/nirtuttnauer/Documents/Code/modelanvil/.claude/worktrees/anvil-019
PY=/Users/nirtuttnauer/Documents/Code/modelanvil/.claude/worktrees/anvil-gates/.venv/bin/python
CACHE=/tmp/modelanvil-premerge/cache
OUT=$1
mkdir -p $OUT/run1 $OUT/run2
cd $WT
{
  echo "lock_acquired_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "head=$(git rev-parse HEAD)"
  echo "git_status_porcelain_begin"; git status --porcelain; echo "git_status_porcelain_end"
  echo "machine=$(sysctl -n machdep.cpu.brand_string) $(uname -srm) cpus=$(sysctl -n hw.ncpu) mem=$(sysctl -n hw.memsize)"
  echo "python=$($PY -c 'import sys;print(sys.version.split()[0])')"
} > $OUT/meta.txt 2>&1
docker compose -p modelanvil-premerge -f compose.premerge.yaml up -d --wait db rabbitmq > $OUT/compose-up.txt 2>&1
echo "compose_up_exit=$?" >> $OUT/meta.txt
docker compose -p modelanvil-premerge -f compose.premerge.yaml ps --format '{{.Image}}' >> $OUT/compose-up.txt 2>&1
for run in 1 2; do
  echo "pg_run${run}_start_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $OUT/meta.txt
  env DATABASE_ENGINE=postgresql DATABASE_NAME=modelanvil DATABASE_USER=modelanvil DATABASE_PASSWORD=modelanvil \
    DATABASE_HOST=127.0.0.1 DATABASE_PORT=5432 RABBITMQ_URL='amqp://guest:guest@127.0.0.1:5672/%2F' \
    HF_HOME=$CACHE/embedding-model HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    MODELANVIL_BENCHMARK_CACHE=$CACHE/retrieval-benchmark MODELANVIL_RAG_DECODER_CACHE=$CACHE/rag-decoder \
    MODELANVIL_RAG_GENERATION_REPORT=$OUT/run$run/rag-generation-report.json \
    MODELANVIL_POSITION_REPORT=$OUT/run$run/evidence-position-report.json \
    MODELANVIL_RETRIEVAL_REPORT=$OUT/run$run/retrieval-controls-report.json \
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=$WT DJANGO_SETTINGS_MODULE=modelanvil.settings \
    $PY manage.py test --noinput --tag=pg -v 1 > $OUT/run$run/pg-tests.txt 2>&1
  echo "pg_run${run}_exit=$?" >> $OUT/meta.txt
  echo "pg_run${run}_end_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $OUT/meta.txt
done
# Targeted non-PostgreSQL guards for the touched modules (SQLite default settings).
env PYTHONPATH=$WT DJANGO_SETTINGS_MODULE=modelanvil.settings OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  $PY manage.py test --noinput --exclude-tag=pg -v 2 modelanvil.context_lab.test_positions modelanvil.rag.test_generation \
  modelanvil.rag.test_research modelanvil.rag.test_report > $OUT/targeted-sqlite.txt 2>&1
echo "targeted_sqlite_exit=$?" >> $OUT/meta.txt
docker compose -p modelanvil-premerge -f compose.premerge.yaml down -v --remove-orphans > $OUT/compose-down.txt 2>&1
echo "compose_down_exit=$?" >> $OUT/meta.txt
echo "lock_released_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $OUT/meta.txt
