"""Small dependency-free, write-only XLSX exporter for scientific data."""

import math
import re
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


MAX_EXCEL_ROWS = 1_048_576


def write_xlsx(path, sheets):
    """Write ``[(sheet_name, rows_iterable), ...]`` without keeping rows in memory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _unique_sheet_names([name for name, _rows in sheets])
    with tempfile.TemporaryDirectory(prefix="iface_xlsx_", dir=path.parent) as temp:
        temp_dir = Path(temp)
        sheet_files = []
        for index, ((_name, rows), safe_name) in enumerate(zip(sheets, normalized), 1):
            sheet_path = temp_dir / f"sheet{index}.xml"
            _write_sheet_xml(sheet_path, rows)
            sheet_files.append((safe_name, sheet_path))
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", _content_types(len(sheet_files)))
            archive.writestr("_rels/.rels", _root_relationships())
            archive.writestr("xl/workbook.xml", _workbook_xml(sheet_files))
            archive.writestr("xl/_rels/workbook.xml.rels", _workbook_relationships(len(sheet_files)))
            archive.writestr("xl/styles.xml", _styles_xml())
            for index, (_name, sheet_path) in enumerate(sheet_files, 1):
                archive.write(sheet_path, f"xl/worksheets/sheet{index}.xml")
    return path


def _write_sheet_xml(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        handle.write(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
            'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            '<sheetFormatPr defaultRowHeight="15"/><sheetData>'
        )
        for row_index, row in enumerate(rows, 1):
            if row_index > MAX_EXCEL_ROWS:
                raise ValueError('A worksheet exceeds the Excel limit of 1,048,576 rows.')
            handle.write(f'<row r="{row_index}">')
            for column_index, value in enumerate(row, 1):
                if value is None:
                    continue
                reference = f"{_column_name(column_index)}{row_index}"
                style = ' s="1"' if row_index == 1 else ""
                if isinstance(value, bool):
                    handle.write(f'<c r="{reference}" t="b"{style}><v>{int(value)}</v></c>')
                elif isinstance(value, (int, float)) and math.isfinite(float(value)):
                    handle.write(f'<c r="{reference}"{style}><v>{value}</v></c>')
                else:
                    text = escape(str(value))
                    handle.write(
                        f'<c r="{reference}" t="inlineStr"{style}><is><t>{text}</t></is></c>'
                    )
            handle.write("</row>")
        handle.write("</sheetData><autoFilter ref=\"A1:XFD1\"/></worksheet>")


def _column_name(number):
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _unique_sheet_names(names):
    used = set()
    output = []
    for raw in names:
        base = re.sub(r"[\[\]:*?/\\]", "_", str(raw or "Sheet")).strip()[:31] or "Sheet"
        candidate = base
        suffix = 2
        while candidate.lower() in used:
            tail = f"_{suffix}"
            candidate = base[: 31 - len(tail)] + tail
            suffix += 1
        used.add(candidate.lower())
        output.append(candidate)
    return output


def _content_types(sheet_count):
    sheets = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{sheets}</Types>"
    )


def _root_relationships():
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )


def _workbook_xml(sheet_files):
    sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, (name, _path) in enumerate(sheet_files, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets></workbook>"
    )


def _workbook_relationships(sheet_count):
    relationships = "".join(
        f'<Relationship Id="rId{index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    )
    style_id = sheet_count + 1
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{relationships}<Relationship Id=\"rId{style_id}\" "
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/></Relationships>'
    )


def _styles_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="10"/><name val="Arial"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Arial"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF2563EB"/>'
        '<bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" '
        'applyFont="1" applyFill="1"/></cellXfs></styleSheet>'
    )
