"""
Job Agent Configuration
Edit this file to customize your job search.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "your-key-here")

# ── Your Profile ──────────────────────────────────────────────────────────────
CANDIDATE_PROFILE = """
Name: Joe Allen
Email: joespehallen90@gmail.com
Phone: [+1 XXX-XXX-XXXX]
LinkedIn: linkedin.com/in/joe-allen-264a53366
Location: [City, State] (open to remote)

SUMMARY:
Compliance professional with experience in AML/BSA program management, KYC operations, and regulatory risk within fintech and financial services. Proven track record of building scalable compliance frameworks, managing SAR/CTR filing workflows, and passing regulatory examinations. Combines deep regulatory knowledge (FinCEN, OFAC, Reg E, Reg Z) with a technology-forward approach to compliance automation.

EXPERIENCE:
[Company] | [Title, e.g. Compliance Manager] | [Start - Present]
- Led AML/BSA compliance program covering $X in annual transaction volume
- Managed SAR and CTR filing operations, reducing average filing time by X%
- Directed KYC/CDD/EDD onboarding reviews for X+ customers per month
- Coordinated responses to regulatory examinations with zero findings
- Implemented compliance tooling to automate transaction monitoring

[Company] | [Title, e.g. Compliance Analyst] | [Start - End]
- Conducted risk assessments and due diligence for MSBs, fintechs, crypto entities
- Filed X+ SARs and X+ CTRs per quarter with 100% deadline compliance
- Developed and delivered BSA/AML training across departments
- Drafted and updated compliance policies aligned with FinCEN guidance

EDUCATION:
[Degree] | [University] | [Year]

SKILLS:
Technical: AML/BSA, KYC/CDD/EDD, OFAC Sanctions, SAR/CTR Filing, Reg E, Reg Z, FinCEN, SQL, Excel
Soft Skills: Cross-functional collaboration, regulatory exam prep, policy drafting, stakeholder communication

CERTIFICATIONS:
- CAMS (Certified Anti-Money Laundering Specialist) | [Year or In Progress]
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
