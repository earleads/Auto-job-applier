"""
Job Agent Configuration
Edit this file to customize your job search.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# ── Your Profile ──────────────────────────────────────────────────────────────
CANDIDATE_PROFILE = """
Name: [Your Name]
Email: [your@email.com]
Phone: [+1 234 567 8900]
LinkedIn: [linkedin.com/in/yourprofile]
Location: [City, Country] (open to remote)

SUMMARY:
[2-3 sentence professional summary highlighting your key strengths]

EXPERIENCE:
[Company] | [Title] | [Dates]
- [Key achievement with metric]
- [Key achievement with metric]
- [Key achievement with metric]

[Company] | [Title] | [Dates]
- [Key achievement with metric]
- [Key achievement with metric]

EDUCATION:
[Degree] | [University] | [Year]

SKILLS:
Technical: [skill1, skill2, skill3]
Soft Skills: [skill1, skill2, skill3]

CERTIFICATIONS:
- [Cert name, Year]
"""

# ── Job Search Targets ────────────────────────────────────────────────────────

# Compliance-specific search queries across fintech + banking
SEARCH_QUERIES = [
    # Core compliance titles
    "compliance manager fintech",
    "BSA AML compliance officer",
    "compliance analyst payments",
    "KYC compliance manager",
    "financial crimes compliance",
    "regulatory compliance fintech",
    "CAMS compliance officer bank",
    "fraud compliance analyst",
    "sanctions compliance officer",
    "AML analyst fintech",
    # Emerging / automation-adjacent
    "compliance automation manager",
    "regtech compliance",
    "compliance operations manager fintech",
]

# Series A+ fintechs and banks in payments, credit, lending, crypto
TARGET_COMPANIES = [
    # Payments infrastructure
    "Stripe",
    "Adyen",
    "Marqeta",
    "Checkout.com",
    "Braintree",
    "Dwolla",
    "Modern Treasury",
    "Column",
    "Increase",
    "Melio",
    "Payoneer",
    "Nuvei",
    "Airwallex",
    "Finix",
    "Stax",
    "Orum",
    # Neobanks / consumer fintech
    "Chime",
    "Current",
    "Dave",
    "Varo",
    "SoFi",
    "Aspiration",
    "MoneyLion",
    "Albert",
    "Greenlight",
    "Step",
    "Copper Banking",
    # Credit / lending
    "Affirm",
    "Klarna",
    "Brex",
    "Ramp",
    "Fundbox",
    "Blend",
    "Plaid",
    "Upstart",
    "Figure",
    "Pagaya",
    "Upgrade",
    "LendingClub",
    "Prosper",
    "Avant",
    "Cross River Bank",
    # Crypto / digital assets
    "Coinbase",
    "Kraken",
    "Paxos",
    "Anchorage Digital",
    "Gemini",
    "BitGo",
    "Circle",
    "Ripple",
    "Chainalysis",
    "Fireblocks",
    "Consensys",
    "Alchemy",
    # Fraud / compliance / regtech tooling (Series A+)
    "Sardine",
    "Socure",
    "Alloy",
    "Unit21",
    "Hawk AI",
    "ComplyAdvantage",
    "Hummingbird",
    "Persona",
    "Middesk",
    "Trulioo",
    "Featurespace",
    "Feedzai",
    "Onfido",
    "Jumio",
    "Pliance",
    # Banking-as-a-Service / embedded finance (Series A+)
    "Unit",
    "Treasury Prime",
    "Synctera",
    "Bond",
    "Galileo",
    "Marqeta",
    "Lithic",
    "Highnote",
    # Insurance / wealthtech fintech (Series A+)
    "Lemonade",
    "Wealthsimple",
    "Betterment",
    "Robinhood",
    "Public.com",
    "Titan",
    # Regional / mid-size banks with compliance hiring
    "Cross River Bank",
    "Grasshopper Bank",
    "Blue Ridge Bank",
    "Piermont Bank",
    "Vast Bank",
    "Lead Bank",
    "Coastal Community Bank",
    "Metropolitan Commercial Bank",
    "Customers Bank",
    "WebBank",
    # Large banks (always hiring compliance)
    "JPMorgan Chase",
    "Goldman Sachs",
    "Morgan Stanley",
    "Bank of America",
    "Citibank",
    "Wells Fargo",
    "Capital One",
    "US Bank",
    "PNC",
    "Truist",
]

# USA only — major fintech hubs + remote
LOCATIONS = [
    "New York, NY",
    "San Francisco, CA",
    "Chicago, IL",
    "Miami, FL",
    "Austin, TX",
    "Boston, MA",
    "Los Angeles, CA",
    "Remote",
]

# Minimum match score (0-100) to proceed to application
MIN_MATCH_SCORE = 70

# ── Filtering Rules ────────────────────────────────────────────────────────────

# Only apply to jobs that contain at least one of these keywords in title/description
REQUIRED_KEYWORDS = [
    "compliance", "AML", "BSA", "KYC", "financial crimes",
    "sanctions", "fraud", "regulatory", "regtech",
]

# Automatically skip jobs matching these patterns (too senior, wrong industry, etc.)
EXCLUDE_KEYWORDS = [
    "chief compliance officer",   # likely too senior — remove if appropriate
    "VP of compliance",           # adjust based on target seniority
    "healthcare compliance",
    "HIPAA",
    "environmental compliance",
    "construction",
    "manufacturing",
]

# Company stage filter hint for Claude's scoring (enforced in scoring prompt)
TARGET_COMPANY_STAGE = "Series A or above, or established bank / financial institution"
TARGET_GEOGRAPHY = "United States"

# ── Job Boards to Scrape ──────────────────────────────────────────────────────
ENABLED_SOURCES = {
    "linkedin": True,
    "indeed": True,
    "greenhouse": True,   # company ATS
    "lever": True,        # company ATS
}

# ── Scheduler ─────────────────────────────────────────────────────────────────
SCRAPE_INTERVAL_HOURS = 4   # Check for new jobs every 4 hours
MAX_APPLICATIONS_PER_DAY = 20

# ── Output Paths ──────────────────────────────────────────────────────────────
DB_PATH = "data/jobs.db"
OUTPUT_DIR = "data/applications"
BASE_CV_PATH = "data/base_cv.txt"   # Plain text version of your CV
