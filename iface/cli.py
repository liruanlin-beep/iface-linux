"""English terminal menus and automation-friendly subcommands."""

import argparse
import json
import math
from pathlib import Path
import shlex
import sys

from iface import __version__
from iface import api
from iface.files import archive_outputs, write_new
from iface.results import results_csv


def mesh(value):
    try:
        values = tuple(int(v) for v in value.lower().replace(",", "x").split("x"))
        api.kpoints_text(values)
        return values
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use three positive mesh sizes, for example 7x7x1.") from exc


def miller(value):
    try:
        values = tuple(int(v) for v in value.split(","))
        if len(values) != 3 or not any(values):
            raise ValueError
        return values
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use a nonzero Miller index, for example 1,1,1.") from exc


def offset(value):
    try:
        values = tuple(float(v) for v in value.split(","))
        if len(values) != 2 or not all(math.isfinite(v) for v in values):
            raise ValueError
        return values
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use two fractional in-plane offsets, for example 0.5,0.") from exc


def parser():
    p = argparse.ArgumentParser(prog="iface", description="iface: Linux interface modeling, interlayer control and surface calculations")
    p.add_argument("--version", action="version", version=f"iface {__version__}")
    groups = p.add_subparsers(dest="group")
    groups.add_parser("menu", help="Open the interactive numbered menu")
    structures = groups.add_parser("structure", help="Existing iface slab/interface engines (optional dependency)")
    structure_cmd = structures.add_subparsers(dest="action", required=True)
    convert = structure_cmd.add_parser("convert", help="Convert CIF or a supported structure to POSCAR")
    convert.add_argument("source")
    convert.add_argument("output")
    slab = structure_cmd.add_parser("slab", help="Generate a surface slab")
    slab.add_argument("source")
    slab.add_argument("output")
    slab.add_argument("--miller", type=miller, default=(1, 0, 0))
    slab.add_argument("--layers", type=int, default=6)
    slab.add_argument("--vacuum", type=float, default=15)
    slab.add_argument("--termination", type=int, default=0)
    interface = structure_cmd.add_parser("interface", help="Match two crystals and scan interface gaps")
    for name in ("substrate", "film", "output"):
        interface.add_argument(name)
    for name in ("substrate", "film"):
        interface.add_argument(f"--{name}-miller", type=miller, default=(1, 0, 0))
        interface.add_argument(f"--{name}-layers", type=int, default=6)
    interface.add_argument("--gaps", nargs="+", type=float, default=[2.5])
    interface.add_argument("--lateral-offsets", nargs="+", type=offset,
                           default=[(0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5)])
    interface.add_argument("--max-strain", type=float, default=0.05)
    interface.add_argument("--max-area", type=float, default=500)
    interface.add_argument("--max-atoms", type=int, default=1000)
    interface.add_argument("--limit", type=int, default=24)
    scan = structure_cmd.add_parser("scan", help="Generate a batch of material, layer and interface-gap combinations")
    scan.add_argument("output")
    scan.add_argument("--substrates", nargs="+", required=True)
    scan.add_argument("--films", nargs="+", required=True)
    for name in ("substrate", "film"):
        scan.add_argument(f"--{name}-miller", type=miller, default=(1, 0, 0))
        scan.add_argument(f"--{name}-layer-values", nargs="+", type=int, default=[6])
    scan.add_argument("--gaps", nargs="+", type=float, default=[2.5])
    scan.add_argument("--lateral-offsets", nargs="+", type=offset, default=[(0.0, 0.0)])
    scan.add_argument("--max-strain", type=float, default=0.05)
    scan.add_argument("--max-area", type=float, default=500)
    scan.add_argument("--max-atoms", type=int, default=1000)
    scan.add_argument("--limit-per-gap", type=int, default=1)
    scan_results = structure_cmd.add_parser("scan-results", help="Inspect energies for an interface batch")
    scan_results.add_argument("output")
    surface = structure_cmd.add_parser("surface-energy", help="Calculate surface energy from a slab result and a bulk reference")
    surface.add_argument("directory")
    surface.add_argument("--bulk-energy-per-atom", type=float, required=True, help="Consistent bulk reference energy in eV/atom")
    surface.add_argument("--surfaces", type=int, default=2, help="Number of equivalent exposed slab surfaces")
    os_group = groups.add_parser("os", help="Optimization and static calculations")
    os_cmd = os_group.add_subparsers(dest="action", required=True)
    prep = os_cmd.add_parser("prepare", help="Create a new VASP input directory")
    prep.add_argument("structure", help="VASP 5 POSCAR/CONTCAR path")
    prep.add_argument("output")
    prep.add_argument("--preset", choices=("relax", "surface", "static", "pdos", "charge"), default="relax")
    prep.add_argument("--encut", type=float, default=520)
    prep.add_argument("--mesh", type=mesh, default=(7, 7, 1))
    prep.add_argument("--potcar-root")
    prep.add_argument("--variants", nargs="+", help="Exact potentials in POSCAR order, e.g. Fe_pv O")
    scheduler_arguments(prep, resources=True)
    static = os_cmd.add_parser("static", help="Create static inputs from relaxed CONTCAR")
    static.add_argument("source")
    static.add_argument("output")
    kp = os_cmd.add_parser("kpoints", help="Generate an automatic KPOINTS file")
    kp.add_argument("output")
    kp.add_argument("--mesh", type=mesh, default=(7, 7, 1))
    kp.add_argument("--mode", choices=("Gamma", "Monkhorst-Pack"), default="Gamma")
    pot = os_cmd.add_parser("potcar", help="Concatenate explicitly selected local potentials")
    pot.add_argument("structure")
    pot.add_argument("library")
    pot.add_argument("output")
    pot.add_argument("--variants", nargs="+")
    job = os_cmd.add_parser("script", help="Generate a Slurm/PBS job script")
    job.add_argument("output")
    scheduler_arguments(job, resources=True)
    check = os_cmd.add_parser("check", help="Validate input files without submitting")
    check.add_argument("directory", nargs="?", default=".")
    scheduler_arguments(check)
    report = os_cmd.add_parser("results", help="Inspect energies, forces, progress and warnings")
    report.add_argument("directory", nargs="?", default=".")
    report.add_argument("--recursive", action="store_true")
    report.add_argument("--csv", action="store_true", help="Print CSV instead of JSON")
    cleanup = os_cmd.add_parser("clean", help="Preview or archive outputs while retaining inputs")
    cleanup.add_argument("directory", nargs="?", default=".")
    cleanup.add_argument("--keep", nargs="*", default=[])
    cleanup.add_argument("--apply", action="store_true", help="Move outputs into .iface-archive")
    test = groups.add_parser("test", help="ENCUT and k-point convergence tests")
    test_cmd = test.add_subparsers(dest="action", required=True)
    for name, conversion in (("encut", float), ("kpoints", mesh)):
        scan = test_cmd.add_parser(name, help=f"Prepare a fixed-geometry {name} sweep")
        scan.add_argument("source")
        scan.add_argument("output")
        scan.add_argument("--values", nargs="+", type=conversion, required=True)
    summary = test_cmd.add_parser("results", help="Compare energies with the densest sweep point")
    summary.add_argument("directory")
    summary.add_argument("--tolerance", type=float, default=1.0, help="Tolerance in meV/atom")
    jobs = groups.add_parser("jobs", help="Explicit local-cluster submission and queue commands")
    jobs_cmd = jobs.add_subparsers(dest="action", required=True)
    submit = jobs_cmd.add_parser("submit", help="Preflight and submit exactly one calculation")
    submit.add_argument("directory", nargs="?", default=".")
    scheduler_arguments(submit)
    submit.add_argument("--yes", action="store_true", help="Confirm real cluster submission")
    status = jobs_cmd.add_parser("status", help="Show the current user's scheduler queue")
    scheduler_arguments(status)
    cancel = jobs_cmd.add_parser("cancel", help="Cancel a specific scheduler job")
    cancel.add_argument("job_id")
    scheduler_arguments(cancel)
    cancel.add_argument("--yes", action="store_true", help="Confirm cancellation")
    return p


def scheduler_arguments(p, resources=False):
    p.add_argument("--scheduler", choices=("slurm", "pbs"), default="slurm")
    if resources:
        p.add_argument("--name", default="iface")
        p.add_argument("--partition", default="", help="Slurm partition or PBS queue")
        p.add_argument("--nodes", type=int, default=1)
        p.add_argument("--tasks", type=int, default=1, help="MPI tasks per node")
        p.add_argument("--walltime", default="01:00:00")
        p.add_argument("--executable", default="vasp_std", help="VASP executable path (no shell arguments)")


def execute(args):
    values = vars(args).copy()
    group, action = values.pop("group"), values.pop("action", None)
    if group == "os":
        if action == "prepare":
            return api.prepare(**values)
        if action == "static":
            return api.to_static(**values)
        if action == "kpoints":
            path = write_new(args.output, api.kpoints_text(args.mesh, args.mode))
            return {"file": str(path.resolve())}
        if action == "potcar":
            payload = api.potcar_bytes(api.Poscar.read(args.structure), args.library, args.variants)
            path = write_new(args.output, payload)
            return {"file": str(path.resolve())}
        if action == "script":
            output = values.pop("output")
            return {"file": str(write_new(output, api.script_text(**values)).resolve())}
        if action == "check":
            return api.preflight(**values)
        if action == "results":
            rows = api.inspect_tree(args.directory, args.recursive)
            return results_csv(rows) if args.csv else rows
        if action == "clean":
            return archive_outputs(**values)
    if group == "test":
        if action == "results":
            return api.convergence_report(args.directory, args.tolerance)
        return api.convergence_sweep(args.source, args.output, action, args.values)
    if group == "structure":
        if action == "convert":
            return api.convert_structure(**values)
        if action == "slab":
            return api.slab(**values)
        if action == "interface":
            return api.interfaces(**values)
        if action == "scan":
            return api.interface_scan(**values)
        if action == "scan-results":
            return api.inspect_interface_scan(**values)
        if action == "surface-energy":
            return api.surface_energy(**values)
    if group == "jobs":
        if action == "submit":
            return api.submit(args.directory, args.scheduler, args.yes)
        if action == "status":
            return api.queue_status(args.scheduler)
        if action == "cancel":
            return api.cancel(args.job_id, args.scheduler, args.yes)
    raise ValueError("Unknown command. Run iface --help.")


def show(result):
    if isinstance(result, str):
        print(result, end="" if result.endswith("\n") else "\n")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


def _ask(label, default=None):
    suffix = f" [{default}]" if default is not None else ""
    answer = input(f"{label}{suffix}: ").strip()
    return answer or default or ""


def menu():
    sections = {
        "1": ("Structures and interfaces", [("Convert structure", "structure convert"), ("Generate slab", "structure slab"),
              ("Match interfaces", "structure interface"), ("Scan interface combinations", "structure scan"),
              ("Inspect interface scan results", "structure scan-results"), ("Calculate surface energy", "structure surface-energy")]),
        "2": ("VASP inputs and results", [("Generate inputs", "os prepare"), ("Relaxed to static", "os static"),
              ("Generate POTCAR", "os potcar"), ("Generate KPOINTS", "os kpoints"),
              ("Generate job script", "os script"), ("Archive outputs", "os clean"),
              ("Preflight inputs", "os check"), ("Inspect results", "os results")]),
        "3": ("Convergence tests", [("ENCUT sweep", "test encut"), ("K-point sweep", "test kpoints"),
              ("Inspect convergence results", "test results")]),
        "4": ("Scheduler jobs", [("Show queue", "jobs status"), ("Submit calculation", "jobs submit"),
              ("Cancel job", "jobs cancel")]),
    }
    print(f"\niface {__version__} | Linux terminal edition | English\nWorking directory: {Path.cwd()}")
    while True:
        print("\n" + "\n".join(f"  {key}. {value[0]}" for key, value in sections.items()) + "\n  0. Exit")
        choice = _ask("Module", "0")
        if choice == "0":
            return 0
        if choice not in sections:
            print("Select a listed module number.")
            continue
        title, entries = sections[choice]
        print(f"\n{title}\n" + "\n".join(f"  {i}. {entry[0]}" for i, entry in enumerate(entries, 1)) + "\n  0. Back")
        option = _ask("Action", "0")
        if not option.isdigit() or not 1 <= int(option) <= len(entries):
            continue
        command = entries[int(option) - 1][1].split()
        # The same parser powers interactive prompts, documented flags and scripts.
        root_parser = parser()
        group_parser = next(a for a in root_parser._actions if isinstance(a, argparse._SubParsersAction)).choices[command[0]]
        action_parser = next(a for a in group_parser._actions if isinstance(a, argparse._SubParsersAction)).choices[command[1]]
        print(f"\nCommand: iface {' '.join(command)}")
        action_parser.print_help()
        try:
            for argument in action_parser._actions:
                if argument.option_strings and not argument.required:
                    continue
                default = argument.default if argument.default is not None else None
                label = argument.dest.replace("_", " ").capitalize()
                multiple = argument.nargs in ("+", "*") or isinstance(argument.nargs, int)
                if multiple:
                    label += " (space-separated; quote paths containing spaces)"
                value = _ask(label, default)
                if argument.option_strings:
                    command.append(argument.option_strings[0])
                command.extend(shlex.split(value) if multiple else [value])
            extras = _ask("Options (quote paths containing spaces; Enter uses defaults)")
            command.extend(shlex.split(extras))
            parsed = root_parser.parse_args(command)
            if parsed.group == "jobs" and parsed.action in ("submit", "cancel"):
                if _ask("This changes real cluster jobs. Type YES to continue") != "YES":
                    print("Cancelled.")
                    continue
                parsed.yes = True
            show(execute(parsed))
        except (ValueError, OSError, RuntimeError, ImportError) as exc:
            print(f"Error: {exc}")
        except SystemExit:
            pass


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.group in (None, "menu"):
            if not sys.stdin.isatty():
                p.print_help()
                return 0
            return menu()
        result = execute(args)
        show(result)
        return 2 if isinstance(result, dict) and result.get("ok") is False else 0
    except (ValueError, OSError, RuntimeError, ImportError, OverflowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
