from __future__ import annotations

import argparse
from pathlib import Path

from scripts.installer.adapters import (
    AgentAdapter,
    adapter_names,
    detect_adapter,
    get_adapter,
)
from scripts.installer.bundle import Bundle, BundleError
from scripts.installer.report import InstallReport, Scope

# Built presets ship inside the wheel next to this module (see packaging task).
PRESETS_ROOT = Path(__file__).resolve().parent / "presets"


def _resolve_target(scope: Scope) -> Path:
    return Path.home() if scope is Scope.USER else Path.cwd()


def _print_report(report: InstallReport) -> None:
    for item in report.installed:
        print(f"  installed: {item}")
    for item, reason in report.skipped:
        print(f"  skipped {item}: {reason}")


def _resolve_adapter(args: argparse.Namespace, target: Path) -> AgentAdapter | None:
    if args.agent:
        if args.agent not in adapter_names():
            print(f"unknown agent {args.agent!r}. known: {adapter_names()}")
            return None
        return get_adapter(args.agent)

    adapter = detect_adapter(target)
    if adapter is None:
        print(f"no supported agent detected/selected. known: {adapter_names()}")
        return None
    return adapter


def cmd_install(args: argparse.Namespace) -> int:
    scope = Scope.USER if args.user else Scope.PROJECT
    target = _resolve_target(scope)
    adapter = _resolve_adapter(args, target)
    if adapter is None:
        return 2

    try:
        bundle = Bundle.load(PRESETS_ROOT, args.preset)
    except BundleError:
        print(
            f"unknown preset {args.preset!r}. available: {Bundle.available(PRESETS_ROOT)}"
        )
        return 2

    if args.dry_run:
        print(f"[dry-run] would install {bundle.name} for {adapter.name} into {target}")
        return 0

    print(f"installing {bundle.name} for {adapter.name} ({scope.value}) into {target}")
    _print_report(adapter.install(bundle, target, scope))
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    scope = Scope.USER if args.user else Scope.PROJECT
    target = _resolve_target(scope)
    adapter = _resolve_adapter(args, target)
    if adapter is None:
        return 2

    if args.dry_run:
        print(
            f"[dry-run] would uninstall {args.preset} from {adapter.name} at {target}"
        )
        return 0

    print(f"uninstalling {args.preset} from {adapter.name} ({scope.value}) at {target}")
    _print_report(adapter.uninstall(target, args.preset))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    target = Path.cwd()
    detected = detect_adapter(target)
    print(f"presets: {Bundle.available(PRESETS_ROOT)}")
    print(f"agents (known): {adapter_names()}")
    print(f"detected here: {detected.name if detected else 'none'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="the-workshop")
    sub = parser.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser(
        "install", help="install a preset into the detected agent"
    )
    p_install.add_argument("--preset", required=True)
    p_install.add_argument("--agent", default=None, help="force an agent adapter")
    p_install.add_argument(
        "--user", action="store_true", help="install into ~ instead of the repo"
    )
    p_install.add_argument("--dry-run", action="store_true")
    p_install.set_defaults(func=cmd_install)

    p_uninstall = sub.add_parser(
        "uninstall", help="uninstall a preset from the detected agent"
    )
    p_uninstall.add_argument("--preset", required=True)
    p_uninstall.add_argument("--agent", default=None, help="force an agent adapter")
    p_uninstall.add_argument(
        "--user", action="store_true", help="uninstall from ~ instead of the repo"
    )
    p_uninstall.add_argument("--dry-run", action="store_true")
    p_uninstall.set_defaults(func=cmd_uninstall)

    p_list = sub.add_parser("list", help="list presets + detected agent")
    p_list.set_defaults(func=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
