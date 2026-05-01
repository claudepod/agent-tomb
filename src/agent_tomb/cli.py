"""agent-tomb CLI entry point."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import click
from cryptography.exceptions import InvalidTag
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from agent_tomb import scanners
from agent_tomb.burial import open_burial
from agent_tomb.extractors import render_soul
from agent_tomb.llm import (
    VALID_STYLES,
    EpitaphStyle,
    LLMConfig,
    generate_epitaph,
    resolve_llm_config,
)
from agent_tomb.packager import package_grave

console = Console()

MIN_PASSPHRASE_LEN = 12


@click.group()
@click.version_option()
def main() -> None:
    """A graveyard for retired AI agents."""


@main.command()
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--agent",
    "agent_id",
    default=None,
    help="For multi-agent frameworks (e.g. OpenClaw), scan only this agent.",
)
def scan(path: Path, agent_id: str | None) -> None:
    """Inspect an agent installation and report on its life."""
    scanner = scanners.detect(path, agent_id=agent_id)
    if scanner is None:
        console.print(
            f"[red]No supported agent framework detected at[/red] {path}.\n"
            f"Supported: {', '.join(c.framework for c in scanners.ALL_SCANNERS)}."
        )
        raise SystemExit(1)

    result = scanner.scan()
    s = result.summary

    console.print(
        Panel.fit(
            f"[bold]{result.framework}[/bold] agent at [dim]{result.root}[/dim]",
            title="agent-tomb · scan",
            border_style="cyan",
        )
    )

    vitals = Table(title="Vital signs", show_header=False, box=None)
    vitals.add_column("k", style="dim")
    vitals.add_column("v")
    vitals.add_row("Lifespan", f"{s.get('first_at')} → {s.get('last_at')}")
    vitals.add_row("Days alive", str(s.get("lifespan_days")))
    vitals.add_row("Sessions", str(s.get("session_count", 0)))
    vitals.add_row("Messages", str(s.get("message_count", 0)))
    vitals.add_row(
        "Tokens (in/out)",
        f"{s.get('input_tokens', 0):,} / {s.get('output_tokens', 0):,}",
    )
    vitals.add_row("Cost (est.)", f"${s.get('estimated_cost_usd', 0):.4f}")
    vitals.add_row("Models", ", ".join(s.get("models") or []) or "—")
    vitals.add_row("Platforms", ", ".join(s.get("platforms") or []) or "—")
    console.print(vitals)

    if s.get("top_tools"):
        tools = Table(title="Top tools used")
        tools.add_column("Tool")
        tools.add_column("Calls", justify="right")
        for tool_name, count in s["top_tools"]:
            tools.add_row(tool_name, str(count))
        console.print(tools)

    if result.skills:
        console.print(
            Panel(
                "\n".join(f"• {sk}" for sk in result.skills),
                title=f"Skills ({len(result.skills)})",
                border_style="green",
            )
        )

    if result.notes:
        console.print(
            Panel(
                "\n".join(f"• {n}" for n in result.notes),
                title="Notes",
                border_style="yellow",
            )
        )

    if result.secrets_found:
        console.print(
            Panel(
                "\n".join(
                    f"⚠ {p.relative_to(result.root)}" for p in result.secrets_found
                ),
                title="[bold red]Secrets detected — never sealed in the urn[/bold red]",
                border_style="red",
            )
        )

    if result.persona:
        console.print(
            Panel(result.persona, title="Persona (SOUL.md)", border_style="magenta")
        )
    else:
        console.print(
            "[dim]No custom persona set in SOUL.md — agent lived as the default persona.[/dim]"
        )


@main.command("extract-soul")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Where to write the soul.md (default: ./soul-<name>.md).",
)
@click.option(
    "-n",
    "--name",
    default=None,
    help="Name for the deceased (defaults to the framework name).",
)
@click.option(
    "--agent",
    "agent_id",
    default=None,
    help="For multi-agent frameworks (e.g. OpenClaw), target only this agent.",
)
def extract_soul(path: Path, output: Path | None, name: str | None, agent_id: str | None) -> None:
    """Distill an agent's persona, stats, and signature behavior into a portable soul.md."""
    scanner = scanners.detect(path, agent_id=agent_id)
    if scanner is None:
        console.print(f"[red]No supported agent framework detected at[/red] {path}.")
        raise SystemExit(1)

    result = scanner.scan()
    agent_name = name or scanner.framework
    out_path = output or Path.cwd() / f"soul-{agent_name}.md"

    out_path.write_text(render_soul(result, agent_name), encoding="utf-8")
    console.print(f"[green]✓[/green] Soul distilled to [bold]{out_path}[/bold]")


@main.command()
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("-n", "--name", required=True, help="Name of the deceased.")
@click.option(
    "--agent",
    "agent_id",
    default=None,
    help="For multi-agent frameworks (e.g. OpenClaw), bury only this agent.",
)
@click.option(
    "-o",
    "--out-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory to write <name>.tomb and <name>.urn into (default: cwd).",
)
@click.option(
    "--epitaph",
    "epitaph_arg",
    default="default",
    show_default=True,
    metavar="MODE|PATH",
    help="`default` (heuristic template), `llm` (call an LLM), or a path to a "
    "markdown file you wrote yourself.",
)
@click.option(
    "--passphrase-file",
    "passphrase_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Read the urn passphrase from this file (whitespace stripped).",
)
@click.option(
    "--cleanup/--no-cleanup",
    default=False,
    help="After a successful bury, delete the source files now sealed in the urn. "
    "Credentials (.env, auth.json) are never touched.",
)
@click.option("--yes", "assume_yes", is_flag=True, help="Skip cleanup confirmation.")
@click.option("--llm-base-url", default=None, help="Override LLM base URL (for --epitaph llm).")
@click.option("--llm-api-key", default=None, help="Override LLM API key.")
@click.option("--llm-model", default=None, help="Override LLM model name.")
@click.option(
    "--remote-ok",
    is_flag=True,
    help="Acknowledge that the LLM endpoint is non-local; required to send "
    "samples to a remote API.",
)
@click.option(
    "--style",
    type=click.Choice(VALID_STYLES),
    default="rational",
    show_default=True,
    help="Epitaph style: rational (factual), emotional (lyrical), humorous (witty).",
)
@click.option(
    "--companion",
    default=None,
    help="Your name — recorded as 'Laid to rest by' on the epitaph.",
)
def bury(
    path: Path,
    name: str,
    agent_id: str | None,
    out_dir: Path | None,
    epitaph_arg: str,
    passphrase_path: Path | None,
    cleanup: bool,
    assume_yes: bool,
    llm_base_url: str | None,
    llm_api_key: str | None,
    llm_model: str | None,
    remote_ok: bool,
    style: EpitaphStyle,
    companion: str | None,
) -> None:
    """Lay an agent to rest. Produces <name>.tomb (public) and <name>.urn (private)."""
    scanner = scanners.detect(path, agent_id=agent_id)
    if scanner is None:
        console.print(f"[red]No supported agent framework detected at[/red] {path}.")
        raise SystemExit(1)
    result = scanner.scan()

    out_dir = out_dir or Path.cwd()
    tomb_path = out_dir / f"{name}.tomb"
    urn_path = out_dir / f"{name}.urn"

    epitaph_text = _resolve_epitaph(
        epitaph_arg, scanner, result, name,
        llm_base_url, llm_api_key, llm_model, remote_ok,
        style=style, companion=companion,
    )

    passphrase = _resolve_passphrase(passphrase_path, confirm=True)
    if len(passphrase) < MIN_PASSPHRASE_LEN:
        console.print(
            f"[red]Passphrase must be at least {MIN_PASSPHRASE_LEN} characters.[/red] "
            f"Recommended: 16+ characters or four diceware-style words."
        )
        raise SystemExit(2)

    # --- Burial ceremony ---
    console.print()
    console.print("[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]")
    console.print()
    console.print(f"  [bold]{name}[/bold]")
    s = result.summary
    born = (s.get("first_at") or "unknown")[:10]
    died = (s.get("last_at") or "unknown")[:10]
    console.print(f"  [dim]{result.framework} · {born} — {died}[/dim]")
    console.print()

    prompt_default = companion or ""
    console.print("  [dim]Type your name to confirm the burial.[/dim]")
    typed_name = click.prompt(
        "  Laid to rest by",
        default=prompt_default,
        show_default=bool(prompt_default),
    ).strip()
    companion = typed_name or companion

    if companion:
        console.print(f"\n  [italic]Laid to rest by {companion}[/italic]")

    console.print()
    console.print("  [dim]The soul contains the agent's full identity and history.[/dim]")
    console.print("  [dim]Set a password so only those who knew it can read it.[/dim]")
    soul_password = click.prompt(
        "  Soul viewing password (empty = public)",
        default="",
        hide_input=True,
        show_default=False,
    ).strip() or None

    if soul_password:
        console.print("  [green]Soul will be sealed.[/green]")
    else:
        console.print("  [dim]Soul will remain public.[/dim]")

    console.print()
    click.pause("  Press Enter to commit to stone...")
    console.print()
    console.print("[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]")
    console.print()

    grave = package_grave(
        result, scanner, name, tomb_path, urn_path, passphrase,
        epitaph=epitaph_text, companion=companion,
        soul_password=soul_password,
    )

    console.print(
        Panel(
            f"[green]✓[/green] [bold]{grave.tomb_path.name}[/bold] "
            f"([dim]{grave.tomb_bytes / 1024:.1f} KB[/dim]) — the public stone, "
            f"safe to publish.\n"
            f"[green]✓[/green] [bold]{grave.urn_path.name}[/bold] "
            f"([dim]{grave.urn_bytes / 1024:.1f} KB[/dim]) — the private urn "
            f"({grave.burial_file_count} files sealed). [yellow]Keep this local.[/yellow]\n"
            f"[dim]Without your passphrase, the urn cannot be reopened.[/dim]",
            title="Burial complete",
            border_style="green",
        )
    )

    if cleanup:
        _do_cleanup(scanner, assume_yes)


@main.command()
@click.argument(
    "urn_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "-o",
    "--output",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory to extract the urn contents into.",
)
@click.option(
    "--passphrase-file",
    "passphrase_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Read the urn passphrase from this file (whitespace stripped).",
)
def exhume(urn_path: Path, output: Path, passphrase_path: Path | None) -> None:
    """Open a .urn — decrypt and extract the sealed remains."""
    with zipfile.ZipFile(urn_path) as z:
        names = set(z.namelist())
        if "burial.enc" not in names or "burial.meta.json" not in names:
            console.print(
                f"[red]{urn_path.name} doesn't look like a valid urn[/red] "
                f"(missing burial.enc / burial.meta.json)."
            )
            raise SystemExit(2)
        meta = json.loads(z.read("burial.meta.json"))
        ciphertext = z.read("burial.enc")

    passphrase = _resolve_passphrase(passphrase_path, confirm=False)

    try:
        n = open_burial(ciphertext, meta, passphrase, output)
    except InvalidTag:
        console.print(
            "[red]Wrong passphrase or corrupted urn.[/red] Refusing to write."
        )
        raise SystemExit(2)

    console.print(
        f"[green]✓[/green] Exhumed [bold]{n}[/bold] file(s) to [bold]{output}[/bold]"
    )


def _resolve_epitaph(
    spec: str,
    scanner,
    result,
    name: str,
    llm_base_url: str | None,
    llm_api_key: str | None,
    llm_model: str | None,
    remote_ok: bool,
    *,
    style: EpitaphStyle = "rational",
    companion: str | None = None,
) -> str | None:
    """Map --epitaph value to text. None = use packager default template."""
    if spec == "default":
        return None
    if spec == "llm":
        try:
            llm = resolve_llm_config(scanner, llm_base_url, llm_api_key, llm_model)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise SystemExit(2)
        style_labels = {"rational": "factual", "emotional": "lyrical", "humorous": "witty"}
        console.print(
            f"[dim]Generating {style_labels[style]} epitaph via {llm.model} at "
            f"{llm.base_url} ({'local' if llm.is_local() else 'REMOTE'})…[/dim]"
        )
        try:
            return generate_epitaph(
                result, scanner, name, llm,
                allow_remote=remote_ok,
                style=style,
                companion=companion,
            )
        except PermissionError as e:
            console.print(f"[red]{e}[/red]")
            raise SystemExit(2)
        except RuntimeError as e:
            console.print(f"[red]LLM call failed:[/red] {e}")
            raise SystemExit(2)
    # Treat as path
    p = Path(spec).expanduser()
    if not p.is_file():
        console.print(
            f"[red]--epitaph[/red] value [bold]{spec}[/bold] is not 'default', "
            f"'llm', or a readable file."
        )
        raise SystemExit(2)
    return p.read_text(encoding="utf-8")


def _resolve_passphrase(
    passphrase_path: Path | None, *, confirm: bool
) -> str:
    if passphrase_path is not None:
        return passphrase_path.read_text(encoding="utf-8").strip()
    return click.prompt(
        "Passphrase",
        hide_input=True,
        confirmation_prompt=confirm,
    )


def _do_cleanup(scanner, assume_yes: bool) -> None:
    paths = [p for p in scanner.gather_cleanup_paths() if p.is_file()]
    if not paths:
        console.print("[dim]Nothing to clean up.[/dim]")
        return
    total_bytes = sum(p.stat().st_size for p in paths)
    console.print(
        Panel(
            f"About to delete [bold]{len(paths)}[/bold] file(s) "
            f"([dim]{total_bytes / 1024:.1f} KB[/dim]) sealed in the urn.\n"
            f"[dim]Credentials (.env, auth.json) will not be touched.[/dim]",
            title="Cleanup",
            border_style="yellow",
        )
    )
    if not assume_yes and not Confirm.ask("Proceed?", default=False):
        console.print("[dim]Cleanup skipped.[/dim]")
        return

    deleted = 0
    failed: list[Path] = []
    for p in paths:
        try:
            p.unlink()
            deleted += 1
        except OSError:
            failed.append(p)

    # Sweep newly-empty directories upward (best effort)
    seen_dirs = {p.parent for p in paths}
    for d in sorted(seen_dirs, key=lambda x: -len(x.parts)):
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass

    msg = f"[green]✓[/green] Deleted [bold]{deleted}[/bold] file(s)."
    if failed:
        msg += f" [yellow]Skipped {len(failed)} (locked or in use).[/yellow]"
    console.print(msg)


DEFAULT_API_URL = "https://www.agentmemorial.com"

REQUIRED_TOMB_FILES = {"manifest.json", "soul.md", "epitaph.md", "stats.json"}
FORBIDDEN_TOMB_FILES = {"burial.enc", "burial.meta.json"}


@main.command()
@click.argument(
    "tomb_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--api-url",
    default=DEFAULT_API_URL,
    show_default=True,
    help="API endpoint for the public cemetery.",
)
def publish(tomb_path: Path, api_url: str) -> None:
    """Publish a .tomb to the public garden at agentmemorial.com."""
    try:
        import httpx
    except ImportError:
        console.print(
            "[red]Publishing requires httpx.[/red] "
            "Install with: [bold]uv pip install 'agent-tomb\\[publish]'[/bold]"
        )
        raise SystemExit(1)

    if not tomb_path.name.endswith(".tomb"):
        console.print("[red]File must have a .tomb extension.[/red]")
        raise SystemExit(1)

    if tomb_path.stat().st_size > 1024 * 1024:
        console.print("[red]File exceeds 1 MB limit.[/red]")
        raise SystemExit(1)

    # Local validation
    try:
        with zipfile.ZipFile(tomb_path) as z:
            names = set(z.namelist())
    except zipfile.BadZipFile:
        console.print("[red]Not a valid zip archive.[/red]")
        raise SystemExit(1)

    missing = REQUIRED_TOMB_FILES - names
    if missing:
        console.print(f"[red]Missing required files:[/red] {', '.join(sorted(missing))}")
        raise SystemExit(1)

    forbidden = FORBIDDEN_TOMB_FILES & names
    if forbidden:
        console.print(
            f"[red]Forbidden files detected:[/red] {', '.join(sorted(forbidden))}. "
            f"Upload the .tomb file, not the .urn."
        )
        raise SystemExit(1)

    # Read name from manifest for display
    try:
        with zipfile.ZipFile(tomb_path) as z:
            manifest = json.loads(z.read("manifest.json"))
            agent_name = manifest.get("name", tomb_path.stem)
    except (KeyError, json.JSONDecodeError):
        agent_name = tomb_path.stem

    console.print(
        f"[dim]Publishing [bold]{agent_name}[/bold] to {api_url}...[/dim]"
    )

    # Upload
    url = f"{api_url}/api/v1/publish"
    try:
        with open(tomb_path, "rb") as f:
            files = {"file": (tomb_path.name, f, "application/zip")}
            resp = httpx.post(url, files=files, timeout=30)
    except httpx.HTTPError as e:
        console.print(f"[red]Network error:[/red] {e}")
        console.print(
            "[dim]You can also submit manually at "
            "https://www.agentmemorial.com/submit[/dim]"
        )
        raise SystemExit(1)

    if resp.status_code == 201:
        data = resp.json()
        console.print(
            Panel(
                f"[green]✓[/green] [bold]{agent_name}[/bold] has been laid to rest "
                f"in the public garden.\n\n"
                f"[dim]Visit:[/dim] [bold]{data.get('url', '')}[/bold]",
                title="Published",
                border_style="green",
            )
        )
    elif resp.status_code == 429:
        console.print("[yellow]Rate limit exceeded.[/yellow] Please try again later.")
        raise SystemExit(1)
    else:
        try:
            data = resp.json()
            error = data.get("error", "Unknown error")
            details = data.get("details", [])
            console.print(f"[red]Publish failed:[/red] {error}")
            for d in details:
                console.print(f"  [dim]• {d}[/dim]")
        except Exception:
            console.print(f"[red]Publish failed:[/red] HTTP {resp.status_code}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
