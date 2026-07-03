"""Domain objects for the dataset-ingestion capability.

These are plain, DB-free, LLM-free data shapes that tie CSV parsing,
schema profiling, and anomaly detection together into the single
`DatasetProfile` object other slices (API, graph) consume. Field names
are chosen to match `spec/agent.md`'s `dataset_schema` / `dataset_anomalies`
and `spec/api.md`'s upload response shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ColumnProfile:
    """Per-column schema profile.

    Matches `spec/agent.md`'s `dataset_schema` entry shape:
    ``{name, dtype, null_pct, distinct_count, min, max, mean, std}``
    (numeric fields only where applicable) plus `null_count`, which
    `spec/data.md`'s `schema_json` also requires.
    """

    name: str
    dtype: str
    null_count: int
    null_pct: float
    distinct_count: int
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    std: float | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "null_count": self.null_count,
            "null_pct": self.null_pct,
            "distinct_count": self.distinct_count,
            "min": self.min,
            "max": self.max,
            "mean": self.mean,
            "std": self.std,
        }


@dataclass
class Anomaly:
    """A single data-quality anomaly finding.

    Matches `spec/data.md`'s `anomalies_json` entry shape.
    `type` is one of: missing_values | outliers | mixed_types |
    inconsistent_format | duplicate_rows.
    """

    column: str
    type: str
    severity: str  # low | medium | high
    description: str

    def to_dict(self) -> dict:
        return {
            "column": self.column,
            "type": self.type,
            "severity": self.severity,
            "description": self.description,
        }


@dataclass
class ParseDecision:
    """A structured "needs decision" result returned when a CSV cannot be
    cleanly/unambiguously parsed. Never raised as an exception — always
    returned as a value so the caller can surface it to the user.
    """

    issue: str
    choices: list[str] = field(default_factory=list)


@dataclass
class DatasetProfile:
    """The successful outcome of ingesting + profiling a CSV.

    This is the contract other slices (API, graph) depend on.
    """

    row_count: int
    column_count: int
    schema: list[ColumnProfile]
    anomalies: list[Anomaly]
    parse_warnings: str | None = None

    def to_dict(self) -> dict:
        return {
            "row_count": self.row_count,
            "column_count": self.column_count,
            "schema": [c.to_dict() for c in self.schema],
            "anomalies": [a.to_dict() for a in self.anomalies],
            "parse_warnings": self.parse_warnings,
        }
