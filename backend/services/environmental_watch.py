"""
Shuhul Environmental Watch
--------------------------

Turns Kashmir environmental/infrastructure reporting into structured
planning issues that can be linked to Shuhul's GIS workflow.

Current MVP:
    articles/ -> ingestion -> lightweight retrieval -> Strands/Bedrock
              -> validated EnvironmentalIssue -> Action Card

The article corpus is intentionally kept outside this module:
    Shuhul/articles/

Important design rule:
    The LLM extracts and structures information. It does NOT decide
    whether a project should be built. Spatial measurements and
    environmental calculations remain the responsibility of Shuhul's
    deterministic GIS engine.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

# environmental_watch.py lives in:
# Shuhul/backend/services/environmental_watch/
#
# parents[0] = environmental_watch
# parents[1] = services
# parents[2] = backend
# parents[3] = Shuhul
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTICLES_DIR = PROJECT_ROOT / "articles"
WATCH_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "environmental_watch"


# ---------------------------------------------------------------------------
# Shuhul jurisdiction
# ---------------------------------------------------------------------------

DISTRICTS: dict[str, str] = {
    "anantnag": "ant",
    "budgam": "bdg",
    "bandipora": "bnd",
    "ganderbal": "gnd",
    "kulgam": "klgm",
    "kupwara": "kpwr",
    "pulwama": "plwoam",
    "shopian": "shpyn",
    "srinagar": "sxr",
    "baramulla": "var",
}

DISTRICT_DISPLAY_NAMES: dict[str, str] = {
    code: name.title()
    for name, code in DISTRICTS.items()
}

# Common aliases appearing in Kashmir reporting.
DISTRICT_ALIASES: dict[str, str] = {
    "srinagar": "sxr",
    "srinagar district": "sxr",
    "budgam": "bdg",
    "budgam district": "bdg",
    "budgam district": "bdg",
    "bandipora": "bnd",
    "bandipora district": "bnd",
    "ganderbal": "gnd",
    "ganderbal district": "gnd",
    "kulgam": "klgm",
    "kulgam district": "klgm",
    "kupwara": "kpwr",
    "kupwara district": "kpwr",
    "pulwama": "plwoam",
    "pulwama district": "plwoam",
    "shopian": "shpyn",
    "shopian district": "shpyn",
    "baramulla": "var",
    "baramulla district": "var",
    "anantnag": "ant",
    "anantnag district": "ant",
}


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

ISSUE_CATEGORIES = [
    "infrastructure",
    "water",
    "forest",
    "waste",
    "pollution",
    "land_degradation",
    "flooding",
    "biodiversity",
    "mining",
    "urban_development",
    "agriculture",
    "other",
]

ENVIRONMENTAL_FACTORS = [
    "reserved_forest",
    "forest_land",
    "ecologically_sensitive_area",
    "tree_loss",
    "vegetation_loss",
    "medicinal_plants",
    "green_space",
    "canopy",
    "water_crossing",
    "water_body",
    "wetland",
    "riparian_vegetation",
    "water_pollution",
    "waste",
    "slope",
    "erosion",
    "flood_risk",
    "built_up_area",
    "building_density",
    "heritage",
    "alternative_route",
    "environmental_clearance",
    "land_use",
    "biodiversity",
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Article:
    article_id: str
    filename: str
    title: str
    date: Optional[str]
    source: Optional[str]
    url: Optional[str]
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReportedClaim:
    claim: str
    attributed_to: Optional[str] = None
    status: str = "reported_claim"
    value: Optional[float] = None
    unit: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SpatialContext:
    named_places: list[str] = field(default_factory=list)
    district: Optional[str] = None
    district_code: Optional[str] = None
    within_shuhul: Optional[bool] = None
    location_verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Issue:
    title: str
    category: str
    issue_type: str
    status: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Action:
    title: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EnvironmentalIssue:
    article_id: str
    relevant: bool
    issue: Issue
    spatial_context: SpatialContext
    environmental_factors: list[str]
    reported_claims: list[ReportedClaim]
    action: Action
    source: dict[str, Any]
    confidence: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "relevant": self.relevant,
            "issue": self.issue.to_dict(),
            "spatial_context": self.spatial_context.to_dict(),
            "environmental_factors": self.environmental_factors,
            "reported_claims": [
                claim.to_dict() for claim in self.reported_claims
            ],
            "action": self.action.to_dict(),
            "source": self.source,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Article ingestion
# ---------------------------------------------------------------------------

def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "PDF support requires pypdf. Install with: pip install pypdf"
        ) from exc

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError(
            "DOCX support requires python-docx. "
            "Install with: pip install python-docx"
        ) from exc

    document = Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def read_article_file(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        return _read_text_file(path)

    if suffix == ".pdf":
        return _read_pdf(path)

    if suffix == ".docx":
        return _read_docx(path)

    raise ValueError(
        f"Unsupported article format: {path.name}. "
        "Supported formats: .txt, .md, .pdf, .docx"
    )


def _first_match(pattern: str, text: str) -> Optional[str]:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def extract_article_metadata(path: Path, text: str) -> dict[str, Optional[str]]:
    """
    Best-effort metadata extraction.

    We intentionally do not infer missing metadata from external sources.
    If an article does not contain a field, it remains None.
    """

    title = (
        _first_match(r"^\s*TITLE\s*:\s*(.+)$", text)
        or _first_match(r"^\s*HEADLINE\s*:\s*(.+)$", text)
    )

    date = _first_match(
        r"^\s*DATE\s*:\s*(.+)$",
        text,
    )

    source = (
        _first_match(r"^\s*SOURCE\s*:\s*(.+)$", text)
        or _first_match(r"^\s*PUBLISHER\s*:\s*(.+)$", text)
    )

    url = _first_match(r"^\s*(?:URL|LINK)\s*:\s*(https?://\S+)\s*$", text)

    # If no explicit title exists, use the first non-empty line only when
    # it looks like a heading. Otherwise use the filename.
    if not title:
        non_empty = [line.strip() for line in text.splitlines() if line.strip()]
        if non_empty:
            candidate = non_empty[0]
            if len(candidate) <= 180 and not candidate.upper().startswith("DATE:"):
                title = candidate

    return {
        "title": title or path.stem.replace("_", " ").replace("-", " ").title(),
        "date": date,
        "source": source,
        "url": url,
    }


def ingest_articles(
    articles_dir: Path | str = ARTICLES_DIR,
) -> list[Article]:
    """
    Read every supported article in the articles/ directory.

    Files are sorted for deterministic IDs and reproducible runs.
    """
    directory = Path(articles_dir)

    if not directory.exists():
        raise FileNotFoundError(
            f"Articles directory does not exist: {directory}"
        )

    supported = {".txt", ".md", ".pdf", ".docx"}
    paths = sorted(
        path for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in supported
    )

    articles: list[Article] = []

    for index, path in enumerate(paths, start=1):
        text = read_article_file(path).strip()

        if not text:
            continue

        metadata = extract_article_metadata(path, text)

        articles.append(
            Article(
                article_id=f"article_{index:03d}",
                filename=str(path.relative_to(directory)),
                title=metadata["title"] or path.stem,
                date=metadata["date"],
                source=metadata["source"],
                url=metadata["url"],
                text=text,
            )
        )

    return articles


def save_ingested_articles(
    articles: Iterable[Article],
    output_path: Path | str | None = None,
) -> Path:
    output = (
        Path(output_path)
        if output_path
        else WATCH_OUTPUT_DIR / "articles.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    payload = [article.to_dict() for article in articles]
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return output


# ---------------------------------------------------------------------------
# Lightweight retrieval
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]+")


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if len(token) > 2
    ]


class ArticleRetriever:
    """
    Small TF-IDF-style retriever for the 21-article MVP.

    This intentionally has no vector database dependency. It can later be
    replaced by Bedrock Knowledge Bases/OpenSearch without changing the
    EnvironmentalIssue schema or agent contract.
    """

    def __init__(self, articles: list[Article]):
        self.articles = articles
        self.documents = [_tokens(article.text) for article in articles]

        self.document_frequency: Counter[str] = Counter()

        for tokens in self.documents:
            self.document_frequency.update(set(tokens))

        self.total_documents = max(len(self.documents), 1)

    def _idf(self, token: str) -> float:
        df = self.document_frequency.get(token, 0)
        return math.log(
            (1 + self.total_documents) / (1 + df)
        ) + 1.0

    def _vector(self, tokens: list[str]) -> dict[str, float]:
        counts = Counter(tokens)
        total = max(len(tokens), 1)

        return {
            token: (count / total) * self._idf(token)
            for token, count in counts.items()
        }

    @staticmethod
    def _cosine(
        left: dict[str, float],
        right: dict[str, float],
    ) -> float:
        common = set(left) & set(right)

        numerator = sum(left[token] * right[token] for token in common)

        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))

        if not left_norm or not right_norm:
            return 0.0

        return numerator / (left_norm * right_norm)

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        query_vector = self._vector(_tokens(query))

        scored = []

        for article, tokens in zip(self.articles, self.documents):
            score = self._cosine(query_vector, self._vector(tokens))
            scored.append((score, article))

        scored.sort(key=lambda item: item[0], reverse=True)

        return [
            {
                "score": round(score, 6),
                "article": article.to_dict(),
            }
            for score, article in scored[:top_k]
        ]


# ---------------------------------------------------------------------------
# Deterministic jurisdiction helpers
# ---------------------------------------------------------------------------

def resolve_district_from_text(text: str) -> list[dict[str, str]]:
    """
    Detect explicit district names from article text.

    This is intentionally conservative. It does not attempt to infer a
    district from an arbitrary village name.
    """
    lowered = text.lower()
    matches: list[dict[str, str]] = []

    for alias, code in DISTRICT_ALIASES.items():
        pattern = rf"\b{re.escape(alias)}\b"

        if re.search(pattern, lowered):
            matches.append(
                {
                    "district": DISTRICT_DISPLAY_NAMES[code],
                    "district_code": code,
                }
            )

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[dict[str, str]] = []

    for match in matches:
        code = match["district_code"]
        if code not in seen:
            seen.add(code)
            unique.append(match)

    return unique


def build_jurisdiction_context(
    *,
    district: Optional[str],
    named_places: Optional[list[str]] = None,
) -> SpatialContext:
    """
    Build deterministic jurisdiction information after the agent extracts
    a district.

    A location is NOT considered verified merely because the LLM mentioned
    a district. Actual GIS boundary verification can be added later.
    """
    normalized = district.strip().lower() if district else None
    code = DISTRICT_ALIASES.get(normalized or "")

    return SpatialContext(
        named_places=named_places or [],
        district=DISTRICT_DISPLAY_NAMES.get(code) if code else district,
        district_code=code,
        within_shuhul=code is not None,
        location_verified=False,
    )


# ---------------------------------------------------------------------------
# Strands / Bedrock agent
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """
You are the Environmental Watch agent inside Shuhul, a spatial
environmental planning system for Kashmir.

Your task is to convert environmental and infrastructure reporting into a
structured planning issue.

Rules:

1. Extract information from the supplied source only.
2. Never invent facts, locations, numbers, dates, or sources.
3. Preserve attribution for allegations, disputed figures, and claims.
4. Never turn an allegation into an established fact.
5. Identify environmental factors that Shuhul should investigate.
6. Identify the district only when the source supports it.
7. If the district cannot be established, leave it unresolved.
8. Shuhul covers these districts:
   Anantnag, Budgam, Bandipora, Ganderbal, Kulgam, Kupwara,
   Pulwama, Shopian, Srinagar, and Baramulla.
9. The agent must not decide that a project should or should not be built.
10. The agent should create an investigation/action item, such as:
    "Conduct preliminary environmental route assessment."
11. Numerical environmental measurements must come from Shuhul's GIS
    engine, not from the agent.
12. Clearly distinguish:
    - source-reported claims
    - facts explicitly stated by the source
    - items requiring verification
13. Keep the action useful to a planner or government reviewer.
"""


def _build_pydantic_models():
    """
    Define Pydantic models lazily so the rest of the ingestion/retrieval
    system can run without installing Strands immediately.
    """
    from pydantic import BaseModel, Field

    class ReportedClaimModel(BaseModel):
        claim: str = Field(description="Claim made or reported by the source.")
        attributed_to: Optional[str] = Field(
            default=None,
            description="Person, organization, or source to whom the claim is attributed.",
        )
        status: str = Field(
            default="reported_claim",
            description="Use reported_claim, reported_figure, or source_stated_fact.",
        )
        value: Optional[float] = Field(
            default=None,
            description="Numeric value if the claim contains one.",
        )
        unit: Optional[str] = Field(
            default=None,
            description="Unit for the numeric value, if applicable.",
        )

    class SpatialContextModel(BaseModel):
        named_places: list[str] = Field(default_factory=list)
        district: Optional[str] = None
        district_code: Optional[str] = None
        within_shuhul: Optional[bool] = None
        location_verified: bool = False

    class IssueModel(BaseModel):
        title: str
        category: str
        issue_type: str
        status: str
        description: str

    class ActionModel(BaseModel):
        title: str
        description: str

    class EnvironmentalIssueModel(BaseModel):
        relevant: bool
        issue: IssueModel
        spatial_context: SpatialContextModel
        environmental_factors: list[str]
        reported_claims: list[ReportedClaimModel]
        action: ActionModel
        confidence: Optional[str] = None

    return EnvironmentalIssueModel


def create_strands_agent():
    """
    Create the Environmental Watch agent using Strands + Amazon Bedrock.

    Requires:
        pip install strands-agents pydantic

    AWS credentials and Bedrock model access must already be configured
    in the environment/profile used to run the Flask backend.
    """
    from strands import Agent
    from strands.models import BedrockModel

    model_id = (
        __import__("os").environ.get(
            "SHUHUL_BEDROCK_MODEL_ID",
            "qwen.qwen3-coder-next",
        )
    )

    model = BedrockModel(
        model_id=model_id,
        temperature=0.2,
    )

    return Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
    )


def analyse_article_with_agent(
    article: Article,
    *,
    retrieved_context: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    Run one article through Strands and return a JSON-serializable issue.

    Retrieval context is included as supporting material, but the article
    itself remains the primary source.
    """
    output_model = _build_pydantic_models()
    agent = create_strands_agent()

    context_text = json.dumps(
        retrieved_context or [],
        indent=2,
        ensure_ascii=False,
    )

    prompt = f"""
Analyze this source article for Shuhul Environmental Watch.

SOURCE ARTICLE
---------------
Article ID: {article.article_id}
Filename: {article.filename}
Title: {article.title}
Date: {article.date}
Source: {article.source}
URL: {article.url}

ARTICLE TEXT
------------
{article.text}

RETRIEVED RELATED ARTICLES
---------------------------
{context_text}

Return a structured EnvironmentalIssue.

For the spatial context:
- extract named places explicitly mentioned in the article;
- identify a district only when supported by the source;
- map a supported district to its Shuhul district code;
- do not claim that a location has been GIS-verified yet.

For reported claims:
- preserve who made the claim;
- preserve competing figures where present;
- do not collapse disputed values into one number.

For the action:
- create a concrete investigation task for Shuhul;
- do not recommend that government definitely approve or reject a project.
"""

    result = agent(
        prompt,
        structured_output_model=output_model,
    )

    data = result.structured_output.model_dump()

    # Add source metadata outside the LLM schema.
    data["article_id"] = article.article_id
    data["source"] = {
        "title": article.title,
        "date": article.date,
        "publisher": article.source,
        "url": article.url,
        "filename": article.filename,
    }

    return data


# ---------------------------------------------------------------------------
# Action card transformation
# ---------------------------------------------------------------------------

def issue_to_action_card(
    issue: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert the agent's structured output into the frontend-friendly card
    format.
    """
    spatial = issue.get("spatial_context") or {}
    action = issue.get("action") or {}
    source = issue.get("source") or {}
    environmental_factors = issue.get("environmental_factors") or []

    return {
        "id": issue.get("article_id"),
        "title": (issue.get("issue") or {}).get(
            "title",
            "Environmental issue",
        ),
        "category": (issue.get("issue") or {}).get(
            "category",
            "other",
        ),
        "status": (issue.get("issue") or {}).get(
            "status",
            "reported",
        ),
        "description": (issue.get("issue") or {}).get(
            "description",
            "",
        ),
        "location": {
            "district": spatial.get("district"),
            "districtCode": spatial.get("district_code"),
            "places": spatial.get("named_places", []),
            "withinShuhul": spatial.get("within_shuhul"),
            "verified": spatial.get("location_verified", False),
        },
        "environmentalFactors": environmental_factors,
        "reportedClaims": issue.get("reported_claims", []),
        "action": {
            "title": action.get(
                "title",
                "Conduct preliminary environmental assessment",
            ),
            "description": action.get("description", ""),
        },
        "source": source,
        "confidence": issue.get("confidence"),
        "analysisAvailable": bool(
            spatial.get("district_code")
        ),
    }


# ---------------------------------------------------------------------------
# Local corpus utilities
# ---------------------------------------------------------------------------

def build_article_index() -> dict[str, Any]:
    """
    Ingest all articles and save the normalized corpus plus a small manifest.
    """
    articles = ingest_articles()
    corpus_path = save_ingested_articles(articles)

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "article_count": len(articles),
        "articles_directory": str(ARTICLES_DIR),
        "corpus_file": str(corpus_path),
        "districts": DISTRICTS,
    }

    manifest_path = WATCH_OUTPUT_DIR / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return manifest


def search_environmental_watch(
    query: str,
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    Convenience function used by the future Flask endpoint.
    """
    articles = ingest_articles()
    retriever = ArticleRetriever(articles)
    return retriever.search(query, top_k=top_k)



# ---------------------------------------------------------------------------
# Flask API
# ---------------------------------------------------------------------------

def _find_article_by_id(article_id: str) -> Optional[Article]:
    for article in ingest_articles():
        if article.article_id == article_id:
            return article
    return None


def register_environmental_watch_routes(app):
    """
    Register Environmental Watch API routes on the existing Flask app.

    Routes:
        GET  /api/environmental-watch/articles
        GET  /api/environmental-watch/search?q=...
        GET  /api/environmental-watch/articles/<article_id>
        POST /api/environmental-watch/analyse/<article_id>

    The analyse endpoint requires Strands + AWS Bedrock configuration.
    The other endpoints work without AWS credentials.
    """
    from flask import jsonify, request

    @app.get("/api/environmental-watch/articles")
    def environmental_watch_articles():
        articles = ingest_articles()

        return jsonify({
            "count": len(articles),
            "articles": [
                {
                    "article_id": article.article_id,
                    "title": article.title,
                    "date": article.date,
                    "source": article.source,
                    "url": article.url,
                    "filename": article.filename,
                }
                for article in articles
            ],
        })

    @app.get("/api/environmental-watch/search")
    def environmental_watch_search():
        query = (request.args.get("q") or "").strip()

        if not query:
            return jsonify({
                "error": "Missing query parameter 'q'.",
                "example": "/api/environmental-watch/search?q=trees",
            }), 400

        try:
            top_k = max(1, min(int(request.args.get("top_k", 5)), 20))
        except ValueError:
            top_k = 5

        return jsonify({
            "query": query,
            "results": search_environmental_watch(
                query,
                top_k=top_k,
            ),
        })

    @app.get("/api/environmental-watch/articles/<article_id>")
    def environmental_watch_article(article_id: str):
        article = _find_article_by_id(article_id)

        if article is None:
            return jsonify({
                "error": "Article not found.",
                "article_id": article_id,
            }), 404

        return jsonify(article.to_dict())

    @app.post("/api/environmental-watch/analyse/<article_id>")
    def environmental_watch_analyse(article_id: str):
        article = _find_article_by_id(article_id)

        if article is None:
            return jsonify({
                "error": "Article not found.",
                "article_id": article_id,
            }), 404

        try:
            # Retrieve related articles first. This gives the agent useful
            # Kashmir-specific context without requiring a vector database.
            retriever = ArticleRetriever(ingest_articles())

            retrieval_query = (
                f"{article.title}\n"
                f"{article.text[:4000]}"
            )

            related = retriever.search(
                retrieval_query,
                top_k=5,
            )

            analysis = analyse_article_with_agent(
                article,
                retrieved_context=related,
            )

            card = issue_to_action_card(analysis)

            result = {
                "article": article.to_dict(),
                "analysis": analysis,
                "action_card": card,
                "retrieved_articles": [
                    {
                        "article_id": item["article"]["article_id"],
                        "title": item["article"]["title"],
                        "score": item["score"],
                    }
                    for item in related
                ],
            }

            # Save each generated analysis so the frontend can load cards
            # without asking Bedrock to regenerate them.
            WATCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            analysis_path = (
                WATCH_OUTPUT_DIR
                / f"{article.article_id}_analysis.json"
            )

            analysis_path.write_text(
                json.dumps(
                    result,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            return jsonify(result)

        except Exception as exc:
            # Keep the error useful during hackathon development. Do not
            # silently convert an AWS/Strands failure into a fake card.
            return jsonify({
                "error": "Environmental Watch analysis failed.",
                "message": str(exc),
                "article_id": article_id,
                "hint": (
                    "Check Strands installation, AWS credentials, "
                    "Bedrock model access, and SHUHUL_BEDROCK_MODEL_ID."
                ),
            }), 500

# ---------------------------------------------------------------------------
# Example CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Shuhul Environmental Watch")
    print("=" * 60)

    if not ARTICLES_DIR.exists():
        print(f"Articles directory not found: {ARTICLES_DIR}")
        raise SystemExit(1)

    articles = ingest_articles()

    print(f"Articles discovered: {len(articles)}")

    for article in articles:
        print(
            f"- {article.article_id}: "
            f"{article.title} "
            f"({article.filename})"
        )

    output = save_ingested_articles(articles)

    print()
    print(f"Normalized corpus written to: {output}")
    print()
    print("Next step: connect analyse_article_with_agent() to Flask.")
