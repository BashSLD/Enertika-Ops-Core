from devtools.git_diff import parse_unified_diff


def test_parse_unified_diff_extracts_only_added_lines():
    diff = """diff --git a/core/example.py b/core/example.py
--- a/core/example.py
+++ b/core/example.py
@@ -10,2 +10,3 @@
-old_value = 1
+new_value = 2
+other_value = 3
 context = True
"""

    result = parse_unified_diff(diff)

    assert [line.number for line in result["core/example.py"]] == [10, 11]
    assert [line.text for line in result["core/example.py"]] == [
        "new_value = 2",
        "other_value = 3",
    ]


def test_parse_unified_diff_ignores_deleted_file():
    diff = """diff --git a/core/old.py b/core/old.py
--- a/core/old.py
+++ /dev/null
@@ -1 +0,0 @@
-print('old')
"""

    assert parse_unified_diff(diff) == {}


def test_parse_unified_diff_accepts_added_content_starting_with_plus_signs():
    diff = """diff --git a/static/app.js b/static/app.js
--- a/static/app.js
+++ b/static/app.js
@@ -1,0 +2 @@
+++ counter
"""

    result = parse_unified_diff(diff)

    assert result["static/app.js"][0].text == "++ counter"
    assert result["static/app.js"][0].number == 2
