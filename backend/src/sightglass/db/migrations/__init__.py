"""Alembic migration environment and revisions."""


def include_object(obj: object, name: str | None, type_: str, reflected: bool, compare_to: object) -> bool:
    """Leave the job queue's tables to procrastinate's own schema when comparing models with the database."""
    table = getattr(obj, "table", obj)
    table_name = getattr(table, "name", name) or ""
    return not table_name.startswith("procrastinate_")
