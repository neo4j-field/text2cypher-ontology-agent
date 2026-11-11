"""
Offline smoke tests for the ontology tool (tools/get_ontology.py) and the ontology document
(ontology/movies.ontology.yaml).

Runs with no .env, no API key and no database:

    uv run python tests/smoke_test.py

Plain Python on purpose: no pytest and no new dependencies. The only network access is
downloading the published ontology JSON Schema for validation; if that download fails
(e.g. on a fully offline machine) the validation is skipped with a message and everything
else still runs. Exits non-zero with a list of failed checks if anything is broken.
"""

import json
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY_FILE = REPO_ROOT / "ontology" / "movies.ontology.yaml"
SPEC_SCHEMA_URL = "https://neo4j.com/docs/ontology-graph-spec/1.1.0/schema.json"

# tools/ is not an installed package: put the repo root on sys.path to import it.
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from tools.get_ontology import get_ontology  # noqa: E402

ALL_ENTITIES = ("Movie", "Person", "User", "Genre", "ACTED_IN", "DIRECTED", "RATED", "IN_GENRE")

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """Print one readable PASS/FAIL line and record failures."""
    line = f"[{'PASS' if condition else 'FAIL'}] {name}"
    if detail and not condition:
        line += f" -- {detail}"
    print(line)
    if not condition:
        failures.append(name)


def check_ontology_document() -> None:
    """The ontology file parses and validates against the published spec schema."""
    print("\n# Ontology document (ontology/movies.ontology.yaml)")

    document = yaml.safe_load(ONTOLOGY_FILE.read_text())
    check("ontology file parses as a YAML mapping", isinstance(document, dict))

    try:
        with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as tmp:
            tmp.write(urllib.request.urlopen(SPEC_SCHEMA_URL).read())
            schema_file = Path(tmp.name)
    except OSError as error:
        print(f"[SKIP] spec schema validation -- cannot download {SPEC_SCHEMA_URL} ({error})")
        return

    # `jsonschema` is already in the lockfile (a dependency of the `mcp` package), so this
    # adds no new dependency. If it ever disappears from the environment, fall back to a
    # light structural check of the document instead of failing.
    try:
        import jsonschema

        schema = json.loads(schema_file.read_text())
        errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(document), key=str)
        check(
            "ontology validates against the published JSON Schema",
            not errors,
            "; ".join(str(error) for error in errors[:3]),
        )
    except ImportError:
        print("[SKIP] jsonschema not installed -- falling back to a light structural check")
        check(
            "ontology has the expected top-level keys",
            all(
                key in document
                for key in ("schema", "version", "id", "name", "nodes", "relationships")
            ),
            str(sorted(document)),
        )
        nodes = document.get("nodes", {})
        check(
            "every node has a label and a description",
            all(node.get("label") and node.get("description") for node in nodes.values()),
            str(sorted(nodes)),
        )


def check_ontology_tool() -> None:
    """The get_ontology tool renders cards, sub-schemas and helpful error messages."""
    print("\n# Ontology tool (tools/get_ontology.py)")

    # Default call: the whole ontology. This ontology is small (~500-token card), well
    # under the tool's token budget, so the full card is returned.
    full = get_ontology()
    full_card = full["schema_card"]
    check("full card has a title", full_card.startswith("# Movies ontology"))
    for entity in ALL_ENTITIES:
        check(f"full card mentions {entity}", entity in full_card)

    # Sub-schema: only the requested entities, plus the relationships that connect the
    # selected nodes (that is the tool's actual behavior: DIRECTED is included because
    # both its endpoints, Person and Movie, were requested).
    sub = get_ontology(entities=["Movie", "Person", "ACTED_IN"])
    sub_card = sub["schema_card"]
    check(
        "sub-schema lists the requested entities",
        {"Movie", "Person", "ACTED_IN"} <= set(sub["entities"]),
        str(sub["entities"]),
    )
    check(
        "sub-schema also lists relationships between the requested nodes",
        "DIRECTED" in sub["entities"],
        str(sub["entities"]),
    )
    check(
        "sub-schema card shows the Person -[ACTED_IN]-> Movie line",
        "Person -[ACTED_IN]-> Movie" in sub_card,
    )
    # Entities that were not requested must not appear. Checked as headings and
    # relationship types, because the ontology's own description legitimately contains
    # the lowercase words "genres" and "users".
    for unwanted in ("### Genre", "### User", "RATED", "IN_GENRE"):
        check(f"sub-schema card omits {unwanted!r}", unwanted not in sub_card)

    # Nonexistent entity: a helpful message listing what is available.
    missing = get_ontology(entities=["TotallyNotAnEntity"])
    missing_card = missing.get("schema_card", "")
    check(
        "nonexistent entity returns a no-match message",
        "No ontology entities matched" in missing_card,
        missing_card[:200],
    )
    check(
        "no-match message lists the available entities",
        "Available labels and relationship types" in missing_card
        and all(entity in missing_card for entity in ALL_ENTITIES),
        missing_card[:200],
    )

    # include_properties: property detail is omitted or included accordingly.
    bare = get_ontology(entities=["Movie"], include_properties=False)
    check(
        "include_properties=False omits property detail",
        "Properties:" not in bare["schema_card"] and "imdbRating" not in bare["schema_card"],
    )
    detailed = get_ontology(entities=["Movie"], include_properties=True)
    check(
        "include_properties=True lists property detail",
        "imdbRating: FLOAT" in detailed["schema_card"],
    )


def main() -> int:
    print(f"Smoke-testing the ontology tool in {REPO_ROOT} (offline: no .env, no key, no DB)")
    check_ontology_document()
    check_ontology_tool()

    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
