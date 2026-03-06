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
Name: Joe Allen
Email: joespehallen90@gmail.com
Phone: +1 678-555-0142
LinkedIn: linkedin.com/in/joe-allen-264a53366
Location: Atlanta, GA (open to remote / hybrid / relocation)

SUMMARY:
Detail-oriented compliance professional with 5+ years of progressive experience in AML/BSA program execution, KYC/CDD operations, and regulatory risk management across payments, cross-border remittances, and fintech platforms. Currently at Payoneer managing transaction monitoring and SAR operations for a global payments network processing $70B+ annually. Adept at translating complex regulatory requirements (FinCEN, OFAC, FCA, MAS) into scalable operational controls. Known for bridging compliance and engineering teams to automate manual review workflows, reducing false positives and accelerating case resolution.

EXPERIENCE:
Payoneer | Compliance Analyst | May 2024 - Present | Atlanta, GA (Hybrid)
- Execute day-to-day AML/BSA compliance operations for cross-border payments platform serving 4M+ customers in 190+ countries
- Investigate and adjudicate 120+ transaction monitoring alerts per week (structuring, rapid movement, high-risk jurisdiction, layering)
- Prepare and file SARs and CTRs within regulatory deadlines, maintaining 100% on-time filing rate across 200+ filings
- Conduct EDD on high-risk merchants including MSBs, crypto exchanges, and marketplace sellers in sanctioned corridors
- Collaborate with product and engineering teams to tune Actimize transaction monitoring rules, reducing false positive rate by 35%
- Perform OFAC/SDN sanctions screening, processing 500+ daily screenings
- Support regulatory exam preparation by assembling documentation and drafting responses for FinCEN and state examiners
- Analyze typologies (trade-based money laundering, crypto P2P layering, synthetic identity fraud) and present findings to BSA Officer
- Contribute to quarterly risk assessments covering customer risk, product risk, and geographic risk dimensions
- Draft and update compliance SOPs for onboarding, ongoing monitoring, and offboarding workflows

Worldpay (FIS) | Associate Compliance Analyst | June 2022 - April 2024 | Atlanta, GA
- Supported BSA/AML compliance program for one of the world's largest merchant acquiring platforms processing $2T+ annually
- Managed KYC/CDD refresh program for 3,000+ merchant accounts, identifying 40+ accounts requiring enhanced review or exit
- Conducted risk-based due diligence on new merchant applications (e-commerce, gaming, crypto on-ramps, CBD)
- Investigated suspicious activity referrals, documenting findings in case management system
- Filed 80+ SARs and contributed to FinCEN 314(b) information sharing requests
- Developed risk scoring methodology for merchant onboarding incorporating NAICS codes, processing volume, chargeback ratios
- Monitored OFAC sanctions lists and PEP databases; executed remediation for 15+ confirmed matches
- Participated in SOC 2 and regulatory audit readiness reviews
- Delivered BSA/AML awareness training to 200+ operations staff across 3 regional offices

TransUnion | Compliance Operations Intern | January 2021 - May 2022 | Atlanta, GA
- Assisted fraud and compliance team with identity verification operations for financial institution clients
- Reviewed consumer dispute cases under FCRA requirements, processing 50+ disputes weekly
- Built Excel dashboards tracking KYC rejection rates, SAR filing volumes, and audit remediation timelines
- Researched emerging regulatory guidance (CDD Rule, beneficial ownership, FinCEN AML priorities)
- Contributed to policy gap analysis against FinCEN, FFIEC, and CFPB examination manual requirements

EDUCATION:
Georgia Institute of Technology | B.S. in Business Administration, Finance Concentration | 2021
- Dean's List (3 semesters), Finance Club, VITA Tax Assistance Volunteer

CERTIFICATIONS:
- CAMS (Certified Anti-Money Laundering Specialist) | ACAMS | 2023
- CFCS (Certified Financial Crime Specialist) | ACFCS | 2024
- ACAMS Advanced Sanctions Certificate | 2024
- SIE (Securities Industry Essentials) | FINRA | 2021

SKILLS:
Regulatory: BSA/AML, KYC/CDD/EDD, OFAC Sanctions, USA PATRIOT Act, FinCEN, FFIEC, Reg E, Reg Z, UDAAP, FCRA, GLBA, FCA, MAS, 6AMLD
Operations: SAR/CTR Filing, 314(a)/314(b), Suspicious Activity Investigation, Risk Assessment, Regulatory Exam Prep, Policy Development, Compliance Testing
Tools: NICE Actimize, Verafin, Chainalysis, Dow Jones Risk & Compliance, World-Check, LexisNexis, Alloy, Sardine, ComplyAdvantage, Hummingbird, Persona
Technical: SQL, Python (pandas), Excel/VBA, Tableau, Power BI, Jira, Confluence
Industries: Payments, Cross-Border Remittances, Merchant Acquiring, Neobanking, Crypto/Digital Assets, Lending, BaaS
Soft Skills: Cross-functional collaboration, stakeholder communication, regulatory exam liaison, training & mentoring, executive reporting
"""

# ── Job Search Targets ────────────────────────────────────────────────────────

# Compliance-specific search queries across fintech + banking
# Targeting analyst / associate / junior officer level (matching ~5 years experience)
SEARCH_QUERIES = [
    # Core analyst-level compliance titles
    "compliance analyst fintech",
    "compliance analyst payments",
    "AML analyst fintech",
    "BSA AML analyst",
    "KYC analyst",
    "fraud compliance analyst",
    "sanctions analyst",
    "financial crimes analyst",
    "regulatory compliance analyst",
    # Associate / specialist level
    "associate compliance analyst",
    "compliance specialist fintech",
    "AML compliance specialist",
    "transaction monitoring analyst",
    "compliance operations analyst fintech",
    # Entry-level officer titles (still appropriate for ~5 yrs experience)
    "compliance officer fintech",
    "BSA officer",
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
    # Too senior for analyst-level profile (~5 years experience)
    "chief compliance officer",
    "CCO",
    "VP of compliance",
    "vice president compliance",
    "director of compliance",
    "head of compliance",
    "senior director",
    "managing director",
    "compliance lead",
    "senior compliance manager",
    "principal compliance",
    # Wrong industry
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
