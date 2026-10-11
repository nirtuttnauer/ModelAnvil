"""ModelAnvil CLI command-line interface.

CLI commands supporting developer operations, headless automation, and private worker setup.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from modelanvil.cli.client import ModelAnvilClient, ModelAnvilClientError
from modelanvil.cli.config import get_setting, load_config, set_setting


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="modelanvil",
        description="ModelAnvil CLI: Developer tools for dataset, training, evaluation, and release pipelines.",
    )
    parser.add_argument("--url", help="Base URL for the ModelAnvil control plane (default: env or config)")
    parser.add_argument("--token", help="Bearer API key or token (default: env or config)")
    parser.add_argument("--tenant", help="Tenant ID (default: env or config)")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # config command
    cfg_p = subparsers.add_parser("config", help="Manage local CLI configuration")
    cfg_sub = cfg_p.add_subparsers(dest="subcommand", required=True)
    cfg_sub.add_parser("show", help="Show current configuration")
    cfg_set = cfg_sub.add_parser("set", help="Set a configuration variable")
    cfg_set.add_argument("key", choices=["url", "token", "tenant"])
    cfg_set.add_argument("value")

    # datasets command
    data_p = subparsers.add_parser("datasets", help="Dataset management")
    data_sub = data_p.add_subparsers(dest="subcommand", required=True)
    data_create = data_sub.add_parser("create", help="Create a dataset")
    data_create.add_argument("name", help="Dataset name")
    data_create.add_argument("--description", default="", help="Dataset description")
    data_sub.add_parser("list", help="List datasets")
    data_get = data_sub.add_parser("get", help="Get dataset details")
    data_get.add_argument("dataset_id", help="Dataset UUID")

    # training command
    train_p = subparsers.add_parser("training", help="Training management")
    train_sub = train_p.add_subparsers(dest="subcommand", required=True)
    train_launch = train_sub.add_parser("launch", help="Launch a training run")
    train_launch.add_argument("name", help="Run name")
    train_launch.add_argument("--recipe", default="pretrain_scratch", help="Training recipe")
    train_launch.add_argument("--dataset-id", help="Dataset revision ID")
    train_get = train_sub.add_parser("get", help="Get training run status")
    train_get.add_argument("run_id", help="Training run UUID")

    # evaluation command
    eval_p = subparsers.add_parser("evaluation", help="Evaluation management")
    eval_sub = eval_p.add_subparsers(dest="subcommand", required=True)
    eval_launch = eval_sub.add_parser("launch", help="Launch an evaluation run")
    eval_launch.add_argument("name", help="Evaluation run name")
    eval_launch.add_argument("--model-version-id", required=True, help="Model version UUID")
    eval_launch.add_argument("--suite-id", default="default-suite", help="Evaluation suite UUID")
    eval_get = eval_sub.add_parser("get", help="Get evaluation run results")
    eval_get.add_argument("run_id", help="Evaluation run UUID")

    # releases command
    rel_p = subparsers.add_parser("releases", help="Release and export management")
    rel_sub = rel_p.add_subparsers(dest="subcommand", required=True)
    rel_create = rel_sub.add_parser("create", help="Create a release")
    rel_create.add_argument("name", help="Release name")
    rel_create.add_argument("--model-version-id", required=True, help="Model version UUID")
    rel_create.add_argument("--version", default="1.0.0", help="Semantic version")
    rel_export = rel_sub.add_parser("export", help="Export release bundle")
    rel_export.add_argument("release_version_id", help="Release version UUID")
    rel_sbom = rel_sub.add_parser("sbom", help="Get release SPDX SBOM")
    rel_sbom.add_argument("release_version_id", help="Release version UUID")

    # rag command
    rag_p = subparsers.add_parser("rag", help="Retrieval Augmented Generation operations")
    rag_sub = rag_p.add_subparsers(dest="subcommand", required=True)
    rag_q = rag_sub.add_parser("query", help="Execute retrieval query")
    rag_q.add_argument("index_id", help="Index version UUID")
    rag_q.add_argument("query_text", help="Query string")
    rag_q.add_argument("--mode", default="hybrid", choices=["hybrid", "dense", "lexical"], help="Retrieval mode")
    rag_q.add_argument("--top-k", type=int, default=5, help="Top K results")

    # context-lab command
    ctx_p = subparsers.add_parser("context-lab", help="Context Lab experiments and compilation")
    ctx_sub = ctx_p.add_subparsers(dest="subcommand", required=True)
    ctx_cmp = ctx_sub.add_parser("compile", help="Compile recipe version prompt")
    ctx_cmp.add_argument("recipe_version_id", help="Recipe version UUID")
    ctx_cmp.add_argument("--vars", default="{}", help="Template variables JSON")

    # dataset-bank command
    bank_p = subparsers.add_parser("dataset-bank", help="Open Dataset Bank operations")
    bank_sub = bank_p.add_subparsers(dest="subcommand", required=True)
    bank_srch = bank_sub.add_parser("search", help="Search curated datasets")
    bank_srch.add_argument("query_text", nargs="?", default="", help="Search query")

    # workers command
    worker_p = subparsers.add_parser("workers", help="Worker operations and hybrid private egress (TECH-029)")
    worker_sub = worker_p.add_subparsers(dest="subcommand", required=True)
    worker_enroll = worker_sub.add_parser("enroll", help="Enroll a worker in a pool")
    worker_enroll.add_argument("--pool-id", type=int, required=True, help="Worker pool ID")
    worker_enroll.add_argument("--name", required=True, help="Worker name")
    worker_egress = worker_sub.add_parser("egress", help="Configure pool result egress boundary")
    worker_egress.add_argument("--pool-id", type=int, required=True, help="Worker pool ID")
    worker_egress.add_argument("--mode", choices=["envelope", "metadata_only"], required=True, help="Result egress mode")

    # journey command (TECH-004 API-only journey)
    journey_p = subparsers.add_parser("journey", help="Execute complete automated journeys")
    journey_sub = journey_p.add_subparsers(dest="subcommand", required=True)
    journey_smoke = journey_sub.add_parser("smoke", help="Run end-to-end API-only journey: import -> train -> evaluate -> export")
    journey_smoke.add_argument("--dataset-name", default="cli-smoke-dataset", help="Dataset name")
    journey_smoke.add_argument("--model-name", default="cli-smoke-model", help="Model name")
    journey_smoke.add_argument("--recipe", default="pretrain_scratch", help="Training recipe")

    return parser


def get_client(args: argparse.Namespace) -> ModelAnvilClient:
    url = args.url or get_setting("url", "http://localhost:8000")
    token = args.token or get_setting("token", "")
    tenant = args.tenant or get_setting("tenant", "")
    return ModelAnvilClient(base_url=url, token=token, tenant_id=tenant)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "config":
            if args.subcommand == "show":
                res = load_config()
                if args.json:
                    print(json.dumps(res, indent=2))
                else:
                    for k, v in res.items():
                        print(f"{k}: {v}")
                return 0
            elif args.subcommand == "set":
                set_setting(args.key, args.value)
                if not args.json:
                    print(f"Config updated: {args.key} = {args.value}")
                return 0

        client = get_client(args)

        if args.command == "datasets":
            if args.subcommand == "create":
                res = client.create_dataset(args.name, args.description)
            elif args.subcommand == "list":
                res = client.list_datasets()
            elif args.subcommand == "get":
                res = client.get_dataset(args.dataset_id)

        elif args.command == "training":
            if args.subcommand == "launch":
                res = client.launch_training_run(args.name, args.recipe, dataset_version_id=args.dataset_id)
            elif args.subcommand == "get":
                res = client.get_training_run(args.run_id)

        elif args.command == "evaluation":
            if args.subcommand == "launch":
                res = client.launch_evaluation_run(args.name, args.model_version_id, args.suite_id)
            elif args.subcommand == "get":
                res = client.get_evaluation_run(args.run_id)

        elif args.command == "releases":
            if args.subcommand == "create":
                res = client.create_release(args.name, args.model_version_id, args.version)
            elif args.subcommand == "export":
                res = client.export_release(args.release_version_id)
            elif args.subcommand == "sbom":
                res = client.get_release_sbom(args.release_version_id)

        elif args.command == "rag":
            if args.subcommand == "query":
                res = client.query_rag(args.index_id, args.query_text, mode=args.mode, top_k=args.top_k)

        elif args.command == "context-lab":
            if args.subcommand == "compile":
                vars_dict = json.loads(args.vars)
                res = client.compile_context(args.recipe_version_id, variables=vars_dict)

        elif args.command == "dataset-bank":
            if args.subcommand == "search":
                res = client.search_dataset_bank(args.query_text)

        elif args.command == "workers":
            if args.subcommand == "enroll":
                res = client.enroll_worker(args.pool_id, args.name)
            elif args.subcommand == "egress":
                res = client.configure_pool_egress(args.pool_id, args.mode)

        elif args.command == "journey":
            if args.subcommand == "smoke":
                res = client.run_api_journey(args.dataset_name, args.model_name, args.recipe)

        else:
            parser.print_help()
            return 2

        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(json.dumps(res, indent=2) if isinstance(res, (dict, list)) else str(res))
        return 0

    except ModelAnvilClientError as err:
        sys.stderr.write(f"Error ({err.status_code}): {err}\n")
        return 1
    except Exception as exc:
        sys.stderr.write(f"Unexpected error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
