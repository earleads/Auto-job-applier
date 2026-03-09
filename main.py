"""
Job Agent — Main Orchestrator

Runs the full pipeline:
  Scrape → Score → Tailor → Apply → Track

Usage:
    python main.py              # Run once
    python main.py --loop       # Run on schedule (every N hours)
    python main.py --stats      # Show stats and exit
    python main.py --dry-run    # Scrape + score but don't apply
    python main.py --test       # Quick run: 3 ATS companies, no browser, max 2 apps
"""

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

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
TEST_MODE = "--test" in sys.argv
REPORT_PATH = "data/run_report.txt"


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


def save_run_report(report_lines: list[str]):
    """Save run report to disk so it's captured in GitHub Actions artifacts."""
    Path("data").mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    header = f"=== Run Report — {timestamp} ===\n"

    # Append to report file (keeps history across runs if DB persists)
    with open(REPORT_PATH, "a") as f:
        f.write(header)
        for line in report_lines:
            f.write(line + "\n")
        f.write("\n")


async def run_pipeline():
    """Full pipeline: scrape → score → generate docs → apply."""
    run_start = datetime.utcnow()
    report = []

    print(f"\n{'='*54}")
    print(f"🚀 Pipeline started at {run_start.strftime('%Y-%m-%d %H:%M UTC')}")
    if TEST_MODE:
        print("🧪 TEST MODE — limited scrape (3 ATS companies, 2 LinkedIn queries)")
        report.append("Mode: TEST")
    if DRY_RUN:
        print("🔍 DRY RUN MODE — applications will not be submitted")
        report.append("Mode: DRY RUN")
    elif not TEST_MODE:
        report.append("Mode: LIVE")
    print(f"{'='*54}")

    # ── Step 1: Scrape ─────────────────────────────────────
    print("\n[1/4] SCRAPING JOB BOARDS...")
    new_count, source_counts = await run_scrapers(test_mode=TEST_MODE)

    # Diagnostics: per-source breakdown
    print(f"\n  📡 Scrape results by source:")
    for source, count in source_counts.items():
        print(f"     {source}: {count} new jobs")
    report.append(f"Scraped: {new_count} total new jobs")
    for source, count in source_counts.items():
        report.append(f"  {source}: {count}")

    if new_count == 0:
        print("\n  ⚠️  WARNING: Zero new jobs scraped across all sources!")
        print("     Possible causes: bot detection, expired session, or no new postings")
        report.append("WARNING: Zero new jobs scraped")

    # ── Step 2: Score new jobs ─────────────────────────────
    print("\n[2/4] SCORING NEW JOBS...")
    new_jobs = get_jobs_by_status("new")
    qualified = []
    scores = []

    for job in new_jobs:
        result = process_job(job)

        if result is None:
            update_job_score(job["id"], 0)
            update_job_status(job["id"], "skipped")
            scores.append(0)
        else:
            update_job_score(job["id"], result["score"])
            update_job_status(job["id"], "matched")
            scores.append(result["score"])
            qualified.append({
                "job": job,
                "cv_path": result["cv_path"],
                "cover_letter_path": result["cover_letter_path"],
            })

    # Also retry previously failed applications
    failed_jobs = get_jobs_by_status("apply_failed")
    if failed_jobs:
        print(f"\n  🔄 Retrying {len(failed_jobs)} previously failed applications...")
        for job in failed_jobs:
            result = process_job(job)
            if result is not None:
                qualified.append({
                    "job": job,
                    "cv_path": result["cv_path"],
                    "cover_letter_path": result["cover_letter_path"],
                })

    print(f"\n  → {len(qualified)} jobs qualified out of {len(new_jobs)} scored (+ {len(failed_jobs)} retries)")
    report.append(f"Scored: {len(new_jobs)} jobs")
    report.append(f"Qualified (score >= {MIN_MATCH_SCORE}): {len(qualified)}")

    # Score distribution
    if scores:
        above_70 = sum(1 for s in scores if s >= 70)
        between_50_69 = sum(1 for s in scores if 50 <= s < 70)
        below_50 = sum(1 for s in scores if s < 50)
        print(f"  📊 Score distribution: {above_70} >= 70 | {between_50_69} 50-69 | {below_50} < 50")
        report.append(f"Score distribution: {above_70} >= 70, {between_50_69} 50-69, {below_50} < 50")

    # ── Step 3 & 4: Apply ──────────────────────────────────
    applied_count = 0
    failed_count = 0

    if not qualified:
        print("\n[3/4] No qualified jobs to apply to this run.")
        report.append("Applications: 0 (no qualified jobs)")
    else:
        # Respect daily application limit
        today_count = count_today_applications()
        max_apps = 2 if TEST_MODE else MAX_APPLICATIONS_PER_DAY
        remaining = max_apps - today_count
        to_apply = qualified[:remaining]

        if DRY_RUN:
            print(f"\n[3/4] DRY RUN: Would apply to {len(to_apply)} jobs")
            for item in to_apply:
                print(f"  📄 {item['job']['title']} @ {item['job']['company']}")
            report.append(f"DRY RUN: Would apply to {len(to_apply)} jobs")
        else:
            print(f"\n[3/4] APPLYING TO {len(to_apply)} JOBS (daily limit: {MAX_APPLICATIONS_PER_DAY})...")
            results = await run_applications(to_apply)

            # Track per-job success/failure
            for item, success in zip(to_apply, results):
                job = item["job"]
                if success:
                    update_job_status(job["id"], "applied")
                    log_application(
                        job["id"],
                        item["cv_path"],
                        item["cover_letter_path"],
                        notes="Auto-applied via agent"
                    )
                    applied_count += 1
                    report.append(f"  APPLIED: {job['title']} @ {job['company']}")
                else:
                    update_job_status(job["id"], "apply_failed")
                    failed_count += 1
                    report.append(f"  FAILED:  {job['title']} @ {job['company']}")

            print(f"\n  ✅ Successfully applied: {applied_count}/{len(to_apply)}")
            if failed_count > 0:
                print(f"  ❌ Failed: {failed_count}/{len(to_apply)} (will retry next run)")
            report.append(f"Applications: {applied_count} succeeded, {failed_count} failed")

    # ── Summary ────────────────────────────────────────────
    elapsed = (datetime.utcnow() - run_start).seconds
    print(f"\n[4/4] PIPELINE COMPLETE in {elapsed}s")
    report.append(f"Duration: {elapsed}s")
    print_stats()

    # Save report
    save_run_report(report)
    print(f"📝 Run report saved to {REPORT_PATH}")


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
