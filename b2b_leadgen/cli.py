import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from b2b_leadgen.config import settings
from b2b_leadgen.models import EnrichedLead
from b2b_leadgen.pipeline import LeadGenPipeline, load_input_csv

app = typer.Typer(
    help="Automated B2B Lead Generation Pipeline using Google GenAI SDK (gemini-1.5-flash)",
    add_completion=False
)
console = Console()


@app.command()
def run(
    input_file: Path = typer.Option(
        Path("data/sample_companies.csv"),
        "--input", "-i",
        help="Path to input CSV file containing company names."
    ),
    output_file: Path = typer.Option(
        Path("data/output/enriched_leads.csv"),
        "--output", "-o",
        help="Path where enriched CSV output will be saved."
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit", "-n",
        help="Limit number of companies to process."
    ),
    concurrency: int = typer.Option(
        settings.max_concurrent_requests,
        "--concurrency", "-c",
        help="Maximum concurrent web requests and API calls."
    ),
    model: str = typer.Option(
        settings.gemini_model,
        "--model", "-m",
        help="Google Gemini model identifier (e.g. gemini-1.5-flash, gemini-1.5-pro, gemini-2.0-flash)."
    ),
    no_checkpoint: bool = typer.Option(
        False,
        "--no-checkpoint",
        help="Disable caching / checkpointing mechanism."
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="Explicit Google Gemini API key (or set GEMINI_API_KEY env var)."
    )
):
    """
    Executes the B2B lead enrichment pipeline end-to-end.
    """
    console.rule("[bold blue]B2B Lead Generation Pipeline[/bold blue]")
    console.print(f"[cyan]Input File:[/cyan] {input_file}")
    console.print(f"[cyan]Output File:[/cyan] {output_file}")
    console.print(f"[cyan]Model:[/cyan] {model}")
    console.print(f"[cyan]Concurrency:[/cyan] {concurrency}")

    if not input_file.exists():
        console.print(f"[bold red]Error:[/bold red] Input file {input_file} does not exist!")
        raise typer.Exit(code=1)

    effective_key = api_key or settings.effective_api_key
    if not effective_key:
        console.print("[yellow]Warning: No GEMINI_API_KEY detected in environment or arguments.[/yellow]")
        console.print("[yellow]The pipeline will attempt fallback heuristics or default credentials.[/yellow]")

    # Load input companies
    leads_input = load_input_csv(str(input_file))
    if not leads_input:
        console.print(f"[bold red]Error:[/bold red] No valid company records found in {input_file}!")
        raise typer.Exit(code=1)

    if limit and limit > 0:
        leads_input = leads_input[:limit]

    console.print(f"[green]Loaded {len(leads_input)} company records to process.[/green]\n")

    pipeline = LeadGenPipeline(
        api_key=effective_key,
        model=model,
        max_concurrency=concurrency,
        use_checkpoint=not no_checkpoint
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        task_id = progress.add_task("[cyan]Processing companies...", total=len(leads_input))

        def on_progress(lead: EnrichedLead, current: int, total: int):
            status_color = "green" if lead.status == "success" else "yellow"
            email_info = f" ({lead.primary_email})" if lead.primary_email else ""
            progress.update(
                task_id,
                advance=1,
                description=f"[{status_color}]{lead.company_name}[/{status_color}]{email_info}"
            )

        results = asyncio.run(
            pipeline.run_batch(
                inputs=leads_input,
                output_csv_path=str(output_file),
                progress_callback=on_progress
            )
        )

    # Render Summary Table
    console.print("\n")
    console.rule("[bold green]Enrichment Summary[/bold green]")

    table = Table(show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Company", style="bold", width=15)
    table.add_column("Website", style="cyan", width=25)
    table.add_column("Contact Email", style="yellow", width=25)
    table.add_column("1-Sentence Summary", style="dim", width=40)
    table.add_column("Status", width=10)

    for r in results:
        status_badge = f"[green]Success[/green]" if r.status == "success" else f"[red]{r.status}[/red]"
        table.add_row(
            r.company_name,
            r.website_url or "-",
            r.primary_email or "[dim]None found[/dim]",
            r.company_summary or "-",
            status_badge
        )

    console.print(table)
    console.print(f"\n[bold green]Saved enriched dataset to:[/bold green] [underline]{output_file}[/underline]\n")


@app.command()
def find(
    query: str = typer.Argument(
        ...,
        help="Search query to discover leads (e.g. 'Plumbing contractors in Austin, TX')."
    ),
    count: int = typer.Option(
        15,
        "--count", "-n",
        help="Number of leads to discover and enrich (10-30)."
    ),
    output_file: Path = typer.Option(
        Path("data/output/discovered_leads.csv"),
        "--output", "-o",
        help="Path where enriched CSV output will be saved."
    ),
    concurrency: int = typer.Option(
        settings.max_concurrent_requests,
        "--concurrency", "-c",
        help="Maximum concurrent web requests and API calls."
    ),
    model: str = typer.Option(
        settings.gemini_model,
        "--model", "-m",
        help="Google Gemini model identifier."
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="Explicit Google Gemini API key."
    )
):
    """
    Autonomously discovers companies for a keyword query, then scrapes and enriches them.
    """
    from b2b_leadgen.finder import discover_leads_by_keyword

    console.rule("[bold cyan]Autonomous Lead Discovery & Enrichment[/bold cyan]")
    console.print(f"[cyan]Keyword Query:[/cyan] {query}")
    console.print(f"[cyan]Target Count:[/cyan] {count}")
    console.print(f"[cyan]Output File:[/cyan] {output_file}\n")

    with console.status(f"[bold yellow]Discovering companies matching '{query}'...[/bold yellow]"):
        discovered = discover_leads_by_keyword(query, max_results=count)

    if not discovered:
        console.print(f"[bold red]No business websites could be discovered for query:[/bold red] '{query}'")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Discovered {len(discovered)} businesses.[/bold green]")
    for i, lead in enumerate(discovered, 1):
        console.print(f" {i:2d}. [bold]{lead.company_name}[/bold] -> [dim]{lead.website_url}[/dim]")

    console.print("\n[cyan]Starting enrichment pipeline...[/cyan]\n")

    effective_key = api_key or settings.effective_api_key
    pipeline = LeadGenPipeline(
        api_key=effective_key,
        model=model,
        max_concurrency=concurrency,
        use_checkpoint=True
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        task_id = progress.add_task("[cyan]Enriching leads...", total=len(discovered))

        def on_progress(lead: EnrichedLead, current: int, total: int):
            status_color = "green" if lead.status == "success" else "yellow"
            email_info = f" ({lead.primary_email})" if lead.primary_email else ""
            progress.update(
                task_id,
                advance=1,
                description=f"[{status_color}]{lead.company_name}[/{status_color}]{email_info}"
            )

        results = asyncio.run(
            pipeline.run_batch(
                inputs=discovered,
                output_csv_path=str(output_file),
                progress_callback=on_progress
            )
        )

    # Render Summary Table
    console.print("\n")
    console.rule("[bold green]Discovered & Enriched Leads[/bold green]")

    table = Table(show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Company", style="bold", width=16)
    table.add_column("Website", style="cyan", width=22)
    table.add_column("Contact Email", style="yellow", width=22)
    table.add_column("Summary & Pitch", style="dim", width=42)
    table.add_column("Status", width=10)

    for r in results:
        status_badge = f"[green]Success[/green]" if r.status == "success" else f"[red]{r.status}[/red]"
        desc = f"{r.company_summary or ''}\n[italic cyan]Pitch:[/italic cyan] {r.personalized_pitch or ''}"
        table.add_row(
            r.company_name,
            r.website_url or "-",
            r.primary_email or "[dim]None found[/dim]",
            desc,
            status_badge
        )

    console.print(table)
    console.print(f"\n[bold green]Saved enriched dataset to:[/bold green] [underline]{output_file}[/underline]\n")


@app.command()
def verify():
    """Checks API keys, settings, and environment readiness."""
    console.rule("[bold cyan]Configuration Verification[/bold cyan]")
    key = settings.effective_api_key
    masked_key = f"{key[:4]}...{key[-4:]}" if key and len(key) > 8 else ("Set" if key else "[red]Missing[/red]")

    console.print(f"• GEMINI_API_KEY: {masked_key}")
    console.print(f"• Default Model: [bold]{settings.gemini_model}[/bold]")
    console.print(f"• Max Concurrency: {settings.max_concurrent_requests}")
    console.print(f"• Request Timeout: {settings.request_timeout_seconds}s")
    console.print(f"• Follow Contact Subpages: {settings.follow_contact_pages}")


if __name__ == "__main__":
    app()
