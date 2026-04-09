"""
Extract all degree-bearing programs (majors) from the LU Academic Catalog PDF.

Why the earlier logic missed majors:
- The old code only parsed course description headers (e.g. "CSC 1058 Computer Programming I 4 credits")
  and never scanned for degree program listings at all.
- The ACADEMIC PROGRAMS AND DEPARTMENTS section is a Table of Contents section listing program
  names with page numbers, not course data, so it was completely skipped.
- Multi-track programs like "English Liberal Arts - Literature (BA)" were split across hyphenated
  names and wouldn't match a simple single-word pattern.
- Graduate programs (MBA, M.Ed., MA) followed entirely different naming conventions.
- Foreign language programs (French, Spanish) had no obvious department prefix to detect.

Improved approach:
- Extract text from the catalog PDF using pdfplumber.
- Locate the ACADEMIC PROGRAMS AND DEPARTMENTS section specifically.
- Stop at SCHOOL OF ADULT & CONTINUING EDUCATION for undergrad, then continue for grad.
- Apply flexible regex patterns that handle:
    (BS, BA), (BS), (BA), (MBA), (M.Ed.), (MA), (M. Ed.) with/without spaces
    Hyphenated tracks: "English Liberal Arts - Literature (BA)"
    Concentration lines: "Chemistry: Forensic Science Concentration (BS)"
    Full program names: "Bachelor of Human Services (BHS-FLEX) Program"
    Graduate programs: "Master of Business Administration – General (MBA)"
- Explicitly exclude: Minors, Certificates, Course Descriptions, section headers, page numbers.
- Merge adjacent lines before matching to handle line-break splits.
- Deduplicate matched programs.
- Output structured JSON.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional

try:
    import pdfplumber
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pdfplumber"])
    import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PDF = ROOT / "data" / "catalogs" / "2025_26-Catalog_1282026.pdf"
CATALOG_TXT = ROOT / "data" / "catalogs" / "2025_26-Catalog_1282026.txt"
OUTPUT_FILE = ROOT / "data" / "catalogs" / "extracted_majors.json"

# ---------------------------------------------------------------------------
# Degree markers: patterns to detect degree type in parentheses
# ---------------------------------------------------------------------------
DEGREE_PATTERN = re.compile(
    r"\((BS,\s*BA|BA,\s*BS|BS|BA|MBA|M\.?\s*Ed\.?|MA|BHS(?:-FLEX)?|M\.?\s*A\.?)\)",
    re.IGNORECASE,
)

# Graduate program patterns (no parenthesized degree, uses "Master of" or "Bachelor of")
GRAD_NAME_PATTERN = re.compile(
    r"^(Master of .+|Bachelor of .+Program.*|Early Childhood .+|Educational Leadership.+|Special Education.+)$",
    re.IGNORECASE,
)

# Lines to explicitly EXCLUDE even if they match a degree pattern
EXCLUDE_KEYWORDS = [
    "minor", "certificate", "course description", "course descriptions",
    "department of", "division of", "school of", "and departments",
    "pre-law certificate", "expansion courses", "pk-12 certification",
]

# Table of contents noise: lines ending with dots + page number
TOC_LINE = re.compile(r"\.{3,}\s*\d+\s*$")

# Pure page number lines
PAGE_NUMBER = re.compile(r"^\d+$")

# ---------------------------------------------------------------------------
# Helper: clean a line
# ---------------------------------------------------------------------------
def clean(line: str) -> str:
    # Collapse multiple spaces, strip
    line = re.sub(r"\s+", " ", line).strip()
    # Remove trailing TOC dots and page numbers: "Biology (BS, BA) .... 99" -> "Biology (BS, BA)"
    line = re.sub(r"\s*\.{2,}\s*\d+\s*$", "", line).strip()
    # Remove em-dash artifacts
    line = line.replace("\u2013", "-").replace("\u2014", "-")
    return line

# ---------------------------------------------------------------------------
# Helper: is this line a major entry?
# ---------------------------------------------------------------------------
def is_excluded(line: str) -> bool:
    lower = line.lower()
    return any(kw in lower for kw in EXCLUDE_KEYWORDS)

def extract_degree(line: str) -> Optional[str]:
    m = DEGREE_PATTERN.search(line)
    if m:
        raw = m.group(1).strip()
        # Normalize
        raw = re.sub(r"\s+", " ", raw)
        raw = raw.replace("M. Ed.", "M.Ed.").replace("M.Ed .", "M.Ed.")
        return raw
    return None

def infer_category(degree: str, name: str) -> str:
    deg_upper = degree.upper()
    name_lower = name.lower()
    if any(x in deg_upper for x in ["MBA", "M.ED", "M.A", "MA"]):
        return "graduate"
    if "master of" in name_lower or "m. ed" in name_lower:
        return "graduate"
    if "bhs" in deg_upper or "bachelor of human services" in name_lower:
        return "graduate_professional"
    return "undergraduate"

# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------
def extract_majors_from_text(text: str) -> List[Dict]:
    lines = text.splitlines()
    results = []
    seen_names = set()

    # Find start of ACADEMIC PROGRAMS section
    start_idx = 0
    for i, line in enumerate(lines):
        if "ACADEMIC PROGRAMS AND DEPARTMENTS" in line.upper():
            start_idx = i + 1
            print(f"[DEBUG] Found ACADEMIC PROGRAMS section at line {i}")
            break

    # Find end — stop after graduate programs section
    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        if "Academic Calendar" in lines[i] or "ACADEMIC CALENDAR" in lines[i].upper():
            end_idx = i
            print(f"[DEBUG] Stopping at Academic Calendar at line {i}")
            break

    print(f"[DEBUG] Scanning lines {start_idx} to {end_idx} ({end_idx - start_idx} lines)")
    print()

    # Merge adjacent lines before matching to handle wrap-arounds
    # Build a list of cleaned, merged candidate strings
    cleaned_lines = []
    for line in lines[start_idx:end_idx]:
        c = clean(line)
        if c and not PAGE_NUMBER.match(c):
            cleaned_lines.append(c)

    # Try to match each line (and merged pairs)
    for i, line in enumerate(cleaned_lines):
        # Also try merging with next line for split entries
        candidates = [line]
        if i + 1 < len(cleaned_lines):
            merged = line + " " + cleaned_lines[i + 1]
            candidates.append(merged)

        for candidate in candidates:
            if is_excluded(candidate):
                continue

            degree = extract_degree(candidate)

            # Case 1: Standard "(BS, BA)" style
            if degree:
                # Strip the degree parenthesis to get the name
                name = DEGREE_PATTERN.sub("", candidate).strip()
                name = re.sub(r"[–-]\s*ACS Accredited", "", name).strip()
                name = re.sub(r"\s*[–-]\s*$", "", name).strip()
                name = re.sub(r"^\s*[–-]\s*", "", name).strip()
                name = clean(name)

                if not name or len(name) < 3:
                    continue
                if is_excluded(name):
                    continue

                # Strip department prefix noise like "Biology Biology" or
                # "Communication Communication" that comes from merging dept header + program line
                # These happen because the TOC has "Biology ..... 98" then "Biology (BS, BA) .... 99"
                # When merged it becomes "Biology Biology (BS, BA)"
                words = name.split()
                if len(words) >= 2 and words[0].lower() == words[1].lower():
                    name = " ".join(words[1:])
                # Also handle "Computer Science Computer Science" etc.
                half = len(words) // 2
                if len(words) >= 4 and words[:half] == words[half:]:
                    name = " ".join(words[half:])
                # Strip leading department group names fused onto program name
                # e.g. "Business and Entrepreneurial Studies Accounting" -> "Accounting"
                dept_prefixes = [
                    "Business and Entrepreneurial Studies ",
                    "Chemistry and Physics ",
                    "History, Philosophy & Religion ",
                    "Languages & Literature ",
                    "Mathematical Sciences ",
                    "Psychology and Human Services ",
                    "Anthropology, Sociology and Criminal Justice ",
                    "Foreign Languages ",
                    "Pan-Africana Studies ",  # when fused with itself
                    "Political Science ",      # when fused with itself
                    "Visual Arts ",            # when fused with itself
                    "Health Science ",         # when fused with itself
                    "Communication ",          # when fused with itself
                    "Music ",                  # when fused with itself
                    "Biology ",               # when fused with itself
                ]
                for prefix in dept_prefixes:
                    if name.startswith(prefix):
                        stripped = name[len(prefix):]
                        if stripped:
                            name = stripped
                        break

                name = clean(name)
                if not name or len(name) < 3:
                    continue
                if is_excluded(name):
                    continue

                key = name.lower()
                if key not in seen_names:
                    seen_names.add(key)
                    category = infer_category(degree, name)
                    results.append({
                        "name": name,
                        "degree": degree,
                        "category": category,
                    })
                    print(f"[MATCHED] {name} ({degree}) [{category}]")
                break  # Don't try merged version if single matched

            # Case 2: Graduate "Master of..." or "Bachelor of..." full name lines
            elif GRAD_NAME_PATTERN.match(candidate):
                name = candidate.strip()
                name = clean(name)
                if is_excluded(name):
                    continue
                # Try to find degree in the name itself
                if "mba" in name.lower() or "master of business" in name.lower():
                    degree = "MBA"
                elif "m.ed" in name.lower() or "m. ed" in name.lower() or "education" in name.lower():
                    degree = "M.Ed."
                elif "master of arts" in name.lower():
                    degree = "MA"
                elif "bachelor of human services" in name.lower():
                    degree = "BHS-FLEX"
                else:
                    degree = "Graduate"

                # Deduplicate: "Master of Arts in Human Services Program" and
                # "Master of Arts in Human Services" -> keep shorter canonical name
                key = name.lower().replace(" program", "").strip()
                if key not in seen_names:
                    seen_names.add(key)
                    canonical_name = name.replace(" Program", "").strip()
                    results.append({
                        "name": canonical_name,
                        "degree": degree,
                        "category": "graduate",
                    })
                    print(f"[MATCHED-GRAD] {canonical_name} ({degree}) [graduate]")
                break

    return results


def main():
    print("=" * 60)
    print("GradPath Major Extractor")
    print("=" * 60)
    print()

    # Use the pre-extracted text file if available (faster), else parse PDF
    if CATALOG_TXT.exists():
        print(f"Using pre-extracted text: {CATALOG_TXT.name}")
        with CATALOG_TXT.open(encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        print(f"Extracting text from PDF: {CATALOG_PDF.name}")
        pages = []
        with pdfplumber.open(CATALOG_PDF) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        text = "\n".join(pages)

    print()
    majors = extract_majors_from_text(text)

    # Sort: undergrad first, then graduate
    undergrad = [m for m in majors if m["category"] == "undergraduate"]
    grad = [m for m in majors if m["category"] != "undergraduate"]

    output = {
        "total_programs": len(majors),
        "total_undergraduate": len(undergrad),
        "total_graduate": len(grad),
        "undergraduate_majors": undergrad,
        "graduate_programs": grad,
    }

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Total programs found : {len(majors)}")
    print(f"Undergraduate majors : {len(undergrad)}")
    print(f"Graduate programs    : {len(grad)}")
    print()
    print("UNDERGRADUATE MAJORS:")
    for m in undergrad:
        print(f"  {m['name']:55} ({m['degree']})")
    print()
    print("GRADUATE PROGRAMS:")
    for m in grad:
        print(f"  {m['name']:55} ({m['degree']})")
    print()
    print(f"Output written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
