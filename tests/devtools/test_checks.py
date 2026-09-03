from devtools.checks import run_checks
from devtools.models import AddedLine, ChangedFile, DiffSnapshot, Severity


def _snapshot(*files: ChangedFile) -> DiffSnapshot:
    return DiffSnapshot(base="HEAD", files=files)


def _changed_file(path: str, *lines: str) -> ChangedFile:
    return ChangedFile(
        path=path,
        status="M",
        added_lines=tuple(
            AddedLine(path=path, number=index, text=text)
            for index, text in enumerate(lines, start=1)
        ),
    )


def test_python_rules_report_project_violations():
    snapshot = _snapshot(
        _changed_file(
            "modules/demo/service.py",
            "today = date.today()",
            "now = datetime.now()",
            "except Exception as exc:",
            "print(exc)",
            'return templates.TemplateResponse("demo/page.html", {})',
        )
    )

    findings = run_checks(snapshot)

    assert {finding.code for finding in findings} == {
        "EXC001",
        "LOG001",
        "TPL001",
        "TZ001",
        "TZ002",
    }
    assert all(finding.severity is Severity.ERROR for finding in findings)


def test_exc001_allow_broad_except_marker_suppresses_only_generic_exception():
    snapshot = _snapshot(
        _changed_file(
            "modules/demo/service.py",
            "except Exception as exc:  # devtools: allow-broad-except",
            "except Exception as exc:",
            "except:",
        )
    )

    findings = run_checks(snapshot)

    assert [finding.line for finding in findings] == [2, 3]
    assert all(finding.code == "EXC001" for finding in findings)


def test_rules_do_not_scan_test_helpers_or_devtools():
    snapshot = _snapshot(
        _changed_file("tests/test_example.py", "print(date.today())"),
        _changed_file("devtools/cli.py", "print(date.today())"),
    )

    assert run_checks(snapshot) == ()


def test_frontend_rules_and_tailwind_action_are_reported_once():
    snapshot = _snapshot(
        _changed_file(
            "templates/demo/tabs.html",
            '<button :class="tab === \'uno\' ? \'active\' : \'inactive\'">',
            "const value = date.toISOString().slice(0, 10);",
            '<div class="grid gap-4">',
        )
    )

    findings = run_checks(snapshot)

    assert {finding.code for finding in findings} == {
        "HTMX001",
        "TAILWIND_BUILD",
        "TZ003",
    }
    tailwind = next(item for item in findings if item.code == "TAILWIND_BUILD")
    assert tailwind.command == "npm run build:css"


def test_sql_change_requests_agent_audit():
    snapshot = _snapshot(
        _changed_file(
            "modules/demo/db_service.py",
            'query = "SELECT id FROM tb_demo WHERE activo = $1"',
        )
    )

    findings = run_checks(snapshot)

    assert len(findings) == 1
    assert findings[0].code == "SQL_AUDIT"
    assert findings[0].severity is Severity.ACTION
    assert findings[0].command == "/auditar-sql diff"


def test_emoji_flagged_in_backend_and_templates():
    snapshot = _snapshot(
        _changed_file("modules/demo/service.py", 'mensaje = "Listo \U0001F600"'),
        _changed_file("templates/demo/page.html", "<span>Aprobado ✅</span>"),
        _changed_file("devtools/cli.py", 'mensaje = "\U0001F600"'),
    )

    findings = run_checks(snapshot)

    emoji_findings = [item for item in findings if item.code == "EMOJI001"]
    assert {item.path for item in emoji_findings} == {
        "modules/demo/service.py",
        "templates/demo/page.html",
    }
    assert all(item.severity is Severity.ERROR for item in emoji_findings)


def test_toast_container_typo_is_flagged_but_global_id_is_not():
    snapshot = _snapshot(
        _changed_file(
            "templates/demo/partial.html",
            '<div hx-swap-oob="afterbegin:#toast-container">',
        ),
        _changed_file(
            "templates/shared/toast.html",
            '<div hx-swap-oob="afterbegin:#global-toast-container">',
        ),
    )

    findings = run_checks(snapshot)

    htmx002 = [item for item in findings if item.code == "HTMX002"]
    assert len(htmx002) == 1
    assert htmx002[0].path == "templates/demo/partial.html"


def test_alpine_tojson_in_x_data_is_flagged():
    snapshot = _snapshot(
        _changed_file(
            "templates/demo/widget.html",
            "<div x-data=\"{{ payload | tojson }}\">",
        )
    )

    findings = run_checks(snapshot)

    assert {item.code for item in findings} == {"ALPINE001"}


def test_tojson_in_double_quoted_js_attr_is_flagged():
    snapshot = _snapshot(
        _changed_file(
            "templates/demo/boton.html",
            '<button @click="abrirModal({{ payload | tojson }})">Abrir</button>',
        )
    )

    findings = run_checks(snapshot)

    alpine002 = [item for item in findings if item.code == "ALPINE002"]
    assert len(alpine002) == 1
    assert alpine002[0].severity is Severity.ERROR


def test_tojson_in_single_quoted_js_attr_is_not_flagged():
    snapshot = _snapshot(
        _changed_file(
            "templates/demo/boton_ok.html",
            "<button @click='abrirModal({{ payload | tojson }})'>Abrir</button>",
        ),
        _changed_file(
            "templates/demo/data_attr_ok.html",
            "<div data-items='{{ items | tojson }}'>",
        ),
    )

    findings = run_checks(snapshot)

    assert [item for item in findings if item.code == "ALPINE002"] == []


def test_tojson_with_forceescape_in_double_quoted_attr_is_not_flagged():
    snapshot = _snapshot(
        _changed_file(
            "templates/demo/hidden_ok.html",
            '<input type="hidden" value="{{ payload | tojson | forceescape }}">',
        )
    )

    findings = run_checks(snapshot)

    assert [item for item in findings if item.code == "ALPINE002"] == []


def test_tojson_beyond_lookahead_window_in_double_quoted_attr_needs_root(tmp_path):
    """Igual que el caso analogo de HTMX003: sin `root`, la ventana fija (6
    lineas) no alcanza a ver un `| tojson` que aparece mas lejos dentro del
    mismo atributo multilinea -- falso negativo. Con `root`, el escaneo de
    archivo completo balanceando comillas lo encuentra sin importar cuantas
    lineas tenga el atributo en medio."""
    relative_path = "templates/demo/tojson_lejano.html"
    lines = (
        '<button @click="abrirModal(',
        "    1,",
        "    2,",
        "    3,",
        "    4,",
        "    5,",
        "    6,",
        "    {{ payload | tojson }}",
        ')">Abrir</button>',
    )
    file_path = tmp_path / relative_path
    file_path.parent.mkdir(parents=True)
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    snapshot = _snapshot(_changed_file(relative_path, lines[0]))

    findings_without_root = run_checks(snapshot)
    findings_with_root = run_checks(snapshot, tmp_path)

    assert [item for item in findings_without_root if item.code == "ALPINE002"] == []
    alpine002 = [item for item in findings_with_root if item.code == "ALPINE002"]
    assert len(alpine002) == 1
    assert alpine002[0].line == 1


def test_rbac_double_depends_is_flagged():
    snapshot = _snapshot(
        _changed_file(
            "modules/demo/router.py",
            'dependencies=[Depends(require_module_access("demo", 2))]',
        )
    )

    findings = run_checks(snapshot)

    assert {item.code for item in findings} == {"RBAC001"}


def test_sql_fstring_in_db_service_is_flagged_as_warning():
    snapshot = _snapshot(
        _changed_file(
            "modules/demo/db_service.py",
            'query = f"SELECT id FROM tb_demo WHERE codigo = {codigo}"',
        )
    )

    findings = run_checks(snapshot)

    sql002 = [item for item in findings if item.code == "SQL002"]
    assert len(sql002) == 1
    assert sql002[0].severity is Severity.WARNING


def test_extract_dow_without_conversion_is_flagged():
    snapshot = _snapshot(
        _changed_file(
            "modules/demo/db_service.py",
            "SELECT * FROM tb_demo WHERE EXTRACT(DOW FROM fecha) = 1",
        ),
        _changed_file(
            "migrations/999_demo.sql",
            "WHERE ((EXTRACT(DOW FROM fecha)::int + 6) % 7) = dia_semana",
        ),
    )

    findings = run_checks(snapshot)

    tz004 = [item for item in findings if item.code == "TZ004"]
    assert len(tz004) == 1
    assert tz004[0].path == "modules/demo/db_service.py"


def test_global_transition_selector_is_flagged_but_scoped_is_not():
    snapshot = _snapshot(
        _changed_file(
            "static/css/input.css",
            "* { transition: all 0.3s ease; }",
            ".card * { transition: opacity 0.2s; }",
            "a, button { transition: color 0.2s; }",
        ),
        _changed_file(
            "static/css/tailwind.css",
            "*,::before,::after{transition:none}",
        ),
    )

    findings = run_checks(snapshot)

    css001 = [item for item in findings if item.code == "CSS001"]
    assert len(css001) == 1
    assert css001[0].path == "static/css/input.css"
    assert css001[0].line == 1
    assert css001[0].severity is Severity.ERROR


def test_modal_overlay_without_stacking_layer_is_flagged():
    snapshot = _snapshot(
        _changed_file(
            "templates/demo/modal.html",
            '<div class="fixed inset-0 bg-black bg-opacity-50">',
        ),
        _changed_file(
            "templates/demo/modal_ok.html",
            '<div class="fixed inset-0 bg-black bg-opacity-50 modal-overlay-layer">',
        ),
    )

    findings = run_checks(snapshot)

    ui001 = [item for item in findings if item.code == "UI001"]
    assert len(ui001) == 1
    assert ui001[0].path == "templates/demo/modal.html"
    assert ui001[0].severity is Severity.WARNING


def test_htmx_ajax_missing_source_is_flagged_same_line_and_multiline():
    snapshot = _snapshot(
        _changed_file(
            "templates/demo/sin_source.html",
            "htmx.ajax('GET', url, {target: '#x', swap: 'innerHTML'});",
        ),
        _changed_file(
            "templates/demo/sin_source_multilinea.html",
            "htmx.ajax('GET', url, {",
            "    target: '#report-content',",
            "    swap: 'innerHTML'",
            "});",
        ),
    )

    findings = run_checks(snapshot)

    htmx003 = [item for item in findings if item.code == "HTMX003"]
    assert {item.path for item in htmx003} == {
        "templates/demo/sin_source.html",
        "templates/demo/sin_source_multilinea.html",
    }
    assert all(item.severity is Severity.WARNING for item in htmx003)


def test_htmx_ajax_with_source_same_line_or_multiline_is_not_flagged():
    snapshot = _snapshot(
        _changed_file(
            "templates/demo/con_source.html",
            "htmx.ajax('GET', url, {target: '#x', source: '#x', swap: 'innerHTML'});",
        ),
        _changed_file(
            "templates/demo/con_source_multilinea.html",
            "htmx.ajax('GET', url, {",
            "    target: '#report-content',",
            "    source: '#report-content',",
            "    swap: 'innerHTML'",
            "});",
        ),
        _changed_file(
            "templates/demo/con_source_el.html",
            '@change="htmx.ajax(\'PATCH\', url, { source: $el, swap: \'none\' })"',
        ),
    )

    findings = run_checks(snapshot)

    assert [item for item in findings if item.code == "HTMX003"] == []


def test_htmx_ajax_source_beyond_lookahead_window_needs_root_to_not_false_positive(tmp_path):
    """Sin `root`, el heuristico de ventana fija (6 lineas) no ve un 'source'
    que aparece mas lejos dentro de la misma llamada -- falso positivo. Con
    `root`, el escaneo de archivo completo balanceando parentesis lo encuentra
    sin importar cuantas lineas tenga el objeto de values en medio."""
    relative_path = "templates/demo/source_lejano.html"
    lines = (
        "htmx.ajax('POST', url, {",
        "    target: '#x',",
        "    values: {",
        "        a: 1,",
        "        b: 2,",
        "        c: 3,",
        "        d: 4,",
        "    },",
        "    swap: 'innerHTML',",
        "    source: '#x'",
        "});",
    )
    file_path = tmp_path / relative_path
    file_path.parent.mkdir(parents=True)
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    snapshot = _snapshot(_changed_file(relative_path, *lines))

    findings_without_root = run_checks(snapshot)
    findings_with_root = run_checks(snapshot, tmp_path)

    assert [item for item in findings_without_root if item.code == "HTMX003"] != []
    assert [item for item in findings_with_root if item.code == "HTMX003"] == []


def test_htmx_ajax_source_untouched_by_diff_is_not_false_flagged_with_root(tmp_path):
    """--unified=0 no trae lineas de contexto: si solo la linea de apertura de
    htmx.ajax(...) se toco en el diff pero 'source' ya existia en una linea
    sin tocar, el heuristico basado solo en added_lines no puede verla. Con
    `root` disponible, el escaneo lee el archivo real y no genera falso
    positivo."""
    relative_path = "templates/demo/source_sin_tocar.html"
    file_path = tmp_path / relative_path
    file_path.parent.mkdir(parents=True)
    file_path.write_text(
        "htmx.ajax('POST', url, {\n"
        "    source: '#x',\n"
        "    swap: 'innerHTML'\n"
        "});\n",
        encoding="utf-8",
    )
    snapshot = _snapshot(
        _changed_file(relative_path, "htmx.ajax('POST', url, {")
    )

    findings_with_root = run_checks(snapshot, tmp_path)

    assert [item for item in findings_with_root if item.code == "HTMX003"] == []
