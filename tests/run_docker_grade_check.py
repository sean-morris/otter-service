#!/usr/bin/env python3
"""
Submit student and solution notebooks to a locally-running otter-service container
and verify grades in Firestore.

Each submission uses a UNIQUE user_id (passed via the Referer header — see
otter_nb.py OtterHandler.post which parses url_referer.split("/")[4] when
no LTI auth is present). That eliminates grade-doc collision: every grade
lives at exactly one (user, course, assignment) row, so a late-arriving
grade can never be misread for a different submission.

Assumes the container is already running on localhost:10101 with:
  ENVIRONMENT=otter-ci-{run_id}
  POST_GRADE=false

Usage:
  python tests/run_docker_grade_check.py --run-id "${{ github.run_id }}"
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from google.cloud import firestore

SERVICE_URL = "http://localhost:10101/services/otter_grade/"
TEST_FILES_DIR = Path("tests/test_files")
DEFAULT_CONCURRENCY = int(os.environ.get("GRADING_CONCURRENCY", "3"))
POLL_INTERVAL = 10  # seconds between Firestore polls
POLL_TIMEOUT = 600  # seconds — autograder image pulls + grade can take 5+ min cold


def make_user_id(run_id, course, assignment, role):
    """Unique user per submission. Each grade lives at its own row."""
    return f"TEST_USER_{run_id}_{course}_{assignment}_{role}"


def referer_for(user_id):
    """
    Build a Referer URL whose split('/')[4] is user_id. otter_nb.py uses
    that index to extract the test username when no LTI auth is present.
    'https://courses.edx.org/courses/<user_id>/test'.split('/') yields
    ['https:', '', 'courses.edx.org', 'courses', '<user_id>', 'test'] —
    index 4 is the user_id.
    """
    return f"https://courses.edx.org/courses/{user_id}/test"


def submit_notebook(nb_path, user_id):
    nb = json.loads(nb_path.read_text())
    resp = requests.post(
        SERVICE_URL,
        data=json.dumps({"nb": nb}),
        headers={"Referer": referer_for(user_id)},
        timeout=30,
    )
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"POST failed {resp.status_code}: {resp.text[:200]}")


def poll_for_grade(db, collection, user, course, assignment, deadline):
    """Poll until exactly one grade for (user, course, assignment) shows up."""
    while True:
        docs = (
            db.collection(collection)
            .where("user", "==", user)
            .where("course", "==", course)
            .where("assignment", "==", assignment)
            .get()
        )
        if docs:
            doc = docs[0]
            return doc.to_dict().get("grade"), doc.reference
        if time.time() >= deadline:
            raise TimeoutError(
                f"Timed out waiting for grade: user={user}, course={course}, assignment={assignment}"
            )
        time.sleep(POLL_INTERVAL)


def cleanup(db, collection_prefix):
    """Nuke every doc in the run's collections. Cheap because run_id-isolated."""
    for suffix in ("grades", "logs", "submissions", "tornado-logs"):
        coll = db.collection(f"{collection_prefix}-{suffix}")
        for doc in coll.stream():
            doc.reference.delete()
    print(f"  cleaned up {collection_prefix}-*")


def run_pair(db, collection_prefix, run_id, course, assignment):
    tag = f"[{course}/{assignment}]"
    nb_name = f"{assignment}.ipynb"
    student_nb = TEST_FILES_DIR / course / assignment / "student" / nb_name
    solution_nb = TEST_FILES_DIR / course / assignment / "solution" / nb_name

    if not student_nb.exists() or not solution_nb.exists():
        print(f"{tag} skip: notebook pair not present", flush=True)
        return True, []

    errors = []
    for role, nb_path, expected_grade in [
        ("student", student_nb, 0.0),
        ("solution", solution_nb, 1.0),
    ]:
        user_id = make_user_id(run_id, course, assignment, role)
        print(f"{tag} submitting {role} as {user_id}", flush=True)
        deadline = time.time() + POLL_TIMEOUT
        try:
            submit_notebook(nb_path, user_id)
            grade, _ = poll_for_grade(
                db, f"{collection_prefix}-grades", user_id, course, assignment, deadline,
            )
            if grade != expected_grade:
                errors.append(
                    f"{course}/{assignment} {role}: expected grade {expected_grade}, got {grade}"
                )
                print(f"{tag} FAIL {role}: expected {expected_grade}, got {grade}", flush=True)
            else:
                print(f"{tag} PASS {role}: grade = {grade}", flush=True)
        except TimeoutError as e:
            errors.append(f"{course}/{assignment} {role}: {e}")
            print(f"{tag} FAIL {role}: {e}", flush=True)
        except RuntimeError as e:
            errors.append(f"{course}/{assignment} {role}: submission error — {e}")
            print(f"{tag} FAIL {role}: submission error: {e}", flush=True)

    return not errors, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True, help="GitHub Actions run ID for isolation")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help="Max pairs to grade in parallel (default 3; override with GRADING_CONCURRENCY env)",
    )
    args = parser.parse_args()

    run_id = args.run_id
    collection_prefix = f"otter-ci-{run_id}"
    project = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        print("Error: GCP_PROJECT_ID env var is required", file=sys.stderr)
        sys.exit(1)

    db = firestore.Client(project=project)

    pairs = []
    if TEST_FILES_DIR.exists():
        for course_dir in sorted(TEST_FILES_DIR.iterdir()):
            if not course_dir.is_dir():
                continue
            for assignment_dir in sorted(course_dir.iterdir()):
                if assignment_dir.is_dir():
                    pairs.append((course_dir.name, assignment_dir.name))

    if not pairs:
        print("No notebook pairs found in tests/test_files/ — nothing to test")
        sys.exit(0)

    workers = min(args.concurrency, len(pairs))
    print(f"Grading {len(pairs)} pair(s) with concurrency={workers}")

    all_errors = []
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(run_pair, db, collection_prefix, run_id, course, assignment): (course, assignment)
                for course, assignment in pairs
            }
            for fut in as_completed(futures):
                course, assignment = futures[fut]
                try:
                    _, errors = fut.result()
                    all_errors.extend(errors)
                except Exception as ex:  # pylint: disable=broad-except
                    all_errors.append(f"{course}/{assignment}: pair runner crashed — {ex}")
    finally:
        print("\nCleaning up Firestore test data...")
        cleanup(db, collection_prefix)

    if all_errors:
        print(f"\n{len(all_errors)} failure(s):")
        for e in all_errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print(f"\nAll {len(pairs)} notebook pair(s) graded correctly")


if __name__ == "__main__":
    main()
