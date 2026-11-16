"""Typed reading scope, unknowns, version attribution and actual DOCX guards."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools import documents, fidelity
from tools.core import ContractError, canonical_bytes, sha256_bytes


def record(identity="E1", version="A2", total=13, ranges=None, **changes):
    return {"subject": {"document_id": identity, "version": version}, "medium": "pdf", "unit": "physical_page",
            "operation": "visual_review", "origin": "reported", "event_id": "演示研究", "state": "known",
            "total": total, "ranges": [[1, 1], [4, 4], [6, 13]] if ranges is None else ranges, **changes}


def example(rows=None):
    rows = rows if rows is not None else [record(), record("E2", "A1", 38, [[1, 1], [19, 38]])]
    serialized = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows]
    text = "\n".join(serialized) + "\n"
    doc = {"id": "Evidence", "role": "source", "version": "v1", "text": text,
           "sha256": sha256_bytes(text.encode("utf-8"))}
    readings, offset = [], 0
    for n, value in enumerate(serialized, 1):
        readings.append({"id": "R" + str(n), "citation": {"document_id": "Evidence", "start": offset,
            "end": offset + len(value), "quote": value}})
        offset += len(value) + 1
    statements = [{"id": "S" + str(n), "kind": "single", "reading_ids": ["R" + str(n)]}
                  for n in range(1, len(rows) + 1)]
    if len(rows) > 1:
        statements.append({"id": "Total", "kind": "aggregate", "reading_ids": [r["id"] for r in readings]})
    return {"documents": [doc], "readings": readings, "statements": statements}


def expected(subjects, covered, total):
    return {"subjects": [{"document_id": identity, "version": version} for identity, version in subjects],
            "covered": covered, "total": total}


class ReadingScopeTests(unittest.TestCase):
    def audit(self, value=None, **kwargs):
        return fidelity.audit_reading_scope(example() if value is None else value, **kwargs)

    def codes(self, report):
        return {row["code"] for row in report["issues"]}

    def test_single_sources_and_explicit_aggregate_have_exact_projections(self):
        out = self.audit()
        self.assertEqual("checked", out["status"])
        self.assertEqual([(10, 13), (21, 38), (31, 51)], [(s["covered"], s["total"]) for s in out["statements"]])
        self.assertEqual("转述记录〔演示研究〕：E1（A2）PDF目视覆盖10/13页。", out["statements"][0]["projection"])
        self.assertEqual("转述记录〔演示研究〕：E1（A2）＋E2（A1）PDF目视合计覆盖31/51页（仅所列版本）。", out["statements"][2]["projection"])
        self.assertFalse(out["natural_language_verified"])
        self.assertEqual("not_performed", out["evidence_authentication"])
        self.assertEqual("not_performed", out["professional_review"])

    def test_r28_combined_count_cannot_be_attributed_to_single_A1(self):
        value = example()
        value["statements"][1]["expected"] = expected([("E2", "A1")], 31, 51)
        out = self.audit(value)
        self.assertEqual("blocked", out["status"])
        self.assertIn("reading_count_mismatch", self.codes(out))

    def test_correct_total_does_not_hide_wrong_subject_or_version(self):
        for subjects in [[("E2", "A1")], [("E1", "B1"), ("E2", "A1")]]:
            value = example(); value["statements"][2]["expected"] = expected(subjects, 31, 51)
            self.assertIn("reading_subject_mismatch", self.codes(self.audit(value)))

    def test_different_medium_unit_operation_origin_or_event_is_not_added(self):
        alternatives = [{"medium": "xml", "unit": "numbered_paragraph"}, {"unit": "logical_figure"},
                        {"operation": "rendered"}, {"origin": "direct"}, {"event_id": "另一次研究"}]
        for change in alternatives:
            with self.subTest(change=change):
                out = self.audit(example([record(), record("E2", "A1", 38, [[1, 1], [19, 38]], **change)]))
                self.assertEqual("blocked", out["status"])
                self.assertIn("reading_context_mismatch", self.codes(out))

    def test_overlapping_ranges_merge_in_same_document_without_double_count(self):
        value = example([record(ranges=[[1, 3]]), record(ranges=[[3, 5]])])
        value["statements"] = [{"id": "Union", "kind": "single", "reading_ids": ["R1", "R2"],
                                "expected": expected([("E1", "A2")], 5, 13)}]
        out = self.audit(value)
        self.assertEqual("checked", out["status"])
        self.assertEqual(5, out["statements"][0]["covered"])

    def test_duplicate_document_is_not_a_two_document_aggregate(self):
        out = self.audit(example([record(), record()]))
        self.assertIn("reading_aggregate_subjects_required", self.codes(out))
        self.assertIsNone(out["statements"][-1]["projection"])

    def test_same_subject_with_conflicting_denominator_is_blocked(self):
        value = example([record(ranges=[[1, 3]]), record(total=14, ranges=[[4, 5]])])
        value["statements"] = [{"id": "Union", "kind": "single", "reading_ids": ["R1", "R2"]}]
        out=self.audit(value)
        self.assertIn("reading_total_conflict", self.codes(out))
        self.assertIsNone(out["statements"][0]["projection"])

    def test_range_without_its_own_total_cannot_exceed_a_known_same_subject_total(self):
        value=example([record(total=None,ranges=[[1,20]]),record(ranges=[[1,3]])])
        value["statements"]=[{"id":"Union","kind":"single","reading_ids":["R1","R2"]}]
        out=self.audit(value)
        self.assertEqual("blocked",out["status"])
        self.assertIn("reading_range_total_conflict",self.codes(out))
        self.assertIsNone(out["statements"][0]["projection"])

    def test_one_unknown_denominator_is_not_silently_filled_from_another_record(self):
        value=example([record(total=None,ranges=[[1,3]]),record(ranges=[[4,5]])])
        value["statements"]=[{"id":"Union","kind":"single","reading_ids":["R1","R2"]}]
        out=self.audit(value)
        self.assertEqual("needs_review",out["status"])
        self.assertEqual(5,out["statements"][0]["covered"])
        self.assertIsNone(out["statements"][0]["total"])

    def test_unknown_not_checked_unavailable_and_not_applicable_are_not_zero(self):
        for state in ["unknown", "not_checked", "unavailable", "not_applicable"]:
            with self.subTest(state=state):
                value = example([record(state=state, ranges=[], reason="没有相应观察")])
                out = self.audit(value)
                self.assertEqual("needs_review", out["status"])
                self.assertIsNone(out["statements"][0]["covered"])
                value["statements"][0]["expected"] = expected([("E1", "A2")], 0, 13)
                self.assertIn("reading_count_mismatch", self.codes(self.audit(value)))

    def test_unknown_total_and_unknown_version_do_not_become_full_review(self):
        for row in [record(total=None, ranges=[[1, 3]]), record(version=None)]:
            out = self.audit(example([row])); self.assertEqual("needs_review", out["status"])
        self.assertEqual(3, self.audit(example([record(total=None, ranges=[[1, 3]])]))["statements"][0]["covered"])

    def test_explicit_known_zero_is_distinct_from_unknown(self):
        out = self.audit(example([record(ranges=[])]))
        self.assertEqual((0, 13), (out["statements"][0]["covered"], out["statements"][0]["total"]))

    def test_nonknown_states_remain_distinct_in_generated_wording(self):
        for state,label in [("unknown","未知"),("not_checked","未检查"),("unavailable","未取得"),("not_applicable","声明不适用")]:
            with self.subTest(state=state):
                row=self.audit(example([record(state=state,ranges=[],reason="没有相应观察")]))["statements"][0]
                self.assertIn(label,row["projection"]);self.assertIn("没有相应观察",row["projection"])
                self.assertNotIn("覆盖0/",row["projection"])

    def test_large_valid_union_does_not_reuse_the_per_record_interval_limit(self):
        first=[[n,n] for n in range(1,512,2)];second=[[n,n] for n in range(513,1024,2)]
        value=example([record(total=2000,ranges=first),record(total=2000,ranges=second)])
        value["statements"]=[{"id":"Union","kind":"single","reading_ids":["R1","R2"]}]
        self.assertEqual(512,self.audit(value)["statements"][0]["covered"])

    def test_malformed_enum_shapes_fail_as_contract_errors(self):
        for field in ["medium","unit","operation","origin","state"]:
            with self.subTest(field=field),self.assertRaises(ContractError):self.audit(example([record(**{field:[]})]))

    def test_noninteger_or_invalid_ranges_are_rejected(self):
        for change in [{"total": True}, {"ranges": [[True, 2]]}, {"ranges": [[0, 2]]},
                       {"ranges": [[5, 4]]}, {"ranges": [[1, 14]]}, {"state": "unknown"}]:
            with self.subTest(change=change), self.assertRaises(ContractError):
                self.audit(example([record(**change)]))

    def test_cited_record_is_strict_json_and_cannot_be_self_authored_candidate(self):
        for quote in ['{"subject":1,"subject":2}', "not a structured record"]:
            value = example();doc = value["documents"][0];doc["text"] = quote;doc["sha256"] = sha256_bytes(quote.encode())
            value["readings"] = [{"id": "R1", "citation": {"document_id": "Evidence", "start": 0, "end": len(quote), "quote": quote}}]
            value["statements"] = [{"id": "S1", "kind": "single", "reading_ids": ["R1"]}]
            with self.subTest(quote=quote), self.assertRaises(ContractError):self.audit(value)
        value = example();value["documents"][0]["role"] = "candidate"
        with self.assertRaisesRegex(ContractError, "reading_evidence_source_role"):self.audit(value)

    def test_stale_hash_citation_and_duplicate_reading_identity_are_rejected(self):
        variants=[]
        value=example();value["documents"][0]["sha256"]="0"*64;variants.append(value)
        value=example();value["readings"][0]["citation"]["quote"]+="x";variants.append(value)
        value=example();value["readings"].append(copy.deepcopy(value["readings"][0]));variants.append(value)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ContractError):self.audit(value)

    def test_actual_block_must_equal_projection_and_every_statement_is_bound(self):
        value=example();out=self.audit(value)
        texts={row["id"]:row["projection"] for row in out["statements"]};bindings={key:key for key in texts}
        self.assertEqual("checked",self.audit(value,texts=texts,bindings=bindings)["status"])
        texts["S2"]=texts["S2"].replace("21/38","31/51")
        self.assertIn("reading_projection_mismatch",self.codes(self.audit(value,texts=texts,bindings=bindings)))
        del texts["Total"];del bindings["Total"]
        self.assertIn("reading_statement_unbound",self.codes(self.audit(value,texts=texts,bindings=bindings)))


class ReadingScopeDocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="dyz-reading-scope-");self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.payload=example()
        self.evidence=self.payload["documents"][0]["text"]
        self.lines=["转述记录〔演示研究〕：E1（A2）PDF目视覆盖10/13页。", "转述记录〔演示研究〕：E2（A1）PDF目视覆盖21/38页。",
                    "转述记录〔演示研究〕：E1（A2）＋E2（A1）PDF目视合计覆盖31/51页（仅所列版本）。"]
        (self.root/"evidence.md").write_bytes(self.evidence.encode("utf-8"))
        self.draft="\n".join(self.lines)+"\n";(self.root/"draft.md").write_bytes(self.draft.encode("utf-8"))
        self.spec={"sensitivity":"synthetic","document_id":"ScopeExample","version":"1","business":"patent",
            "sources":[{"id":"Evidence","path":"evidence.md","version":"v1","sha256":sha256_bytes(self.evidence.encode())},
                       {"id":"Draft","path":"draft.md","sha256":sha256_bytes(self.draft.encode())}],
            "blocks":[{"id":"B"+str(n),"kind":"reading_scope","audience":"body","source_id":"Draft","start_line":n,"end_line":n} for n in range(1,4)],
            "reading_scope":{"payload":self.payload,"blocks":{"B1":"S1","B2":"S2","B3":"Total"}},"figures":[]}

    def test_build_reverify_and_actual_bookmark_texts_share_the_projection(self):
        manifest=documents.build(self.root,self.spec,"pack",synthetic=True)
        self.assertEqual("checked",manifest["reading_scope"]["status"])
        self.assertEqual("needs_review",manifest["status"])
        documents.verify(self.root,self.spec,"pack",synthetic=True)
        from tools.document_review import review_docx
        report=review_docx((self.root/"pack/body/document.docx").read_bytes())
        self.assertEqual(self.lines,[row["text"] for row in report["current"]["bookmarks"]])

    def test_crlf_evidence_uses_actual_bytes_and_character_offsets(self):
        doc=self.payload["documents"][0];lines=doc["text"].splitlines();text="\r\n".join(lines)+"\r\n"
        doc["text"]=text;doc["sha256"]=sha256_bytes(text.encode());offset=0
        for row,line in zip(self.payload["readings"],lines):
            row["citation"].update(start=offset,end=offset+len(line));offset+=len(line)+2
        (self.root/"evidence.md").write_bytes(text.encode());self.spec["sources"][0]["sha256"]=doc["sha256"]
        self.assertEqual("checked",documents.build(self.root,self.spec,"crlf",synthetic=True)["reading_scope"]["status"])
        self.assertEqual("checked",documents.build(self.root,self.generated_spec(),"crlf-generated",synthetic=True)["reading_scope"]["status"])

    def generated_spec(self):
        spec=copy.deepcopy(self.spec)
        for n,block in enumerate(spec["blocks"]):
            block.update(generate=True,source_id="Evidence",start_line=n+1 if n<2 else 1,end_line=n+1 if n<2 else 2)
        return spec

    def test_generated_blocks_calculate_text_and_preserve_derivation_not_fake_literal_copy(self):
        spec=self.generated_spec();before=copy.deepcopy(spec)
        out=documents.build(self.root,spec,"generated",synthetic=True)
        self.assertEqual(before,spec)
        documents.verify(self.root,spec,"generated",synthetic=True)
        actual=(self.root/"generated/body/source.txt").read_text(encoding="utf-8")
        self.assertEqual("\n\n".join(self.lines)+"\n",actual)
        mapping=json.loads((self.root/"generated/internal/source-map.json").read_bytes())
        self.assertTrue(all(not row["derivation"]["literal_source_copy"] for row in mapping["blocks"]))
        self.assertEqual(2,len(mapping["blocks"][2]["derivation"]["citations"]))
        self.assertEqual("checked",out["reading_scope"]["status"])

    def test_generated_primary_range_and_flag_are_validated(self):
        spec=self.generated_spec();spec["blocks"][1].update(start_line=1,end_line=1)
        with self.assertRaisesRegex(ContractError,"document_reading_scope_source_range"):documents.build(self.root,spec,"wrong-range",synthetic=True)
        spec=self.generated_spec();spec["blocks"][0]["generate"]="yes"
        with self.assertRaisesRegex(ContractError,"document_reading_scope_generate_flag"):documents.build(self.root,spec,"wrong-flag",synthetic=True)

    def test_identical_quote_at_a_different_source_location_does_not_satisfy_the_cited_range(self):
        spec=self.generated_spec();spec["blocks"]=spec["blocks"][:1]
        scope=spec["reading_scope"];scope["blocks"]={"B1":"S1"}
        payload=scope["payload"];payload["statements"]=payload["statements"][:1];payload["readings"]=payload["readings"][:1]
        quote=payload["readings"][0]["citation"]["quote"];text=quote+"\n"+quote+"\n"
        payload["readings"][0]["citation"].update(start=len(quote)+1,end=2*len(quote)+1)
        payload["documents"][0].update(text=text,sha256=sha256_bytes(text.encode()))
        (self.root/"evidence.md").write_bytes(text.encode());spec["sources"][0]["sha256"]=sha256_bytes(text.encode())
        spec["blocks"][0].update(start_line=2,end_line=2)
        self.assertEqual("checked",documents.build(self.root,spec,"right-location",synthetic=True)["reading_scope"]["status"])
        spec["blocks"][0].update(start_line=1,end_line=1)
        with self.assertRaisesRegex(ContractError,"document_reading_scope_source_range"):
            documents.build(self.root,spec,"wrong-location",synthetic=True)
        self.assertFalse((self.root/"wrong-location").exists())

    def test_other_fidelity_binds_generated_output_not_the_preprojection_JSON(self):
        spec=self.generated_spec();spec["blocks"]=spec["blocks"][:1];spec["reading_scope"]["payload"]["statements"]=self.payload["statements"][:1]
        spec["reading_scope"]["blocks"]={"B1":"S1"};text=self.lines[0]
        candidate={"id":"C","role":"candidate","version":"1","text":text,"sha256":sha256_bytes(text.encode())}
        cite={"document_id":"C","start":0,"end":len(text),"quote":text};basis=self.payload["readings"][0]["citation"]
        payload={"documents":[self.payload["documents"][0],candidate],"atoms":[],
            "facts":[{"id":"F","state":"explicit","citation":basis,"formula":True}],
            "assertions":[{"id":"A","citation":cite,"formula":True,"basis_fact_ids":["F"],"proof_scope":"technical_consistency"}],
            "regions":[{"id":"R","citation":cite,"kind":"technical","assertion_ids":["A"]}],"parameter_requests":[],"parameter_assessments":[]}
        spec["fidelity"]={"payload":payload,"blocks":{"B1":cite}}
        manifest=documents.build(self.root,spec,"combined",synthetic=True)
        self.assertEqual("checked",manifest["fidelity"]["status"]);self.assertEqual("checked",manifest["reading_scope"]["status"])
        documents.verify(self.root,spec,"combined",synthetic=True)

    def test_source_evidence_version_and_actual_bytes_are_bound_before_output(self):
        for mutation in ["version","text"]:
            with self.subTest(mutation=mutation):
                spec=copy.deepcopy(self.spec)
                if mutation=="version":spec["sources"][0]["version"]="v2"
                else:
                    spec["reading_scope"]["payload"]["documents"][0]["text"]+="\n"
                    spec["reading_scope"]["payload"]["documents"][0]["sha256"]=sha256_bytes(spec["reading_scope"]["payload"]["documents"][0]["text"].encode())
                with self.assertRaisesRegex(ContractError,"document_reading_scope_source_binding"):
                    documents.build(self.root,spec,mutation,synthetic=True)
                self.assertFalse((self.root/mutation).exists())

    def test_wrong_literal_or_missing_feature_declaration_is_not_exported(self):
        self.lines[1]=self.lines[1].replace("21/38","31/51");raw=("\n".join(self.lines)+"\n").encode();(self.root/"draft.md").write_bytes(raw)
        self.spec["sources"][1]["sha256"]=sha256_bytes(raw)
        with self.assertRaisesRegex(ContractError,"document_reading_scope_blocked"):documents.build(self.root,self.spec,"bad",synthetic=True)
        self.assertFalse((self.root/"bad").exists())
        del self.spec["reading_scope"]
        with self.assertRaisesRegex(ContractError,"document_reading_scope_required"):documents.build(self.root,self.spec,"missing",synthetic=True)

    def test_research_classification_stays_research_without_enabling_legal_fidelity(self):
        spec=copy.deepcopy(self.spec);spec["sensitivity"]="research_example"
        spec["research_materials"]=[{k:row[k] for k in ["path","sha256"]}|{"content_kind":"original_synthetic","third_party_text":"not_included",
            "processing_basis":"Authorized synthetic unit fixture.","export_basis":"Local unit fixture export."} for row in spec["sources"]]
        out=documents.build(self.root,spec,"research",research_example=True)
        self.assertEqual("research_example",out["mode"]);self.assertEqual("checked",out["reading_scope"]["status"])
        documents.verify(self.root,spec,"research",research_example=True)
        spec["fidelity"]={}
        with self.assertRaisesRegex(ContractError,"research_fidelity_not_supported"):documents.build(self.root,spec,"forbidden",research_example=True)

    def test_word_count_edit_cannot_be_hidden_by_rehashing_the_manifest(self):
        documents.build(self.root,self.spec,"pack",synthetic=True)
        target=self.root/"pack/body/document.docx";output=io.BytesIO()
        with zipfile.ZipFile(target) as old,zipfile.ZipFile(output,"w") as new:
            for info in old.infolist():
                raw=old.read(info.filename)
                if info.filename=="word/document.xml":raw=raw.replace(b"21/38",b"31/51")
                new.writestr(info,raw)
        target.write_bytes(output.getvalue());p=self.root/"pack/manifest.json";manifest=json.loads(p.read_bytes())
        row=next(row for row in manifest["files"] if row["path"]=="body/document.docx")
        row.update(sha256=sha256_bytes(target.read_bytes()),bytes=target.stat().st_size);p.write_bytes(canonical_bytes(manifest)+b"\n")
        with self.assertRaisesRegex(ContractError,"document_package_content_changed"):documents.verify(self.root,self.spec,"pack",synthetic=True)

    def test_report_tampering_and_unmarked_projection_cannot_claim_feature(self):
        documents.build(self.root,self.spec,"pack",synthetic=True)
        (self.root/"pack/internal/reading-scope-review.json").write_bytes(b'{}\n')
        with self.assertRaisesRegex(ContractError,"document_reading_scope_report_changed"):documents.verify(self.root,self.spec,"pack",synthetic=True)
        for block in self.spec["blocks"]:block["kind"]="paragraph"
        with self.assertRaisesRegex(ContractError,"document_reading_scope_blocks_required"):documents.build(self.root,self.spec,"unmarked",synthetic=True)
