"""Terminal-based review UI for proposed corrections."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .config import CLASS_ORDER

console = Console()


def display_issue(way: dict, index: int, total: int) -> None:
    """Display a single defect for review."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")

    table.add_row("Way ID", str(way.get("id", "?")))
    table.add_row("Street", way.get("name_display", "[Unnamed]"))
    table.add_row("Highway", way.get("highway", "?"))
    table.add_row("Oneway", way.get("oneway", "(not set)"))
    table.add_row("Defect Class", way.get("defect_class", "?"))
    table.add_row("Severity", way.get("severity", "?"))
    table.add_row("Review Status", way.get("review_status", "?"))
    table.add_row("Review Reason", way.get("review_reason", "?"))

    fix = proposed_fix(way)
    if fix:
        table.add_row("Proposed Fix", fix["description"])

    console.print(Panel(
        table,
        title=f"[bold]Issue {index}/{total}[/bold]",
        border_style="yellow" if way.get("severity") == "CRITICAL" else "blue",
    ))


def proposed_fix(way: dict) -> dict | None:
    """Generate a proposed fix for a classified defect."""
    defect = way.get("defect_class")
    if defect in ("A", "AB"):
        if way.get("oneway") == "yes" and way.get("highway") == "residential":
            return {
                "action": "remove_tag",
                "tag": "oneway",
                "description": f"Remove false oneway=yes from way {way['id']} ({way.get('name_display', '?')})",
                "element_type": "way",
                "element_id": way["id"],
                "changes": {"oneway": None},
            }
    return None


def review_defects(classified: dict) -> list[dict]:
    """Interactive review of all fixable defects. Returns accepted fixes."""
    all_ways = classified["all_ways"]
    fixable = [w for w in all_ways if proposed_fix(w) is not None]

    if not fixable:
        console.print("[yellow]No automatically fixable defects found.[/yellow]")
        return []

    fixable.sort(key=lambda w: (CLASS_ORDER.index(w["defect_class"]), w.get("name_display", "")))

    console.print(f"\n[bold]Found {len(fixable)} fixable defect(s).[/bold]\n")

    mode = Prompt.ask(
        "Review mode",
        choices=["each", "batch-accept", "batch-reject", "quit"],
        default="each",
    )

    if mode == "quit":
        return []
    if mode == "batch-accept":
        accepted = [proposed_fix(w) for w in fixable]
        console.print(f"[green]Accepted all {len(accepted)} fixes.[/green]")
        return [f for f in accepted if f is not None]
    if mode == "batch-reject":
        console.print("[red]Rejected all fixes.[/red]")
        return []

    accepted: list[dict] = []
    for i, w in enumerate(fixable, 1):
        display_issue(w, i, len(fixable))
        if Confirm.ask("  Accept this fix?", default=True):
            fix = proposed_fix(w)
            if fix:
                accepted.append(fix)
                console.print("  [green]Accepted[/green]")
        else:
            console.print("  [red]Skipped[/red]")

    console.print(f"\n[bold]Accepted {len(accepted)} of {len(fixable)} fixes.[/bold]")
    return accepted


def save_review(accepted: list[dict], out_path: Path) -> None:
    """Save accepted fixes to JSON for later submission."""
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(accepted, fh, indent=2, ensure_ascii=False)
    console.print(f"Saved {len(accepted)} accepted fixes to {out_path}")


def load_review(path: Path) -> list[dict]:
    """Load previously saved accepted fixes."""
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)
