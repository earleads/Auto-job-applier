"""
AI Generator — Job ranking, CV tailoring, and cover letter generation via Claude.
"""

import json
import re
from pathlib import Path
from datetime import datetime

import anthropic

from config import ANTHROPIC_API_KEY, CANDIDATE_PROFILE, MIN_MATCH_SCORE, OUTPUT_DIR

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)


# ── Job Ranker ─────────────────────────────────────────────────────────────────

def score_job(job: dict) -> int:
    """
    Use Claude to score job fit 0–100 against candidate profile.
    Returns integer score.
    """
    prompt = f"""You are a career advisor evaluating job fit for a compliance professional targeting fintech and banking roles.

CANDIDATE PROFILE:
{CANDIDATE_PROFILE}

JOB POSTING:
Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Description:
{job.get('description', 'No description available')[:3000]}

Score this job fit from 0 to 100 using these criteria:

HARD DISQUALIFIERS (score 0 immediately if any apply):
- Company is outside financial services (payments, lending, credit, crypto, banking)
- Company appears to be pre-Series A (seed stage startup with no institutional funding)
- Role is not compliance-related (AML, BSA, KYC, sanctions, fraud, regulatory)
- Location is outside the United States (non-remote international roles)
- Role is too senior for the candidate's experience level (~5 years). Disqualify: Director, VP, Head of, Chief, Senior Manager, Managing Director, Principal. These roles typically require 10+ years and team leadership experience the candidate does not yet have.

SENIORITY GUIDANCE:
The candidate has ~5 years of compliance experience (intern → associate analyst → analyst).
Appropriate titles: Analyst, Senior Analyst, Associate, Specialist, Coordinator, junior Officer roles.
Stretch but acceptable: Compliance Manager (if individual contributor or small team), Compliance Officer (non-senior).
Too senior: Director, VP, Head of, Senior Manager, Lead, Principal — score 0.

SCORING RUBRIC:
- 90-100: Perfect match — analyst/specialist compliance role at Series A+ fintech/bank, strong keyword alignment, appropriate seniority
- 70-89: Strong match — compliance role, right sector, right seniority level, minor gaps in domain
- 50-69: Partial — compliance adjacent (risk, legal, ops), slightly above target seniority, or sector is adjacent
- 0-49: Poor match — wrong function, wrong industry, wrong seniority, or disqualified above

Respond ONLY with a JSON object:
{{"score": 82, "reason": "BSA/AML role at Series C payments company. Strong match on KYC/SAR experience. Gap: candidate lacks direct crypto compliance exposure."}}
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        # Strip any markdown fences
        text = re.sub(r"```json|```", "", text).strip()
        data = json.loads(text)
        score = int(data.get("score", 0))
        print(f"  📊 Score {score}/100 — {data.get('reason', '')[:80]}")
        return score
    except Exception as e:
        print(f"  ⚠️  Scoring failed: {e}")
        return 0


# ── CV Tailor ──────────────────────────────────────────────────────────────────

def tailor_cv(job: dict) -> str:
    """
    Rewrite the candidate's CV to match the job description.
    Returns tailored CV as plain text.
    """
    prompt = f"""You are an expert CV writer specialising in compliance roles at fintechs and financial institutions.

INSTRUCTIONS:
- Keep all facts truthful — never fabricate experience or credentials
- Front-load compliance-specific language: AML, BSA, KYC, SAR, sanctions, OFAC, FinCEN, Reg E, Reg Z as applicable
- Mirror keywords from the job description naturally — compliance hiring managers scan for exact terms
- Reorder bullets to surface the most relevant experience first
- If the company is a fintech or payments company, emphasise technology-forward compliance experience
- If it's a bank, emphasise regulatory examination readiness and formal policy frameworks
- Adjust the summary to speak directly to this role and company
- Keep total length under 1 page (600 words max)
- Format as clean plain text with clear sections

JOB:
Title: {job['title']}
Company: {job['company']}
Description:
{job.get('description', '')[:3000]}

CANDIDATE'S BASE CV:
{CANDIDATE_PROFILE}

Output ONLY the tailored CV text, no preamble or explanation.
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


# ── Cover Letter Generator ─────────────────────────────────────────────────────

def write_cover_letter(job: dict) -> str:
    """
    Generate a tailored, concise cover letter for the job.
    Returns cover letter as plain text.
    """
    prompt = f"""Write a compelling, direct cover letter for a compliance role at a fintech or financial institution.

GUIDELINES:
- 3 paragraphs, under 250 words
- Hook: reference something specific about this company's compliance challenges or growth stage (payments scale, crypto regulation, bank partnership model — whatever fits)
- Body: 2 concrete examples of the candidate's compliance impact — use numbers where available (e.g. "reduced SAR filing time by 40%", "onboarded 10K customers per month with <0.3% false positive rate")
- Close: confident and specific — name the role, express readiness to contribute fast, propose a conversation
- Tone: direct, knowledgeable, compliance-native — sounds like someone who lives in this space, not a generalist
- NO: "I am writing to express my interest", "Please find attached", "I would be a great fit", generic openers

JOB:
Title: {job['title']}
Company: {job['company']}
Description:
{job.get('description', '')[:2500]}

CANDIDATE:
{CANDIDATE_PROFILE}

Output ONLY the cover letter text.
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


# ── Save Documents ─────────────────────────────────────────────────────────────

def save_documents(job: dict, cv_text: str, cover_letter: str) -> tuple[str, str]:
    """Save CV and cover letter to disk. Returns (cv_path, cl_path)."""
    safe_company = re.sub(r"[^\w]", "_", job["company"])
    safe_title = re.sub(r"[^\w]", "_", job["title"])[:30]
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
    prefix = f"{OUTPUT_DIR}/{timestamp}_{safe_company}_{safe_title}"

    cv_path = f"{prefix}_CV.txt"
    cl_path = f"{prefix}_CoverLetter.txt"

    with open(cv_path, "w") as f:
        f.write(cv_text)
    with open(cl_path, "w") as f:
        f.write(cover_letter)

    print(f"  💾 Saved: {cv_path}")
    print(f"  💾 Saved: {cl_path}")
    return cv_path, cl_path


# ── Main pipeline step ─────────────────────────────────────────────────────────

def process_job(job: dict) -> dict | None:
    """
    Score job, tailor docs if qualified.
    Returns dict with score + paths, or None if below threshold.
    """
    print(f"\n🤖 Processing: {job['title']} @ {job['company']}")

    score = score_job(job)

    if score < MIN_MATCH_SCORE:
        print(f"  ⏭️  Score {score} below threshold {MIN_MATCH_SCORE} — skipping")
        return None

    print(f"  ✅ Qualified! Generating tailored docs...")
    cv_text = tailor_cv(job)
    cover_letter = write_cover_letter(job)
    cv_path, cl_path = save_documents(job, cv_text, cover_letter)

    return {
        "score": score,
        "cv_path": cv_path,
        "cover_letter_path": cl_path,
    }
