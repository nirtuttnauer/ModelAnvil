"""Help coverage for every ModelAnvil CLI leaf subcommand.

Walks the parser from ``build_parser()``. Each leaf is invoked with ``--help``.
The documented summary is the ``help=`` string argparse prints on the parent
command.
"""

from __future__ import annotations

import argparse
import io
from contextlib import redirect_stderr, redirect_stdout

from django.test import SimpleTestCase

from modelanvil.cli.main import build_parser, main

# Claims the public CLI help must not make. Matched in generated help text.
_FORBIDDEN = ("production-ready", "qualified", "best", "first")


def _subparsers(parser: argparse.ArgumentParser):
    found = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if not found:
        return None
    if len(found) != 1:
        raise AssertionError(f"{parser.prog} has {len(found)} subparser groups")
    return found[0]


def _choice_summary(action: argparse._SubParsersAction, name: str):
    for choice in action._choices_actions:
        if choice.dest == name:
            return choice.help
    raise AssertionError(f"{name} has no subparser choice")


def walk_commands(parser: argparse.ArgumentParser, prefix=()):
    """Yield ``(path, summary, parser, parent)`` for every subcommand."""
    action = _subparsers(parser)
    if action is None:
        return
    for name, child in action.choices.items():
        path = prefix + (name,)
        yield path, _choice_summary(action, name), child, parser
        yield from walk_commands(child, path)


def walk_leaves(parser: argparse.ArgumentParser, prefix=()):
    """Yield ``(path, summary, leaf_parser, parent_parser)`` for every leaf."""
    for path, summary, child, parent in walk_commands(parser, prefix):
        if _subparsers(child) is None:
            yield path, summary, child, parent


def walk_parsers(parser: argparse.ArgumentParser):
    yield parser
    action = _subparsers(parser)
    if action is None:
        return
    for child in action.choices.values():
        yield from walk_parsers(child)


def _collapsed(text: str) -> str:
    """Join formatter wrapping so a documented summary can be matched."""
    return " ".join(text.split())


def invoke_help(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = main(list(argv))
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    if code is None:
        code = 0
    return code, stdout.getvalue(), stderr.getvalue()


def _leaf_test(path, summary, leaf, parent):
    def test(self):
        code, text, err = invoke_help([*path, "--help"])
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertTrue(text.strip())
        self.assertEqual(text, leaf.format_help())
        self.assertIn(path[-1], text)
        self.assertIsInstance(summary, str)
        self.assertTrue(summary.strip())
        parent_code, parent_text, parent_err = invoke_help([*path[:-1], "--help"])
        self.assertEqual(parent_code, 0, parent_err)
        self.assertEqual(parent_err, "")
        self.assertTrue(parent_text.strip())
        self.assertEqual(parent_text, parent.format_help())
        self.assertIn(_collapsed(summary), _collapsed(parent_text))

    joined = " ".join(path)
    test.__doc__ = (
        f"``modelanvil {joined} --help`` exits 0 with non-empty help, "
        "and the parent help includes the documented summary."
    )
    return test


class CliHelpCoverageTests(SimpleTestCase):
    def test_help_text_omits_reserved_claims(self):
        """Generated CLI help does not contain the reserved claim words."""
        parser = build_parser()
        chunks = []
        for item in walk_parsers(parser):
            chunks.append(item.format_help())
            for action in item._actions:
                if isinstance(action.help, str):
                    chunks.append(action.help)
            sub = _subparsers(item)
            if sub is not None:
                for choice in sub._choices_actions:
                    if isinstance(choice.help, str):
                        chunks.append(choice.help)
        text = "\n".join(chunks)
        self.assertTrue(text.strip())
        lowered = text.lower()
        for word in _FORBIDDEN:
            self.assertNotIn(word, lowered)

    def test_every_subcommand_summary_is_documented(self):
        """Every subcommand, including groups, has a help= summary in the parent help."""
        commands = list(walk_commands(build_parser()))
        self.assertGreater(len(commands), len(_LEAVES))
        for path, summary, _child, parent in commands:
            with self.subTest(command=" ".join(path)):
                self.assertIsInstance(summary, str)
                self.assertTrue(summary.strip())
                self.assertIn(_collapsed(summary), _collapsed(parent.format_help()))

    def test_root_help_exits_zero(self):
        code, text, err = invoke_help(["--help"])
        self.assertEqual(code, 0, err)
        self.assertEqual(text, build_parser().format_help())
        self.assertTrue(text.strip())


_LEAVES = list(walk_leaves(build_parser()))
assert _LEAVES, "build_parser() did not expose any leaf subcommand"
for _path, _summary, _leaf, _parent in _LEAVES:
    _name = "test_help_" + "_".join(_path).replace("-", "_")
    setattr(CliHelpCoverageTests, _name, _leaf_test(_path, _summary, _leaf, _parent))
