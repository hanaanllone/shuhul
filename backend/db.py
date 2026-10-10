from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    func,
    insert,
    inspect,
    select,
    text,
    update,
)

from .config import DATABASE_PATH, DATABASE_URL

IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"timeout": 30} if IS_SQLITE else {},
)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(connection, _record):
        # Write-ahead logging lets the API read while the worker writes.
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(320), nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("organisation", Text, nullable=False),
    Column("name", Text),
    Column("created_at", String(32), nullable=False),
)

projects = Table(
    "projects",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("project_name", Text, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("status", String(16), nullable=False, default="queued", index=True),
    Column("stage", Text, nullable=False, default="queued"),
    Column("progress", Integer, nullable=False, default=0),
    Column("result_json", Text),
    Column("preview_json", Text),
    Column("error", Text),
    Column("created_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False),
)

# One row per news report that Environmental Watch judged relevant. The
# article text itself is not kept: only a short excerpt, the link, and
# what was extracted from it.
watch_issues = Table(
    "watch_issues",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("url", String(600), nullable=False, unique=True),
    Column("title_key", String(200), nullable=False, index=True),
    Column("source", String(40), nullable=False),
    Column("title", Text, nullable=False),
    Column("excerpt", Text),
    Column("published_at", String(32), index=True),
    Column("fetched_at", String(32), nullable=False),
    Column("category", String(32), nullable=False, index=True),
    Column("relevance", Integer, nullable=False, default=0),
    Column("factors_json", Text, nullable=False, default="[]"),
    Column("places_json", Text, nullable=False, default="[]"),
    Column("claims_json", Text, nullable=False, default="[]"),
    Column("district_code", String(16), index=True),
    Column("lat", String(16)),
    Column("lng", String(16)),
    Column("location_precision", String(16)),
    Column("extractor", String(16), nullable=False, default="rules"),
)

# Place-name lookups, kept so each name is only ever looked up once.
watch_places = Table(
    "watch_places",
    metadata,
    Column("name_key", String(120), primary_key=True),
    Column("name", Text, nullable=False),
    Column("found", Integer, nullable=False, default=0),
    Column("lat", String(16)),
    Column("lng", String(16)),
    Column("kind", String(40)),
    Column("display_name", Text),
    Column("looked_up_at", String(32), nullable=False),
)

ACTIVE_STATUSES = ("queued", "running")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db():
    metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns():
    """Bring a database created by an earlier version up to date."""
    existing = {column["name"] for column in inspect(engine).get_columns("projects")}

    if "preview_json" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN preview_json TEXT"))


# ------------------------------------------------------------
# USERS
# ------------------------------------------------------------

def create_user(email, password_hash, organisation, name=None):
    with engine.begin() as conn:
        result = conn.execute(
            insert(users).values(
                email=email,
                password_hash=password_hash,
                organisation=organisation,
                name=name,
                created_at=_now(),
            )
        )
        return result.inserted_primary_key[0]


def get_user_by_email(email):
    with engine.connect() as conn:
        row = conn.execute(select(users).where(users.c.email == email)).mappings().first()
    return dict(row) if row else None


def get_user(user_id):
    with engine.connect() as conn:
        row = conn.execute(
            select(
                users.c.id,
                users.c.email,
                users.c.organisation,
                users.c.name,
                users.c.created_at,
            ).where(users.c.id == user_id)
        ).mappings().first()
    return dict(row) if row else None


def update_user(user_id, organisation, name):
    with engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(organisation=organisation, name=name)
        )


def get_password_hash(user_id):
    with engine.connect() as conn:
        return conn.execute(
            select(users.c.password_hash).where(users.c.id == user_id)
        ).scalar_one_or_none()


def set_password_hash(user_id, password_hash):
    with engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(password_hash=password_hash)
        )


# ------------------------------------------------------------
# PROJECTS
# ------------------------------------------------------------

def create_project(project_id, user_id, project_name, payload):
    now = _now()
    with engine.begin() as conn:
        conn.execute(
            insert(projects).values(
                id=project_id,
                user_id=user_id,
                project_name=project_name,
                payload_json=json.dumps(payload),
                status="queued",
                stage="Queued for analysis",
                progress=0,
                created_at=now,
                updated_at=now,
            )
        )


def update_project(project_id, **fields):
    allowed = {"status", "stage", "progress", "result_json", "preview_json", "error"}
    values = {}

    for key, value in fields.items():
        if key not in allowed:
            continue
        if key in ("result_json", "preview_json") and not isinstance(value, str):
            value = json.dumps(value)
        values[key] = value

    if not values:
        return

    values["updated_at"] = _now()
    with engine.begin() as conn:
        conn.execute(update(projects).where(projects.c.id == project_id).values(**values))


def get_project(project_id, user_id):
    with engine.connect() as conn:
        row = conn.execute(
            select(projects).where(
                projects.c.id == project_id,
                projects.c.user_id == user_id,
            )
        ).mappings().first()

    if not row:
        return None

    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    item.pop("preview_json", None)
    result_json = item.pop("result_json", None)
    if result_json:
        item["result"] = json.loads(result_json)
    return item


def list_projects(user_id):
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                projects.c.id,
                projects.c.project_name,
                projects.c.status,
                projects.c.stage,
                projects.c.progress,
                projects.c.error,
                projects.c.created_at,
                projects.c.updated_at,
                projects.c.payload_json,
                projects.c.preview_json,
            )
            .where(projects.c.user_id == user_id)
            .order_by(projects.c.created_at.desc())
        ).mappings().all()

    items = []
    for row in rows:
        item = dict(row)
        payload = json.loads(item.pop("payload_json"))
        preview = item.pop("preview_json")

        # What the project card draws: the routes once they exist, and
        # until then just the two endpoints the planner picked.
        item["preview"] = json.loads(preview) if preview else {
            "start": payload.get("start"),
            "end": payload.get("end"),
            "routes": [],
        }
        item["construction_type"] = payload.get("constructionType")
        items.append(item)
    return items


def count_active_projects(user_id):
    with engine.connect() as conn:
        return conn.execute(
            select(func.count())
            .select_from(projects)
            .where(
                projects.c.user_id == user_id,
                projects.c.status.in_(ACTIVE_STATUSES),
            )
        ).scalar_one()


# ------------------------------------------------------------
# JOB QUEUE
# ------------------------------------------------------------
#
# The projects table is the queue. A queued project survives a restart
# because it lives here and not in the arguments of a thread.

def claim_next_project():
    """
    Take the oldest queued project and mark it running.
    Returns (project_id, payload), or None when nothing is waiting.
    """
    with engine.begin() as conn:
        row = conn.execute(
            select(projects.c.id, projects.c.payload_json)
            .where(projects.c.status == "queued")
            .order_by(projects.c.created_at)
            .limit(1)
        ).first()

        if row is None:
            return None

        # The status check makes the claim safe when two workers race:
        # only one of them changes a row.
        claimed = conn.execute(
            update(projects)
            .where(projects.c.id == row.id, projects.c.status == "queued")
            .values(status="running", stage="Starting analysis", updated_at=_now())
        ).rowcount

        if not claimed:
            return None

        return row.id, json.loads(row.payload_json)


def fail_stale_projects(minutes=30):
    """Mark analyses that a stopped worker left running as failed."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=minutes)
    ).isoformat(timespec="seconds")

    with engine.begin() as conn:
        return conn.execute(
            update(projects)
            .where(projects.c.status == "running", projects.c.updated_at < cutoff)
            .values(
                status="failed",
                stage="Analysis failed",
                progress=0,
                error="The analysis was interrupted. Please run it again.",
                updated_at=_now(),
            )
        ).rowcount


# ------------------------------------------------------------
# ENVIRONMENTAL WATCH
# ------------------------------------------------------------

def known_watch_urls(urls):
    """Which of these article links have already been processed."""
    urls = list(urls)
    if not urls:
        return set()

    with engine.connect() as conn:
        rows = conn.execute(
            select(watch_issues.c.url).where(watch_issues.c.url.in_(urls))
        ).all()
    return {row.url for row in rows}


def add_watch_issue(values):
    """
    Store one issue. Returns False when the link, or the same headline
    from another outlet, is already stored.
    """
    with engine.begin() as conn:
        duplicate = conn.execute(
            select(watch_issues.c.id).where(
                (watch_issues.c.url == values["url"])
                | (watch_issues.c.title_key == values["title_key"])
            ).limit(1)
        ).first()

        if duplicate is not None:
            return False

        conn.execute(insert(watch_issues).values(fetched_at=_now(), **values))
        return True


def list_watch_issues(district=None, category=None, since=None, limit=200):
    query = select(watch_issues).order_by(watch_issues.c.published_at.desc().nulls_last()).limit(limit)

    if district:
        query = query.where(watch_issues.c.district_code == district)
    if category:
        query = query.where(watch_issues.c.category == category)
    if since:
        query = query.where(watch_issues.c.published_at >= since)

    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()

    issues = []
    for row in rows:
        item = dict(row)
        item.pop("title_key")
        for key in ("factors", "places", "claims"):
            item[key] = json.loads(item.pop(f"{key}_json") or "[]")
        for key in ("lat", "lng"):
            item[key] = float(item[key]) if item[key] else None
        issues.append(item)
    return issues


def latest_watch_fetch():
    with engine.connect() as conn:
        return conn.execute(select(func.max(watch_issues.c.fetched_at))).scalar_one()


def get_watch_place(name_key):
    with engine.connect() as conn:
        row = conn.execute(
            select(watch_places).where(watch_places.c.name_key == name_key)
        ).mappings().first()
    return dict(row) if row else None


def save_watch_place(values):
    with engine.begin() as conn:
        exists = conn.execute(
            select(watch_places.c.name_key).where(
                watch_places.c.name_key == values["name_key"]
            )
        ).first()
        if exists is None:
            conn.execute(insert(watch_places).values(looked_up_at=_now(), **values))
