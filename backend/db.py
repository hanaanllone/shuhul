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
    select,
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
    Column("error", Text),
    Column("created_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False),
)

ACTIVE_STATUSES = ("queued", "running")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db():
    metadata.create_all(engine)


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
    allowed = {"status", "stage", "progress", "result_json", "error"}
    values = {}

    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "result_json" and not isinstance(value, str):
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
            )
            .where(projects.c.user_id == user_id)
            .order_by(projects.c.created_at.desc())
        ).mappings().all()
    return [dict(row) for row in rows]


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
