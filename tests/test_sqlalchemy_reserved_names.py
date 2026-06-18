"""Guard SQLAlchemy declarative models against reserved attribute names."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESERVED_ORM_NAMES = {"metadata", "registry"}


def _is_column_call(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id == "Column"
        if isinstance(func, ast.Attribute):
            return func.attr == "Column"
    return False


def _base_class_names(cls: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for base in cls.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def test_sqlalchemy_models_do_not_use_reserved_declarative_attribute_names():
    """Use `meta_data = Column("metadata", ...)`, never `metadata = Column(...)`.

    SQLAlchemy declarative classes reserve names such as `metadata` for the
    declarative base itself. Mapping a database column with that Python
    attribute crashes the app at import time on modern SQLAlchemy.
    """

    offenders: list[str] = []
    for path in (ROOT / "core").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            if "Base" not in _base_class_names(cls):
                continue
            for stmt in cls.body:
                if not isinstance(stmt, ast.Assign) or not _is_column_call(stmt.value):
                    continue
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id in RESERVED_ORM_NAMES:
                        offenders.append(f"{path.relative_to(ROOT)}:{stmt.lineno} {cls.name}.{target.id}")

    assert not offenders, (
        "SQLAlchemy declarative models cannot map columns onto reserved Python "
        "attribute names. Use e.g. meta_data = Column('metadata', JSON, ...) "
        f"instead. Offenders: {offenders}"
    )
