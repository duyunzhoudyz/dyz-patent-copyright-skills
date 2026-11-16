"""合成软件实际版本变化：跨入口行为、旧版保持与失效验证。"""
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import documents
from tools.core import ContractError


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills/dyz-software/resources/harbor-demo/v1.3"


class HarborVersionChangeTests(unittest.TestCase):
    def probe(self, code, *arguments, source=SOURCE):
        setup = "import sys,json,io;sys.path.insert(0,sys.argv[1]);\n"
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-I", "-S", "-c", setup + code,
             str(source), *arguments], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def test_sort_is_optional_and_preserves_values_without_natural_sorting(self):
        rows = [{"id": key, "label": 'a,"b"', "value": i}
                for i, key in enumerate(("2", "10", "a", "A", "中", " A"))]
        result = self.probe(
            "from core import convert,VERSION\n"
            "raw=sys.argv[2].encode('utf-8')\n"
            "print(json.dumps({'version':VERSION,'default':convert(raw),"
            "'sorted':convert(raw,sort_by_id=True),'empty':convert(b'[]',sort_by_id=True)}))",
            json.dumps(rows, ensure_ascii=True))
        self.assertEqual("1.3", result["version"])
        self.assertEqual(rows, list(self._records(result["default"][0])))
        sorted_rows = list(self._records(result["sorted"][0]))
        self.assertEqual([" A", "10", "2", "A", "a", "中"], [r["id"] for r in sorted_rows])
        self.assertEqual({r["id"]: r for r in rows}, {r["id"]: r for r in sorted_rows})
        self.assertEqual(6, result["sorted"][1])
        self.assertEqual(["id,label,value\n", 0], result["empty"])

    @staticmethod
    def _records(text):
        for row in csv.DictReader(io.StringIO(text)):
            row["value"] = int(row["value"])
            yield row

    def test_invalid_complete_batch_creates_no_cli_output(self):
        cases = [
            ([{"id": "B", "label": "x", "value": 1}, {"id": "B", "label": "y", "value": 2}], "duplicate_id"),
            ([{"id": "B", "label": "x", "value": 1}, {"id": "A", "label": "y", "value": True}], "invalid_value"),
            ([{"id": "B", "label": "x", "value": 1, "extra": 2}], "unknown_field"),
        ]
        with tempfile.TemporaryDirectory(prefix="dyz-harbor13-invalid-") as folder:
            base = Path(folder)
            for index, (rows, error) in enumerate(cases):
                with self.subTest(error=error):
                    src, dst = base / f"{index}.json", base / f"{index}.csv"
                    src.write_text(json.dumps(rows), encoding="utf-8")
                    result = subprocess.run([sys.executable, "-X", "utf8", "-E", "-s", "-S", str(SOURCE / "cli.py"),
                                             str(src), str(dst), "--strict", "--sort-by-id"],
                                            capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertEqual(error + "\n", result.stderr)
                    self.assertFalse(dst.exists())

    def test_cli_sort_and_exclusive_new_file(self):
        with tempfile.TemporaryDirectory(prefix="dyz-harbor13-cli-") as folder:
            base = Path(folder); src, dst = base / "in.json", base / "new.csv"
            src.write_text('[{"id":"B","label":"x","value":2},{"id":"A","label":"y","value":1}]', encoding="utf-8")
            args = [sys.executable, "-X", "utf8", "-E", "-s", "-S", str(SOURCE / "cli.py")]
            result = subprocess.run([*args, str(src), str(dst), "--sort-by-id"], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(b"id,label,value\nA,y,1\nB,x,2\n", dst.read_bytes())
            result = subprocess.run([*args, str(src), str(dst), "--sort-by-id"], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(3, result.returncode)
            self.assertEqual("output_exists\n", result.stderr)
            self.assertEqual(b"id,label,value\nA,y,1\nB,x,2\n", dst.read_bytes())

    def test_http_sort_and_strict_flags_are_independent_and_order_independent(self):
        result = self.probe(
            "from api import application\n"
            "raw=b'[{\"id\":\"B\",\"label\":\"x\",\"value\":2},{\"id\":\"A\",\"label\":\"y\",\"value\":1}]'\n"
            "out=[]\n"
            "for query in ('','strict=1','sort_by_id=0','sort_by_id=1','strict=1&sort_by_id=1','sort_by_id=1&strict=1'):\n"
            "    head=[]\n"
            "    env={'PATH_INFO':'/convert','REQUEST_METHOD':'POST','QUERY_STRING':query,'CONTENT_TYPE':'application/json',"
            "'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw)}\n"
            "    body=b''.join(application(env,lambda status,headers:head.append(status))).decode()\n"
            "    out.append({'query':query,'status':head[0],'body':body})\n"
            "print(json.dumps(out))")
        for row in result:
            self.assertEqual("200 OK", row["status"])
            order = [r["id"] for r in self._records(row["body"])]
            self.assertEqual(["A", "B"] if "sort_by_id=1" in row["query"] else ["B", "A"], order)

    def test_invalid_http_options_do_not_read_body(self):
        result = self.probe(
            "from api import application\n"
            "class Unreadable:\n"
            "    def read(self,n): raise AssertionError('invalid query read body')\n"
            "out=[]\n"
            "for query in ('sort_by_id=2','sort_by_id=','sort_by_id','order=id','strict=0&strict=1',"
            "'sort_by_id=1&sort_by_id=1','strict=1&sort_by_id=1&extra=0','strict=1&&sort_by_id=1'):\n"
            "    head=[]\n"
            "    env={'PATH_INFO':'/convert','REQUEST_METHOD':'POST','QUERY_STRING':query,'wsgi.input':Unreadable()}\n"
            "    body=b''.join(application(env,lambda status,headers:head.append(status)))\n"
            "    out.append([head[0],json.loads(body)])\n"
            "print(json.dumps(out))")
        self.assertEqual([["400 Bad Request", {"error": "invalid_query"}]] * 8, result)

    def test_gui_version_and_local_request_boundaries(self):
        result = self.probe(
            "from gui import application\n"
            "out=[]\n"
            "for path,host,origin in (('/version','127.0.0.1:1234',None),('/','127.0.0.1:1234',None),"
            "('/version','other.invalid',None),('/version','127.0.0.1:1234','https://other.invalid')):\n"
            "    head=[];env={'PATH_INFO':path,'REQUEST_METHOD':'GET','HTTP_HOST':host,'SERVER_PORT':'1234'}\n"
            "    if origin is not None: env['HTTP_ORIGIN']=origin\n"
            "    body=b''.join(application(env,lambda status,headers:head.append(status))).decode()\n"
            "    out.append([head[0],body])\n"
            "print(json.dumps(out))")
        self.assertEqual({"name": "港湾记录整理器", "version": "1.3"}, json.loads(result[0][1]))
        self.assertIn('id="sort"', result[1][1])
        self.assertEqual(["403 Forbidden", "403 Forbidden"], [r[0] for r in result[2:]])

    def test_legacy_default_output_is_retained_and_legacy_version_is_separate(self):
        code = ("from core import convert,VERSION\n"
                "print(json.dumps({'version':VERSION,'csv':convert(b'[{\"id\":\"B\",\"label\":\"x\",\"value\":2},"
                "{\"id\":\"A\",\"label\":\"y\",\"value\":1}]',strict=True)[0]}))")
        old = self.probe(code, source=SOURCE.parent / "v1.2")
        new = self.probe(code)
        self.assertEqual("1.2", old["version"])
        self.assertEqual("1.3", new["version"])
        self.assertEqual(old["csv"], new["csv"])

    def test_current_source_mapping_covers_actual_bytes_in_all_five_files(self):
        folder = SOURCE.parent.parent / "harbor-delivery-v1.3"
        facts = json.loads((folder / "facts.json").read_text(encoding="utf-8"))
        mapping = json.loads((folder / "source-lines.json").read_text(encoding="utf-8"))
        export = (folder / "source.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual("1.3", facts["version"])
        self.assertIsNone(facts["applicant"])
        self.assertEqual(266, facts["physical_lines"])
        self.assertEqual(266, len(mapping))
        self.assertEqual(266, len({(r["source"], r["line"]) for r in mapping}))
        source_lines = {}
        for item in facts["source_files"]:
            raw = (SOURCE / item["file"]).read_bytes()
            self.assertEqual(item["sha256"], hashlib.sha256(raw).hexdigest())
            source_lines[item["file"]] = raw.decode("utf-8").splitlines()
            self.assertEqual(item["physical_lines"], len(source_lines[item["file"]]))
        for row in mapping:
            original = source_lines[row["source"]][row["line"] - 1]
            self.assertEqual(f'[{row["source"]}:{row["line"]:03}] {original}', export[row["export_line"] - 1])
        for image in facts["screenshots"]:
            self.assertEqual(image["sha256"], hashlib.sha256((folder / image["path"]).read_bytes()).hexdigest())

    def test_old_material_is_not_accepted_as_new_and_bound_source_edit_rejects_old(self):
        base = Path("skills/dyz-software/resources")
        for name in ("source", "manual", "form"):
            with self.subTest(document=name), tempfile.TemporaryDirectory(prefix="dyz-harbor13-binding-") as folder:
                root = Path(folder)
                old = json.loads((ROOT / base / "harbor-delivery-v1.2" / f"{name}-input.json").read_text(encoding="utf-8"))
                new = json.loads((ROOT / base / "harbor-delivery-v1.3" / f"{name}-input.json").read_text(encoding="utf-8"))
                for entry in [*old["sources"], *old["dependencies"], *new["sources"], *new["dependencies"]]:
                    target = root / entry["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((ROOT / entry["path"]).read_bytes())
                documents.build(root, old, "old-output", synthetic=True)
                old_bytes = (root / "old-output/body/document.docx").read_bytes()
                documents.verify(root, old, "old-output", synthetic=True)
                with self.assertRaisesRegex(ContractError, "^document_input_binding_changed$"):
                    documents.verify(root, new, "old-output", synthetic=True)
                documents.build(root, new, "new-output", synthetic=True)
                documents.verify(root, new, "new-output", synthetic=True)
                old_source = root / base / "harbor-demo/v1.2/core.py"
                old_source.write_bytes((SOURCE / "core.py").read_bytes())
                with self.assertRaisesRegex(ContractError, "^document_source_changed$"):
                    documents.build(root, old, "stale-source-output", synthetic=True)
                self.assertFalse((root / "stale-source-output").exists())
                self.assertEqual(old_bytes, (root / "old-output/body/document.docx").read_bytes())

    def test_current_material_dependencies_reject_changed_facts_map_or_screenshot(self):
        base = Path("skills/dyz-software/resources/harbor-delivery-v1.3")
        for name in ("source", "manual", "form"):
            spec = json.loads((ROOT / base / f"{name}-input.json").read_text(encoding="utf-8"))
            for changed in ("facts.json", "source-lines.json", "gui-sorted.png"):
                with self.subTest(document=name, changed=changed), tempfile.TemporaryDirectory(prefix="dyz-harbor13-deps-") as folder:
                    root = Path(folder)
                    for entry in [*spec["sources"], *spec["dependencies"]]:
                        target = root / entry["path"]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes((ROOT / entry["path"]).read_bytes())
                    documents.resolve_document(root, spec)
                    target = root / base / changed
                    target.write_bytes(target.read_bytes() + b"\nchanged")
                    with self.assertRaisesRegex(ContractError, "^document_source_changed$"):
                        documents.build(root, spec, "changed-output", synthetic=True)
                    self.assertFalse((root / "changed-output").exists())


if __name__ == "__main__":
    unittest.main()
