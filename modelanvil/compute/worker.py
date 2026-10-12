"""Run the scoped outbound agent from operator-provisioned container environment."""
import os

from modelanvil.worker_agent import main


if __name__ == "__main__":
    raise SystemExit(main([
        "--endpoint", os.environ["MODELANVIL_WORKER_ENDPOINT"],
        "--worker-id", os.environ["MODELANVIL_WORKER_ID"],
        "--pool", os.environ["MODELANVIL_WORKER_POOL"],
        "--executor", os.environ["MODELANVIL_WORKER_EXECUTOR"],
        "--result-egress", os.environ["MODELANVIL_RESULT_EGRESS"],
    ]))
