from pathlib import Path

from devtools.models import ChangedFile
from devtools.quality import select_targeted_tests


def test_select_targeted_tests_includes_changed_tests(tmp_path: Path):
    test_file = tmp_path / "tests" / "test_demo.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_demo(): pass\n", encoding="utf-8")
    (test_file.parent / "conftest.py").write_text("", encoding="utf-8")
    (test_file.parent / "__init__.py").write_text("", encoding="utf-8")

    selected = select_targeted_tests(
        tmp_path,
        [
            ChangedFile(path="tests/test_demo.py", status="M"),
            ChangedFile(path="tests/conftest.py", status="M"),
            ChangedFile(path="tests/__init__.py", status="M"),
        ],
    )

    assert selected == ("tests/test_demo.py",)


def test_select_targeted_tests_maps_module_name(tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_vacaciones_logic.py").write_text("", encoding="utf-8")
    (tests_dir / "test_other.py").write_text("", encoding="utf-8")

    selected = select_targeted_tests(
        tmp_path,
        [ChangedFile(path="modules/vacaciones/service.py", status="M")],
    )

    assert selected == ("tests/test_vacaciones_logic.py",)
