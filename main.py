"""
Job Agent — Main Orchestrator

Runs the full pipeline:
  Scrape → Score → Tailor → Apply → Track

Usage:
    python main.py              # Run once
    python main.py --loop       # Run on schedule (every N hours)
    python main.py --stats      # Show stats and exit
    python main.py --dry-run    # Scrape + score but don't apply
"""

import asyncio
import sys
import time
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import SCRAPE_INTERVAL_HOURS, MAX_APPLICATIONS_PER_DAY, MIN_MATCH_SCORE
from database import (
    init_db, get_jobs_by_status, update_job_score, update_job_status,
    log_application, count_today_applications, get_stats
)
from scrapers.scraper import run_scrapers
from generators.ai_generator import process_job
from appliers.auto_applier import run_applications


DRY_RUN = "--dry-run" in sys.argv


def print_banner():
    print("""
╔══════════════════════════════════════════════════════╗
║          🤖 Job Application Agent v1.0               ║
║     Scrape → Score → Tailor → Apply → Track          ║
╚══════════════════════════════════════════════════════╝
""")


def print_stats():
    stats = get_stats()
    print(f"""
📊 Stats:
   Total scraped:  {stats['total_scraped']}
   Matched:        {stats['matched']}
   Applied:        {stats['applied']}
   Pending review: {stats['pending']}
""")


async def run_pipeline():
    """Full pipeline: scrape → score → generate docs → apply."""
    run_start = datetime.utcnow()
    print(f"\n{'='*54}")
    print(f"🚀 Pipeline started at {run_start.strftime('%Y-%m-%d %H:%M UTC')}")
    if DRY_RUN:
        print("🔍 DRY RUN MODE — applications will not be submitted")
    print(f"{'='*54}")

    # ── Step 1: Scrape ─────────────────────────────────────
    print("\n[1/4] SCRAPING JOB BOARDS...")
    new_count = await run_scrapers()

    # ── Step 2: Score new jobs ─────────────────────────────
    print("\n[2/4] SCORING NEW JOBS...")
    new_jobs = get_jobs_by_status("new")
    qualified = []

    for job in new_jobs:
        result = process_job(job)

        if result is None:
            update_job_score(job["id"], 0)
            update_job_status(job["id"], "skipped")
        else:
            update_job_score(job["id"], result["score"])
            update_job_status(job["id"], "matched")
            qualified.append({
                "job": job,
                "cv_path": result["cv_path"],
                "cover_letter_path": result["cover_letter_path"],
            })

    print(f"\n  → {len(qualified)} jobs qualified out of {len(new_jobs)} scored")

    # ── Step 3 & 4: Apply ──────────────────────────────────
    if not qualified:
        print("\n[3/4] No qualified jobs to apply to this run.")
    else:
        # Respect daily application limit
        today_count = count_today_applications()
        remaining = MAX_APPLICATIONS_PER_DAY - today_count
        to_apply = qualified[:remaining]

        if DRY_RUN:
            print(f"\n[3/4] DRY RUN: Would apply to {len(to_apply)} jobs")
            for item in to_apply:
                print(f"  📄 {item['job']['title']} @ {item['job']['company']}")
        else:
            print(f"\n[3/4] APPLYING TO {len(to_apply)} JOBS (daily limit: {MAX_APPLICATIONS_PER_DAY})...")
            successful = await run_applications(to_apply)

            # Log applications
            for item in to_apply:
                update_job_status(item["job"]["id"], "applied")
                log_application(
                    item["job"]["id"],
                    item["cv_path"],
                    item["cover_letter_path"],
                    notes=f"Auto-applied via agent"
                )

            print(f"\n  ✅ Successfully applied: {successful}/{len(to_apply)}")

    # ── Summary ────────────────────────────────────────────
    elapsed = (datetime.utcnow() - run_start).seconds
    print(f"\n[4/4] PIPELINE COMPLETE in {elapsed}s")
    print_stats()


async def main():
    print_banner()
    init_db()

    if "--stats" in sys.argv:
        print_stats()
        return

    if "--loop" in sys.argv:
        print(f"⏰ Scheduled mode: running every {SCRAPE_INTERVAL_HOURS} hours\n")
        scheduler = AsyncIOScheduler()
        scheduler.add_job(run_pipeline, "interval", hours=SCRAPE_INTERVAL_HOURS)
        scheduler.start()
        await run_pipeline()   # Run immediately on start
        try:
            while True:
                await asyncio.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            print("\n👋 Agent stopped")
            scheduler.shutdown()
    else:
        await run_pipeline()


if __name__ == "__main__":
    asyncio.run(main())
