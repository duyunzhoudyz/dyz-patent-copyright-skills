"""受控五文书的本地PDF取证；真实目录包须单独授权，不在worker中运行。

Office仅读取隔离副本；包成员、工具和权限在实际边界重新核验。
文字、几何、逐页PNG和实际页面观察分别记账，不代替专业审阅。
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import ctypes
import io
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import signal
import stat
import struct
import subprocess
import tempfile
import uuid
from xml.etree import ElementTree as ET
import zipfile
import zlib

from tools import documents, omml, standards_delivery
from tools.core import (
    ContractError, canonical_bytes, check_permission, digest, is_macos_system_root_symlink,
    is_reserved_windows_name, preflight, require, sha256_bytes, strict_json_loads,
)

VERSION = '1.5'
MAX_PACKAGE_BYTES = 100_000_000
MAX_FILE_BYTES = 20_000_000
MAX_MANIFEST_BYTES = 1_000_000
MAX_TEXT_BYTES = 5_000_000
MAX_IMAGE_BYTES = 12_000_000
MAX_OUTPUT_BYTES = 300_000_000
MAX_PAGES_PER_DOCUMENT = 50
MAX_TOTAL_PAGES = 150
COMMAND_TIMEOUT = 60
RENDER_TIMEOUT = 30
RENDER_SIZE = 1600
TOOL_NAMES = {
    'soffice': {'soffice', 'soffice.exe', 'soffice.com'},
    'pdfinfo': {'pdfinfo', 'pdfinfo.exe'},
    'pdftotext': {'pdftotext', 'pdftotext.exe'},
    'pdftoppm': {'pdftoppm', 'pdftoppm.exe'},
}
OPTIONAL_TOOL_NAMES = {'office_python': {'python', 'python.exe'}}
_PACKAGE_FILES = {
    'manifest.json', 'internal/input.json', 'internal/source-map.json',
    'internal/checks.json', 'internal/realizations.json',
    'internal/reference-list.json', 'internal/projection-coverage.json',
    'internal/source-trace.json',
    *(f'body/{role}.docx' for role in standards_delivery.ROLES),
}
_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
_OMML_ROOTS = {'{' + omml.M + '}oMath', '{' + omml.M + '}oMathPara'}


def _plain(path: Path, *, missing=False):
    """逐个检查词法祖先，不能resolve后丢失链接/Windows重解析点证据。"""
    for current in (*reversed(path.parents), path):
        try:
            info = current.lstat()
        except FileNotFoundError:
            require(missing and current == path, 'standard_pdf_path_missing')
            return None
        is_link = stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)
        if is_link:
            if current != path and is_macos_system_root_symlink(current):
                try:
                    info = current.stat()
                except OSError:
                    raise ContractError('standard_pdf_link_unsupported') from None
            else:
                require(False, 'standard_pdf_link_unsupported')
        if current != path:
            require(stat.S_ISDIR(info.st_mode), 'standard_pdf_parent_not_directory')
    require(not stat.S_ISREG(info.st_mode) or info.st_nlink == 1,
            'standard_pdf_alias_unsupported')
    return info


def _root(root):
    raw = Path(root)
    require('..' not in raw.parts, 'standard_pdf_root_unsafe')
    path = raw.absolute()
    require(stat.S_ISDIR(_plain(path).st_mode), 'standard_pdf_root_required')
    return path


def _path(root: Path, relative: str, *, missing=False):
    require(isinstance(relative, str) and bool(relative), 'relative_path_required')
    parts = relative.replace('\\', '/').split('/')
    require(not PureWindowsPath(relative).drive
            and not relative.startswith(('/', '\\'))
            and all(part not in {'', '.', '..'} and part == part.rstrip(' .')
                    and not is_reserved_windows_name(part) for part in parts)
            and not any(c in relative for c in ':\x00'), 'unsafe_path')
    path = root.joinpath(*parts)
    _plain(path, missing=missing)
    return path


def _read_file(path: Path, limit: int):
    before = _plain(path)
    require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit,
            'standard_pdf_file_size_or_type')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                and opened.st_nlink == 1, 'standard_pdf_file_changed')
        raw = stream.read(limit + 1)
    after = _plain(path)
    require(len(raw) == before.st_size
            and (before.st_dev, before.st_ino, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_mtime_ns),
            'standard_pdf_file_changed')
    return raw


def _tree(package: Path, expected=None):
    require(stat.S_ISDIR(_plain(package).st_mode), 'standard_pdf_package_required')
    found, folders, pending, total = set(), set(), [package], 0
    while pending:
        folder = pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = _plain(path)
                relative = path.relative_to(package).as_posix()
                if stat.S_ISDIR(info.st_mode):
                    require(relative.split('/')[0] in {'body', 'internal'},
                            'standard_pdf_package_members_changed')
                    folders.add(relative)
                    pending.append(path)
                else:
                    require(stat.S_ISREG(info.st_mode)
                            and (relative == 'manifest.json'
                                 or relative.split('/')[0] in {'body', 'internal'}),
                            'standard_pdf_package_members_changed')
                    limit = (MAX_MANIFEST_BYTES if relative == 'manifest.json'
                             else standards_delivery.MAX_INPUT_BYTES
                             if relative == 'internal/input.json' else MAX_FILE_BYTES)
                    require(0 < info.st_size <= limit, 'standard_pdf_file_size_or_type')
                    total += info.st_size
                    require(total <= MAX_PACKAGE_BYTES, 'standard_pdf_package_too_large')
                    found.add(relative)
    require(_PACKAGE_FILES <= found if expected is None else found == set(expected),
            'standard_pdf_package_members_changed')
    if expected is not None:
        allowed_folders = {parent.as_posix() for name in expected
                           for parent in Path(name).parents if parent != Path('.')}
        require(folders == allowed_folders, 'standard_pdf_package_members_changed')
    return found


def _json(raw):
    try:
        value = strict_json_loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise ContractError('standard_pdf_json_invalid') from exc
    require(isinstance(value, dict), 'standard_pdf_json_object_required')
    return value


class _Access:
    """本地控制器的逐边界核验；不宣称能隔离恶意本机并发进程。"""

    def __init__(self, base, package, output, *, synthetic, admission):
        self.base, self.relative, self.output = base, package, output
        self.synthetic, self.admission = synthetic, admission
        self.package = None
        self.members, self.identities, self.source_inputs = {}, {}, {}
        self.policy_hash = None
        if synthetic:
            require(admission is None, 'standard_pdf_mode_ambiguous')
            self.sensitivity, self.purpose = 'synthetic', None
        else:
            project = Path(__file__).absolute().parents[1]
            require(not (base == project or base.is_relative_to(project)
                         or project.is_relative_to(base)),
                    'standard_pdf_case_root_must_be_independent')
            fields = {'root', 'package', 'output', 'manifest_sha256', 'inputs',
                      'sensitivity', 'purpose', 'permissions', 'environment'}
            require(isinstance(admission, dict) and fields <= set(admission)
                    <= fields | {'source_inputs'}, 'standard_pdf_admission_fields')
            require(isinstance(admission['root'], str), 'standard_pdf_admission_root')
            declared = Path(admission['root'])
            require(declared.is_absolute() and '..' not in declared.parts
                    and declared == base, 'standard_pdf_admission_root')
            _plain(declared)
            require(admission['package'] == package and admission['output'] == output,
                    'standard_pdf_admission_binding_changed')
            require(admission['sensitivity'] in {'public', 'confidential', 'restricted'},
                    'standard_pdf_admission_sensitivity')
            require(isinstance(admission['purpose'], str) and admission['purpose'].strip()
                    and isinstance(admission['environment'], dict),
                    'standard_pdf_admission_context')
            members = admission['inputs']
            require(isinstance(members, dict) and _PACKAGE_FILES <= set(members)
                    and len(members) <= 500
                    and all(isinstance(key, str) and isinstance(value, str)
                            and re.fullmatch('[0-9a-f]{64}', value)
                            for key, value in members.items())
                    and members['manifest.json'] == admission['manifest_sha256'],
                    'standard_pdf_admission_inputs')
            sources = admission.get('source_inputs', {})
            require(isinstance(sources, dict) and len(sources) <= 500
                    and all(isinstance(key, str) and isinstance(value, str)
                            and re.fullmatch('[0-9a-f]{64}', value)
                            for key, value in sources.items()),
                    'standard_pdf_source_inputs')
            self.source_inputs = dict(sources)
            self.sensitivity, self.purpose = admission['sensitivity'], admission['purpose']
            self.policy_hash = digest(admission)
        self.pin(base)
        # 准入时先证实整个计划有权进行；各步骤仍使用当时的UTC重新核验。
        self.authorize('local_read', 'local_process', 'copy', 'local_write')
        if not synthetic:
            package_path = _path(base, package)
            output_path = _path(base, output, missing=True)
            total = 0
            for name, expected in self.source_inputs.items():
                path = _path(base, name)
                require(name == path.relative_to(base).as_posix(),
                        'standard_pdf_source_input_path')
                require(not path.is_relative_to(package_path)
                        and not package_path.is_relative_to(path)
                        and not path.is_relative_to(output_path)
                        and not output_path.is_relative_to(path),
                        'standard_pdf_source_input_overlaps_package_or_output')
                self.authorize('local_read')
                raw = _read_file(path, MAX_FILE_BYTES)
                require(sha256_bytes(raw) == expected, 'standard_pdf_source_input_changed')
                total += len(raw)
                require(total <= MAX_PACKAGE_BYTES, 'standard_pdf_source_inputs_too_large')
                self.pin(path)

    def authorize(self, *actions):
        if self.synthetic:
            return
        context = self.admission
        now = datetime.now(timezone.utc).isoformat()
        preflight(context['environment'], context['permissions'], sensitivity='restricted',
                  purpose=self.purpose, now=now)
        for action in actions:
            check_permission(context['permissions'], action=action, purpose=self.purpose,
                             recipient='local_tool', now=now)
        require(digest(context) == self.policy_hash, 'standard_pdf_admission_changed')

    @staticmethod
    def identity(path):
        info = _plain(path)
        value = (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))
        if stat.S_ISREG(info.st_mode):
            value += (info.st_size, info.st_mtime_ns)
        return value

    def pin(self, path):
        for current in (*reversed(path.parents), path):
            value = self.identity(current)
            require(current not in self.identities or self.identities[current] == value,
                    'standard_pdf_path_changed')
            self.identities[current] = value

    def check(self, *actions, members=True):
        self.authorize(*actions)
        if self.synthetic:
            return
        for path, identity in self.identities.items():
            require(self.identity(path) == identity,
                    'standard_pdf_input_changed' if self.package is not None
                    and path.is_relative_to(self.package) else 'standard_pdf_path_changed')
        for name, expected in self.source_inputs.items():
            self.authorize('local_read')
            raw = _read_file(_path(self.base, name), MAX_FILE_BYTES)
            require(sha256_bytes(raw) == expected, 'standard_pdf_source_input_changed')
        if members and self.package is not None:
            _tree(self.package, self.members)
            for name, expected in self.members.items():
                self.authorize('local_read')
                raw = _read_file(_path(self.package, name), self.limit(name))
                require(sha256_bytes(raw) == expected, 'standard_pdf_input_changed')

    @staticmethod
    def limit(name):
        return (MAX_MANIFEST_BYTES if name == 'manifest.json' else
                standards_delivery.MAX_INPUT_BYTES if name == 'internal/input.json'
                else MAX_FILE_BYTES)

    def read(self, path, limit):
        self.authorize('local_read')
        for ancestor in (*reversed(path.parents), path):
            if ancestor in self.identities:
                require(self.identity(ancestor) == self.identities[ancestor],
                        'standard_pdf_input_changed' if self.package is not None
                        and ancestor.is_relative_to(self.package) else 'standard_pdf_path_changed')
        raw = _read_file(path, limit)
        self.pin(path)
        if self.package is not None and path.is_relative_to(self.package):
            require(sha256_bytes(raw) == self.members[path.relative_to(self.package).as_posix()],
                    'standard_pdf_input_changed')
        if path.is_relative_to(self.base):
            source_hash = self.source_inputs.get(path.relative_to(self.base).as_posix())
            if source_hash is not None:
                require(sha256_bytes(raw) == source_hash, 'standard_pdf_source_input_changed')
        return raw

    def bind(self, package, members):
        self.package, self.members = package, dict(members)
        self.pin(package)
        for name in members:
            self.pin(_path(package, name))
        self.check('local_read')

    def mkdir(self, path):
        self.check('local_write')
        require(_plain(path, missing=True) is None, 'output_exists')
        path.mkdir()
        self.pin(path)

    def write(self, path, raw, *, copying=False):
        self.check('local_write', *(('copy',) if copying else ()))
        require(_plain(path, missing=True) is None, 'output_exists')
        with path.open('xb') as stream:
            stream.write(raw)
        self.pin(path)

    def run(self, arguments, *, timeout=COMMAND_TIMEOUT):
        self.check('local_process', 'copy', 'local_write')
        # 命令只接受已固定的本机工具，输出参数仍由调用点的词法路径控制。
        self.pin(Path(arguments[0]))
        result = _run(arguments, timeout=timeout)
        self.check('local_read')
        return result

    def verify_source_inputs(self, payload):
        if self.synthetic:
            return
        reports = payload.get('source_reports', [])
        require(isinstance(reports, list), 'standard_pdf_source_reports')
        for descriptor in reports:
            require(isinstance(descriptor, dict)
                    and isinstance(descriptor.get('path'), str)
                    and isinstance(descriptor.get('sha256'), str),
                    'standard_pdf_source_report_descriptor')
            path, expected = descriptor['path'], descriptor['sha256']
            require(self.source_inputs.get(path) == expected,
                    'standard_pdf_source_input_not_admitted')
            raw = self.read(_path(self.base, path), MAX_FILE_BYTES)
            try:
                report = strict_json_loads(raw.decode('utf-8-sig'))
            except (UnicodeError, ValueError) as exc:
                raise ContractError('standard_pdf_source_report_invalid') from exc
            require(isinstance(report, dict), 'standard_pdf_source_report_invalid')
            original, original_hash = report.get('path'), report.get('original_sha256')
            require(isinstance(original, str) and isinstance(original_hash, str)
                    and self.source_inputs.get(original) == original_hash,
                    'standard_pdf_source_input_not_admitted')
        self.check('local_read')

    def delivery_admission(self, payload):
        if self.synthetic:
            return None
        self.check('local_read', 'local_process', 'copy')
        # delivery按案例根读取来源；只重定位已授权包成员，包外原件必须显式列入。
        inputs = {(self.package / name).relative_to(self.base).as_posix(): expected
                  for name, expected in self.members.items()}
        inputs.update(self.source_inputs)
        return {**{key: value for key, value in self.admission.items()
                   if key not in {'inputs', 'source_inputs'}},
                'output': self.relative, 'payload_hash': digest(payload), 'inputs': inputs}


def _package(root, relative, access):
    package = _path(root, relative)
    found = _tree(package)
    if not access.synthetic:
        require(found == set(access.admission['inputs']), 'standard_pdf_admission_inputs')
    manifest_raw = access.read(package / 'manifest.json', MAX_MANIFEST_BYTES)
    if not access.synthetic:
        require(sha256_bytes(manifest_raw) == access.admission['manifest_sha256'],
                'standard_pdf_input_changed')
    manifest = _json(manifest_raw)
    require(manifest.get('mode') == ('synthetic' if access.synthetic else 'authorized_case')
            and manifest.get('generator') == 'dyz-standards-delivery'
            and manifest.get('generator_version') == standards_delivery.VERSION
            and type(manifest.get('contract_version')) is int
            and manifest['contract_version'] == 2,
            'standard_pdf_package_not_synthetic_current' if access.synthetic else
            'standard_pdf_package_not_authorized_current')
    entries = manifest.get('files')
    require(isinstance(entries, list) and len(entries) <= 499
            and all(isinstance(row, dict) and isinstance(row.get('path'), str)
                    and re.fullmatch('[0-9a-f]{64}', str(row.get('sha256', '')))
                    for row in entries), 'standard_pdf_package_manifest_invalid')
    hashes = {row['path']: row['sha256'] for row in entries}
    require(len(hashes) == len(entries) and 'manifest.json' not in hashes,
            'standard_pdf_package_manifest_invalid')
    hashes['manifest.json'] = sha256_bytes(manifest_raw)
    _tree(package, hashes)
    if not access.synthetic:
        require(hashes == access.admission['inputs'], 'standard_pdf_admission_inputs')
    access.bind(package, hashes)
    payload = _json(access.read(package / 'internal/input.json',
                                standards_delivery.MAX_INPUT_BYTES))
    require(payload.get('sensitivity') == access.sensitivity,
            'standard_pdf_synthetic_required' if access.synthetic else
            'standard_pdf_input_sensitivity_changed')
    access.verify_source_inputs(payload)
    access.check('local_read', 'local_process', 'copy')
    checked = standards_delivery.verify(root, payload, relative, synthetic=access.synthetic,
                                        admission=access.delivery_admission(payload))
    require(checked.get('file_hashes_equal') is True
            and checked.get('manifest_sha256') == sha256_bytes(manifest_raw),
            'standard_pdf_package_unverified')
    access.check('local_read')
    inputs = {role: access.read(package / f'body/{role}.docx', MAX_FILE_BYTES)
              for role in standards_delivery.ROLES}
    source_map = _json(access.read(package / 'internal/source-map.json', MAX_FILE_BYTES))
    return package, checked, payload, inputs, source_map


def _tools(tool_paths, access):
    require(isinstance(tool_paths, dict) and set(TOOL_NAMES) <= set(tool_paths)
            <= set(TOOL_NAMES) | set(OPTIONAL_TOOL_NAMES),
            'standard_pdf_tool_paths_required')
    paths, evidence = {}, {}
    allowed = {**TOOL_NAMES, **OPTIONAL_TOOL_NAMES}
    for key in tool_paths:
        names = allowed[key]
        path = Path(tool_paths[key])
        require(path.is_absolute() and '..' not in path.parts
                and path.name.lower() in names, 'standard_pdf_tool_invalid')
        raw = access.read(path, 200_000_000)
        paths[key] = path
        evidence[key] = {'name': path.name, 'sha256': sha256_bytes(raw)}
    if 'office_python' in paths:
        require(paths['office_python'].parent == paths['soffice'].parent,
                'standard_pdf_office_python_installation_mismatch')
    return paths, evidence


# 在已绑定专属Job的随附Python进程内启动Office；后代自动继承同一Job。
# 不导入项目业务模块、不执行宏、不接TCP，临时脚本及管道仅活到本次转换结束。
_UNO_SCRIPT = r'''from pathlib import Path
import json
import subprocess
import sys
import time
import uno
from com.sun.star.beans import PropertyValue
from com.sun.star.connection import NoConnectException
from com.sun.star.document.MacroExecMode import NEVER_EXECUTE
from com.sun.star.document.UpdateDocMode import NO_UPDATE


def prop(name, value):
    result = PropertyValue()
    result.Name, result.Value = name, value
    return result


config = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))


def restore_layout(document, phase):
    policy = config.get('layout_policy')
    if policy is None:
        return None
    counts, seen = {}, []

    def apply(properties, scope):
        row = counts.setdefault(scope, {'objects': 0, 'properties': {}})
        row['objects'] += 1
        for name, expected in policy['uno_properties'].items():
            before = properties.getPropertyValue(name)
            properties.setPropertyValue(name, expected)
            after = properties.getPropertyValue(name)
            if after != expected:
                raise RuntimeError('standard_pdf_uno_layout_not_applied')
            values = row['properties'].setdefault(name, {
                'before_true': 0, 'before_false': 0, 'after_false': 0})
            values['before_true' if before else 'before_false'] += 1
            values['after_false'] += 1

    def visit(text, scope):
        if any(text == previous for previous in seen):
            return
        seen.append(text)
        enumeration = text.createEnumeration()
        while enumeration.hasMoreElements():
            item = enumeration.nextElement()
            if item.supportsService('com.sun.star.text.TextTable'):
                for cell in item.getCellNames():
                    visit(item.getCellByName(cell), 'table_cell_paragraphs')
            elif item.supportsService('com.sun.star.text.Paragraph'):
                apply(item, scope)

    # v2源的显式false会被此Office导入为true；实际段落及其生成域样式都需恢复。
    visit(document.getText(), 'body_paragraphs')
    families = document.getStyleFamilies()
    page_styles = families.getByName('PageStyles')
    for name in page_styles.getElementNames():
        style = page_styles.getByName(name)
        if not style.isInUse():
            continue
        info = style.getPropertySetInfo()
        for kind in ('Header', 'Footer'):
            if not style.getPropertyValue(kind + 'IsOn'):
                continue
            for suffix in ('Text', 'TextFirst', 'TextLeft', 'TextRight'):
                key = kind + suffix
                if info.hasPropertyByName(key):
                    visit(style.getPropertyValue(key), 'active_' + kind.lower() + '_paragraphs')
    styles = families.getByName('ParagraphStyles')
    for name in styles.getElementNames():
        apply(styles.getByName(name), 'paragraph_styles')
    return {'phase': phase, 'scopes': counts}


def refresh_fields(document):
    previous = None
    for attempt in range(3):
        document.refresh()
        fields = document.getTextFields()
        fields.refresh()
        indexes = document.getDocumentIndexes()
        for index in range(indexes.getCount()):
            indexes.getByIndex(index).update()
        enumeration, state = fields.createEnumeration(), []
        while enumeration.hasMoreElements():
            state.append(enumeration.nextElement().getPresentation(False))
        state.extend(indexes.getByIndex(index).getAnchor().getString()
                     for index in range(indexes.getCount()))
        if state == previous:
            return
        previous = state
    raise RuntimeError('standard_pdf_uno_fields_unstable')


process = desktop = document = None
try:
    process = subprocess.Popen([
        config['soffice'], '-env:UserInstallation=' + config['profile'],
        '--headless', '--nologo', '--nodefault', '--norestore',
        '--accept=pipe,name=' + config['pipe'] + ';urp;StarOffice.ServiceManager',
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    context = uno.getComponentContext()
    resolver = context.ServiceManager.createInstanceWithContext(
        'com.sun.star.bridge.UnoUrlResolver', context)
    deadline = time.monotonic() + 15
    while True:
        try:
            remote = resolver.resolve('uno:pipe,name=' + config['pipe']
                                      + ';urp;StarOffice.ComponentContext')
            break
        except NoConnectException:
            if time.monotonic() >= deadline or process.poll() is not None:
                raise RuntimeError('standard_pdf_uno_connection_failed')
            time.sleep(0.1)
    desktop = remote.ServiceManager.createInstanceWithContext(
        'com.sun.star.frame.Desktop', remote)
    for source in config['inputs']:
        document = desktop.loadComponentFromURL(Path(source).as_uri(), '_blank', 0, (
            prop('Hidden', True), prop('ReadOnly', False),
            prop('MacroExecutionMode', NEVER_EXECUTE), prop('UpdateDocMode', NO_UPDATE)))
        if document is None:
            raise RuntimeError('standard_pdf_uno_load_failed')
        evidence = [restore_layout(document, 'source_import_before_refresh')]
        refresh_fields(document)
        target = Path(config['output']) / Path(source).name
        document.storeAsURL(target.as_uri(), (
            prop('FilterName', 'Office Open XML Text'), prop('Overwrite', False)))
        document.close(True)
        document = None
        if config.get('layout_policy') is not None:
            document = desktop.loadComponentFromURL(target.as_uri(), '_blank', 0, (
                prop('Hidden', True), prop('ReadOnly', False),
                prop('MacroExecutionMode', NEVER_EXECUTE), prop('UpdateDocMode', NO_UPDATE)))
            if document is None:
                raise RuntimeError('standard_pdf_uno_reload_failed')
            evidence.append(restore_layout(document, 'stored_docx_reopen_before_refresh'))
            refresh_fields(document)
            document.store()
            pdf = Path(config['pdf_output']) / target.with_suffix('.pdf').name
            document.storeToURL(pdf.as_uri(), (
                prop('FilterName', 'writer_pdf_Export'), prop('Overwrite', False),
                prop('FilterData', uno.Any('[]com.sun.star.beans.PropertyValue', (
                    prop('ExportBookmarksToPDFDestination', True),)))))
            print(json.dumps({'role': target.stem, 'passes': evidence,
                              'pdf_export': 'stored_docx_reopened_layout_restored'},
                             ensure_ascii=False), flush=True)
            document.close(True)
            document = None
finally:
    try:
        if document is not None:
            document.close(True)
    finally:
        try:
            if desktop is not None:
                desktop.terminate()
        finally:
            if process is not None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
'''


def _refresh_docx(temporary, staged, target, tools, roles, access, *, layout_policy=None):
    profile = temporary / 'profile'
    if 'office_python' not in tools:
        access.run([tools['soffice'], '-env:UserInstallation=' + profile.as_uri(),
              '--headless', '--nologo', '--nodefault', '--norestore',
              '--convert-to', 'docx:Office Open XML Text', '--outdir', target,
              *(staged / f'{role}.docx' for role in roles)])
        return 'isolated_soffice_docx_save_without_explicit_refresh', {}
    script, config = temporary / 'refresh.py', temporary / 'refresh.json'
    access.write(script, _UNO_SCRIPT.encode('utf-8'))
    access.write(config, canonical_bytes({
        'soffice': str(tools['soffice']), 'profile': profile.as_uri(),
        'pipe': 'dyz_standard_' + uuid.uuid4().hex,
        'inputs': [str(staged / f'{role}.docx') for role in roles], 'output': str(target),
        'layout_policy': layout_policy, 'pdf_output': str(target.parent / 'pdf'),
    }))
    raw = access.run([tools['office_python'], script, config])
    if layout_policy is None:
        return 'bounded_local_uno_refresh_fields_update_indexes_store_docx', {}
    try:
        rows = [strict_json_loads(line) for line in raw.decode('utf-8').splitlines()
                if line.startswith('{')]
    except (ValueError, UnicodeError) as exc:
        raise ContractError('standard_pdf_uno_layout_evidence_invalid') from exc
    require(len(rows) == len(roles) and {row.get('role') for row in rows} == set(roles),
            'standard_pdf_uno_layout_evidence_invalid')
    return ('bounded_local_uno_refresh_fields_store_reopen_export_pdf',
            {row['role']: {**row, 'policy': layout_policy} for row in rows})


class _WindowsJob:
    """仅管理本次悬停启动并绑定的进程树，关闭句柄时清理其子进程。"""

    def __init__(self):
        from ctypes import wintypes as wt

        class BasicLimit(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wt.DWORD), ('minimum_working_set', ctypes.c_size_t),
                        ('maximum_working_set', ctypes.c_size_t), ('active_processes', wt.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wt.DWORD),
                        ('scheduling_class', wt.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('read_ops', 'write_ops', 'other_ops', 'read_bytes',
                         'write_bytes', 'other_bytes')]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [('basic', BasicLimit), ('io', IoCounters),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]

        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateJobObjectW': ([ctypes.c_void_p, wt.LPCWSTR], wt.HANDLE),
            'SetInformationJobObject': ([wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD], wt.BOOL),
            'OpenProcess': ([wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
            'AssignProcessToJobObject': ([wt.HANDLE, wt.HANDLE], wt.BOOL),
            'CreateToolhelp32Snapshot': ([wt.DWORD, wt.DWORD], wt.HANDLE),
            'Thread32First': ([wt.HANDLE, ctypes.c_void_p], wt.BOOL),
            'Thread32Next': ([wt.HANDLE, ctypes.c_void_p], wt.BOOL),
            'OpenThread': ([wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
            'ResumeThread': ([wt.HANDLE], wt.DWORD),
            'CloseHandle': ([wt.HANDLE], wt.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), 'standard_pdf_job_create_failed')
        limit = ExtendedLimit()
        limit.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limit), ctypes.sizeof(limit)):
            self.close()
            raise OSError(ctypes.get_last_error(), 'standard_pdf_job_limit_failed')

    def attach(self, process):
        from ctypes import wintypes as wt

        handle = self.api.OpenProcess(0x0101, False, process.pid)
        if not handle:
            raise OSError(ctypes.get_last_error(), 'standard_pdf_process_open_failed')
        try:
            if not self.api.AssignProcessToJobObject(self.handle, handle):
                raise OSError(ctypes.get_last_error(), 'standard_pdf_job_assign_failed')
        finally:
            self.api.CloseHandle(handle)

        class ThreadEntry(ctypes.Structure):
            _fields_ = [('size', wt.DWORD), ('usage', wt.DWORD),
                        ('thread_id', wt.DWORD), ('process_id', wt.DWORD),
                        ('base_priority', wt.LONG), ('delta_priority', wt.LONG),
                        ('flags', wt.DWORD)]

        snapshot = self.api.CreateToolhelp32Snapshot(0x00000004, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), 'standard_pdf_threads_failed')
        thread_ids = []
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            more = self.api.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.process_id == process.pid:
                    thread_ids.append(entry.thread_id)
                more = self.api.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            self.api.CloseHandle(snapshot)
        require(len(thread_ids) == 1, 'standard_pdf_suspended_process_unexpected')
        thread = self.api.OpenThread(0x0002, False, thread_ids[0])
        if not thread:
            raise OSError(ctypes.get_last_error(), 'standard_pdf_thread_open_failed')
        try:
            if self.api.ResumeThread(thread) == 0xFFFFFFFF:
                raise OSError(ctypes.get_last_error(), 'standard_pdf_process_resume_failed')
        finally:
            self.api.CloseHandle(thread)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def _run(arguments, *, timeout=COMMAND_TIMEOUT):
    """有界执行，不经shell、不打印输入材料或Office原始诊断。"""
    job = _WindowsJob() if os.name == 'nt' else None
    process = None
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                [str(part) for part in arguments], stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, shell=False,
                creationflags=(getattr(subprocess, 'CREATE_NO_WINDOW', 0) | 0x00000004)
                if job else 0, start_new_session=job is None,
            )
            if job:
                # CREATE_SUSPENDED保证Office在任何子进程产生前进入专属Job。
                job.attach(process)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise ContractError('standard_pdf_tool_timeout') from exc
            require(code == 0, 'standard_pdf_tool_failed')
            require(stdout.tell() <= MAX_MANIFEST_BYTES
                    and stderr.tell() <= MAX_MANIFEST_BYTES, 'standard_pdf_tool_output_too_large')
            stdout.seek(0)
            return stdout.read(MAX_MANIFEST_BYTES + 1)
    finally:
        if job:
            job.close()
        elif process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def _normalize(text):
    # 只统一传输换行，技术文字的空格、兼容字符、大小写和符号一律保留。
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _safe_xml(raw, code):
    require(len(raw) <= MAX_FILE_BYTES
            and not re.search(br'<!\s*(?:DOCTYPE|ENTITY)\b', raw, re.IGNORECASE), code)
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ContractError(code) from exc


def _paragraphs(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.getinfo('word/document.xml')
        require(info.file_size <= MAX_FILE_BYTES, 'standard_pdf_document_xml_too_large')
        document = _safe_xml(archive.read(info), 'standard_pdf_document_xml_invalid')
    paragraphs = []
    for paragraph in document.iter(_W + 'p'):
        text = ''.join(node.text or '' if node.tag == _W + 't' else
                       '\t' if node.tag == _W + 'tab' else '\n'
                       for node in paragraph.iter()
                       if node.tag in {_W + 't', _W + 'tab', _W + 'br', _W + 'cr'})
        if text:
            paragraphs.append(text)
    return paragraphs


def _comparison_kind(block):
    explicit = block.get('comparison_kind') or block.get('text_type')
    if explicit == 'narrative':
        return 'narrative'
    if explicit in {'code', 'xml', 'path', 'identifier', 'example_data', 'technical'}:
        return 'technical'
    if block.get('kind') in {'code', 'xml', 'path', 'identifier', 'example_data'}:
        return 'technical'
    if block.get('kind') not in {'paragraph', 'heading1', 'heading2', 'heading3', 'heading4',
                                  'title', 'table', 'field'}:
        return 'unknown'
    text = block.get('text', '')
    # 标识、代码、路径和未声明的西文片段不自动降为可合并空白的叙述。
    if re.search(r'[A-Za-z0-9_<>{}\\/=`\t]', text):
        return 'technical'
    return 'narrative'


def _match_block(text, actual, offset, block, equivalences):
    """仅显式的CJK排版换行、叙述单词间已有空格的换行可等价。"""
    kind = _comparison_kind(block)
    source, position = 0, offset
    while source < len(text):
        if position < len(actual) and text[source] == actual[position]:
            source, position = source + 1, position + 1
            continue
        if (kind == 'narrative' and position < len(actual) and actual[position] == '\n'
                and source > 0 and '\u2e80' <= text[source - 1] <= '\uffff'
                and '\u2e80' <= text[source] <= '\uffff'):
            equivalences.append({'block_id': block['id'], 'rule': 'narrative_cjk_line_wrap',
                                 'source_start': source, 'source_end': source,
                                 'actual_start': position, 'actual_end': position + 1,
                                 'source': '', 'actual': '\n'})
            position += 1
            continue
        if (kind == 'narrative' and text[source] == ' ' and position < len(actual)
                and actual[position] == '\n'):
            equivalences.append({'block_id': block['id'], 'rule': 'narrative_space_line_wrap',
                                 'source_start': source, 'source_end': source + 1,
                                 'actual_start': position, 'actual_end': position + 1,
                                 'source': ' ', 'actual': '\n'})
            source, position = source + 1, position + 1
            continue
        return None
    return position


def compare_text_blocks(blocks: list[dict], actual: str) -> dict:
    """按已知块依序比较文字；不对技术片段作NFKC或全局忽略空白。"""
    require(isinstance(blocks, list) and isinstance(actual, str),
            'standard_pdf_text_comparison_input')
    actual = _normalize(actual)
    offset, rows, mappings, unsupported = 0, [], [], []
    for index, original in enumerate(blocks):
        require(isinstance(original, dict) and isinstance(original.get('text'), str),
                'standard_pdf_text_comparison_block')
        block = {**original, 'id': original.get('id', str(index + 1))}
        kind = _comparison_kind(block)
        text = _normalize(block['text'])
        start, pending = offset, []
        end = _match_block(text, actual, offset, block, pending)
        matched = end is not None
        if kind == 'unknown':
            unsupported.append({'id': block['id'], 'kind': block.get('kind', 'unknown')})
        rows.append({'id': block['id'], 'comparison': kind, 'matched': matched,
                     'actual_start': start, 'actual_end': end,
                     'source_sha256': sha256_bytes(text.encode('utf-8'))})
        if not matched:
            break
        mappings.extend(pending)
        offset = end
        # 块分隔仅在已证明的块边界处理；绝不删除块内部技术空白。
        if index < len(blocks) - 1 and offset < len(actual) and actual[offset] == '\n':
            separator = offset
            while offset < len(actual) and actual[offset] in '\n\f':
                offset += 1
            mappings.append({'block_id': block['id'], 'rule': 'block_boundary',
                             'actual_start': separator, 'actual_end': offset,
                             'source_start': len(text), 'source_end': len(text),
                             'source': '', 'actual': actual[separator:offset]})
    trailing = offset
    while offset < len(actual) and actual[offset] in '\n\f':
        offset += 1
    if offset > trailing:
        mappings.append({'block_id': rows[-1]['id'] if rows else None,
                         'rule': 'page_text_terminator', 'source_start': None,
                         'source_end': None, 'actual_start': trailing, 'actual_end': offset,
                         'source': '', 'actual': actual[trailing:offset]})
    matched = bool(blocks) and len(rows) == len(blocks) and all(row['matched'] for row in rows)
    matched = matched and offset == len(actual)
    return {'matched': matched, 'status': 'needs_review' if not matched else
            'partial' if unsupported else 'complete', 'blocks': rows,
            'equivalences': mappings, 'unsupported_objects': unsupported,
            'method': 'ordered_block_exact_technical_explicit_narrative_wrap_v1'}


def _document_state(raw):
    """读取域、书签及正文直接段落中的有效 OMML 字符与结构摘要。"""
    fields, bookmarks, headings, fragments = [], {}, [], []
    visible_parts, tables, toc_tabs, text_blocks, unsupported = {}, [], [], [], []
    formulas = []
    sections, even_and_odd = [], False
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and len(names) <= 500,
                'standard_pdf_docx_members_invalid')
        stories = [name for name in names if name == 'word/document.xml'
                   or re.fullmatch(r'word/(?:header\d+|footer\d+|footnotes|endnotes)\.xml', name)]
        require('word/document.xml' in stories, 'standard_pdf_document_missing')
        relations = {}
        if 'word/_rels/document.xml.rels' in names:
            relation_xml = _safe_xml(archive.read('word/_rels/document.xml.rels'),
                                     'standard_pdf_document_xml_invalid')
            for relation in relation_xml:
                target = relation.get('Target', '')
                if relation.get('Type', '').endswith(('/header', '/footer')):
                    require(relation.get('TargetMode') != 'External'
                            and not target.startswith('/') and '\\' not in target
                            and '..' not in PurePosixPath(target).parts,
                            'standard_pdf_story_relationship_invalid')
                    relations[relation.get('Id')] = 'word/' + target
        if 'word/settings.xml' in names:
            settings = _safe_xml(archive.read('word/settings.xml'),
                                 'standard_pdf_document_xml_invalid')
            setting = settings.find(_W + 'evenAndOddHeaders')
            even_and_odd = (setting is not None
                            and setting.get(_W + 'val', 'true') not in {'0', 'false', 'off'})
        for name in sorted(stories):
            info = archive.getinfo(name)
            require(info.file_size <= MAX_FILE_BYTES, 'standard_pdf_document_xml_too_large')
            document = _safe_xml(archive.read(info), 'standard_pdf_document_xml_invalid')
            if name == 'word/document.xml':
                for section in document.iter(_W + 'sectPr'):
                    references = {}
                    for kind in ('header', 'footer'):
                        for reference in section.findall(_W + kind + 'Reference'):
                            slot = reference.get(_W + 'type', 'default')
                            relation = reference.get(
                                '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                            require(slot in {'default', 'first', 'even'}
                                    and (kind, slot) not in references and relation in relations,
                                    'standard_pdf_story_relationship_invalid')
                            references[(kind, slot)] = relations[relation]
                    numbering = section.find(_W + 'pgNumType')
                    title = section.find(_W + 'titlePg')
                    sections.append({'references': references,
                                     'first_page': title is not None and title.get(
                                         _W + 'val', 'true') not in {'0', 'false', 'off'},
                                     'page_start': numbering.get(_W + 'start', '1')
                                         if numbering is not None else '1',
                                     'page_format': numbering.get(_W + 'fmt', 'decimal')
                                         if numbering is not None else 'decimal'})
            stack, active, segment, visible = [], {}, [], []

            def flush():
                text = _normalize(''.join(segment))
                if text and name == 'word/document.xml':
                    fragments.append(text)
                segment.clear()

            def start_field(instruction=''):
                flush()
                require(len(fields) < 500, 'standard_pdf_field_limit')
                row = {'id': len(fields) + 1, 'part': name,
                       'instruction': instruction, 'cached_result': '',
                       'parent_id': stack[-1]['id'] if stack else None,
                       'anchors': list(active.values()), '_result': bool(instruction),
                       'text_start': len(_normalize(''.join(visible)))}
                fields.append(row)
                stack.append(row)

            def end_field():
                require(bool(stack), 'standard_pdf_field_unbalanced')
                row = stack.pop()
                row['text_end'] = len(_normalize(''.join(visible)))
                flush()

            def text(value):
                visible.append(value)
                for row in stack:
                    if row['_result']:
                        row['cached_result'] += value
                for bookmark in active.values():
                    bookmarks[bookmark]['text'] += value
                if not stack:
                    segment.append(value)

            def walk(node, parent=None, grandparent=None):
                tag = node.tag
                if tag.rsplit('}', 1)[-1] in {'oMath', 'oMathPara'}:
                    kind = tag.rsplit('}', 1)[-1]
                    if (tag in _OMML_ROOTS and name == 'word/document.xml' and not stack
                            and parent == _W + 'p' and grandparent == _W + 'body'):
                        inspected = omml.inspect_omml(node)
                        if inspected['valid']:
                            formulas.append(inspected['structure_sha256'])
                            text(inspected['extracted_text'])
                            return
                    unsupported.append({'part': name, 'kind': kind})
                    return
                if tag == _W + 'p':
                    flush()
                    paragraph_start = len(''.join(visible))
                if tag == _W + 'tbl':
                    table_start = len(_normalize(''.join(visible)))
                if tag == _W + 'bookmarkStart':
                    bookmark = node.get(_W + 'name', '')
                    require(bookmark and bookmark not in bookmarks,
                            'standard_pdf_bookmark_invalid')
                    bookmarks[bookmark] = {'part': name, 'text': ''}
                    active[node.get(_W + 'id')] = bookmark
                elif tag == _W + 'bookmarkEnd':
                    active.pop(node.get(_W + 'id'), None)
                elif tag == _W + 'fldSimple':
                    start_field(node.get(_W + 'instr', ''))
                elif tag == _W + 'fldChar':
                    kind = node.get(_W + 'fldCharType')
                    if kind == 'begin':
                        start_field()
                    elif kind == 'separate':
                        require(bool(stack), 'standard_pdf_field_unbalanced')
                        stack[-1]['_result'] = True
                    elif kind == 'end':
                        end_field()
                elif tag == _W + 'instrText':
                    require(bool(stack), 'standard_pdf_field_unbalanced')
                    stack[-1]['instruction'] += node.text or ''
                elif tag == _W + 't':
                    text(node.text or '')
                elif tag in {_W + 'tab', _W + 'br', _W + 'cr'} and parent == _W + 'r':
                    if tag == _W + 'tab':
                        toc = next((row for row in stack if row['_result']
                                    and row['instruction'].strip().upper().startswith('TOC ')), None)
                        if toc:
                            toc_tabs.append({'part': name, 'field_id': toc['id'],
                                             'text_offset': len(_normalize(''.join(visible)))})
                    text('\t' if tag == _W + 'tab' else '\n')
                for child in node:
                    walk(child, tag, parent)
                if tag == _W + 'fldSimple':
                    end_field()
                elif tag == _W + 'tbl':
                    header = '\n'.join(''.join(n.text or '' for n in p.iter(_W + 't'))
                                       for tr in node.findall(_W + 'tr')
                                       if tr.find('./' + _W + 'trPr/' + _W + 'tblHeader') is not None
                                       for p in tr.iter(_W + 'p'))
                    cells, cell_start = [], table_start
                    for row_index, tr in enumerate(node.findall(_W + 'tr')):
                        for column, cell in enumerate(tr.findall(_W + 'tc')):
                            paragraphs = list(cell.iter(_W + 'p'))
                            length = sum(len(''.join(n.text or '' if n.tag == _W + 't'
                                         else '\t' if n.tag == _W + 'tab' else '\n'
                                         for n in p.iter() if n.tag in {
                                             _W + 't', _W + 'tab', _W + 'br', _W + 'cr'})) + 1
                                         for p in paragraphs)
                            cells.append({'row': row_index, 'column': column,
                                          'text_start': cell_start,
                                          'text_end': cell_start + length})
                            cell_start += length
                    tables.append({'part': name, 'text_start': table_start,
                                   'text_end': len(_normalize(''.join(visible))),
                                   'repeated_header': _normalize(header), 'cells': cells})
                elif tag == _W + 'p':
                    if not stack:
                        style = node.find('./' + _W + 'pPr/' + _W + 'pStyle')
                        if style is not None and re.fullmatch(
                                r'(?:Heading|AnnexHeading)[1-4]', style.get(_W + 'val', '')):
                            heading_text = ''.join(n.text or '' for n in node.iter(_W + 't'))
                            anchors = [n.get(_W + 'name') for n in node.iter(_W + 'bookmarkStart')]
                            headings.append({'text': heading_text, 'anchors': anchors})
                    paragraph_text = ''.join(visible)[paragraph_start:]
                    style = node.find('./' + _W + 'pPr/' + _W + 'pStyle')
                    formula_paragraph = any(child.tag in _OMML_ROOTS for child in node)
                    anchors = [n.get(_W + 'name') for n in node.iter(_W + 'bookmarkStart')]
                    text_blocks.append({'id': anchors[0] if anchors else
                                        f'{name}#p{len(text_blocks) + 1}', 'part': name,
                                        'text': paragraph_text,
                                        'kind': ('formula' if formula_paragraph else 'code' if style is not None and
                                                 style.get(_W + 'val') == 'Code' else 'paragraph'),
                                        **({'comparison_kind': 'technical'} if formula_paragraph else {}),
                                        'text_start': paragraph_start,
                                        'text_end': len(''.join(visible))})
                    if stack:
                        text('\n')
                    else:
                        visible.append('\n')
                    flush()
                elif tag.rsplit('}', 1)[-1] in {'drawing', 'pict', 'object', 'txbxContent'}:
                    unsupported.append({'part': name, 'kind': tag.rsplit('}', 1)[-1]})

            walk(document)
            flush()
            require(not stack, 'standard_pdf_field_unbalanced')
            visible_parts[name] = _normalize(''.join(visible))
    for row in fields:
        row.pop('_result')
        row['instruction'] = row['instruction'].strip()
        row['cached_result'] = row['cached_result'].strip()
        tokens = re.findall(r'"[^"]*"|\S+', row['instruction'])
        row['kind'] = tokens[0].upper() if tokens else ''
        row['target'] = (tokens[1].strip('"') if len(tokens) > 1
                         and row['kind'] in {'REF', 'PAGEREF', 'SEQ'} else None)
    return {'fields': fields, 'bookmarks': bookmarks, 'headings': headings,
            'nonfield_fragments': fragments, 'visible_parts': visible_parts,
            'tables': tables, 'toc_tabs': toc_tabs, 'text_blocks': text_blocks,
            'formula_structure_sha256s': formulas,
            'unsupported_objects': unsupported, 'sections': sections,
            'even_and_odd_headers': even_and_odd}


def _text_coverage(expected, actual, error):
    # 该入口只证明已保存的非域片段未丢失；完整顺序和多余字另由分块比较核验。
    extracted, offset = _normalize(actual), 0
    require(bool(expected), error)
    for index, fragment in enumerate(expected):
        block = {'id': str(index + 1), 'kind': 'paragraph', 'text': fragment}
        kind = _comparison_kind(block)
        if kind != 'narrative':
            start = extracted.find(fragment, offset)
            require(start >= 0, error)
            offset = start + len(fragment)
            continue
        found, start = False, extracted.find(fragment[:1], offset)
        while start >= 0:
            end = _match_block(fragment, extracted, start, block, [])
            if end is not None:
                offset, found = end, True
                break
            start = extracted.find(fragment[:1], start + 1)
        require(found, error)


def _bookmark_destinations(source, saved, destinations):
    # 本地LibreOffice实测将书签下划线写为5F；遇到名称碰撞不能猜同一目标。
    names = set(source['bookmarks']) | set(saved['bookmarks'])
    candidates = {name: {key for key in (name, name.replace('_', '5F'))
                         if key in destinations} for name in names}
    claims = Counter(key for keys in candidates.values() for key in keys)
    return {name: destinations[next(iter(keys))] for name, keys in candidates.items()
            if len(keys) == 1 and claims[next(iter(keys))] == 1}


def _story_parts(state, number):
    """单节的启用引用决定页眉页脚；未启用的首页/偶数页部件不是附加正文。"""
    sections = state.get('sections', [])
    if len(sections) != 1:
        return None
    section = sections[0]
    if section['page_start'] != '1' or section['page_format'] != 'decimal':
        return None
    slot = ('first' if number == 1 and section['first_page'] else
            'even' if number % 2 == 0 and state.get('even_and_odd_headers') else 'default')
    return {kind: section['references'].get((kind, slot)) for kind in ('header', 'footer')}


def _raw_word_offsets(text, page):
    """raw bbox和raw文本必须逐词同序，才能把物理坐标绑定到原始字符区间。"""
    words, position, separators = [], 0, []
    for word in page['words']:
        start = position
        while position < len(text) and text[position] in ' \t\n\f':
            position += 1
        if not text.startswith(word['text'], position):
            return None
        if position > start:
            separators.append({'start': start, 'end': position})
        words.append({**word, 'actual_start': position,
                      'actual_end': position + len(word['text'])})
        position += len(word['text'])
    if any(character not in '\n\f' for character in text[position:]):
        return None
    return {'words': words, 'separators': separators}


class _PdfEvidenceSyntax:
    """仅供本地字符见证的有界词法器；对象边界始终来自xref和Length。"""

    def __init__(self, raw):
        self.raw, self.position, self.tokens = raw, 0, 0

    def token(self):
        raw, size = self.raw, len(self.raw)
        while self.position < size:
            if raw[self.position] in b'\x00\t\n\f\r ':
                self.position += 1
            elif raw[self.position] == 37:
                end = re.search(rb'[\r\n]', raw[self.position:])
                self.position = self.position + end.end() if end else size
            else:
                break
        if self.position == size:
            return None
        self.tokens += 1
        if self.tokens > 500_000:
            raise ValueError('token_limit')
        start = self.position
        for marker in (b'<<', b'>>'):
            if raw.startswith(marker, start):
                self.position += 2
                return ('delimiter', marker.decode('ascii'))
        char = raw[start]
        if char in b'[]':
            self.position += 1
            return ('delimiter', chr(char))
        if char == 47:
            self.position += 1
            while (self.position < size and raw[self.position] not in
                   b'\x00\t\n\f\r ()<>[]{}/%'):
                self.position += 1
            name = raw[start + 1:self.position]
            if re.search(rb'#(?![0-9A-Fa-f]{2})', name):
                raise ValueError('name_escape')
            name = re.sub(rb'#([0-9A-Fa-f]{2})', lambda m: bytes([int(m[1], 16)]), name)
            return ('name', name.decode('ascii'))
        if char == 60:
            end = raw.find(b'>', start + 1)
            if end < 0:
                raise ValueError('hex_string')
            value = re.sub(rb'[\x00\t\n\f\r ]', b'', raw[start + 1:end])
            if re.search(rb'[^0-9A-Fa-f]', value):
                raise ValueError('hex_string')
            self.position = end + 1
            return ('string', bytes.fromhex((value + (b'0' if len(value) % 2 else b'')).decode('ascii')))
        if char == 40:
            self.position += 1
            depth, value = 1, bytearray()
            while self.position < size:
                char = raw[self.position]
                self.position += 1
                if char == 92:
                    if self.position == size:
                        break
                    char = raw[self.position]
                    self.position += 1
                    if char in b'\r\n':
                        if char == 13 and raw[self.position:self.position + 1] == b'\n':
                            self.position += 1
                        continue
                    escapes = {110: 10, 114: 13, 116: 9, 98: 8, 102: 12}
                    if char in b'01234567':
                        digits = bytes([char])
                        while (len(digits) < 3 and self.position < size
                               and raw[self.position] in b'01234567'):
                            digits += raw[self.position:self.position + 1]
                            self.position += 1
                        value.append(int(digits, 8) & 255)
                    else:
                        value.append(escapes.get(char, char))
                elif char == 40:
                    depth += 1
                    if depth > 16:
                        raise ValueError('string_depth')
                    value.append(char)
                elif char == 41:
                    depth -= 1
                    if not depth:
                        return ('string', bytes(value))
                    value.append(char)
                else:
                    # PDF字面串的裸CR及CRLF均表示一个LF。
                    if char == 13:
                        if raw[self.position:self.position + 1] == b'\n':
                            self.position += 1
                        char = 10
                    value.append(char)
            raise ValueError('literal_string')
        end = start
        while end < size and raw[end] not in b'\x00\t\n\f\r ()<>[]{}/%':
            end += 1
        if end == start:
            raise ValueError('token')
        self.position = end
        value = raw[start:end]
        if re.fullmatch(rb'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', value):
            number = float(value) if b'.' in value else int(value)
            if not math.isfinite(number) or abs(number) > 1_000_000_000:
                raise ValueError('number_limit')
            return ('number', number)
        return ('keyword', value.decode('ascii'))

    def value(self, depth=0):
        if depth > 24:
            raise ValueError('object_depth')
        token = self.token()
        if token is None:
            raise ValueError('object_missing')
        kind, value = token
        if kind == 'delimiter' and value == '<<':
            result = {}
            while True:
                key = self.token()
                if key == ('delimiter', '>>'):
                    return result
                if key is None or key[0] != 'name' or key[1] in result:
                    raise ValueError('dictionary_key')
                result[key[1]] = self.value(depth + 1)
        if kind == 'delimiter' and value == '[':
            result = []
            while True:
                position = self.position
                if self.token() == ('delimiter', ']'):
                    return result
                self.position = position
                result.append(self.value(depth + 1))
                if len(result) > 10_000:
                    raise ValueError('array_limit')
        if kind == 'number' and type(value) is int:
            position = self.position
            generation = self.token()
            if (generation and generation[0] == 'number' and type(generation[1]) is int
                    and self.token() == ('keyword', 'R')):
                if value <= 0 or generation[1] != 0:
                    raise ValueError('reference_generation')
                return ('reference', value)
            self.position = position
        if kind in {'number', 'string'}:
            return value
        if kind == 'name':
            return token
        if token == ('keyword', 'null'):
            return None
        if token in {('keyword', 'true'), ('keyword', 'false')}:
            return value == 'true'
        raise ValueError('object_value')


class _PdfEvidenceFile:
    """只读bytes，不解析文件路径；不支持增量、对象流、加密或外部流。"""

    def __init__(self, raw):
        if (not isinstance(raw, bytes) or len(raw) > MAX_FILE_BYTES
                or not re.match(rb'%PDF-1\.[0-7][\r\n]', raw)):
            raise ValueError('pdf_size_or_header')
        ending = re.search(rb'startxref\s+(\d+)\s+%%EOF[\x00\t\n\f\r ]*$', raw[-1024:])
        if ending is None:
            raise ValueError('classic_xref_required')
        self.raw, self.xref = raw, int(ending[1])
        if not 0 < self.xref < len(raw) or raw[self.xref:self.xref + 4] != b'xref':
            raise ValueError('classic_xref_required')
        position, entries, seen = self.xref + 4, {}, set()
        while True:
            gap = re.match(rb'\s*', raw[position:])
            position += gap.end()
            if raw.startswith(b'trailer', position):
                position += 7
                break
            header = re.match(rb'(\d+) +(\d+)[ \t]*\r?\n', raw[position:])
            if header is None:
                raise ValueError('xref_section')
            first, count = map(int, header.groups())
            if not 0 < count <= 10_000 or first + count > 10_000:
                raise ValueError('xref_limit')
            position += header.end()
            for number in range(first, first + count):
                entry = re.match(rb'(\d{10}) (\d{5}) ([nf])[ \t]*(?:\r\n|\n|\r)', raw[position:])
                if entry is None or number in seen:
                    raise ValueError('xref_entry')
                seen.add(number)
                position += entry.end()
                if entry[3] == b'n':
                    offset = int(entry[1])
                    if number == 0 or int(entry[2]) != 0 or not 8 <= offset < self.xref:
                        raise ValueError('xref_offset')
                    entries[number] = offset
        syntax = _PdfEvidenceSyntax(raw[position:])
        trailer = syntax.value()
        if (not isinstance(trailer, dict) or {'Prev', 'XRefStm', 'Encrypt'} & trailer.keys()
                or type(trailer.get('Size')) is not int or trailer['Size'] != len(seen)
                or seen != set(range(trailer['Size'])) or len(set(entries.values())) != len(entries)
                or not re.fullmatch(rb'\s*startxref\s+' + str(self.xref).encode('ascii')
                                    + rb'\s+%%EOF[\x00\t\n\f\r ]*', raw[position + syntax.position:])):
            raise ValueError('xref_trailer')
        self.entries, self.trailer = entries, trailer
        offsets = sorted(entries.values()) + [self.xref]
        self.ends = dict(zip(offsets, offsets[1:]))
        self.objects, self.active, self.decoded = {}, set(), {}
        self.decoded_bytes = 0
        # 验证全部索引区间，防止xref故意指入另一对象的stream字节中。
        for number in entries:
            self.object(number)

    def number(self, value):
        if (not isinstance(value, tuple) or len(value) != 2 or value[0] != 'reference'
                or value[1] not in self.entries):
            raise ValueError('local_reference_required')
        return value[1]

    def object(self, number):
        if number in self.objects:
            return self.objects[number]
        if number in self.active or len(self.active) > 24:
            raise ValueError('object_cycle')
        self.active.add(number)
        offset = self.entries[number]
        syntax = _PdfEvidenceSyntax(self.raw[offset:self.ends[offset]])
        if (syntax.token(), syntax.token(), syntax.token()) != (
                ('number', number), ('number', 0), ('keyword', 'obj')):
            raise ValueError('object_header')
        value, stream = syntax.value(), None
        token = syntax.token()
        if token == ('keyword', 'stream'):
            if not isinstance(value, dict):
                raise ValueError('stream_dictionary')
            length = value.get('Length')
            if isinstance(length, tuple):
                length, nested = self.object(self.number(length))
                if nested is not None:
                    raise ValueError('stream_length')
            if type(length) is not int or not 0 <= length <= MAX_FILE_BYTES:
                raise ValueError('stream_length')
            newline = re.match(rb'\r\n|\n|\r', syntax.raw[syntax.position:])
            if newline is None:
                raise ValueError('stream_newline')
            start = syntax.position + newline.end()
            end = start + length
            if end > len(syntax.raw):
                raise ValueError('stream_length')
            stream = syntax.raw[start:end]
            syntax.position = end
            if syntax.token() != ('keyword', 'endstream'):
                raise ValueError('stream_end')
            token = syntax.token()
        if token != ('keyword', 'endobj') or syntax.token() is not None:
            raise ValueError('object_end')
        self.active.remove(number)
        self.objects[number] = value, stream
        return value, stream

    def value(self, value):
        if isinstance(value, tuple) and value[0] == 'reference':
            result, stream = self.object(self.number(value))
            if stream is not None:
                raise ValueError('dictionary_or_array_required')
            return result
        return value

    def stream(self, number):
        if number not in self.decoded:
            dictionary, raw = self.object(number)
            if (raw is None or set(dictionary) - {'Length', 'Filter'}
                    or dictionary.get('Filter') not in (None, ('name', 'FlateDecode'))):
                raise ValueError('local_flate_or_plain_stream_required')
            if dictionary.get('Filter') is None:
                decoded = raw
            else:
                inflater = zlib.decompressobj()
                decoded = inflater.decompress(raw, MAX_TEXT_BYTES + 1)
                if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
                    raise ValueError('flate_stream_limit_or_trailing_data')
            self.decoded_bytes += len(decoded)
            if len(decoded) > MAX_TEXT_BYTES or self.decoded_bytes > MAX_FILE_BYTES:
                raise ValueError('decoded_stream_limit')
            self.decoded[number] = decoded
        return self.decoded[number]

    def pages(self):
        catalog = self.value(self.trailer.get('Root'))
        if not isinstance(catalog, dict) or catalog.get('Type') != ('name', 'Catalog'):
            raise ValueError('catalog')
        result, visited = [], set()

        def visit(reference, parent=None, inherited=None):
            number = self.number(reference)
            if number in visited or len(visited) > 100:
                raise ValueError('page_tree_limit_or_cycle')
            visited.add(number)
            node = self.value(reference)
            if (not isinstance(node, dict) or node.get('Parent') != parent
                    or node.get('Type') not in {('name', 'Pages'), ('name', 'Page')}):
                raise ValueError('page_tree')
            attributes = dict(inherited or {})
            attributes.update({key: node[key] for key in
                               ('Resources', 'MediaBox', 'CropBox', 'Rotate', 'UserUnit') if key in node})
            if node['Type'] == ('name', 'Page'):
                result.append((number, {**attributes, 'Contents': node.get('Contents')}))
                if len(result) > MAX_PAGES_PER_DOCUMENT:
                    raise ValueError('page_limit')
                return 1
            kids = self.value(node.get('Kids'))
            if not isinstance(kids, list) or not kids:
                raise ValueError('page_kids')
            total = sum(visit(child, reference, attributes) for child in kids)
            if type(node.get('Count')) is not int or total != node['Count']:
                raise ValueError('page_count')
            return total

        visit(catalog.get('Pages'))
        return result


def _pdf_evidence_font(document, reference):
    number = document.number(reference)
    font = document.value(reference)
    if (not isinstance(font, dict) or font.get('Type') != ('name', 'Font')
            or font.get('Subtype') != ('name', 'TrueType')
            or not isinstance(font.get('BaseFont'), tuple) or font['BaseFont'][0] != 'name'
            or set(font) - {'Type', 'Subtype', 'BaseFont', 'FirstChar', 'LastChar',
                            'Widths', 'FontDescriptor', 'ToUnicode'}):
        raise ValueError('simple_truetype_required')
    first, last = font.get('FirstChar'), font.get('LastChar')
    widths = document.value(font.get('Widths'))
    descriptor = document.value(font.get('FontDescriptor'))
    if (type(first) is not int or type(last) is not int or not 0 <= first <= last <= 255
            or not isinstance(widths, list) or len(widths) != last - first + 1
            or any(type(w) not in (int, float) or not 0 <= w <= 5000 for w in widths)
            or not isinstance(descriptor, dict)
            or descriptor.get('Type') != ('name', 'FontDescriptor')
            or type(descriptor.get('Ascent')) not in (int, float)
            or type(descriptor.get('Descent')) not in (int, float)
            or not -2000 <= descriptor['Descent'] <= 0 < descriptor['Ascent'] <= 2000):
        raise ValueError('font_metrics')
    cmap_number = document.number(font.get('ToUnicode'))
    cmap = document.stream(cmap_number)
    # 明确只接受Office本地单字节bfchar框架；usecmap/bfrange/多字符映射不补猜。
    match = re.fullmatch(
        rb'\s*/CIDInit\s*/ProcSet\s+findresource\s+begin\s+12\s+dict\s+begin\s+begincmap\s+'
        rb'/CIDSystemInfo\s*<<\s*/Registry\s*\(Adobe\)\s*/Ordering\s*\(UCS\)\s*'
        rb'/Supplement\s+0\s*>>\s*def\s*/CMapName\s*/Adobe-Identity-UCS\s+def\s*'
        rb'/CMapType\s+2\s+def\s+1\s+begincodespacerange\s+<00>\s*<FF>\s+'
        rb'endcodespacerange\s+(.*?)\s*endcmap\s+CMapName\s+currentdict\s+/CMap\s+'
        rb'defineresource\s+pop\s+end\s+end\s*', cmap, re.S)
    if match is None:
        raise ValueError('single_byte_bfchar_cmap_required')
    codes, position = {}, 0
    body = match[1]
    while position < len(body):
        block = re.match(rb'\s*(\d+)\s+beginbfchar\s+(.*?)\s*endbfchar\s*', body[position:], re.S)
        if block is None or not 0 < int(block[1]) <= 256:
            raise ValueError('bfchar_block')
        rows = re.findall(rb'<([0-9a-fA-F]{2})>\s*<([0-9a-fA-F]{4})>', block[2])
        residue = re.sub(rb'<[0-9a-fA-F]{2}>\s*<[0-9a-fA-F]{4}>', b'', block[2])
        if len(rows) != int(block[1]) or residue.strip():
            raise ValueError('bfchar_count_or_mapping')
        for code, unicode_value in rows:
            code, point = int(code, 16), int(unicode_value, 16)
            if code in codes or not first <= code <= last or 0xD800 <= point <= 0xDFFF:
                raise ValueError('bfchar_ambiguous_or_range')
            codes[code] = chr(point)
        position += block.end()
    return {'font_object': number, 'cmap_object': cmap_number,
            'cmap_sha256': sha256_bytes(cmap), 'font_sha256': sha256_bytes(canonical_bytes(font)),
            'codes': codes, 'first': first, 'widths': widths,
            'ascent': descriptor['Ascent'], 'descent': descriptor['Descent']}


def _pdf_evidence_glyphs(document, page_number, page, physical):
    media = document.value(page.get('MediaBox'))
    crop = document.value(page.get('CropBox', media))
    if (not isinstance(media, list) or len(media) != 4
            or any(type(v) not in (int, float) for v in media)
            or media[:2] != [0, 0] or not 0 < media[2] <= 2000 or not 0 < media[3] <= 2000
            or crop != media or page.get('Rotate', 0) != 0 or page.get('UserUnit', 1) != 1
            or physical.get('rotation') not in (None, 0)
            or abs(physical['width'] - media[2]) > 0.05
            or abs(physical['height'] - media[3]) > 0.05):
        raise ValueError('unrotated_default_page_required')
    resources = document.value(page.get('Resources'))
    if not isinstance(resources, dict) or set(resources) - {'Font', 'ProcSet'}:
        raise ValueError('simple_page_resources_required')
    fonts = document.value(resources.get('Font'))
    if not isinstance(fonts, dict):
        raise ValueError('font_resources')
    content_number = document.number(page.get('Contents'))
    content = document.stream(content_number)
    encoded = document.object(content_number)[1]
    provenance = {'page_object': page_number, 'content_object': content_number,
                  'content_stream_sha256': sha256_bytes(content),
                  'encoded_stream_sha256': sha256_bytes(encoded)}
    syntax = _PdfEvidenceSyntax(content)
    state = {'font': None, 'size': None, 'mode': 0, 'clip': media}
    stack, operands, glyphs, cache = [], [], [], {}
    inside, positioned, x, y, line_x, line_y = False, False, 0, 0, 0, 0
    rectangle, path_present, pending_clip = None, False, False
    numeric = {'w': 1, 'J': 1, 'j': 1, 'M': 1, 'rg': 3, 'RG': 3,
               'g': 1, 'G': 1, 'k': 4, 'K': 4, 'm': 2, 'l': 2,
               'c': 6, 'v': 4, 'y': 4, 're': 4}
    paint = {'S', 's', 'f', 'F', 'f*', 'B', 'B*', 'b', 'b*', 'n'}
    while True:
        start = syntax.position
        token = syntax.token()
        if token is None:
            break
        if token[0] != 'keyword':
            syntax.position = start
            operands.append(syntax.value())
            if len(operands) > 4096:
                raise ValueError('content_operand_limit')
            continue
        operator, args = token[1], operands
        operands = []
        numbers = all(type(v) in (int, float) for v in args)
        if operator in numeric:
            if not numbers or len(args) != numeric[operator]:
                raise ValueError('graphics_operands')
            if operator in {'m', 'l', 'c', 'v', 'y', 're'}:
                rectangle = ([args[0], args[1], args[0] + args[2], args[1] + args[3]]
                             if operator == 're' and not path_present
                             and args[2] > 0 and args[3] > 0 else None)
                path_present = True
            continue
        if operator in paint:
            if args:
                raise ValueError('path_operands')
            if pending_clip:
                if rectangle is None:
                    raise ValueError('nonrectangular_clip')
                left, bottom, right, top = state['clip']
                state['clip'] = [max(left, rectangle[0]), max(bottom, rectangle[1]),
                                 min(right, rectangle[2]), min(top, rectangle[3])]
            rectangle, path_present, pending_clip = None, False, False
            continue
        if operator in {'W', 'W*'} and not args and not pending_clip:
            pending_clip = True
        elif operator == 'q' and not args and not inside and len(stack) < 32:
            stack.append(dict(state))
        elif operator == 'Q' and not args and not inside and stack:
            state = stack.pop()
        elif operator == 'cm' and args == [1, 0, 0, 1, 0, 0] and not inside:
            pass
        elif operator == 'BT' and not args and not inside:
            inside, positioned, x, y, line_x, line_y = True, False, 0, 0, 0, 0
        elif operator == 'ET' and not args and inside:
            inside = False
        elif operator in {'Td', 'Tm'} and inside and numbers:
            if operator == 'Td' and len(args) == 2:
                line_x, line_y = line_x + args[0], line_y + args[1]
            elif operator == 'Tm' and len(args) == 6 and args[:4] == [1, 0, 0, 1]:
                line_x, line_y = args[4:]
            else:
                raise ValueError('horizontal_text_matrix_required')
            x, y, positioned = line_x, line_y, True
        elif operator == 'Tf' and inside and len(args) == 2:
            name, size = args
            if (not isinstance(name, tuple) or name[0] != 'name' or name[1] not in fonts
                    or type(size) not in (int, float) or not 0 < size <= 1000):
                raise ValueError('font_selection')
            if name[1] not in cache:
                cache[name[1]] = _pdf_evidence_font(document, fonts[name[1]])
            state.update(font=name[1], size=size)
        elif operator == 'Tr' and inside and len(args) == 1 and args[0] in (0, 2):
            state['mode'] = args[0]
        elif (operator in {'Tc', 'Tw', 'Ts', 'TL', 'Tz'} and inside and len(args) == 1
              and args[0] == (100 if operator == 'Tz' else 0)):
            pass
        elif operator in {'Tj', 'TJ'} and inside and positioned and state['font']:
            if len(args) != 1 or (operator == 'Tj' and not isinstance(args[0], bytes)):
                raise ValueError('text_show')
            pieces = [args[0]] if operator == 'Tj' else args[0]
            if not isinstance(pieces, list):
                raise ValueError('text_array')
            font, size = cache[state['font']], state['size']
            show = {**provenance, 'font_resource': state['font'],
                    **{key: font[key] for key in
                       ('font_object', 'cmap_object', 'cmap_sha256', 'font_sha256')},
                    'font_size': size, 'text_show_end': syntax.position}
            glyph_index = 0
            for piece in pieces:
                if type(piece) in (int, float):
                    x -= piece * size / 1000
                    continue
                if not isinstance(piece, bytes):
                    raise ValueError('text_array_member')
                for code in piece:
                    if code not in font['codes']:
                        raise ValueError('unmapped_font_code')
                    width = font['widths'][code - font['first']] * size / 1000
                    bbox = [x, media[3] - y - font['ascent'] * size / 1000,
                            x + width, media[3] - y - font['descent'] * size / 1000]
                    clip = state['clip']
                    if (width <= 0 or bbox[0] < clip[0] - 0.05 or bbox[2] > clip[2] + 0.05
                            or media[3] - bbox[3] < clip[1] - 0.05
                            or media[3] - bbox[1] > clip[3] + 0.05):
                        raise ValueError('glyph_metrics_or_clip')
                    glyphs.append({'text': font['codes'][code], 'font_code_hex': f'{code:02X}',
                                   'bbox': bbox, 'baseline_y': y, 'show': show,
                                   'glyph_index': glyph_index})
                    x += width
                    glyph_index += 1
                    if len(glyphs) > 200_000:
                        raise ValueError('glyph_limit')
        else:
            # 未解释的字距、变换、ActualText、XObject或渲染模式不能产生见证。
            raise ValueError('unsupported_content_operator_' + operator[:24])
    if operands or inside or stack or pending_clip:
        raise ValueError('content_state_unbalanced')
    return glyphs


def _pdf_literal_space_evidence(pdf_raw, texts, physical_pages):
    """从PDF字码证明raw换行处省略的U+0020；绝不读取源文或用词间宽缝造字。"""
    report = {'method': 'classic_xref_simple_truetype_bfchar_literal_space_v1',
              'pdf_sha256': sha256_bytes(pdf_raw), 'status': 'checked', 'pages': []}
    try:
        document = _PdfEvidenceFile(pdf_raw)
        pages = document.pages()
        if len(pages) != len(texts) or len(pages) != len(physical_pages):
            raise ValueError('page_count_mismatch')
    except (ValueError, KeyError, UnicodeError, zlib.error) as exc:
        report.update(status='unsupported', reason=str(exc))
        pages = [None] * len(texts)
    for number, (text, physical, page) in enumerate(zip(texts, physical_pages, pages), 1):
        raw_text = _normalize(text)
        row = {'page': number, 'pdf_sha256': report['pdf_sha256'], 'status': 'checked',
               'raw_text_sha256': sha256_bytes(raw_text.encode('utf-8')),
               'raw_words_sha256': sha256_bytes(canonical_bytes(physical['words'])),
               'witnesses': []}
        report['pages'].append(row)
        if page is None:
            row.update(status='unsupported', reason=report['reason'])
            continue
        try:
            mapped = _raw_word_offsets(raw_text, physical)
            if mapped is None or physical.get('page', number) != number:
                raise ValueError('raw_word_page_binding')
            glyphs = _pdf_evidence_glyphs(document, *page, physical)

            def anchors(word):
                found = []
                length = len(word['text'])
                for start, glyph in enumerate(glyphs):
                    if (glyph['text'] != word['text'][:1]
                            or abs(glyph['bbox'][0] - word['bbox'][0]) > 0.05):
                        continue
                    selected = glyphs[start:start + length]
                    if len(selected) != length or ''.join(g['text'] for g in selected) != word['text']:
                        continue
                    if any(abs(a['baseline_y'] - b['baseline_y']) > 0.01
                           or abs(a['bbox'][2] - b['bbox'][0]) > 0.05
                           for a, b in zip(selected, selected[1:])):
                        continue
                    box = [min(g['bbox'][0] for g in selected), min(g['bbox'][1] for g in selected),
                           max(g['bbox'][2] for g in selected), max(g['bbox'][3] for g in selected)]
                    if all(abs(a - b) <= 0.05 for a, b in zip(box, word['bbox'])):
                        found.append((start, start + length))
                return found

            claimed = set()
            for previous, following in zip(mapped['words'], mapped['words'][1:]):
                gap = previous['actual_end']
                if (raw_text[gap:following['actual_start']] != '\n'
                        or following['bbox'][1] < previous['bbox'][3] - 0.5):
                    continue
                before, after = anchors(previous), anchors(following)
                if len(before) != 1 or len(after) != 1:
                    continue
                end, next_start = before[0][1], after[0][0]
                missing = glyphs[end:next_start] if end < next_start <= end + 256 else []
                if not missing or any(g['text'] != ' ' for g in missing):
                    continue
                sequence = [glyphs[end - 1], *missing]
                if (any(abs(a['baseline_y'] - b['baseline_y']) > 0.01
                        or abs(a['bbox'][2] - b['bbox'][0]) > 0.05
                        for a, b in zip(sequence, sequence[1:]))
                        or glyphs[next_start]['baseline_y'] >= sequence[0]['baseline_y']
                        or any(index in claimed for index in range(end, next_start))):
                    continue
                claimed.update(range(end, next_start))
                row['witnesses'].append({
                    'page': number, 'raw_line_break_start': gap, 'raw_line_break_end': gap + 1,
                    'preceding_word': previous, 'following_word': following,
                    'text': ' ' * len(missing),
                    'glyphs': [{**g['show'], 'font_code_hex': g['font_code_hex'],
                                'glyph_index': g['glyph_index'], 'unicode': 'U+0020',
                                'bbox': g['bbox'], 'baseline_y_bottom_left_points': g['baseline_y']}
                               for g in missing]})
        except (ValueError, KeyError, UnicodeError, zlib.error) as exc:
            row.update(status='unsupported', reason=str(exc), witnesses=[])
    if any(row['status'] == 'unsupported' for row in report['pages']):
        report['status'] = 'unsupported' if all(row['status'] == 'unsupported'
                                               for row in report['pages']) else 'partial'
    return report


def _physical_body(saved, texts, physical_pages, rendering_profile):
    """只移除启用部件且在声明页眉/页脚坐标带内的精确文字。"""
    result, mappings, footer_fields, raw_maps = [], [], {}, []
    margins = rendering_profile.get('geometry', {}).get(
        'body_margins_twips', rendering_profile.get('margin_twips'))
    if isinstance(margins, (int, float)):
        margins = {key: margins for key in ('top', 'right', 'bottom', 'left')}
    require(isinstance(margins, dict), 'standard_pdf_geometry_profile')
    distances = rendering_profile.get('header_footer', {})
    valid = len(texts) == len(physical_pages)
    for number, (raw_text, physical) in enumerate(zip(texts, physical_pages), 1):
        raw_text = _normalize(raw_text)
        mapped = _raw_word_offsets(raw_text, physical)
        parts = _story_parts(saved, number)
        if mapped is None or parts is None:
            valid = False
            result.append({'text': raw_text, 'raw_offsets': list(range(len(raw_text))),
                           'line_breaks': set(), 'page': number})
            raw_maps.append([])
            continue
        words = mapped['words']
        raw_maps.append(words)
        removed = set()
        for kind in ('header', 'footer'):
            name = parts[kind]
            template = saved['visible_parts'].get(name, '').rstrip('\n') if name else ''
            candidates = [word for word in words if (
                word['bbox'][3] <= margins['top'] / 20 if kind == 'header' else
                word['bbox'][1] >= physical['height'] - margins['bottom'] / 20)]
            if not template:
                if candidates:
                    valid = False
                continue
            fields = [row for row in saved['fields'] if row['part'] == name]
            story_ok = all(row['kind'] == 'PAGE' and row['parent_id'] is None for row in fields)
            expected = template
            for field in sorted(fields, key=lambda row: row['text_start'], reverse=True):
                expected = (expected[:field['text_start']] + str(number)
                            + expected[field['text_end']:])
            expected = expected.rstrip('\n')
            start = candidates[0]['actual_start'] if candidates else 0
            end = candidates[-1]['actual_end'] if candidates else 0
            edge = distances.get(kind + '_distance_twips')
            story_ok = (story_ok and bool(candidates) and edge is not None
                        and raw_text[start:end] == expected)
            for word in candidates:
                x1, y1, x2, y2 = word['bbox']
                story_ok = (story_ok and x1 >= margins['left'] / 20 - 0.5
                            and x2 <= physical['width'] - margins['right'] / 20 + 0.5
                            and (y1 >= edge / 20 - 0.5 if kind == 'header' else
                                 y2 <= physical['height'] - edge / 20 + 0.5))
            if not story_ok:
                valid = False
            else:
                # 只消费该物理故事及其紧随的提取行分隔，正文同文字仍保留。
                cut = end
                if raw_text[cut:cut + 1] == '\n':
                    cut += 1
                removed.update(range(start, cut))
                mappings.append({'page': number, 'rule': 'coordinate_bound_' + kind,
                                 'part': name, 'actual_start': start, 'actual_end': cut,
                                 'bbox': [min(w['bbox'][0] for w in candidates),
                                          min(w['bbox'][1] for w in candidates),
                                          max(w['bbox'][2] for w in candidates),
                                          max(w['bbox'][3] for w in candidates)]})
            for field in fields:
                footer_fields.setdefault(field['id'], []).append({
                    'page': number, 'matched': bool(story_ok), 'expected': str(number),
                    'normalized_text_start': start, 'normalized_text_end': end,
                    'part': name})
        offsets = [index for index in range(len(raw_text)) if index not in removed]
        cleaned = ''.join(raw_text[index] for index in offsets)
        reverse = {raw: index for index, raw in enumerate(offsets)}
        line_breaks = set()
        for previous, following in zip(words, words[1:]):
            start, end = previous['actual_end'], following['actual_start']
            separator = raw_text[start:end]
            if (separator.startswith('\n') and all(c in ' \t' for c in separator[1:])
                    and start in reverse
                    and previous['actual_start'] in reverse and following['actual_start'] in reverse
                    and following['bbox'][1] >= previous['bbox'][3] - 0.5):
                line_breaks.add(reverse[start])
        literal_spaces = {}
        evidence = physical.get('literal_space_evidence', {})
        if (evidence.get('status') == 'checked' and evidence.get('page') == number
                and evidence.get('raw_text_sha256') == sha256_bytes(raw_text.encode('utf-8'))
                and evidence.get('raw_words_sha256') == sha256_bytes(canonical_bytes(physical['words']))):
            for witness in evidence['witnesses']:
                start = witness['raw_line_break_start']
                position = reverse.get(start)
                if (position in line_breaks and raw_text[start:start + 1] == '\n'
                        and witness['preceding_word'] in words and witness['following_word'] in words
                        and witness['preceding_word']['actual_start'] in reverse
                        and witness['following_word']['actual_start'] in reverse):
                    literal_spaces[position] = witness
        result.append({'page': number, 'text': cleaned, 'raw_offsets': offsets,
                       'line_breaks': line_breaks, 'literal_spaces': literal_spaces})
    return {'matched': valid, 'pages': result, 'equivalences': mappings,
            'footer_fields': footer_fields, 'raw_words': raw_maps}


def _ordered_pdf_evidence(saved, texts, *, physical_pages=None, rendering_profile=None):
    """全文对齐保留技术字符；省略空格须由当前PDF字码和同一物理换行见证。"""
    expected = saved['visible_parts'].get('word/document.xml', '')
    blocks = [row for row in saved['text_blocks'] if row['part'] == 'word/document.xml']
    boundaries = {row['text_end'] for row in blocks}
    tabs = {row['text_offset']: row for row in saved['toc_tabs']
            if row['part'] == 'word/document.xml'}
    supported = not saved['unsupported_objects']
    footer_parts = {name: value for name, value in saved['visible_parts'].items()
                    if re.fullmatch(r'word/footer\d+\.xml', name) and value}
    header_parts = {name: value for name, value in saved['visible_parts'].items()
                    if re.fullmatch(r'word/header\d+\.xml', name) and value}
    if any(value and name != 'word/document.xml'
           and name not in footer_parts and name not in header_parts
           for name, value in saved['visible_parts'].items()):
        supported = False
    pages, mappings, repetitions, leaders, spans = [], [], [], [], []
    footer_fields, cursor, failed = {}, 0, False
    physical = (_physical_body(saved, texts, physical_pages, rendering_profile)
                if physical_pages is not None else None)
    if physical is not None:
        mappings.extend(physical['equivalences'])
        footer_fields = physical['footer_fields']
        failed = not physical['matched']
    for number, raw_text in enumerate(texts, 1):
        physical_page = physical['pages'][number - 1] if physical is not None else None

        def actual_range(start, end):
            if physical_page is None:
                return {'actual_start': start, 'actual_end': end}
            offsets = physical_page['raw_offsets']
            begin = offsets[start] if start < len(offsets) else len(_normalize(raw_text))
            finish = offsets[end - 1] + 1 if end > start else begin
            return {'actual_start': begin, 'actual_end': finish}

        page = physical_page['text'] if physical_page else _normalize(raw_text)
        page_end = len(page.rstrip('\n\f'))
        if page_end < len(page):
            mappings.append({'page': number, 'rule': 'page_text_terminator',
                             **actual_range(page_end, len(page))})
        page = page[:page_end]
        active = _story_parts(saved, number)
        if active is None:
            supported = False
        active_headers = ({name: value for name, value in header_parts.items()
                           if active and name == active['header']} if active is not None else header_parts)
        active_footers = ({name: value for name, value in footer_parts.items()
                           if active and name == active['footer']} if active is not None else footer_parts)
        for name, template in ({} if physical is not None else active_headers).items():
            header = template.rstrip('\n')
            if page.startswith(header + '\n'):
                mappings.append({'page': number, 'rule': 'declared_header', 'part': name,
                                 'actual_start': 0, 'actual_end': len(header) + 1})
                page = page[len(header) + 1:]
            else:
                failed = True
        for name, template in ({} if physical is not None else active_footers).items():
            fields = [row for row in saved['fields'] if row['part'] == name]
            valid = all(row['kind'] == 'PAGE' and row['parent_id'] is None for row in fields)
            footer = template
            for field in sorted(fields, key=lambda row: row['text_start'], reverse=True):
                footer = (footer[:field['text_start']] + str(number)
                          + footer[field['text_end']:])
            footer = footer.rstrip('\n')
            prefix = '\n' + footer
            matched = valid and bool(footer) and (page.endswith(prefix) or page == footer)
            start = len(page) - len(footer)
            if matched:
                page = page[:start].rstrip('\n')
                mappings.append({'page': number, 'rule': 'declared_footer', 'part': name,
                                 'actual_start': len(page), 'actual_end': page_end})
            else:
                failed = True
            for field in fields:
                footer_fields.setdefault(field['id'], []).append({
                    'page': number, 'matched': matched, 'expected': str(number),
                    'normalized_text_start': start, 'normalized_text_end': page_end})
        position = 0
        for index, table in enumerate(saved['tables'], 1):
            header = table['repeated_header']
            if (number > 1 and table['part'] == 'word/document.xml' and header
                    and table['text_start'] < cursor < table['text_end']
                    and not expected[cursor:].startswith(header)):
                header_blocks = [{'id': f'header-{index}-{part}', 'kind': 'paragraph', 'text': text}
                                 for part, text in enumerate(header.splitlines())]
                trial, local = 0, []
                for block in header_blocks:
                    end = _match_block(block['text'], page, trial, block, local)
                    if end is None:
                        break
                    trial = end
                    if trial < len(page) and page[trial] in '\n\t ':
                        trial += 1
                else:
                    position = trial
                    repetitions.append({'page': number, 'table': index, 'text': header,
                                        **actual_range(0, position)})
                    break
        clean, consumed_spaces = [], set()
        while position < len(page) and not failed:
            witness = (physical_page.get('literal_spaces', {}).get(position)
                       if physical_page else None)
            if witness is not None and position not in consumed_spaces:
                literal = witness['text']
                if expected[cursor:cursor + len(literal)] != literal:
                    failed = True
                    break
                for offset, glyph in enumerate(witness['glyphs']):
                    span = {'page': number, 'rule': 'pdf_literal_space_glyph',
                            'source_start': cursor + offset, 'source_end': cursor + offset + 1,
                            'actual_start': witness['raw_line_break_start'],
                            'actual_end': witness['raw_line_break_start'],
                            'raw_line_break_end': witness['raw_line_break_end'],
                            'pdf_sha256': physical_pages[number - 1]['literal_space_evidence']['pdf_sha256'],
                            'glyph': glyph, 'preceding_word': witness['preceding_word'],
                            'following_word': witness['following_word']}
                    spans.append(span)
                    mappings.append(span)
                clean.append(literal)
                cursor += len(literal)
                consumed_spaces.add(position)
            if cursor in boundaries and expected[cursor:cursor + 1] == '\n':
                start = position
                # 表格各单元格的段落分界可以被提取器排成空格或制表符。
                table_boundary = any(row['part'] == 'word/document.xml'
                                     and row['text_start'] <= cursor < row['text_end']
                                     for row in saved['tables'])
                if page[position] == '\n':
                    while position < len(page) and page[position] == '\n':
                        position += 1
                elif page[position] in ' \t':
                    position += 1
                mappings.append({'page': number, 'rule': 'table_cell_boundary' if table_boundary
                                 else 'paragraph_boundary', 'source_start': cursor,
                                 'source_end': cursor + 1, **actual_range(start, position)})
                cursor += 1
                if position == len(page):
                    break
                continue
            if cursor in tabs and expected[cursor:cursor + 1] == '\t':
                end = position
                while end < len(page) and page[end] in '. \t':
                    end += 1
                if end > position:
                    count = page[position:end].count('.')
                    leaders.append({'page': number, 'field_id': tabs[cursor]['field_id'],
                                    'text_offset': cursor, 'dots': count})
                    spans.append({'source_start': cursor, 'source_end': cursor + 1,
                                  'page': number, **actual_range(position, end)})
                    position, cursor = end, cursor + 1
                    continue
            if cursor < len(expected) and page[position] == expected[cursor]:
                actual_start = (physical_page['raw_offsets'][position]
                                if physical_page else position)
                spans.append({'source_start': cursor, 'source_end': cursor + 1,
                              'page': number, 'actual_start': actual_start,
                              'actual_end': actual_start + 1})
                clean.append(page[position])
                cursor, position = cursor + 1, position + 1
                continue
            block = next((row for row in blocks
                          if row['text_start'] < cursor < row['text_end']), None)
            if (block and _comparison_kind(block) == 'narrative' and page[position] == '\n'
                    and (physical_page is None or position in physical_page['line_breaks'])
                    and '\u2e80' <= expected[cursor - 1] <= '\uffff'
                    and '\u2e80' <= expected[cursor] <= '\uffff'):
                mappings.append({'page': number, 'block_id': block['id'],
                                 'rule': 'narrative_cjk_line_wrap', 'source_start': cursor,
                                 'source_end': cursor, **actual_range(position, position + 1)})
                position += 1
                continue
            if (physical_page and position in physical_page['line_breaks']
                    and page[position] == '\n' and cursor < len(expected)
                    and expected[cursor] not in '\t\n'):
                # PDF物理行分割不能吞掉源中的任何字符（含技术空格/换行）。
                mappings.append({'page': number, 'rule': 'coordinate_bound_line_wrap',
                                 'source_start': cursor, 'source_end': cursor,
                                 'actual_start': physical_page['raw_offsets'][position],
                                 'actual_end': physical_page['raw_offsets'][position] + 1})
                position += 1
                continue
            failed = True
        if (not failed and cursor not in boundaries and expected[cursor:cursor + 1] == '\n'
                and raw_text and (physical_page['text'] if physical_page else
                                  _normalize(raw_text))[page_end:page_end + 1] == '\n'):
            # 显式w:br恰好落在物理页末，必须与实际提取的换行一对一消费。
            actual_start = physical_page['raw_offsets'][page_end] if physical_page else page_end
            spans.append({'source_start': cursor, 'source_end': cursor + 1,
                          'page': number, 'actual_start': actual_start,
                          'actual_end': actual_start + 1})
            cursor += 1
        while cursor in boundaries and expected[cursor:cursor + 1] == '\n':
            mappings.append({'page': number, 'rule': 'paragraph_page_boundary',
                             'source_start': cursor, 'source_end': cursor + 1,
                             **actual_range(position, position)})
            cursor += 1
        pages.append(''.join(clean))
    return {'matched': bool(expected) and not failed and cursor == len(expected),
            'scope_supported': supported, 'pages': pages, 'removals': [],
            'repeated_table_headers': repetitions, 'toc_tab_leaders': leaders,
            'equivalences': mappings, 'character_spans': spans, 'footer_fields': footer_fields,
            'expected': expected, 'compared_source_characters': cursor,
            'physical_raw_words': physical['raw_words'] if physical else [],
            'physical_mapping': physical is not None}


def _field_pdf_span(field, ordered):
    value = _normalize(field['cached_result'])
    start, end = field.get('text_start', -1), field.get('text_end', -1)
    expected = ordered['expected']
    footer = ordered['footer_fields'].get(field['id'], [])
    if field['kind'] == 'PAGE' and footer:
        matched = ordered['matched'] and all(row['matched'] for row in footer)
        spans = [{key: row[key] for key in ('page', 'normalized_text_start', 'normalized_text_end')}
                 for row in footer] if matched else []
        return {'saved_cache_found_in_pdf_span': bool(matched), 'pdf_spans': spans,
                'pdf_cached_result': value if matched else None,
                'field_page': spans[0]['page'] if spans else None,
                'pdf_page_values': [row['expected'] for row in footer] if matched else []}
    matched = (ordered['matched'] and field['part'] == 'word/document.xml'
               and 0 <= start < end <= len(expected) and value == expected[start:end])
    spans = []
    if matched:
        selected = [row for row in ordered['character_spans']
                    if start <= row['source_start'] < end]
        for number in sorted({row['page'] for row in selected}):
            current = [row for row in selected if row['page'] == number]
            spans.append({'page': number,
                          'normalized_text_start': min(row['actual_start'] for row in current),
                          'normalized_text_end': max(row['actual_end'] for row in current)})
    return {'saved_cache_found_in_pdf_span': bool(matched), 'pdf_spans': spans,
            'pdf_cached_result': expected[start:end] if matched else None,
            'field_page': spans[0]['page'] if spans else None}


def _story_signature(state, part, *, include_cache=True):
    fields = [row for row in state['fields'] if row['part'] == part]
    text = state['visible_parts'].get(part, '')
    for field in sorted(fields, key=lambda row: row['text_start'], reverse=True):
        text = text[:field['text_start']] + '\x00FIELD\x00' + text[field['text_end']:]
    return (text, tuple((row['kind'], row['target'], row['instruction'],
                         row['cached_result'] if include_cache else None,
                         row['parent_id'] is not None) for row in fields))


def _field_correspondence(source, saved):
    originals = [row for row in source['fields'] if row['parent_id'] is None]
    finals, duplicates, issues, used = [], {}, [], set()
    source_sections, saved_sections = source.get('sections', []), saved.get('sections', [])
    part_map = {'word/document.xml': 'word/document.xml'}
    active_parts = set()
    if len(source_sections) == len(saved_sections) == 1:
        before, after = source_sections[0], saved_sections[0]
        if (before['first_page'] != after['first_page']
                or source.get('even_and_odd_headers') != saved.get('even_and_odd_headers')
                or before['page_start'] != after['page_start']
                or before['page_format'] != after['page_format']):
            issues.append('story_page_mapping_changed')
        slots = {'default'}
        if after['first_page']:
            slots.add('first')
        if saved.get('even_and_odd_headers'):
            slots.add('even')
        for kind in ('header', 'footer'):
            for slot in slots:
                old = before['references'].get((kind, slot))
                new = after['references'].get((kind, slot))
                if old and new:
                    part_map[old] = new
                    active_parts.add(new)
                    if (_story_signature(source, old, include_cache=False) !=
                            _story_signature(saved, new, include_cache=False)):
                        issues.append('story_template_changed')
                elif old or new:
                    issues.append('story_reference_changed')
    else:
        issues.append('story_sections_unsupported')
    for original in originals:
        target_part = part_map.get(original['part'], original['part'])
        candidates = [row for row in saved['fields'] if row['part'] == target_part
                      and row['parent_id'] is None and row['id'] not in used]
        final = candidates[0] if candidates else None
        finals.append(final)
        if final:
            used.add(final['id'])
    # 只接受未启用引用中的完整故事副本，不把新增或嵌套域当作刷新成功。
    referenced = ({part for part in saved_sections[0]['references'].values()}
                  if len(saved_sections) == 1 else set())
    for final in saved['fields']:
        if final['id'] in used:
            continue
        if final['parent_id'] is None and final['part'] in referenced - active_parts:
            candidates = [row for row in finals if row and row['part'] in active_parts
                          and _story_signature(saved, row['part']) ==
                              _story_signature(saved, final['part'])]
            index = [row['id'] for row in saved['fields']
                     if row['part'] == final['part']].index(final['id'])
            equivalent = [row for row in saved['fields'] if candidates
                          and row['part'] == candidates[0]['part']]
            if index < len(equivalent):
                duplicates[final['id']] = equivalent[index]['id']
    return originals, finals, duplicates, issues


def _field_evidence(source, saved, texts, destinations, *, physical_pages=None,
                    rendering_profile=None):
    """只有保存缓存、书签目标及PDF页面一致，才计实际刷新；不以退出码推断。"""
    rows, sequence = [], Counter()
    ordered = _ordered_pdf_evidence(saved, texts, physical_pages=physical_pages,
                                    rendering_profile=rendering_profile)
    originals, finals, duplicates, correspondence_issues = _field_correspondence(source, saved)
    global_issues = list(correspondence_issues)
    if len(originals) != len(source['fields']):
        global_issues.append('nested_source_field_unsupported')
    if (any(row is None for row in finals)
            or len(source['fields']) + len(duplicates) != len(saved['fields'])):
        global_issues.append('field_count_changed')
    if not ordered['matched']:
        global_issues.append('pdf_ordered_text_mismatch')
    if not ordered['scope_supported']:
        global_issues.append('unsupported_document_objects_partial')
    for index, original in enumerate(originals):
        final = finals[index] if index < len(finals) else None
        issues = []
        row = {'id': original['id'], 'part': original['part'],
               'kind': original['kind'], 'instruction': original['instruction'],
               'source_cached_result': original['cached_result'],
               'saved_instruction': final['instruction'] if final else None,
               'saved_cached_result': final['cached_result'] if final else None,
               'target': original['target'], 'target_text': None,
               'target_page': None, 'field_page': None,
               'cache_changed': bool(final and original['cached_result'] != final['cached_result'])}
        if final is None or (original['kind'], original['target']) != (final['kind'], final['target']):
            issues.append('field_missing_or_changed')
        else:
            def instruction_key(instruction):
                tokens = re.findall(r'"[^"]*"|\S+', instruction)
                return tokens[0].upper(), sorted(tokens[1:])
            if instruction_key(original['instruction']) != instruction_key(final['instruction']):
                issues.append('field_instruction_changed')
            value = _normalize(final['cached_result'])
            if not value:
                issues.append('saved_cache_empty')
            if not row['cache_changed'] and original['kind'] != 'PAGE':
                issues.append('field_refresh_not_observed')
            row.update(_field_pdf_span(final, ordered))
            row['saved_field_id'] = final['id']
            target = original['target']
            if original['kind'] in {'REF', 'PAGEREF'}:
                bookmark = saved['bookmarks'].get(target)
                row['target_text'] = bookmark['text'].strip() if bookmark else None
                row['target_page'] = destinations.get(target)
                if bookmark is None or not _normalize(bookmark['text']):
                    issues.append('target_missing_or_empty')
                if row['target_page'] is None:
                    issues.append('target_pdf_page_unverified')
                if original['kind'] == 'REF' and bookmark and value != _normalize(bookmark['text']).rstrip('\n'):
                    issues.append('saved_ref_cache_mismatch')
                if original['kind'] == 'PAGEREF' and value != str(row['target_page']):
                    issues.append('saved_pageref_cache_mismatch')
            elif original['kind'] == 'SEQ':
                sequence[(original['part'], target)] += 1
                row['expected_sequence'] = sequence[(original['part'], target)]
                if value != str(row['expected_sequence']):
                    issues.append('saved_sequence_cache_mismatch')
            elif original['kind'] == 'PAGE':
                if not re.fullmatch(r'word/footer\d+\.xml', original['part']):
                    issues.append('page_field_outside_footer')
                expected_pages = [str(page) for page in range(1, len(texts) + 1)
                                  if (_story_parts(saved, page) or {}).get('footer') == final['part']]
                if (not expected_pages or value not in expected_pages
                        or row.get('pdf_page_values') != expected_pages):
                    issues.append('saved_page_cache_or_pdf_mismatch')
            elif original['kind'] == 'TOC':
                entries, parsed_entries = [], []
                for line in final['cached_result'].splitlines():
                    match = re.fullmatch(r'(.+?)[\t ]+([1-9]\d*)', line.strip())
                    if match:
                        parsed_entries.append((_normalize(match[1]), int(match[2])))
                    elif line.strip():
                        parsed_entries.append(None)
                for entry_index, heading in enumerate(source['headings']):
                    anchors = [anchor for anchor in heading['anchors'] if anchor in destinations]
                    page = destinations[anchors[0]] if anchors else None
                    actual = parsed_entries[entry_index] if entry_index < len(parsed_entries) else None
                    entries.append({'text': heading['text'],
                                    'target': anchors[0] if anchors else None,
                                    'target_page': page,
                                    'saved_cache_matches': page is not None
                                    and actual == (_normalize(heading['text']), page)})
                row['toc_entries'] = entries
                if (not entries or len(entries) != len(parsed_entries)
                        or not all(entry['saved_cache_matches'] for entry in entries)):
                    issues.append('saved_toc_cache_mismatch')
            else:
                issues.append('unsupported_field')
            if not row['saved_cache_found_in_pdf_span']:
                issues.append('saved_cache_pdf_mismatch')
        row['issues'] = issues
        row['status'] = 'verified' if not issues else 'needs_review'
        rows.append(row)
    saved_results = []
    for final in saved['fields']:
        result = {**final, **_field_pdf_span(final, ordered)}
        counterpart = duplicates.get(final['id'], final['id'])
        corresponding = next((row for row in rows if row.get('saved_field_id') == counterpart), None)
        if final['id'] in duplicates and corresponding:
            result.update(_field_pdf_span(next(row for row in saved['fields']
                                               if row['id'] == counterpart), ordered))
            result['inactive_story_duplicate_of'] = counterpart
            result['duplicate_basis'] = 'inactive_section_reference_and_exact_story_field_structure'
        bookmark = saved['bookmarks'].get(final['target'])
        result['target_text'] = bookmark['text'].strip() if bookmark else None
        result['target_page'] = destinations.get(final['target'])
        result['status'] = corresponding['status'] if corresponding else 'needs_review'
        result['issues'] = (corresponding['issues'] if corresponding else
                            ['office_added_or_nested_field_unverified'])
        saved_results.append(result)
    if any(row['status'] == 'needs_review' for row in saved_results):
        global_issues.append('saved_field_requires_review')
    status = ('needs_review' if global_issues or any(row['issues'] for row in rows)
              else 'verified' if rows else 'not_applicable')
    return {'status': status, 'method': 'isolated_soffice_docx_save_then_pdf_export',
            'evidence_basis': 'saved_cache_target_pdf_destination_and_ordered_text_span_not_exit_code',
            'pdf_full_text_match': ordered['matched'],
            'pdf_repeated_table_headers': ordered['repeated_table_headers'],
            'pdf_toc_tab_leaders': ordered['toc_tab_leaders'],
            'text_equivalences': ordered['equivalences'],
            'text_scope_supported': ordered['scope_supported'],
            'saved_field_results': saved_results,
            'source_field_count': len(source['fields']), 'saved_field_count': len(saved['fields']),
            'fields': rows, 'source_fields': source['fields'],
            'saved_fields': saved['fields'], 'issues': global_issues,
            'professional_review': 'not_performed'}


def _file_record(target, path, limit, access):
    raw = access.read(path, limit)
    return {'path': path.relative_to(target).as_posix(),
            'bytes': len(raw), 'sha256': sha256_bytes(raw)}, raw


def parse_bbox_layout(raw: bytes) -> list[dict]:
    """有界解析Poppler的XHTML bbox；不加载DTD或展开实体。"""
    require(isinstance(raw, bytes) and len(raw) <= MAX_TEXT_BYTES,
            'standard_pdf_bbox_size')
    # Poppler固定的无内部子集DOCTYPE只是格式声明；任何实体或其他DTD均拒绝。
    clean = re.sub(br'<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1\.0 Transitional//EN"\s+'
                   br'"http://www\.w3\.org/TR/xhtml1/DTD/xhtml1-transitional\.dtd">',
                   b'', raw)
    document = _safe_xml(clean, 'standard_pdf_bbox_xml_invalid')

    def local(node):
        return node.tag.rsplit('}', 1)[-1]

    def numeric(node, names):
        try:
            values = [float(node.attrib[name]) for name in names]
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError('standard_pdf_bbox_coordinates_invalid') from exc
        require(all(math.isfinite(value) for value in values),
                'standard_pdf_bbox_coordinates_invalid')
        return values

    pages, count = [], 0
    for element in document.iter():
        if local(element) != 'page':
            continue
        width, height = numeric(element, ('width', 'height'))
        require(0 < width <= 20000 and 0 < height <= 20000,
                'standard_pdf_bbox_page_invalid')
        page = {'page': len(pages) + 1, 'width': width, 'height': height,
                'rotation': None, 'words': []}
        blocks = [node for node in element.iter() if local(node) == 'block']
        for block_index, block in enumerate(blocks, 1):
            lines = [node for node in block.iter() if local(node) == 'line']
            for line_index, line in enumerate(lines, 1):
                for node in line:
                    if local(node) != 'word':
                        continue
                    bbox = numeric(node, ('xMin', 'yMin', 'xMax', 'yMax'))
                    require(bbox[0] < bbox[2] and bbox[1] < bbox[3],
                            'standard_pdf_bbox_coordinates_invalid')
                    text = ''.join(node.itertext())
                    require(bool(text) and '\ufffd' not in text,
                            'standard_pdf_bbox_text_invalid')
                    page['words'].append({'text': text, 'bbox': bbox,
                                          'block': block_index, 'line': line_index,
                                          'order': count})
                    count += 1
                    require(count <= 100000, 'standard_pdf_bbox_word_limit')
        if not blocks:
            for node in element:
                if local(node) != 'word':
                    continue
                bbox = numeric(node, ('xMin', 'yMin', 'xMax', 'yMax'))
                require(bbox[0] < bbox[2] and bbox[1] < bbox[3],
                        'standard_pdf_bbox_coordinates_invalid')
                text = ''.join(node.itertext())
                require(bool(text) and '\ufffd' not in text,
                        'standard_pdf_bbox_text_invalid')
                page['words'].append({'text': text, 'bbox': bbox, 'order': count})
                count += 1
                require(count <= 100000, 'standard_pdf_bbox_word_limit')
        require(page['words'], 'standard_pdf_bbox_words_missing')
        pages.append(page)
        require(len(pages) <= MAX_PAGES_PER_DOCUMENT, 'standard_pdf_bbox_page_limit')
    require(pages, 'standard_pdf_bbox_pages_missing')
    return pages


def _bind_table_owners(pages, ordered, saved):
    """完整文字对齐后才把同坐标词框绑定到源表格单元格。"""
    if not ordered['matched']:
        return
    for page in pages:
        number = page['page']
        raw_words = ordered['physical_raw_words'][number - 1]
        spans = [span for span in ordered['character_spans'] if span['page'] == number]
        indexed = {}
        for word in raw_words:
            key = (word['text'], tuple(round(value, 6) for value in word['bbox']))
            indexed.setdefault(key, []).append(word)
        for word in page['words']:
            key = (word['text'], tuple(round(value, 6) for value in word['bbox']))
            candidates = indexed.get(key, [])
            if len(candidates) != 1:
                continue
            raw = candidates[0]
            mapped = [span for span in spans if raw['actual_start'] <= span['actual_start']
                      and span['actual_end'] <= raw['actual_end']]
            if not mapped:
                continue
            start = min(span['source_start'] for span in mapped)
            end = max(span['source_end'] for span in mapped)
            owners = [(index, cell) for index, table in enumerate(saved['tables'], 1)
                      if table['part'] == 'word/document.xml' for cell in table['cells']
                      if cell['text_start'] <= start < end <= cell['text_end']]
            if len(owners) == 1:
                index, cell = owners[0]
                word['table_cell'] = {'table': index, 'row': cell['row'],
                                      'column': cell['column'], 'source_start': start,
                                      'source_end': end,
                                      'binding': 'exact_text_span_and_identical_word_bbox'}


def check_geometry(pages: list[dict], rendering_profile: dict, *,
                   screenshots: list[dict] | None = None,
                   unsupported_objects: list | None = None) -> dict:
    """只核词框版心、重叠和序列；页图观察、图中文字和裁切不属于本核验。"""
    require(isinstance(rendering_profile, dict), 'standard_pdf_geometry_profile')
    geometry = rendering_profile.get('geometry', {})
    require(isinstance(geometry, dict), 'standard_pdf_geometry_profile')
    margins = geometry.get('body_margins_twips', rendering_profile.get('margin_twips'))
    if isinstance(margins, (int, float)) and not isinstance(margins, bool):
        margins = {key: margins for key in ('top', 'right', 'bottom', 'left')}
    require(isinstance(margins, dict) and set(margins) == {'top', 'right', 'bottom', 'left'}
            and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value) and value >= 0 for value in margins.values()),
            'standard_pdf_geometry_profile')
    shots = {row['page']: row for row in screenshots or []}
    diagnostics, page_results = [], []
    unsupported = list(unsupported_objects or [])
    total_words = 0

    def contains(area, bbox):
        tolerance = 0.5  # Poppler小数坐标舍入，不放宽整个字或整行。
        return (bbox[0] >= area[0] - tolerance and bbox[1] >= area[1] - tolerance
                and bbox[2] <= area[2] + tolerance and bbox[3] <= area[3] + tolerance)

    for page in pages:
        number, width, height = page['page'], page['width'], page['height']
        body = [margins['left'] / 20, margins['top'] / 20,
                width - margins['right'] / 20, height - margins['bottom'] / 20]
        require(body[0] < body[2] and body[1] < body[3], 'standard_pdf_geometry_page')
        allowed = [('body', body)]
        header_footer = rendering_profile.get('header_footer', {})
        for kind in ('header', 'footer'):
            distance = header_footer.get(kind + '_distance_twips')
            declared = header_footer.get('header_text') if kind == 'header' else header_footer.get('footer_field')
            if declared and isinstance(distance, (int, float)) and math.isfinite(distance):
                edge = distance / 20
                area = ([body[0], edge, body[2], body[1]] if kind == 'header' else
                        [body[0], body[3], body[2], height - edge])
                require(area[0] < area[2] and area[1] < area[3],
                        'standard_pdf_geometry_profile_area')
                allowed.append((kind, area))
        for kind in ('header', 'footer', 'figure', 'table'):
            for area in geometry.get(kind + '_areas', []):
                require(isinstance(area, list) and len(area) == 4
                        and all(isinstance(value, (int, float)) and math.isfinite(value)
                                for value in area)
                        and 0 <= area[0] < area[2] <= width
                        and 0 <= area[1] < area[3] <= height,
                        'standard_pdf_geometry_profile_area')
                allowed.append((kind, area))
        if page.get('rotation') not in (0,):
            unsupported.append('nonzero_page_rotation' if page.get('rotation') is not None
                               else 'page_rotation_unverified')
        words = page['words']
        total_words += len(words)
        current, previous = [], None

        def issue(rule, word, related=None):
            row = {'page': number, 'object': word.get('order', words.index(word)),
                   'rule': rule, 'bbox': list(word['bbox']), 'text': word['text']}
            if word.get('table_cell'):
                row['table_cell'] = dict(word['table_cell'])
            if related is not None:
                row['related_bbox'] = list(related['bbox'])
                row['related_text'] = related['text']
            shot = shots.get(number)
            if shot:
                row['screenshot'] = {'path': shot['path'], 'bbox_pixels': [
                    word['bbox'][0] * shot['width'] / width,
                    word['bbox'][1] * shot['height'] / height,
                    word['bbox'][2] * shot['width'] / width,
                    word['bbox'][3] * shot['height'] / height]}
            else:
                row['screenshot'] = None
            diagnostics.append(row)
            current.append(row)

        body_words = []
        for word in words:
            bbox = word['bbox']
            area = next((kind for kind, bounds in allowed if contains(bounds, bbox)), None)
            if area is None:
                issue('outside_permitted_area', word)
            if area != 'body':
                continue
            body_words.append(word)
            if previous is not None:
                old = previous['bbox']
                same_line = (word['block'], word['line']) == (previous['block'], previous['line'])
                current_cell, old_cell = word.get('table_cell'), previous.get('table_cell')
                next_cell = (current_cell and old_cell
                             and current_cell['table'] == old_cell['table']
                             and current_cell['row'] == old_cell['row']
                             and current_cell['column'] > old_cell['column']
                             and bbox[0] > old[0])
                if (bbox[1] < old[1] - 1 and not same_line and not next_cell
                        or same_line and bbox[0] < old[0] - 1):
                    issue('reading_order_regression', word, previous)
            previous = word
        # 仅比较独立词框；不拆同一word内部字形，也不把表格边框当文字。
        ordered = sorted(body_words, key=lambda row: row['bbox'][1])
        active = []
        for word in ordered:
            box = word['bbox']
            active = [old for old in active if old['bbox'][3] > box[1] + 0.5]
            for old in active:
                other = old['bbox']
                dx = min(box[2], other[2]) - max(box[0], other[0])
                dy = min(box[3], other[3]) - max(box[1], other[1])
                if dx > 0.5 and dy > 0.5:
                    smaller = min((box[2] - box[0]) * (box[3] - box[1]),
                                  (other[2] - other[0]) * (other[3] - other[1]))
                    if dx * dy >= smaller * 0.15:
                        issue('text_overlap', word, old)
            active.append(word)
        page_results.append({'page': number, 'width_points': width, 'height_points': height,
                             'rotation': page.get('rotation'), 'body_bbox': body,
                             'permitted_areas': [{'kind': kind, 'bbox': bbox} for kind, bbox in allowed],
                             'words_checked': len(words), 'diagnostic_count': len(current)})
    return {'status': 'needs_review' if diagnostics else 'partial' if unsupported else
            'checked_no_findings', 'method': 'word_bbox_layout_profile_geometry_v1',
            'coordinate_system': 'points_origin_top_left_unrotated',
            'pages': page_results, 'diagnostics': diagnostics,
            'unsupported_objects': unsupported,
            'coverage': {'pages': len(pages), 'words': total_words,
                         'text_bbox': 'checked', 'image_text': 'not_checked',
                         'image_crop': 'not_checked', 'visual_appearance': 'not_checked'},
            'visual_review': 'not_performed', 'professional_review': 'not_performed'}


def _inspect_pdf(target, role, source, tools, remaining_pages, *, source_state,
                 saved_state, rendering_profile, access):
    pdf = _path(target, f'pdf/{role}.pdf')
    pdf_record, pdf_raw = _file_record(target, pdf, MAX_FILE_BYTES, access)
    require(pdf_raw.startswith(b'%PDF-'), 'standard_pdf_header_invalid')
    info = access.run([tools['pdfinfo'], '-box', pdf])
    matches = re.findall(rb'^Pages:\s*(\d+)\s*$', info, re.MULTILINE)
    require(len(matches) == 1, 'standard_pdf_page_count_missing')
    pages = int(matches[0])
    require(0 < pages <= min(MAX_PAGES_PER_DOCUMENT, remaining_pages),
            'standard_pdf_page_count_limit')
    folder = _path(target, f'pages/{role}', missing=True)
    access.mkdir(folder)
    page_records, texts, records, bbox_pages, raw_pages = [], [], [pdf_record], [], []
    for number in range(1, pages + 1):
        stem = folder / f'page-{number:04d}'
        text_path, image_path = stem.with_suffix('.txt'), stem.with_suffix('.png')
        _plain(text_path, missing=True)
        access.run([tools['pdftotext'], '-f', number, '-l', number, '-raw',
                    '-enc', 'UTF-8', pdf, text_path])
        text_record, raw = _file_record(target, text_path, MAX_TEXT_BYTES, access)
        try:
            text = raw.decode('utf-8')
        except UnicodeError as exc:
            raise ContractError('standard_pdf_text_unreadable') from exc
        require(bool(text.strip()) and '\ufffd' not in text,
                'standard_pdf_text_unreadable')
        raw_bbox_path = stem.with_suffix('.raw-bbox.xhtml')
        _plain(raw_bbox_path, missing=True)
        access.run([tools['pdftotext'], '-f', number, '-l', number, '-raw', '-bbox',
                    '-enc', 'UTF-8', pdf, raw_bbox_path])
        raw_bbox_record, raw_bbox = _file_record(target, raw_bbox_path, MAX_TEXT_BYTES, access)
        raw_extracted = parse_bbox_layout(raw_bbox)
        require(len(raw_extracted) == 1, 'standard_pdf_bbox_page_mismatch')
        raw_extracted[0]['page'] = number
        raw_pages.append(raw_extracted[0])
        bbox_path = stem.with_suffix('.bbox.xhtml')
        _plain(bbox_path, missing=True)
        access.run([tools['pdftotext'], '-f', number, '-l', number, '-bbox-layout',
                    '-enc', 'UTF-8', pdf, bbox_path])
        bbox_record, bbox_raw = _file_record(target, bbox_path, MAX_TEXT_BYTES, access)
        extracted = parse_bbox_layout(bbox_raw)
        require(len(extracted) == 1, 'standard_pdf_bbox_page_mismatch')
        page_geometry = extracted[0]
        page_geometry['page'] = number
        page_info = access.run([tools['pdfinfo'], '-f', number, '-l', number, '-box', pdf])
        rotations = re.findall(rb'^(?:Page\s+\d+\s+rot|Page rot):\s*(-?\d+)\s*$',
                               page_info, re.MULTILINE)
        if len(rotations) == 1:
            page_geometry['rotation'] = int(rotations[0])
        page_geometry['pdfinfo_sha256'] = sha256_bytes(page_info)
        bbox_pages.append(page_geometry)
        _plain(image_path, missing=True)
        access.run([tools['pdftoppm'], '-f', number, '-l', number, '-singlefile',
                    '-scale-to', RENDER_SIZE, '-png', pdf, stem], timeout=RENDER_TIMEOUT)
        image_record, image = _file_record(target, image_path, MAX_IMAGE_BYTES, access)
        require(len(image) >= 33 and image[:16] == b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR',
                'standard_pdf_page_image_invalid')
        width, height = struct.unpack('>II', image[16:24])
        require(0 < width <= RENDER_SIZE and 0 < height <= RENDER_SIZE,
                'standard_pdf_page_image_dimensions')
        page_records.append({'page': number, 'text': text_record, 'image': image_record,
                             'bbox': bbox_record, 'raw_bbox': raw_bbox_record,
                             'width': width, 'height': height,
                             'width_points': page_geometry['width'],
                             'height_points': page_geometry['height'],
                             'rotation': page_geometry['rotation']})
        texts.append(text)
        records.extend([text_record, image_record, bbox_record, raw_bbox_record])
    literal_spaces = _pdf_literal_space_evidence(pdf_raw, texts, raw_pages)
    for page, evidence in zip(raw_pages, literal_spaces['pages']):
        page['literal_space_evidence'] = evidence
    expected = source_state['nonfield_fragments']
    ordered = _ordered_pdf_evidence(saved_state, texts, physical_pages=raw_pages,
                                    rendering_profile=rendering_profile)
    require(ordered['matched'], 'standard_pdf_text_coverage_incomplete')
    destinations, destination_record = {}, None
    if (source_state['fields'] or saved_state['fields'] or source_state['bookmarks']
            or saved_state['bookmarks']):
        destination_raw = access.run([tools['pdfinfo'], '-dests', pdf])
        try:
            destination_text = destination_raw.decode('utf-8')
        except UnicodeError as exc:
            raise ContractError('standard_pdf_destinations_unreadable') from exc
        for match in re.finditer(r'^\s*(\d+)\s+\[[^\r\n]*\]\s+"([^"\r\n]+)"\s*$',
                                 destination_text, re.MULTILINE):
            number, name = int(match[1]), match[2]
            require(1 <= number <= pages and name not in destinations,
                    'standard_pdf_destinations_invalid')
            destinations[name] = number
        destination_path = target / 'fields' / (role + '-destinations.txt')
        _plain(destination_path, missing=True)
        access.write(destination_path, destination_raw)
        destination_record, _ = _file_record(target, destination_path, MAX_MANIFEST_BYTES, access)
        records.append(destination_record)
    resolved = _bookmark_destinations(source_state, saved_state, destinations)
    fields = _field_evidence(source_state, saved_state, texts, resolved,
                              physical_pages=raw_pages, rendering_profile=rendering_profile)
    fields['pdf_destinations'] = destination_record
    fields['pdf_destination_names'] = destinations
    _bind_table_owners(bbox_pages, ordered, saved_state)
    geometry = check_geometry(bbox_pages, rendering_profile, screenshots=[
        {'page': row['page'], 'path': row['image']['path'],
         'width': row['width'], 'height': row['height']} for row in page_records],
        unsupported_objects=saved_state['unsupported_objects'])
    return {'role': role, 'input_docx': {
                'path': f'body/{role}.docx', 'bytes': len(source), 'sha256': sha256_bytes(source)},
            'pdf': pdf_record, 'total_pages': pages,
            'page_count_source': 'pdfinfo', 'pdfinfo_sha256': sha256_bytes(info),
            'text_sha256': sha256_bytes('\f'.join(texts).encode('utf-8')),
            'text_hash_method': 'utf8_page_text_joined_by_form_feed',
            'text_coverage': {'status': 'needs_review' if not fields['pdf_full_text_match'] else
                              'partial' if saved_state['unsupported_objects'] else 'complete',
                              'pages_extracted': pages, 'source_nonfield_fragments': len(expected),
                              'matched_nonfield_fragments': len(expected) if fields['pdf_full_text_match'] else None,
                              'scope': 'ordered_exact_technical_coordinate_bound_stories_line_wrap_literal_glyphs_fields_table_headers_toc',
                              'literal_space_evidence': literal_spaces,
                              'equivalences': fields['text_equivalences'],
                              'unsupported_objects': saved_state['unsupported_objects'],
                              'image_text': 'not_checked'},
            'pages': page_records, 'field_refresh': fields, 'geometry': geometry,
            'bookmark_pages': resolved,
            'visual_review': 'not_performed',
            'page_observation': {'status': 'not_performed', 'observer_type': None,
                                 'pages_observed': [], 'findings': []}}, records


def _apply_block_metadata(state, blocks):
    metadata = {row['id']: row for row in blocks if isinstance(row, dict) and 'id' in row}
    for row in state['text_blocks']:
        source = metadata.get(row['id'])
        if source is not None and row['kind'] != 'formula':
            for name in ('comparison_kind', 'text_type'):
                if name in source:
                    row[name] = source[name]
            if source.get('kind') in {'code', 'xml', 'path', 'identifier', 'example_data'}:
                row['kind'] = source['kind']
    return state


def convert(root: str | Path, package_dir: str, output: str, *,
            synthetic: bool = False, tool_paths: dict, admission: dict | None = None) -> dict:
    """隔离另存当前delivery版五文书并导出PDF、文字、bbox和逐页PNG。

    synthetic=True沿用显式合成路径；False要求目录包admission：root/package/
    output/manifest_sha256/inputs/sensitivity/purpose/permissions/environment。
    inputs以包内完整成员相对路径绑定原始字节SHA-256，包含manifest.json。
    可选source_inputs为案例根内、包外且不落入输出的规范相对路径→原始字节
    SHA-256字典；报告和原件分别明示，不从载荷补授权或复制原件到输出。
    真实根须独立于工具源码/安装根；每个数据边界以当时UTC复核六条宿主路径
    及local_read/local_process/copy/local_write，不认证声明者身份。
    tool_paths显式列本机soffice/pdfinfo/pdftotext/pdftoppm绝对路径；可提供同安装
    office_python经有界命名管道刷新。失败可留无清单部分产物，不覆盖、不外发。
    公式仅取正文直接段落中有效 OMML 的字符及结构摘要，PDF 仍要求字面顺序吻合。
    """
    require(type(synthetic) is bool, 'standard_pdf_synthetic_required')
    require(synthetic or isinstance(admission, dict), 'standard_pdf_synthetic_required')
    base = _root(root)
    access = _Access(base, package_dir, output, synthetic=synthetic, admission=admission)
    target = _path(base, output, missing=True)
    require(not target.exists(), 'output_exists')
    package, checked, payload, inputs, source_map = _package(base, package_dir, access)
    require(not target.is_relative_to(package) and not package.is_relative_to(target),
            'standard_pdf_output_overlaps_input')
    tools, tool_evidence = _tools(tool_paths, access)
    rendering = documents.document_profile(payload['profile'].get('rendering'))
    maps = source_map.get('documents', {})
    states = {role: _apply_block_metadata(_document_state(raw), maps.get(role, []))
              for role, raw in inputs.items()}
    require(all(field['kind'] in {'TOC', 'REF', 'SEQ', 'PAGEREF', 'PAGE'}
                for state in states.values() for field in state['fields']),
            'standard_pdf_source_field_unsupported')
    require(all(item['kind'] not in {'oMath', 'oMathPara'}
                for state in states.values() for item in state['unsupported_objects']),
            'standard_pdf_source_formula_unsupported')
    access.mkdir(target)
    for folder in ('pdf', 'pages', 'derived-docx', 'fields'):
        access.mkdir(target / folder)
    results, files, total_pages, total_bytes = [], [], 0, 0
    access.check('local_write', 'copy')
    with tempfile.TemporaryDirectory(prefix='dyz-standard-office-') as scratch:
        temporary = _root(scratch)
        access.pin(temporary)
        profile = temporary / 'profile'
        access.mkdir(profile)
        staged = temporary / 'input'
        access.mkdir(staged)
        for role, raw in inputs.items():
            access.write(staged / f'{role}.docx', raw, copying=True)
        office = [tools['soffice'], '-env:UserInstallation=' + profile.as_uri(),
                  '--headless', '--nologo', '--nodefault', '--norestore']
        layout_policy = None
        if rendering['profile_id'] in {'dyz-standard-internal-v2', 'dyz-standard-internal-v3'}:
            for raw in inputs.values():
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    styles = _safe_xml(archive.read('word/styles.xml'),
                                       'standard_pdf_document_xml_invalid')
                    declared = {row.get(_W + 'styleId'): row for row in styles.findall(_W + 'style')}
                    for name in rendering['sizes']:
                        style = declared.get(name)
                        for setting in ('autoSpaceDE', 'autoSpaceDN', 'overflowPunct'):
                            flag = style.find('./' + _W + 'pPr/' + _W + setting) if style is not None else None
                            require(flag is not None and flag.get(_W + 'val') in {'0', 'false', 'off'},
                                    'standard_pdf_v2_layout_policy_missing')
            layout_policy = {'profile_id': rendering['profile_id'],
                             'source_ooxml_false': ['autoSpaceDE', 'autoSpaceDN', 'overflowPunct'],
                             'uno_properties': {'ParaIsCharacterDistance': False,
                                                'ParaIsHangingPunctuation': False},
                             'reason': 'office_import_does_not_preserve_explicit_source_false'}
        refresh_method, layout_evidence = _refresh_docx(
            temporary, staged, target / 'derived-docx', tools, standards_delivery.ROLES,
            access, layout_policy=layout_policy)
        saved_states, derived_records = {}, {}
        pdf_inputs = temporary / 'pdf-input'
        access.mkdir(pdf_inputs)
        for role in standards_delivery.ROLES:
            record, raw = _file_record(target, target / 'derived-docx' / (role + '.docx'),
                                       MAX_FILE_BYTES, access)
            state = _apply_block_metadata(_document_state(raw), maps.get(role, []))
            require(all(item['kind'] not in {'oMath', 'oMathPara'} for item in state['unsupported_objects'])
                    and states[role]['formula_structure_sha256s'] == state['formula_structure_sha256s'],
                    'standard_pdf_derived_formula_changed')
            _text_coverage(states[role]['nonfield_fragments'],
                           '\n'.join(state['nonfield_fragments']),
                           'standard_pdf_derived_body_incomplete')
            require(states[role]['nonfield_fragments'] == state['nonfield_fragments'],
                    'standard_pdf_derived_body_changed')
            saved_states[role], derived_records[role] = state, record
            access.write(pdf_inputs / (role + '.docx'), raw, copying=True)
        if not layout_evidence:
            access.run([*office, '--convert-to',
                        'pdf:writer_pdf_Export:{"ExportBookmarksToPDFDestination":{"type":"boolean","value":"true"}}',
                        '--outdir', target / 'pdf',
                        *(pdf_inputs / f'{role}.docx' for role in standards_delivery.ROLES)])
        for role in standards_delivery.ROLES:
            row, records = _inspect_pdf(target, role, inputs[role], tools,
                                        MAX_TOTAL_PAGES - total_pages,
                                        source_state=states[role], saved_state=saved_states[role],
                                        rendering_profile=rendering, access=access)
            row['derived_docx'] = derived_records[role]
            row['derived_from_sha256'] = sha256_bytes(inputs[role])
            row['derived_nonfield_body_preserved'] = True
            row['nonfield_body_preserved'] = row['text_coverage']['status'] == 'complete'
            row['field_refresh']['method'] = refresh_method
            row['office_layout_compatibility'] = layout_evidence.get(role, {
                'status': 'not_applied', 'profile_id': rendering['profile_id']})
            row['pdf_input'] = 'derived_docx'
            records.append(derived_records[role])
            total_pages += row['total_pages']
            total_bytes += sum(record['bytes'] for record in records)
            require(total_bytes <= MAX_OUTPUT_BYTES, 'standard_pdf_output_too_large')
            results.append(row)
            files.extend(records)
        access.check('local_read', 'local_write')
        access.identities = {path: value for path, value in access.identities.items()
                             if not path.is_relative_to(temporary)}
    access.check('local_read', 'local_process', 'copy')
    current = standards_delivery.verify(base, payload, package_dir, synthetic=synthetic,
                                        admission=access.delivery_admission(payload))
    require(current['manifest_sha256'] == checked['manifest_sha256'],
            'standard_pdf_input_changed')
    access.check('local_read')
    trace_raw = access.read(package / 'internal/source-trace.json', MAX_FILE_BYTES)
    try:
        source_traces = strict_json_loads(trace_raw.decode('utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ContractError('standard_pdf_source_trace_invalid') from exc
    require(isinstance(source_traces, list) and all(isinstance(row, dict) for row in source_traces),
            'standard_pdf_source_trace_invalid')
    source_trace_pages = []
    by_role = {row['role']: row for row in results}
    for trace in source_traces:
        locations = []
        for location in trace.get('final_locations', []):
            require(isinstance(location, dict), 'standard_pdf_source_trace_invalid')
            document = by_role.get(location.get('document_role'))
            bookmark = location.get('bookmark')
            page = document['bookmark_pages'].get(bookmark) if document else None
            locations.append({**location, 'page': page,
                              'page_binding': 'pdf_bookmark_destination' if page is not None
                              else 'not_verified',
                              'page_status': 'verified_pdf_destination' if page is not None
                              else 'not_verified',
                              'pdf': document['pdf']['path'] if document else None,
                              'semantic_review': 'not_performed'})
        source_trace_pages.append({**trace, 'final_locations': locations})
    actual = set()
    for path in target.rglob('*'):
        info = _plain(path)
        if stat.S_ISREG(info.st_mode):
            actual.add(path.relative_to(target).as_posix())
    require(actual == {row['path'] for row in files}, 'standard_pdf_output_members_changed')
    for row in files:
        raw = access.read(_path(target, row['path']), max(MAX_FILE_BYTES, MAX_IMAGE_BYTES))
        require(len(raw) == row['bytes'] and sha256_bytes(raw) == row['sha256'],
                'standard_pdf_output_changed')
    fields_need_review = any(row['field_refresh']['status'] == 'needs_review' for row in results)
    needs_review = fields_need_review or any(
        row['geometry']['status'] in {'needs_review', 'partial'}
        or row['text_coverage']['status'] != 'complete' for row in results)
    report = {
        'generator': 'dyz-standard-pdf', 'generator_version': VERSION,
        'mode': 'synthetic' if synthetic else 'authorized_case',
        'sensitivity': access.sensitivity, 'purpose': access.purpose,
        'admission': None if synthetic else {
            'sha256': access.policy_hash, 'manifest_sha256': admission['manifest_sha256'],
            'inputs': dict(access.members), 'source_inputs': dict(access.source_inputs),
            'sensitivity': access.sensitivity,
            'purpose': access.purpose, 'time_source': 'current_utc_at_each_boundary',
            'identity_verification': 'caller_responsibility'},
        'status': 'needs_review' if needs_review else 'structure_checked_needs_visual_review',
        'source_manifest_sha256': checked['manifest_sha256'],
        'source_generator_version': standards_delivery.VERSION,
        'input_hash': checked['input_hash'], 'tools': tool_evidence,
        'rendering_profile': rendering,
        'total_documents': len(results), 'total_pages': total_pages,
        'machine_checks': 'needs_review' if needs_review else 'completed_no_issues',
        'field_refresh': 'needs_review' if fields_need_review else
                         'verified' if any(row['field_refresh']['fields'] for row in results)
                         else 'not_applicable',
        'geometry': 'needs_review' if any(row['geometry']['status'] == 'needs_review' for row in results)
                    else 'partial' if any(row['geometry']['status'] == 'partial' for row in results)
                    else 'checked_no_findings',
        'documents': results, 'files': sorted(files, key=lambda row: row['path']),
        'source_trace_pages': source_trace_pages,
        'source_trace_sha256': sha256_bytes(trace_raw),
        'visual_review': 'not_performed', 'professional_review': 'not_performed',
        'page_observation': {'status': 'not_performed', 'observer_type': None,
                             'pages_observed': [], 'findings': []},
        'official_status': 'not_asserted', 'external_action': 'not_performed',
    }
    access.write(target / 'manifest.json', canonical_bytes(report) + b'\n')
    return report
