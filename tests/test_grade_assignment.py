import pytest
import otter_service.grade_assignment as ga
import os
import shutil

KEY_FILE_PATH = "test_files/gh_key.yaml"


@pytest.fixture()
def configure():
    print("Starting tests")
    yield "resource"
    print("Removing Tree")
    if os.path.isdir("./materials-x22-private"):
        shutil.rmtree("./materials-x22-private")
    if os.path.isdir("./Data88e-online-dev"):
        shutil.rmtree("./Data88e-online-dev")
    if os.path.isfile("./final_grades.csv"):
        os.remove("./final_grades.csv")


def test_download_autograder_materials(configure):
    key_test = "tests/test_files/gh_key.yaml"
    sops_path = "sops"
    ga.download_autograder_materials("8x", sops_path, key_test)
    assert os.path.isdir("./materials-x22-private")


@pytest.mark.asyncio
@pytest.mark.skip(reason="need to update to otter-grader 6")
async def test_grade_assignment_8x(configure):
    secrets_file = os.path.join(os.path.dirname(__file__), KEY_FILE_PATH)
    args = {
        "course": "8x",
        "section": "1",
        "assignment": "lab01",
        "autograder_materials_repo": "github.com/data-8/materials-x22-private"
    }
    grade, _ = await ga.grade_assignment("tests/test_files/lab01.ipynb",
                                         args,
                                         sops_path="sops",
                                         secrets_file=secrets_file,
                                         save_path=".")
    assert 1.0 == grade


@pytest.mark.asyncio
async def test_grade_assignment_88e(configure):
    secrets_file = os.path.join(os.path.dirname(__file__), KEY_FILE_PATH)
    args = {
        "assignment": "lab01",
        "course": "88ex",
        "section": "1",
        "autograder_materials_repo": "github.com/data-88e/Data88e-online-dev"
    }
    grade, _ = await ga.grade_assignment("tests/test_files/lab01-88e.ipynb",
                                         args,
                                         sops_path="sops",
                                         secrets_file=secrets_file,
                                         save_path=".")
    assert 1.0 == grade
