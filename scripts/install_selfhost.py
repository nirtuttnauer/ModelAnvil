#!/usr/bin/env python3
"""Install a built self-host release by running that release's own controller.

The release copy of modelanvil.py stays the installer: it verifies every release file
against release.json, loads the release's local images and generates the instance
secrets. This script builds nothing, pulls nothing and never calls deploy/production.
"""
import argparse
from pathlib import Path
import subprocess
import sys


class ReleaseMissing(ValueError):pass


def parse(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True,help='New private instance directory.')
    parser.add_argument('--release',type=Path,required=True,help='Built release directory from scripts/build_selfhost_release.py.')
    parser.add_argument('--host');parser.add_argument('--bind')
    parser.add_argument('--http-port',type=int);parser.add_argument('--https-port',type=int)
    parser.add_argument('--credentials-stdin',action='store_true',help='Read the owner JSON from standard input instead of prompting.')
    return parser.parse_args(argv)


def controller_command(args):
    """The argument list for `<release>/modelanvil.py install`; only flags the operator passed are forwarded."""
    release=args.release.expanduser().resolve();controller=release/'modelanvil.py'
    if not release.is_dir():raise ReleaseMissing('Release directory not found: '+str(release))
    if not controller.is_file() or not (release/'release.json').is_file():raise ReleaseMissing('Not a built release (needs modelanvil.py and release.json): '+str(release))
    command=[sys.executable,str(controller),'install','--directory',str(args.directory.expanduser().resolve()),'--release',str(release)]
    for flag,value in (('--host',args.host),('--bind',args.bind),('--http-port',args.http_port),('--https-port',args.https_port)):
        if value is not None:command+=[flag,str(value)]
    if args.credentials_stdin:command.append('--credentials-stdin')
    return command


def main(argv=None):
    args=parse(argv)
    try:command=controller_command(args)
    except ReleaseMissing as exc:
        print('ModelAnvil: '+str(exc),file=sys.stderr);return 2
    # Standard input passes straight through to the controller, so this script never reads the owner credentials.
    return subprocess.run(command).returncode


if __name__=='__main__':sys.exit(main())
