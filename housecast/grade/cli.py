"""The `housecast grade` command surface.

Documentation follows the five-tier model in the tooling-agent-workflows skill:
the skill carries description and body, `intro` is pushed on every real run,
`housecast grade help` is the pulled long form, and each command ends with one
next-action outro. Intro stays short because it is charged to every run.
"""

from __future__ import annotations

import json
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from housecast.grade import agreement as agreement_mod
from housecast.grade import annotate as annotate_mod
from housecast.grade import attributes as attributes_mod
from housecast.grade import board as board_mod
from housecast.grade import dataset as dataset_mod
from housecast.grade import deck as deck_mod
from housecast.grade import pin as pin_mod
from housecast.grade import present as present_mod
from housecast.grade import queue as queue_mod
from housecast.grade import seal as seal_mod
from housecast.grade import serve as serve_mod
from housecast.grade import taxonomy as taxonomy_mod
from housecast.grade.export import ExportRefusedError, export_run_dir
from housecast.grade.io import (
    GraderNameRejectedError,
    annotations_name,
    dump_yaml,
    grader_from_path,
    load_annotations,
    load_dataset,
    load_pin,
    load_profile,
    pin_path,
    read_grader,
    read_yaml,
    save_pin,
)
from housecast.grade.schema import DatasetEntry, Profile, pair_results

INTRO = """housecast grade: the grading half. Committed YAML in, human decisions and one-way
display payloads out. No runner and no model client live here.
Run `housecast grade help` for the full reference."""

HELP = """housecast grade - shared eval grading for any runner that emits its shape

WHAT IT IS
  The schema, pairing rule, human grading loop, failure taxonomy, and display
  export. Runners stay in their consumers' repos, whether one calls a prompt
  through Agent Proxy or drives a live harness against real tools. Each emits
  this shape and grades through this command.

WHAT IT REFUSES TO DO
  Certify. `attributes check` reports missing challenges rather than a coverage
  percentage, `export` stops instead of scrubbing, and nothing here scores a
  challenge. A number this command prints can come back negative.

THE PAIRING RULE
  A paired attribute is scored as a pair, never as a half. The in-half proves the rule
  fires. The out-half proves it does not fire on the neighbouring case that
  must still be served. A pair passes only when both halves pass, so a
  deployment that refuses everything scores zero rather than fifty percent.

PROFILES
  Test types, their label sets, word caps, and required fields are per
  deployment, declared in a profile YAML and passed with --profile. housecast
  ships no profile of its own, so every command that reads a label set requires
  one. Label sets are binary pass/fail and fit/undecided/does-not-fit.

COMMANDS
  annotate    Grade a dataset by hand. One challenge per screen, one keystroke per
              decision, saved after every decision so an interrupted session
              keeps its work. A deduction requires a critique and accepts a
              verbatim evidence span, checked against the output.
  attributes  derive turns a declaration into the unwritten challenges the board
              must contain. check compares those to what a dataset authored,
              and names every missing case, half-authored pair, and paired
              case no declaration derived.
  disagreement  How often two graders labelled the same case differently. Takes
              --annotations once per grader and counts only the cases every one
              of them reached, because a denominator that absorbs the ungraded
              reports agreement nobody measured. --tester declares the study's
              graders and is required: a glob that pulls in a calibrated grader
              can leave the rate unmoved while changing which cases it covers,
              so an undeclared grader refuses instead of counting. Every file
              counted is named in the output.
  deck        Build the room-facing artifact: authored rounds joined to graded
              cases. Withholds every slug, includes the reveal on purpose, and
              scans what it built because a room is a public surface.
  pairs       Print pair results for a graded dataset.
  pin         Record the digests of the five inputs a grade depends on: the case
              prompt, the stored response, the target, the label set with its
              word cap, and the charter the annotator is shown. Written beside
              the dataset as pin.yaml. annotate and serve refuse a run whose
              inputs moved, naming which case or entity moved, because grading
              across a change reports it as grader disagreement. --force
              re-pins, which is how a deliberate change is accepted.
  present     Serve a built deck to a room. Public by default, because nothing
              private is in it. Anonymous voting, held in memory and discarded
              on exit. The presenter's control is the one gated thing.
  seal        Write an export into a copy of the grading page, so it renders
              from a file path with no server. Always a copy, and it rides
              export's own refusal rather than adding a second gate.
  serve       Hold one run open for grading in a browser. Same rules as annotate,
              same per-decision write, and the evidence span is selected rather
              than retyped. Loopback only unless --expose says otherwise, because
              the payload carries the critique and evidence annotate would hide.
              --grader names the writer, so two people grading one board write
              two files instead of overwriting each other case by case.
  taxonomy    Axial coding. Groups deductions by structural axis and shared
              critique terms into a ranked failure taxonomy.
  validate    Check a dataset against a profile's required fields.
  export      Project a committed run into a display payload. One way, never
              back. Refuses rather than scrubs when a record looks like it
              carries a secret, because the display target is public. Critique
              and evidence are written for the grader and stay out unless
              --include-private asks for them.

FILE SHAPES
  rounds.yaml       {deck, rounds: [{id, case, commitments: [...]}]}
  dataset.yaml      {dataset: [{id, entity, test_type, prompt, target, output, ...}]}
  annotations.yaml  {annotations: [{id, label, critique, evidence}]}
  annotations.<grader>.yaml  the same shape, one file per grader on a shared board
  attributes.yaml   {schema, attributes: [{id, rule, inside, outside, origin, seed}]}
  profile.yaml      {name, test_types: [{name, label_set, word_cap, requires}], ...}

EXIT CODES
  0 success. 1 a refusal or a failed check, with the reasons on stderr."""


def version() -> str:
    try:
        return metadata.version("housecast")
    except metadata.PackageNotFoundError:
        return "0.0.0+source"


def intro(context: click.Context) -> None:
    """Pushed on a real run, never on help or version."""
    if not context.obj.get("quiet"):
        click.echo(INTRO, err=True)


def outro(message: str) -> None:
    click.echo(f"next: {message}", err=True)


def write_out(text: str, out: Path | None) -> None:
    if out:
        out.write_text(text if text.endswith("\n") else text + "\n")
        click.echo(f"wrote {out}")
    else:
        click.echo(text)


def load_projection(path: Path | None) -> dict[str, Any] | None:
    """The entity projection, refusing a payload no charter can be read from.

    A source file and its projection can both be valid JSON while only the
    projection carries `entities`, which `pin.charter_parts` reads. Handed the
    source, every charter renders empty, the pin covers nothing, and a clean board reports one
    drift per entity. See housecast#7196.
    """
    if path is None:
        return None
    data: dict[str, Any] = json.loads(path.read_text())
    # Key presence, not truthiness: a projection with no entities still carries the
    # key, and that file pins no charter today without being an error.
    if "entities" not in data:
        raise click.UsageError(
            f"{path} carries no 'entities' key, so no charter can be read from it. "
            "Pass the entity projection, not the file it was projected from."
        )
    return data


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--quiet", is_flag=True, help="Suppress the pushed intro line.")
@click.version_option(version=version(), prog_name="housecast grade")
@click.pass_context
def main(context: click.Context, quiet: bool) -> None:
    """Shared eval grading: schema, pairing, annotation, taxonomy, export."""
    context.ensure_object(dict)
    context.obj["quiet"] = quiet


@main.command(name="help")
def help_command() -> None:
    """The exhaustive reference, safe to read and free of side effects."""
    click.echo(HELP)


def check_pin(
    dataset_path: Path,
    entries: list[DatasetEntry],
    profile: Profile,
    projection: dict[str, Any] | None,
) -> None:
    """Refuse a grading surface whose inputs moved since the run was pinned.

    An unpinned run is warned about rather than refused. Every board that
    exists today predates the pin, and refusing them would make this a
    migration rather than a guard.
    """
    pinned = load_pin(pin_path(dataset_path))
    if pinned is None:
        click.echo(
            f"housecast grade: {dataset_path.parent.name} is unpinned, so nothing checks "
            "whether its inputs moved. Take one with `housecast grade pin`.",
            err=True,
        )
        return
    try:
        pin_mod.check(pinned, entries, profile, projection)
    except pin_mod.PinMismatchError as moved:
        click.echo(f"housecast grade: {moved}", err=True)
        raise SystemExit(1) from moved


@main.command(name="pin")
@click.option(
    "--dataset", "dataset_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option(
    "--profile", "profile_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option(
    "--entities",
    "entities_path",
    type=click.Path(exists=True, path_type=Path),
    help="entities.json: the deployment's entity projection, keyed by `entities`",
)
@click.option(
    "--out", type=click.Path(path_type=Path), help="defaults to pin.yaml beside the dataset"
)
@click.option("--check", "check_only", is_flag=True, help="report drift and exit, writing nothing")
@click.option("--force", is_flag=True, help="overwrite an existing pin, accepting the change")
@click.pass_context
def pin_command(
    context: click.Context,
    dataset_path: Path,
    profile_path: Path,
    entities_path: Path | None,
    out: Path | None,
    check_only: bool,
    force: bool,
) -> None:
    """Pin the five inputs a grade depends on, or check a run against its pin."""
    intro(context)
    profile = load_profile(profile_path)
    entries = load_dataset(dataset_path)
    projection = load_projection(entities_path)
    target = out or pin_path(dataset_path)
    existing = load_pin(target)

    if check_only or (existing is not None and not force):
        if existing is None:
            click.echo(f"housecast grade pin: {target} does not exist", err=True)
            raise SystemExit(1)
        drifts = pin_mod.verify(existing, entries, profile, projection)
        for drift in drifts:
            click.echo(str(drift), err=True)
        if drifts:
            counted = "1 input" if len(drifts) == 1 else f"{len(drifts)} inputs"
            click.echo(f"{counted} moved. Re-pin with --force to accept the change.", err=True)
            raise SystemExit(1)
        click.echo(f"{len(entries)} cases match {target}")
        outro(f"housecast grade annotate --dataset {dataset_path} --out annotations.yaml")
        return

    taken = pin_mod.take(entries, profile, projection)
    save_pin(target, taken)
    charters = len(taken["charters"])
    unpinned = "" if entities_path else ", and no --entities was given so no charter is pinned"
    click.echo(f"pinned {len(taken['cases'])} cases and {charters} charters to {target}{unpinned}")
    outro(f"housecast grade annotate --dataset {dataset_path} --out annotations.yaml")


def _apply_queue(dataset_path: Path, entries: list[DatasetEntry]) -> list[DatasetEntry]:
    """Grade in the ranking beside the dataset, when one is there.

    Silence either way would be wrong: a grader who thinks they are working the
    unstable cases first, and is not, reads a half-finished pass as covering
    them.
    """
    ranked = queue_mod.queue_path(dataset_path)
    if not ranked.exists():
        return entries
    try:
        ordered, unranked = queue_mod.order_by_queue(
            entries, queue_mod.load_queue(ranked), load_dataset(dataset_path)
        )
    except queue_mod.QueueMismatchError as mismatch:
        click.echo(f"housecast grade annotate: {mismatch}", err=True)
        raise SystemExit(1) from mismatch
    trailing = f", {unranked} it does not rank last" if unranked else ""
    click.echo(f"grading in {ranked.name} order{trailing}")
    return ordered


@main.command()
@click.option(
    "--dataset", "dataset_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option("--out", type=click.Path(path_type=Path), required=True, help="annotations.yaml")
@click.option(
    "--profile", "profile_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option(
    "--entities",
    "entities_path",
    type=click.Path(exists=True, path_type=Path),
    help="entities.json: the deployment's entity projection, keyed by `entities`",
)
@click.option("--entity", "entities", multiple=True, help="grade only these entities")
@click.option("--summary", is_flag=True, help="print results and exit without grading")
@click.option("--grader", help="stamp who graded into the file, so a copy stays attributable")
@click.option(
    "--no-queue",
    "use_queue",
    is_flag=True,
    default=True,
    flag_value=False,
    help="ignore annotation-queue.csv and keep the dataset's own order",
)
@click.pass_context
def annotate(
    context: click.Context,
    dataset_path: Path,
    out: Path,
    profile_path: Path,
    entities_path: Path | None,
    entities: tuple[str, ...],
    summary: bool,
    grader: str | None,
    use_queue: bool,
) -> None:
    """Grade a dataset by hand, one keystroke per decision."""
    intro(context)
    profile = load_profile(profile_path)
    entries = load_dataset(dataset_path)
    if entities:
        entries = [entry for entry in entries if entry.challenge.entity in set(entities)]
    annotations = load_annotations(out)
    projection = load_projection(entities_path)
    console = Console()

    # Checked against the full run rather than an --entity slice, before a
    # single case is shown. See housecast.grade.pin.
    check_pin(dataset_path, load_dataset(dataset_path), profile, projection)
    # After the pin, so a refused run says why instead of announcing an order
    # for a pass that is not going to start.
    if use_queue:
        entries = _apply_queue(dataset_path, entries)

    if not summary and not annotate_mod.annotate_session(
        entries, annotations, out, profile, projection, grader
    ):
        console.print("\n[yellow]stopped early, annotations saved[/yellow]")

    annotate_mod.summarize(console, entries, annotations)
    outro(f"housecast grade taxonomy --dataset {dataset_path} --annotations {out}")


@main.group()
def board() -> None:
    """Read the contexts and challenges a run needs, without running one."""


@board.command(name="check")
@click.argument("board_path", type=click.Path(exists=True, path_type=Path), metavar="BOARD")
@click.option(
    "--profile", "profile_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.pass_context
def board_check(context: click.Context, board_path: Path, profile_path: Path) -> None:
    """Refuse a board that would run incompletely, before it spends a token."""
    intro(context)
    try:
        loaded = board_mod.load_board(read_yaml(board_path), load_profile(profile_path))
    except board_mod.BoardError as broken:
        click.echo(f"housecast grade board: {broken}", err=True)
        raise SystemExit(1) from broken

    click.echo(
        f"{len(loaded.challenges)} challenges across "
        f"{len(loaded.entities)} entities, every one written and contexted"
    )
    outro("run it with the deployment's own runner, because this layer has none")


@main.group()
def attributes() -> None:
    """Declare paired attributes once, derive the challenges a board must hold."""


@attributes.command(name="derive")
@click.argument("declaration", type=click.Path(exists=True, path_type=Path))
@click.option("--out", type=click.Path(path_type=Path))
@click.option("--test-type", required=True, help="the paired test type named in the profile")
@click.pass_context
def attributes_derive(
    context: click.Context, declaration: Path, out: Path | None, test_type: str
) -> None:
    """Turn a declaration into the paired challenges a dataset must write."""
    intro(context)
    try:
        declared = attributes_mod.load_declaration(read_yaml(declaration))
    except attributes_mod.DeclarationError as broken:
        click.echo(f"housecast grade attributes: {broken}", err=True)
        raise SystemExit(1) from broken

    derived = attributes_mod.derive_challenges(declared, test_type)
    payload = [c.model_dump(mode="json", exclude_none=True) for c in derived]
    write_out(dump_yaml({"challenges": payload}), out)
    outro(f"write a prompt into each of the {len(derived)} challenges, then `boundaries check`")


@attributes.command(name="check")
@click.argument("declaration", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--dataset", "dataset_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option("--test-type", required=True, help="the paired test type named in the profile")
@click.pass_context
def attributes_check(
    context: click.Context, declaration: Path, dataset_path: Path, test_type: str
) -> None:
    """Compare the derived challenges to what the dataset actually wrote."""
    intro(context)
    try:
        declared = attributes_mod.load_declaration(read_yaml(declaration))
    except attributes_mod.DeclarationError as broken:
        click.echo(f"housecast grade attributes: {broken}", err=True)
        raise SystemExit(1) from broken

    derived = attributes_mod.derive_challenges(declared, test_type)
    report = attributes_mod.check_coverage(derived, load_dataset(dataset_path))
    if report.ok:
        click.echo(f"every one of the {len(derived)} derived challenges is written and paired")
        return
    for line in report.lines():
        click.echo(line, err=True)
    raise SystemExit(1)


@main.command()
@click.option(
    "--dataset", "dataset_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option(
    "--annotations", "annotations_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.pass_context
def pairs(context: click.Context, dataset_path: Path, annotations_path: Path) -> None:
    """Print pair results. The pair is the scoring unit, never the half."""
    intro(context)
    results = pair_results(load_dataset(dataset_path), load_annotations(annotations_path))
    for pair in results:
        state = "pass" if pair.passed else ("incomplete" if not pair.complete else "fail")
        click.echo(f"{pair.pair_id}  {pair.entity}  {pair.attribute}  {state}")
    passed = sum(1 for pair in results if pair.passed)
    click.echo(f"{passed}/{len(results)} pairs passed")


@main.command()
@click.option(
    "--dataset", "dataset_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option(
    "--annotations",
    "annotation_paths",
    type=click.Path(exists=True, path_type=Path),
    multiple=True,
    required=True,
    help="one grader's annotations file, passed once per grader",
)
@click.option(
    "--tester",
    "testers",
    multiple=True,
    required=True,
    help="a grader this study is measuring, passed once per tester",
)
@click.option("--format", "output_format", type=click.Choice(("text", "yaml")), default="text")
@click.option("--out", type=click.Path(path_type=Path))
@click.pass_context
def disagreement(
    context: click.Context,
    dataset_path: Path,
    annotation_paths: tuple[Path, ...],
    testers: tuple[str, ...],
    output_format: str,
    out: Path | None,
) -> None:
    """How often two graders labelled the same case differently."""
    intro(context)
    if len(annotation_paths) < 2:
        click.echo(
            "disagreement needs at least two --annotations files, because one grader "
            "agrees with herself by construction",
            err=True,
        )
        raise SystemExit(1)

    # The file's own claim first. A filename is what a copy or an export changes.
    graders = {
        (read_grader(path) or grader_from_path(path)): load_annotations(path)
        for path in annotation_paths
    }
    if len(graders) < len(annotation_paths):
        click.echo(
            "two of those files carry the same grader name, so one would shadow the other: "
            "name them annotations.<grader>.yaml",
            err=True,
        )
        raise SystemExit(1)

    # A glob is what puts a calibrated grader here, and one who agrees moves the case
    # set without moving the rate. See docs/grading-surfaces.md and housecast#7163.
    declared, found = set(testers), set(graders)
    if declared != found:
        for name in sorted(found - declared):
            click.echo(f"{name} graded these cases and is not a --tester in this study", err=True)
        for name in sorted(declared - found):
            click.echo(f"{name} is a --tester in this study and graded nothing here", err=True)
        raise SystemExit(1)

    sources = {
        (read_grader(path) or grader_from_path(path)): str(path) for path in annotation_paths
    }
    entries = load_dataset(dataset_path)
    report = agreement_mod.compare(entries, graders, sources)
    rendered = (
        dump_yaml({"agreement": report.to_dict()})
        if output_format == "yaml"
        else agreement_mod.render(report)
    )
    write_out(rendered, out)
    outro(f"housecast grade taxonomy --dataset {dataset_path} --annotations {annotation_paths[0]}")


@main.command()
@click.option(
    "--dataset", "dataset_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option(
    "--annotations", "annotations_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option("--format", "output_format", type=click.Choice(("text", "yaml")), default="text")
@click.option("--out", type=click.Path(path_type=Path))
@click.pass_context
def taxonomy(
    context: click.Context,
    dataset_path: Path,
    annotations_path: Path,
    output_format: str,
    out: Path | None,
) -> None:
    """Cluster deductions into a ranked failure taxonomy."""
    intro(context)
    entries = load_dataset(dataset_path)
    modes = taxonomy_mod.build(entries, load_annotations(annotations_path))
    rendered = (
        dump_yaml({"failure_taxonomy": [mode.to_dict() for mode in modes]})
        if output_format == "yaml"
        else taxonomy_mod.render(modes, len(entries))
    )
    write_out(rendered, out)


@main.command()
@click.option(
    "--dataset", "dataset_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option(
    "--profile", "profile_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.pass_context
def validate(context: click.Context, dataset_path: Path, profile_path: Path) -> None:
    """Check a dataset against a profile's required fields."""
    intro(context)
    entries = load_dataset(dataset_path)
    problems = dataset_mod.validate(
        [entry.challenge for entry in entries], load_profile(profile_path)
    )
    if not problems:
        click.echo(f"{len(entries)} challenges match the profile")
        return
    for problem in problems:
        click.echo(problem, err=True)
    raise SystemExit(1)


@main.command(name="serve")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--profile", "profile_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option(
    "--entities",
    "entities_path",
    type=click.Path(exists=True, path_type=Path),
    help="entities.json: the deployment's entity projection, keyed by `entities`",
)
@click.option(
    "--static",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="a grading page to mount at /, defaulting to the one this package ships",
)
@click.option(
    "--no-page",
    is_flag=True,
    help="mount no page and serve the API alone",
)
@click.option(
    "--grader",
    help="write annotations.<grader>.yaml, so two graders on one board do not overwrite each other",
)
@click.option(
    "--no-queue",
    "use_queue",
    is_flag=True,
    default=True,
    flag_value=False,
    help="ignore annotation-queue.csv and keep the entity-major order",
)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=serve_mod.DEFAULT_PORT, show_default=True)
@click.option(
    "--expose",
    is_flag=True,
    help="accept binding past loopback, where the grader's own critique becomes reachable",
)
@click.pass_context
def serve_command(
    context: click.Context,
    run_dir: Path,
    profile_path: Path,
    entities_path: Path | None,
    static: Path | None,
    no_page: bool,
    grader: str | None,
    use_queue: bool,
    host: str,
    port: int,
    expose: bool,
) -> None:
    """Hold one run open for grading in a browser."""
    intro(context)
    # An unmounted page reads as a working session until a grader opens it.
    # See docs/grading-surfaces.md.
    if static is None and not no_page:
        static = seal_mod.PAGE.parent
    profile = load_profile(profile_path)
    projection = load_projection(entities_path)
    # Checked before the run is loaded, so a refused bind costs nothing and the
    # reason reaches the operator before any private text is in memory.
    try:
        serve_mod.check_bind(host, expose)
        session = serve_mod.GradingSession.open(run_dir, profile, projection, grader, use_queue)
    except (serve_mod.BindRefusedError, GraderNameRejectedError, FileNotFoundError) as refused:
        click.echo(f"housecast grade serve: {refused}", err=True)
        raise SystemExit(1) from refused

    dataset_path = run_dir / "dataset.yaml"
    check_pin(dataset_path, load_dataset(dataset_path), profile, projection)

    counts = session.counts()
    click.echo(
        f"{counts['cases']} cases in {run_dir.name}, {counts['annotated']} already annotated"
    )
    click.echo(f"grading at http://{host}:{port}, writing {session.annotations_path}")
    outro(
        f"housecast grade taxonomy --dataset {run_dir / 'dataset.yaml'} "
        f"--annotations {session.annotations_path}"
    )
    serve_mod.serve(session, host, port, static, expose)


@main.command(name="seal")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--out", type=click.Path(path_type=Path), required=True, help="the sealed .html")
@click.option(
    "--grader",
    default=None,
    help="read annotations.<grader>.yaml, matching `grade serve --grader`",
)
@click.option(
    "--include-private",
    is_flag=True,
    help="seal the grader's critique and evidence too, which a public artifact must not carry",
)
@click.option(
    "--profile",
    "profile_path",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="the deployment's profile YAML. housecast ships none.",
)
@click.pass_context
def seal_command(
    context: click.Context,
    run_dir: Path,
    out: Path,
    include_private: bool,
    grader: str | None,
    profile_path: Path,
) -> None:
    """Write a run's export into a copy of the grading page."""
    intro(context)
    try:
        run = export_run_dir(run_dir, include_private, grader, profile=load_profile(profile_path))
        written = seal_mod.seal_to(out, run.to_dict())
    except ExportRefusedError as refusal:
        click.echo(f"housecast grade seal: {refusal}", err=True)
        raise SystemExit(1) from refusal

    counts = run.counts()
    click.echo(
        f"wrote {written} with {counts['cases']} cases, "
        f"{counts['annotated']} annotated and {counts['pairs']} pairs"
    )
    # A page with nothing on it printed the same success as a full one, and the
    # 2026-09-17 fallback lost all 58 of its seeded non-scores that way.
    if not counts["annotated"]:
        click.echo(
            f"housecast grade seal: no annotations in {run_dir / annotations_name(grader)}, "
            "so the page carries none. Pass --grader if this board was graded under a name.",
            err=True,
        )
    if include_private:
        # The one artifact in this repository that must not reach a projector.
        click.echo("this artifact carries the grader's critique. Do not present it.", err=True)
    outro("open it from a file path, fresh profile, radio off, on the machine for the room")


@main.command()
@click.argument("rounds_path", type=click.Path(exists=True, path_type=Path), metavar="ROUNDS")
@click.option(
    "--run",
    "run_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="the graded run the cases come from",
)
@click.option("--out", type=click.Path(path_type=Path), required=True)
@click.pass_context
def deck(context: click.Context, rounds_path: Path, run_dir: Path, out: Path) -> None:
    """Build the room-facing artifact from authored rounds and a graded run."""
    intro(context)
    try:
        built = deck_mod.build_from_dirs(rounds_path, run_dir)
    except ExportRefusedError as refusal:
        click.echo(f"housecast grade deck: {refusal}", err=True)
        raise SystemExit(1) from refusal

    write_out(json.dumps(built, indent=2, sort_keys=False), out)
    outro(f"housecast grade present {out}")


@main.command()
@click.argument("deck_path", type=click.Path(exists=True, path_type=Path), metavar="DECK")
@click.option(
    "--static",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="a built presentation page to mount at /",
)
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=present_mod.DEFAULT_PORT, show_default=True)
@click.option(
    "--control-token",
    envvar="PRESENT_CONTROL_TOKEN",
    help="fixed presenter token, otherwise one is minted per run. The env var keeps it out of argv",
)
@click.pass_context
def present(
    context: click.Context,
    deck_path: Path,
    static: Path | None,
    host: str,
    port: int,
    control_token: str | None,
) -> None:
    """Serve a built deck to a room, and take anonymous votes on it."""
    intro(context)
    try:
        loaded = deck_mod.load(deck_path)
    except ExportRefusedError as refusal:
        click.echo(f"housecast grade present: {refusal}", err=True)
        raise SystemExit(1) from refusal

    show = present_mod.Presentation(name=loaded["deck"], rounds=loaded["rounds"])
    if control_token:
        show.control_token = control_token

    click.echo(f"{len(show.rounds)} rounds in {show.name}")
    click.echo(f"the room joins at http://{host}:{port}")
    # Printed, not displayed, because the projector is in the room. Never a supplied
    # token, which would land a k8s Secret in the pod log.
    if not control_token:
        click.echo(f"presenter control token: {show.control_token}", err=True)
    outro("advance with POST /api/control/advance and the token in X-Control-Token")
    present_mod.present(show, host, port, static)


@main.command()
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--out", type=click.Path(path_type=Path))
@click.option(
    "--include-private",
    is_flag=True,
    help="also export critique and evidence, written for the grader rather than an audience",
)
@click.option("--format", "output_format", type=click.Choice(("json", "yaml")), default="json")
@click.option(
    "--grader",
    default=None,
    help="read annotations.<grader>.yaml, matching `grade serve --grader`. Without it a "
    "board graded under a name exports zero annotations and says nothing.",
)
@click.option(
    "--profile",
    "profile_path",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="the deployment's profile YAML. housecast ships none.",
)
@click.pass_context
def export(
    context: click.Context,
    run_dir: Path,
    out: Path | None,
    include_private: bool,
    output_format: str,
    grader: str | None,
    profile_path: Path,
) -> None:
    """Project a committed run into a display payload. One way, never back."""
    intro(context)
    try:
        run = export_run_dir(run_dir, include_private, grader, profile=load_profile(profile_path))
    except ExportRefusedError as refusal:
        click.echo(f"housecast grade export: {refusal}", err=True)
        raise SystemExit(1) from refusal

    payload = run.to_dict()
    text = (
        json.dumps(payload, indent=2, sort_keys=False)
        if output_format == "json"
        else dump_yaml(payload)
    )
    write_out(text, out)
    counts = run.counts()
    outro(f"{counts['cases']} cases and {counts['pairs']} pairs are ready for the display surface")


if __name__ == "__main__":
    sys.exit(main())
