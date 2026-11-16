"""仅创建合成浏览器验收材料；可选服务只暴露本次生成的HTML字节。"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from tools.core import digest, sha256_bytes, write_new_json
from tools.patent import run as patent_run
from tools.rendering import preview_scope, render_preview, write_preview
from tools.software import run as software_run
from tools.standards import run as standards_run


def synthetic_sources() -> dict[str, bytes]:
    """调用三业务真实工具生成候选；不读取任何私有材料或上游研究文件。"""
    common = {"sensitivity": "synthetic", "adaptation": {
        "jurisdiction": "unverified", "right_type": "invention",
        "domain": "synthetic-control", "stage": "internal_draft"}}
    flow = {**common, "nodes": [
        {"id": "s", "kind": "start", "label": "开始"},
        {"id": "a", "kind": "decision", "label": "输入有效？"},
        {"id": "ok", "kind": "end", "label": "成功：记录结果"},
        {"id": "bad", "kind": "end", "label": "失败：停止并报告"}],
        "edges": [{"from": "s", "to": "a", "label": "检查"},
                  {"from": "a", "to": "ok", "label": "是", "outcome": "success"},
                  {"from": "a", "to": "bad", "label": "否", "outcome": "failure"}]}
    good = patent_run("FIG-01", flow)["artifacts"]["svg"]
    flow["nodes"][1]["label"] = "这是用于验证多行边界的合成长中文标签必须检查每一个字形是否超出节点矩形边界而不能仅比较文本锚点"
    long = patent_run("FIG-01", flow)["artifacts"]["svg"]
    clipped = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 80">'
               '<rect x="5" y="5" width="150" height="70" fill="white" stroke="black"/>'
               '<text x="100" y="40" font-size="20">合成长中文标签在导出右边界发生明显裁切</text></svg>')
    standard = standards_run("STD-05", {"project_id": "SYNTHETIC-RENDER", "version": "1",
        "adaptation": {"organization": "SYNTHETIC-ORG", "standard_type": "product",
                       "domain": "synthetic_sensor", "stage": "working_draft"},
        "clauses": [{"id": "C-1", "text": "传感器应记录测量时间。", "strength": "requirement",
                     "kind": "normative", "source": "synthetic-requirement-v1#paragraph-1",
                     "conditions": ["工作温度20摄氏度"], "exceptions": ["维护模式除外"],
                     "method_ids": ["M-1"], "quantities": [{"id": "Q-1", "value": 10,
                     "unit": "ms", "tolerance": 1, "source": "synthetic-requirement-v1#quantity"}]}]
        })["artifacts"]["draft_markdown"]
    context = {"environment": {}, "permissions": [{"action": "local_read", "purpose": "render_demo",
        "recipient": "local_tool", "decision": "allow", "authority_evidence": "synthetic-consent",
        "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2027-01-01T00:00:00Z"}],
        "sensitivity": "synthetic", "purpose": "render_demo", "now": "2026-10-31T10:00:00Z"}
    scope = software_run("SW-01", {"context": context,
        "metadata": {"software_id": "demo", "name": "合成计数器", "version": "1.0",
                     "runtime_environment": {"description": "Python 3.11 CLI", "evidence_id": "synthetic-env"},
                     "completed_date": {"value": "2026-10-01", "evidence_id": "synthetic-date"},
                     "published_date": {"value": "2026-10-02", "evidence_id": "synthetic-publication"}},
        "components": [{"id": "cli", "kind": "standalone", "version": "1.0", "origin": "own",
                        "claim": ["本版命令表达"], "exclusions": ["Python运行时"],
                        "subjects": [{"subject_id": "demo-owner", "basis": "合成合同",
                                      "evidence_id": "synthetic-contract"}]}]})["artifacts"]
    manual = software_run("SW-04", {"context": context, "scope": scope, "mode": "CLI",
        "facts": [{"id": "f1", "text": "仅接收合成整数，不联网。", "evidence_id": "synthetic-fact"}],
        "operations": [{"id": "count", "input": "python counter.py 1 2 3",
                        "expected_output": "3", "failure": "非整数输入时报告错误并停止。",
                        "evidence_id": "synthetic-operation"}]})["artifacts"]["markdown"]
    table = ("# 合成条件表\n\n| 项目 | 条件 | 例外与容差 |\n| --- | --- | --- |\n"
             "| 时延 | 仅当正常运行 | 维护模式除外；10 ms ±1 ms |\n\n"
             "## CLI说明\n执行 `python counter.py`；预期不是实际运行结果。\n")
    source = "\n".join(f"print('合成第{i}行：条件、例外、容差不应删减')" for i in range(1, 86))
    return {name: text.encode("utf-8") for name, text in {
        "flow.svg": good, "long-label.svg": long, "clipped.svg": clipped,
        "standard.md": standard, "manual.md": manual, "table.md": table,
        "source.txt": source}.items()}


def create_demo(output: Path) -> tuple[dict, dict[str, bytes]]:
    """必须给全新的输出目录，保留既有材料；哈希来自这次实际生成的业务字节。"""
    output.mkdir(parents=True, exist_ok=False)
    sources = synthetic_sources()
    manifest = {"mode": "synthetic", "files": [
        {"name": name, "sha256": sha256_bytes(raw)} for name, raw in sorted(sources.items())]}
    package_hash = digest(manifest)
    pages, records = {}, []
    for name, raw in sources.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)
        preview = render_preview(name, raw, package_hash)
        html_name = name + ".html"
        write_preview(output, html_name, preview)
        pages["/" + html_name] = preview["html"].encode("utf-8")
        records.append({"name": name, "html": html_name, "scope": preview_scope(name),
                        "source_sha256": preview["source_sha256"],
                        "rendered_artifact_hash": preview["rendered_artifact_hash"],
                        "preview_status": preview["status"], "preview_issues": preview["issues"]})
    report = {"mode": "synthetic", "manifest": manifest, "manifest_hash": package_hash,
              "files": records, "rendering": "not_executed", "professional_review": "not_performed"}
    write_new_json(output, "manifest.json", report)
    return report, pages


def serve(pages: dict[str, bytes]) -> None:
    """临时loopback仅GET本次内存HTML，无目录列表、静态文件读取或POST。"""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            content = pages.get(self.path)
            if content is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        for path in pages:
            print(f"http://127.0.0.1:{server.server_port}{path}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="只生成合成渲染验收材料")
    parser.add_argument("--output", required=True)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    report, pages = create_demo(Path(args.output))
    print(json.dumps({"manifest_hash": report["manifest_hash"],
                      "preview_statuses": {f["name"]: f["preview_status"] for f in report["files"]}},
                     ensure_ascii=False), flush=True)
    if args.serve:
        serve(pages)


if __name__ == "__main__":
    main()
