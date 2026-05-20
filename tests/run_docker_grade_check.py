#!/usr/bin/env python3
"""
Submit student and solution notebooks to a locally-running otter-service container
and verify grades in Firestore.

Assumes the container is already running on localhost:10101 with:
  ENVIRONMENT=otter-ci-{run_id}
  TEST_USER=TEST_USER_{run_id}
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
from datetime import datetime
from pathlib import Path

import pytz
import requests
from google.cloud import firestore


def get_timestamp():
    """Match otter-service's get_timestamp format (PST, ms precision)."""
    date = datetime.now(tz=pytz.utc).astimezone(pytz.timezone("US/Pacific"))
    return date.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]

SERVICE_URL = "http://localhost:10101/services/otter_grade/"
TEST_FILES_DIR = Path("tests/test_files")
DEFAULT_CONCURRENCY = int(os.environ.get("GRADING_CONCURRENCY", "3"))
POLL_INTERVAL = 10  # seconds between Firestore polls
POLL_TIMEOUT = 600  # seconds — autograder image pulls + grade can take 5+ min cold


def submit_notebook(nb_path):
    nb = json.loads(nb_path.read_text())
    resp = requests.post(SERVICE_URL, data=json.dumps({"nb": nb}), timeout=30)
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"POST failed {resp.status_code}: {resp.text[:200]}")


def poll_for_grade(db, collection, user, course, assignment, deadline,
                   exclude_ids=None, min_timestamp=None):
    """
    Poll Firestore until a grade entry appears. `exclude_ids` skips already-consumed
    docs so the student/solution pair (same user/course/assignment) don't read the
    same grade twice. `min_timestamp` (string from get_timestamp) filters out grades
    written before this poll started — protects solution from picking up a late
    student grade that arrived after the student poll already timed out.
    Returns (grade, doc_ref).
    """
    exclude_ids = exclude_ids or set()
    while True:
        docs = (
            db.collection(collection)
            .where("user", "==", user)
            .where("course", "==", course)
            .where("assignment", "==", assignment)
            .get()
        )
        candidates = [d for d in docs if d.id not in exclude_ids]
        if min_timestamp is not None:
            candidates = [d for d in candidates if d.to_dict().get("timestamp", "") >= min_timestamp]
        if candidates:
            candidates.sort(key=lambda d: d.to_dict().get("timestamp", ""))
            latest = candidates[-1]
            return latest.to_dict().get("grade"), latest.reference
        if time.time() >= deadline:
            raise TimeoutError(
                f"Timed out waiting for grade: user={user}, course={course}, assignment={assignment}"
            )
        time.sleep(POLL_INTERVAL)


def cleanup(db, collection_prefix, user):
    """Delete all documents for this test user across grades/logs/submissions."""
    for suffix in ("grades", "logs", "submissions"):
        coll = db.collection(f"{collection_prefix}-{suffix}")
        docs = coll.where("user", "==", user).get()
        for doc in docs:
            doc.reference.delete()
    print(f"  cleaned up {collection_prefix}-* for user {user}")


def run_pair(db, collection_prefix, test_user, course, assignment):
    tag = f"[{course}/{assignment}]"
    nb_name = f"{assignment}.ipynb"
    student_nb = TEST_FILES_DIR / course / assignment / "student" / nb_name
    solution_nb = TEST_FILES_DIR / course / assignment / "solution" / nb_name

    if not student_nb.exists() or not solution_nb.exists():
        print(f"{tag} skip: notebook pair not present", flush=True)
        return True, []

    errors = []
    consumed_ids = set()

    for role, nb_path, expected_grade in [
        ("student", student_nb, 0.0),
        ("solution", solution_nb, 1.0),
    ]:
        print(f"{tag} submitting {role}", flush=True)
        # Each submission gets its own POLL_TIMEOUT budget — grading is
        # independent per notebook, so a slow student grade shouldn't
        # starve the solution.
        deadline = time.time() + POLL_TIMEOUT
        # Capture submit-time so we ignore any earlier-arriving grade docs
        # (defense against student's late grade being seen by solution poll).
        submit_ts = get_timestamp()
        try:
            submit_notebook(nb_path)
            grade, doc_ref = poll_for_grade(
                db, f"{collection_prefix}-grades", test_user, course, assignment, deadline,
                exclude_ids=consumed_ids, min_timestamp=submit_ts,
            )
            consumed_ids.add(doc_ref.id)
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
    test_user = f"TEST_USER_{run_id}"
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
                pool.submit(run_pair, db, collection_prefix, test_user, course, assignment): (course, assignment)
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
        cleanup(db, collection_prefix, test_user)

    if all_errors:
        print(f"\n{len(all_errors)} failure(s):")
        for e in all_errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print(f"\nAll {len(pairs)} notebook pair(s) graded correctly")


if __name__ == "__main__":
    main()
