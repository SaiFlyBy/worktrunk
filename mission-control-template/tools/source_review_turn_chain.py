"""Validate source-review turns against their adopted review contract.

The original v2.1 phase sequence remains valid for historical evidence.  New
v3 chains use evidence-based assessment and continuation, with the adopted
version, exact schema bytes, and adoption record bound before validation.
The caller still owns the authority and independent adjudication of results.
"""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path

try:
    from schema_subset import validate as validate_schema
except ImportError:
    from validate_json_schema_subset import validate as validate_schema


def canonical_sha256(value) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_ref(root: Path, ref: object) -> Path:
    if not isinstance(ref,str) or not ref.strip() or "\\" in ref or re.match(r"^[A-Za-z]:",ref):
        raise ValueError(f"unsafe ref: {ref!r}")
    raw=Path(ref)
    if raw.is_absolute() or any(part in {"", ".", ".."} for part in raw.parts):
        raise ValueError(f"unsafe ref: {ref!r}")
    path=(root/raw).resolve(); path.relative_to(root.resolve()); return path


def expected_source_ref(source: dict) -> str:
    identity=source.get("identity"); pin=source.get("pin")
    return pin if isinstance(identity,str) and identity.lower().startswith("arxiv:") else f"{identity}@{pin}"


def envelope_hash(envelope: dict) -> str:
    payload=json.loads(json.dumps(envelope))
    payload.pop("turn_sha256",None)
    return canonical_sha256(payload)


def launch_receipt_hash(receipt: dict) -> str:
    payload=json.loads(json.dumps(receipt))
    payload.pop("receipt_sha256",None)
    return canonical_sha256(payload)


def locator_key(locator: dict) -> str:
    return json.dumps(locator,sort_keys=True,separators=(",",":"),ensure_ascii=False)


def checkpoint_hash(checkpoint: dict) -> str:
    return canonical_sha256(checkpoint)


def validate_checkpoint_contract(
    root: Path,
    checkpoint: dict,
    checkpoint_schema: dict | None,
    expected_source_id: str,
    expected_source_ref: str,
    expected_thread: str,
    expected_turn_number: int | None = None,
    expected_source_identity: str | None = None,
    expected_source_version: str | None = None,
    expected_critical_partitions: list[str] | None = None
) -> list[str]:
    errs = []
    if checkpoint_schema:
        for e in validate_schema(checkpoint, checkpoint_schema, checkpoint_schema):
            errs.append(f"checkpoint schema: {e}")
    if checkpoint.get("authority_status") != "NON_AUTHORITATIVE_SCRATCH":
        errs.append(f"checkpoint authority_status must be NON_AUTHORITATIVE_SCRATCH: {checkpoint.get('authority_status')}")
    if checkpoint.get("source_id") != expected_source_id:
        errs.append(f"checkpoint source_id mismatch: expected {expected_source_id}, got {checkpoint.get('source_id')}")
    if checkpoint.get("source_ref") != expected_source_ref:
        errs.append(f"checkpoint source_ref mismatch: expected {expected_source_ref}, got {checkpoint.get('source_ref')}")
    if expected_source_identity is not None and checkpoint.get("source_identity") != expected_source_identity:
        errs.append(f"checkpoint source_identity mismatch: expected {expected_source_identity}, got {checkpoint.get('source_identity')}")
    if expected_source_version is not None and checkpoint.get("source_version") != expected_source_version:
        errs.append(f"checkpoint source_version stale/mismatch: expected {expected_source_version}, got {checkpoint.get('source_version')}")
    if checkpoint.get("thread") != expected_thread:
        errs.append(f"checkpoint thread mismatch: expected {expected_thread}, got {checkpoint.get('thread')}")
    if expected_turn_number is not None and checkpoint.get("turn_number") != expected_turn_number:
        errs.append(f"checkpoint turn_number mismatch: expected {expected_turn_number}, got {checkpoint.get('turn_number')}")
    seq = checkpoint.get("checkpoint_sequence")
    if not isinstance(seq, int) or seq < 1:
        errs.append(f"checkpoint_sequence must be integer >= 1: {seq}")
    prev_digest = checkpoint.get("previous_checkpoint_sha256")
    if seq == 1 and prev_digest is not None:
        errs.append("checkpoint sequence 1 previous_checkpoint_sha256 must be null")
    if isinstance(seq, int) and seq > 1 and not isinstance(prev_digest, str):
        errs.append("checkpoint sequence >1 requires previous_checkpoint_sha256")
    cursor = checkpoint.get("coverage_cursor", {})
    completion = checkpoint.get("completion_flag")
    if completion is True:
        if checkpoint.get("convergence_status") != "CONVERGENCE_PROPOSED":
            errs.append("checkpoint completion_flag cannot be true before convergence is proposed")
        if isinstance(cursor, dict) and cursor.get("remaining_partitions"):
            errs.append("checkpoint completion_flag cannot be true with remaining source partitions")
        questions = checkpoint.get("confidence_and_open_questions", {})
        if isinstance(questions, dict) and (questions.get("open_questions") or questions.get("uninspected_gaps")):
            errs.append("checkpoint completion_flag cannot be true with unresolved questions or gaps")
        if checkpoint.get("unresolved_rights_issues"):
            errs.append("checkpoint completion_flag cannot be true with unresolved rights issues")
    if not isinstance(cursor, dict) or not cursor.get("inspected_partition") or not cursor.get("inspected_paths") or not cursor.get("inspected_commit_or_version"):
        errs.append("checkpoint coverage_cursor missing required partition, paths, or commit")
    elif expected_critical_partitions is not None:
        critical_set = set(expected_critical_partitions)
        completed = set(cursor.get("completed_partitions", []) if isinstance(cursor.get("completed_partitions"), list) else [])
        remaining = set(cursor.get("remaining_partitions", []) if isinstance(cursor.get("remaining_partitions"), list) else [])
        if completed | remaining != critical_set or completed & remaining:
            errs.append("checkpoint critical partition accounting does not match generation manifest")
        if cursor.get("inspected_partition") not in completed:
            errs.append("checkpoint inspected partition is not recorded as completed")
    nxt = checkpoint.get("next_read_cursor", {})
    if not isinstance(nxt, dict) or not nxt.get("target_next_partition") or not nxt.get("target_next_paths") or not nxt.get("stop_condition"):
        errs.append("checkpoint next_read_cursor missing required target partition, paths, or stop condition")
    rights = checkpoint.get("license_and_rights_evidence", {})
    if not isinstance(rights, dict) or not rights.get("license_locator") or not rights.get("rights_state"):
        errs.append("checkpoint license_and_rights_evidence missing required license_locator or rights_state")
    mechanisms = checkpoint.get("mechanism_candidates", [])
    if isinstance(mechanisms, list):
        for idx, mechanism in enumerate(mechanisms, 1):
            if not isinstance(mechanism, dict) or not mechanism.get("evidence_locator"):
                errs.append(f"checkpoint mechanism {idx} missing evidence_locator")
    scratch_ref = checkpoint.get("scratch_evidence_ref")
    if scratch_ref:
        try:
            sp = safe_ref(root, scratch_ref)
            if not sp.is_file():
                errs.append(f"checkpoint scratch evidence missing: {scratch_ref}")
            elif file_sha256(sp) != checkpoint.get("scratch_evidence_sha256"):
                errs.append(f"checkpoint scratch evidence hash drift: {scratch_ref}")
        except Exception as exc:
            errs.append(f"checkpoint scratch evidence ref invalid: {exc}")
    return errs


def validate_checkpoint_resume(previous: dict, current: dict, previous_sha256: str) -> list[str]:
    errs = []
    prev_seq = previous.get("checkpoint_sequence")
    cur_seq = current.get("checkpoint_sequence")
    if not isinstance(prev_seq, int) or not isinstance(cur_seq, int) or cur_seq != prev_seq + 1:
        errs.append(f"checkpoint sequence must be contiguous: {cur_seq} after {prev_seq}")
    if current.get("previous_checkpoint_sha256") != previous_sha256:
        errs.append("checkpoint previous_checkpoint_sha256 does not match exact predecessor")
    prev_next = previous.get("next_read_cursor", {}) if isinstance(previous.get("next_read_cursor"), dict) else {}
    cur_cov = current.get("coverage_cursor", {}) if isinstance(current.get("coverage_cursor"), dict) else {}
    if cur_cov.get("inspected_partition") != prev_next.get("target_next_partition"):
        errs.append("checkpoint resume cursor partition does not match predecessor next cursor")
    if cur_cov.get("inspected_paths") != prev_next.get("target_next_paths"):
        errs.append("checkpoint resume cursor paths do not match predecessor next cursor")
    if prev_next.get("target_next_range") is not None and cur_cov.get("inspected_range_or_locator") != prev_next.get("target_next_range"):
        errs.append("checkpoint resume cursor range does not match predecessor next cursor")
    if current.get("source_id") != previous.get("source_id") or current.get("source_ref") != previous.get("source_ref"):
        errs.append("checkpoint lineage crosses source identity")
    if current.get("source_version") != previous.get("source_version"):
        errs.append("checkpoint lineage crosses source version")
    return errs


def validate_cleanup_manifest(manifest: dict, cleanup_schema: dict | None = None, root: Path | None = None) -> list[str]:
    errs = []
    if cleanup_schema:
        for e in validate_schema(manifest, cleanup_schema, cleanup_schema):
            errs.append(f"cleanup schema: {e}")
    if manifest.get("delete_candidates") and manifest.get("adjudication_complete") is not True:
        errs.append("source payload cleanup forbidden before adjudication completes")
    if root is not None:
        try:
            final_path = safe_ref(root, manifest.get("final_review_ref"))
            if not final_path.is_file():
                errs.append(f"cleanup final durable review missing: {manifest.get('final_review_ref')}")
            elif file_sha256(final_path) != manifest.get("final_review_sha256"):
                errs.append(f"cleanup final durable review hash drift: {manifest.get('final_review_ref')}")
        except Exception as exc:
            errs.append(f"cleanup final durable review ref invalid: {exc}")
    retained = manifest.get("retained_evidence", []) if isinstance(manifest.get("retained_evidence"), list) else []
    for item in retained:
        if not isinstance(item, dict):
            continue
        if item.get("artifact_class") in {"AUTHORITY_EVIDENCE", "AGENT_AUTHORED_REVIEW"} and item.get("protected") is not True:
            errs.append(f"durable {item.get('artifact_class')} must be protected: {item.get('ref')}")
    protected = {x.get("ref") for x in retained if isinstance(x, dict) and x.get("protected") is True}
    attempted = set(manifest.get("delete_candidates", []) if isinstance(manifest.get("delete_candidates"), list) else [])
    overlap = sorted(protected & attempted)
    if overlap:
        errs.append(f"cleanup attempts to delete protected authority evidence: {overlap}")
    temporary_records = manifest.get("temporary_source_payloads", []) if isinstance(manifest.get("temporary_source_payloads"), list) else []
    temporary = {x.get("ref") for x in temporary_records if isinstance(x, dict) and x.get("kind") in {"SOURCE_DOWNLOAD", "SOURCE_CLONE"}}
    illegal = sorted(attempted - temporary)
    if illegal:
        errs.append(f"cleanup delete candidates are not declared temporary source downloads/clones: {illegal}")
    if manifest.get("adjudication_complete") is True:
        unscheduled = sorted(temporary - attempted)
        if unscheduled:
            errs.append(f"temporary source payloads remain unscheduled after adjudication: {unscheduled}")
    return errs


def parse_and_validate_birth_evidence(path: Path, expected_thread: str, expected_provider: str) -> list[str]:
    errs = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    is_json = False
    try:
        data = json.loads(text)
        is_json = True
    except Exception:
        pass

    if is_json and isinstance(data, dict):
        if data.get("thread_id") and data.get("thread_id") != expected_thread:
            errs.append(f"birth evidence thread mismatch: expected {expected_thread}, got {data.get('thread_id')}")
        if data.get("provider") and data.get("provider") != expected_provider:
            errs.append(f"birth evidence provider mismatch: expected {expected_provider}, got {data.get('provider')}")
        if data.get("approval_policy") != "never":
            errs.append(f"birth evidence approval_policy forbidden: {data.get('approval_policy')}")
        if data.get("sandbox_policy") != "danger-full-access":
            errs.append(f"birth evidence sandbox_policy forbidden: {data.get('sandbox_policy')}")
        if data.get("child_thread_created") is True:
            errs.append("birth evidence reports child_thread_created=True")
        if data.get("delegation_used") is True:
            errs.append("birth evidence reports delegation_used=True")
        if data.get("birth_type") in {"create_thread", "fork_thread", "CHILD_SESSION", "FORKED_SESSION"}:
            errs.append(f"birth evidence declares invalid birth type: {data.get('birth_type')}")
        lines = data.get("session_birth_lines") or data.get("events") or []
        if isinstance(lines, list):
            for idx, event in enumerate(lines, 1):
                if isinstance(event, dict):
                    payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
                    if event.get("type") == "response_item" and payload.get("type") == "function_call_output" and payload.get("name") in {"create_thread", "fork_thread"}:
                        errs.append(f"child thread birth detected in session birth lines (line {idx}): {payload.get('name')}")
                    if event.get("type") == "turn_context":
                        app = payload.get("approval_policy")
                        sb = payload.get("sandbox_policy")
                        sb_type = sb.get("type") if isinstance(sb, dict) else sb
                        if app == "on-request" or sb_type == "workspace-write":
                            errs.append(f"forbidden policy detected in session birth lines (line {idx}): approval={app}, sandbox={sb_type}")
                        if app != "never":
                            errs.append(f"approval_policy in session birth lines (line {idx}) must be never: {app}")
                        if sb_type != "danger-full-access":
                            errs.append(f"sandbox_policy in session birth lines (line {idx}) must be danger-full-access: {sb_type}")
    else:
        for line_no, line in enumerate(text.splitlines()[:50], 1):
            if not line.strip(): continue
            try: event = json.loads(line)
            except Exception: continue
            if isinstance(event, dict):
                if event.get("thread_id") and event.get("thread_id") != expected_thread:
                    errs.append(f"birth evidence thread mismatch on line {line_no}: {event.get('thread_id')}")
                payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
                if event.get("type") == "response_item" and payload.get("type") == "function_call_output" and payload.get("name") in {"create_thread", "fork_thread"}:
                    errs.append(f"child thread birth detected on line {line_no}: {payload.get('name')}")
                if event.get("type") == "turn_context":
                    app = payload.get("approval_policy")
                    sb = payload.get("sandbox_policy")
                    sb_type = sb.get("type") if isinstance(sb, dict) else sb
                    if app == "on-request" or sb_type == "workspace-write":
                        errs.append(f"forbidden policy detected on line {line_no}: approval={app}, sandbox={sb_type}")
                    if app != "never":
                        errs.append(f"approval_policy on line {line_no} must be never: {app}")
                    if sb_type != "danger-full-access":
                        errs.append(f"sandbox_policy on line {line_no} must be danger-full-access: {sb_type}")
    return errs



def parse_and_validate_v3_birth_evidence(path: Path, expected_thread: str, expected_provider: str) -> list[str]:
    """Require bound identity and observed policy events; do not authenticate origin.

    Normalized JSON has schema /1, thread_id, provider, direct birth/policy
    fields, and session_birth_lines. JSONL events carry thread_id and provider
    on each turn_context event (at the event or payload level). An observed
    sandbox policy may be a string or an object with a type field.
    """
    errs = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"birth evidence cannot be read as UTF-8: {exc}"]
    if not text.strip():
        return ["birth evidence is empty"]

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None

    normalized = isinstance(parsed, dict) and not ("type" in parsed and "payload" in parsed)
    if normalized:
        if parsed.get("schema") != "flyby/provider-session-birth-evidence/1":
            errs.append("normalized birth evidence schema is missing or unsupported")
        if parsed.get("thread_id") != expected_thread:
            errs.append("normalized birth evidence thread identity is missing or mismatched")
        if parsed.get("provider") != expected_provider:
            errs.append("normalized birth evidence provider identity is missing or mismatched")
        if parsed.get("birth_type") != "DIRECT_TOP_LEVEL_START":
            errs.append("normalized birth evidence must identify a direct top-level start")
        if parsed.get("approval_policy") != "never" or parsed.get("sandbox_policy") != "danger-full-access":
            errs.append("normalized birth evidence declares forbidden policy")
        if parsed.get("child_thread_created") is not False or parsed.get("delegation_used") is not False:
            errs.append("normalized birth evidence must report no child thread or delegation")
        events = parsed.get("session_birth_lines")
        if not isinstance(events, list) or not events:
            errs.append("normalized birth evidence requires observed session_birth_lines")
            events = []
    elif isinstance(parsed, dict):
        events = [parsed]
    elif parsed is not None:
        return ["birth evidence must contain a normalized object or JSONL event objects"]
    else:
        events = []
        for line_no, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                errs.append(f"birth evidence JSONL line {line_no} is invalid")
                continue
            events.append(event)

    observed = 0
    for line_no, event in enumerate(events, 1):
        if not isinstance(event, dict):
            errs.append(f"birth evidence event {line_no} must be an object")
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        for name, expected in (("thread_id", expected_thread), ("provider", expected_provider)):
            identities = [record[name] for record in (event, payload) if name in record]
            if any(value != expected for value in identities):
                errs.append(f"birth evidence {name} mismatch in event {line_no}")
            if not normalized and event.get("type") == "turn_context" and not identities:
                errs.append(f"birth evidence {name} missing from turn_context event {line_no}")
        if event.get("type") == "response_item" and payload.get("type") in {"function_call", "function_call_output"} and payload.get("name") in {"create_thread", "fork_thread"}:
            errs.append(f"child thread birth detected in birth evidence event {line_no}")
        if event.get("type") == "turn_context":
            observed += 1
            sandbox = payload.get("sandbox_policy")
            sandbox_type = sandbox.get("type") if isinstance(sandbox, dict) else sandbox
            if payload.get("approval_policy") != "never" or sandbox_type != "danger-full-access":
                errs.append(f"birth evidence turn_context event {line_no} has forbidden or missing policy")
    if not observed:
        errs.append("birth evidence lacks an observed turn_context event")
    return errs


def validate_turn_chain(root: Path, turn_schema: dict, chain_schema: dict, launch_schema: dict, adoption: dict, plan: dict, index: dict, checkpoint_schema: dict | None = None) -> list[str]:
    errors=[]
    def err(msg: str): errors.append(msg)
    if checkpoint_schema is None and index.get("schema") != "flyby/source-review-turn-chain-index/2":
        for cand in [
            root / "schemas" / "SOURCE_REVIEW_CHECKPOINT_SCHEMA.json",
            root / "control" / "revisions" / "PROVENANCE_EXPANSION_20260901" / "SOURCE_REVIEW_CHECKPOINT_SCHEMA.json"
        ]:
            if cand.is_file():
                try:
                    checkpoint_schema = json.loads(cand.read_text(encoding="utf-8"))
                    break
                except Exception:
                    pass
    for e in validate_schema(index,chain_schema,chain_schema): err(f"chain-index schema: {e}")

    # Index version, rather than a caller-supplied adoption argument, chooses
    # the contract.  The old index remains compatible with legacy callers that
    # never materialized an adoption file; a readable v3 adoption cannot be
    # treated as v2 under that old index.
    declared_version = adoption.get("turn_contract_version") if isinstance(adoption, dict) else None
    v2_versions = (None, "flyby/source-review-turn-contract/2", "flyby/source-review-turn-contract/2.1")
    v3_version = "flyby/source-review-turn-contract/3"
    v3_adoption_schema = "flyby/source-review-turn-contract-adoption/2"
    index_version = index.get("schema")
    if index_version == "flyby/source-review-turn-chain-index/1":
        contract_version = 2
    elif index_version == "flyby/source-review-turn-chain-index/2":
        contract_version = 3
    else:
        contract_version = 0
        err(f"unsupported turn chain index version: {index_version!r}")
    if declared_version not in v2_versions and declared_version != v3_version:
        err(f"unsupported turn contract version: {declared_version!r}")

    if contract_version == 2:
        if declared_version not in v2_versions or (isinstance(adoption, dict) and adoption.get("schema") == v3_adoption_schema):
            err("legacy chain index cannot use a v3 adoption")
        try:
            legacy_adoption_path = safe_ref(root, index.get("adoption_ref"))
            if legacy_adoption_path.is_file():
                disk_adoption = json.loads(legacy_adoption_path.read_text(encoding="utf-8"))
                if isinstance(disk_adoption, dict) and (disk_adoption.get("schema") == v3_adoption_schema or disk_adoption.get("turn_contract_version") == v3_version):
                    err("legacy chain index references a v3 adoption on disk")
        except (OSError, ValueError, UnicodeError):
            # Historic v2 callers did not require a materialized adoption file.
            pass

    if contract_version == 3:
        if declared_version != v3_version:
            err("v3 chain index requires version 3 adoption")
        if not isinstance(adoption, dict) or adoption.get("schema") != v3_adoption_schema:
            err("v3 turn contract requires a version 2 adoption record")
        try:
            adoption_path = safe_ref(root, index.get("adoption_ref"))
            if not adoption_path.is_file():
                err("v3 adoption file missing")
            else:
                if file_sha256(adoption_path) != index.get("adoption_sha256"):
                    err("v3 adoption file hash drift")
                loaded_adoption = json.loads(adoption_path.read_text(encoding="utf-8"))
                if loaded_adoption != adoption:
                    err("v3 adoption content differs from the supplied adoption")
        except Exception as exc:
            err(f"v3 adoption ref or contents invalid: {exc}")

        # Schema IDs alone are not sufficient: bind the exact adopted bytes,
        # and ensure the supplied schema is the installed contract, not an
        # alternate schema with a permissive implementation of that ID.
        def verify_v3_schema(prefix: str, supplied: dict, filename: str) -> None:
            try:
                schema_path = safe_ref(root, adoption.get(f"{prefix}_ref"))
                if not schema_path.is_file():
                    err(f"v3 adopted {prefix} file missing")
                    return
                if file_sha256(schema_path) != adoption.get(f"{prefix}_sha256"):
                    err(f"v3 adopted {prefix} file hash drift")
                adopted_schema = json.loads(schema_path.read_text(encoding="utf-8"))
                if adopted_schema != supplied:
                    err(f"v3 adopted {prefix} differs from supplied schema")
                installed_path = Path(__file__).resolve().parent.parent / "schemas" / filename
                installed_schema = json.loads(installed_path.read_text(encoding="utf-8"))
                if supplied != installed_schema:
                    err(f"v3 supplied {prefix} differs from installed schema")
            except Exception as exc:
                err(f"v3 adopted {prefix} ref or contents invalid: {exc}")

        for prefix, supplied, filename in (
            ("turn_contract_schema", turn_schema, "SOURCE_REVIEW_TURN_CONTRACT_V3_SCHEMA.json"),
            ("turn_chain_index_schema", chain_schema, "SOURCE_REVIEW_TURN_CHAIN_INDEX_V2_SCHEMA.json"),
            ("launch_receipt_schema", launch_schema, "DIRECT_LAUNCH_RECEIPT_SCHEMA.json"),
        ):
            verify_v3_schema(prefix, supplied, filename)

        checkpoint_schema_checked = False
        def ensure_v3_checkpoint_schema() -> None:
            nonlocal checkpoint_schema, checkpoint_schema_checked
            if checkpoint_schema_checked:
                return
            checkpoint_schema_checked = True
            if checkpoint_schema is None:
                try:
                    path = safe_ref(root, adoption.get("checkpoint_schema_ref"))
                    checkpoint_schema = json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    err(f"v3 checkpoint schema required when checkpoints are present: {exc}")
                    return
            verify_v3_schema("checkpoint_schema", checkpoint_schema, "SOURCE_REVIEW_CHECKPOINT_V2_SCHEMA.json")

    phases={}
    for rc in plan.get("round_contracts",[]):
        if not isinstance(rc,dict): continue
        expected=canonical_sha256({"name":rc.get("name"),"instruction":rc.get("instruction"),"phase_authorization":rc.get("phase_authorization")})
        if rc.get("phase_contract_sha256")!=expected: err(f"phase contract hash drift: {rc.get('name')}")
        phases[rc.get("name")]=rc
    phase_index=[{"name":rc.get("name"),"phase_contract_sha256":rc.get("phase_contract_sha256")} for rc in plan.get("round_contracts",[]) if isinstance(rc,dict)]
    if adoption.get("round_contracts_sha256")!=canonical_sha256(phase_index): err("adoption round-contract digest drift")
    policy=adoption.get("policy",{}) if isinstance(adoption,dict) else {}
    for key in ["no_retroactive_turn_hash_fabrication","direct_top_level_sessions_only","child_thread_creation_forbidden","delegation_from_review_session_forbidden","turn_envelopes_append_only","prior_hash_required_after_turn_one","phase_instruction_digest_required","source_pinned_locator_hash_required","evidence_hash_required"]:
        if policy.get(key) is not True: err(f"adoption policy not enforced: {key}")
    plan_target_base=plan.get("target_base")
    if not isinstance(plan_target_base,str) or not plan_target_base: err("plan target_base is missing")
    sources={s.get("source_id"):s for s in plan.get("sources",[]) if isinstance(s,dict)}
    if len(sources)!=len(plan.get("sources",[])): err("plan source ids are missing or duplicated")
    retired=plan.get("retired_review_threads",[]) if isinstance(plan.get("retired_review_threads",[]),list) else []
    retired_threads=[x.get("thread") for x in retired if isinstance(x,dict)]
    if len(retired_threads)!=len(set(retired_threads)): err("retired review thread ids are duplicated")
    for x in retired:
        if not isinstance(x,dict): continue
        if x.get("source_id") not in sources: err(f"retired review thread maps unknown source: {x.get('source_id')}")
    retired_set=set(retired_threads)
    owner_map=plan.get("owner_map",{}).get("sources",[]) if isinstance(plan.get("owner_map"),dict) else []
    owner_by={x.get("source_id"):x for x in owner_map if isinstance(x,dict)}
    if set(owner_by)!=set(sources): err("owner map source set differs from plan source set")
    if len(owner_by)!=len(owner_map): err("owner map source ids are duplicated")
    for sid,source in sources.items():
        owner=owner_by.get(sid,{})
        if source.get("thread"):
            if owner.get("active_thread")!=source.get("thread") or owner.get("active_provider")!=source.get("provider"): err(f"owner map active custody mismatch for {sid}")
        else:
            if owner.get("active_thread") is not None: err(f"owner map active custody mismatch for {sid}")
            if owner.get("envelope_regime") not in {"REPLACEMENT_REQUIRED_DIRECT_TOP_LEVEL","PENDING_DIRECT_LAUNCH","PENDING_REPLACEMENT"}: err(f"owner map replacement regime mismatch for {sid}")
        same_retired=sorted(x.get("thread") for x in retired if isinstance(x,dict) and x.get("source_id")==sid)
        if sorted(owner.get("retired_threads",[]))!=same_retired: err(f"owner map tombstone set mismatch for {sid}")
        if source.get("retired_thread") and source.get("retired_thread") not in same_retired: err(f"replacement source lacks same-source tombstone for {sid}")
        if source.get("thread") and source.get("thread") in retired_set: err(f"active source owner is tombstoned for {sid}")
    legacy=index.get("legacy_pre_enforcement",[]) if isinstance(index,dict) else []
    post=index.get("post_enforcement_generations",[]) if isinstance(index,dict) else []
    legacy_keys=[]; legacy_threads=[]
    for rec in legacy:
        if not isinstance(rec,dict): continue
        sid=rec.get("source_id"); source=sources.get(sid)
        legacy_keys.append((sid,rec.get("generation"))); legacy_threads.append(rec.get("thread_id"))
        if source is None: err(f"legacy generation references unknown source {sid}"); continue
        owner=owner_by.get(sid,{})
        if owner.get("envelope_regime")!="LEGACY_PRE_ENFORCEMENT": err(f"legacy generation not marked legacy in owner map for {sid}")
        if rec.get("source_ref")!=expected_source_ref(source): err(f"legacy generation source_ref mismatch for {sid}")
        if rec.get("thread_id")!=source.get("thread") or rec.get("generation")!=owner.get("active_generation"): err(f"legacy generation active custody mismatch for {sid}")
    if len(legacy_keys)!=len(set(legacy_keys)) or len(legacy_threads)!=len(set(legacy_threads)): err("legacy generation keys/threads are duplicated")
    post_keys=[]; post_threads=[]
    for generation in post:
        if not isinstance(generation,dict): continue
        sid=generation.get("source_id"); source=sources.get(sid); gen=generation.get("generation")
        post_keys.append((sid,gen)); post_threads.append(generation.get("thread_id"))
        if source is None: err(f"post-enforcement generation references unknown source {sid}"); continue
        owner=owner_by.get(sid,{})
        expected_regime = "POST_ENFORCEMENT_V3" if contract_version == 3 else "POST_ENFORCEMENT_V2"
        if owner.get("envelope_regime") != expected_regime: err(f"post-enforcement generation not active in owner map for {sid}")
        if generation.get("thread_id")!=source.get("thread") or generation.get("thread_id")!=owner.get("active_thread") or gen!=owner.get("active_generation"): err(f"post-enforcement generation active custody mismatch for {sid}")
        if generation.get("thread_id") in retired_set: err(f"post-enforcement generation uses tombstoned thread for {sid}")
        if generation.get("source_ref")!=expected_source_ref(source): err(f"post-enforcement source_ref mismatch for {sid}")
        if generation.get("provider")!=source.get("provider"): err(f"post-enforcement provider mismatch for {sid}")
        agent_policy=plan.get("agent_policy",{})
        if generation.get("model")!=agent_policy.get("model") or generation.get("reasoning_effort")!=agent_policy.get("reasoning_effort"): err(f"post-enforcement model/reasoning mismatch for {sid}")
        if generation.get("rights_mode")!=source.get("current_usage_mode"): err(f"post-enforcement rights mode mismatch for {sid}")
        if generation.get("target_base")!=plan_target_base: err(f"post-enforcement target_base mismatch for {sid}")
        if generation.get("execution_custody")!="DIRECT_TOP_LEVEL_SESSION": err(f"post-enforcement review is not direct top-level for {sid}")
        launch_receipt=None
        try: launch_path=safe_ref(root,generation.get("launch_receipt_ref"))
        except Exception as exc: err(f"launch receipt ref invalid for {sid}: {exc}"); launch_path=None
        if launch_path is not None:
            if not launch_path.is_file(): err(f"launch receipt missing for {sid}: {generation.get('launch_receipt_ref')}")
            else:
                if file_sha256(launch_path)!=generation.get("launch_receipt_sha256"): err(f"launch receipt file hash drift for {sid}")
                try: launch_receipt=json.loads(launch_path.read_text(encoding="utf-8"))
                except Exception as exc: err(f"launch receipt unreadable for {sid}: {exc}"); launch_receipt=None
                if contract_version == 3 and not isinstance(launch_receipt, dict):
                    err(f"launch receipt payload must be an object for {sid}")
                if isinstance(launch_receipt,dict):
                    for e in validate_schema(launch_receipt,launch_schema,launch_schema): err(f"launch receipt schema {sid}: {e}")
                    if launch_receipt.get("receipt_sha256")!=launch_receipt_hash(launch_receipt): err(f"launch receipt self-hash mismatch for {sid}")
                    expected_launch={
                        "source_id":sid,
                        "source_ref":generation.get("source_ref"),
                        "target_base":generation.get("target_base"),
                        "generation":gen,
                        "provider":generation.get("provider"),
                        "model":generation.get("model"),
                        "reasoning_effort":generation.get("reasoning_effort"),
                        "approval_policy":"never",
                        "sandbox_policy":"danger-full-access",
                        "execution_custody":"DIRECT_TOP_LEVEL_SESSION",
                        "child_thread_created":False,
                        "delegation_used":False,
                        "assigned_thread_id":generation.get("thread_id")
                    }
                    for key,value in expected_launch.items():
                        if launch_receipt.get(key)!=value: err(f"launch receipt binding mismatch for {sid}: {key}")
                    expected_api="mailbox.codex.start" if generation.get("provider")=="mailbox.codex" else "mailbox.wslcodex.start"
                    if launch_receipt.get("launch_api")!=expected_api: err(f"launch receipt API mismatch for {sid}")
                    try: launch_prompt_path=safe_ref(root,launch_receipt.get("turn_1_prompt_ref"))
                    except Exception as exc: err(f"launch turn-1 prompt ref invalid for {sid}: {exc}")
                    else:
                        if not launch_prompt_path.is_file(): err(f"launch turn-1 prompt missing for {sid}")
                        elif file_sha256(launch_prompt_path)!=launch_receipt.get("turn_1_prompt_sha256"): err(f"launch turn-1 prompt hash drift for {sid}")
                    try: birth_path=safe_ref(root,launch_receipt.get("session_birth_evidence_ref"))
                    except Exception as exc: err(f"session birth evidence ref invalid for {sid}: {exc}"); birth_path=None
                    if birth_path is not None:
                        if not birth_path.is_file(): err(f"session birth evidence missing for {sid}: {launch_receipt.get('session_birth_evidence_ref')}")
                        else:
                            if file_sha256(birth_path)!=launch_receipt.get("session_birth_evidence_sha256"): err(f"session birth evidence file hash drift for {sid}")
                            birth_validator = parse_and_validate_v3_birth_evidence if contract_version == 3 else parse_and_validate_birth_evidence
                            for be in birth_validator(birth_path, generation.get("thread_id"), generation.get("provider")):
                                err(f"session birth evidence {sid}: {be}")
        critical=generation.get("critical_partitions",[])
        if generation.get("critical_partition_manifest_sha256")!=canonical_sha256(critical): err(f"critical partition manifest hash drift for {sid}")
        gen_checkpoints = generation.get("checkpoints", []) if isinstance(generation.get("checkpoints"), list) else []
        if contract_version == 3 and gen_checkpoints: ensure_v3_checkpoint_schema()
        last_seq = 0
        prior_checkpoint_data = None
        prior_checkpoint_sha = None
        for c_entry in gen_checkpoints:
            if not isinstance(c_entry, dict): continue
            c_seq = c_entry.get("checkpoint_sequence")
            if not isinstance(c_seq, int) or c_seq <= last_seq:
                err(f"generation checkpoint sequence not strictly monotonic for {sid}: {c_seq} after {last_seq}")
            last_seq = c_seq if isinstance(c_seq, int) else last_seq
            try: c_path = safe_ref(root, c_entry.get("ref"))
            except Exception as exc: err(f"generation checkpoint ref invalid for {sid}: {exc}"); continue
            if not c_path.is_file(): err(f"generation checkpoint file missing for {sid}: {c_entry.get('ref')}")
            else:
                if file_sha256(c_path) != c_entry.get("sha256"): err(f"generation checkpoint file hash drift for {sid}: {c_entry.get('ref')}")
                try: c_data = json.loads(c_path.read_text(encoding="utf-8"))
                except Exception as exc: err(f"generation checkpoint unreadable for {sid}: {exc}"); continue
                if contract_version == 3 and not isinstance(c_data, dict):
                    err(f"generation checkpoint payload must be an object for {sid}: {c_entry.get('ref')}")
                    continue
                if isinstance(c_data, dict):
                    if c_data.get("checkpoint_sequence") != c_seq:
                        err(f"generation checkpoint sequence in payload ({c_data.get('checkpoint_sequence')}) != index ({c_seq}) for {sid}")
                    for c_err in validate_checkpoint_contract(root, c_data, checkpoint_schema, sid, generation.get("source_ref"), generation.get("thread_id"), expected_source_identity=source.get("identity"), expected_source_version=source.get("pin"), expected_critical_partitions=critical):
                        err(f"generation checkpoint {sid} seq {c_seq}: {c_err}")
                    if prior_checkpoint_data is not None and prior_checkpoint_sha is not None:
                        for c_err in validate_checkpoint_resume(prior_checkpoint_data, c_data, prior_checkpoint_sha):
                            err(f"generation checkpoint {sid} seq {c_seq}: {c_err}")
                    prior_checkpoint_data = c_data
                    prior_checkpoint_sha = file_sha256(c_path)
        turns=generation.get("turns",[]) if isinstance(generation.get("turns"),list) else []
        numbers=[t.get("turn_number") for t in turns if isinstance(t,dict)]
        if numbers!=list(range(1,len(turns)+1)): err(f"turn index sequence is not contiguous for {sid}")
        prior_hash=None; final_disposition=None
        turn_checkpoint_last_seq = 0
        turn_checkpoint_prior_data = None
        turn_checkpoint_prior_sha = None
        for turn_rec in turns:
            if not isinstance(turn_rec,dict): continue
            try: turn_path=safe_ref(root,turn_rec.get("ref"))
            except Exception as exc: err(f"turn ref invalid for {sid}: {exc}"); continue
            if not turn_path.is_file(): err(f"turn envelope missing for {sid}: {turn_rec.get('ref')}"); continue
            if file_sha256(turn_path)!=turn_rec.get("sha256"): err(f"turn envelope file hash drift for {sid} turn {turn_rec.get('turn_number')}")
            try: envelope=json.loads(turn_path.read_text(encoding="utf-8"))
            except Exception as exc: err(f"turn envelope unreadable for {sid}: {exc}"); continue
            for e in validate_schema(envelope,turn_schema,turn_schema): err(f"turn envelope schema {sid}/{turn_rec.get('turn_number')}: {e}")
            expected_turn_version = v3_version if contract_version == 3 else "flyby/source-review-turn-contract/2.1"
            if envelope.get("contract_version") != expected_turn_version:
                err(f"turn contract version mismatch for {sid} turn {turn_rec.get('turn_number')}: expected {expected_turn_version}")
            if envelope.get("turn_sha256")!=envelope_hash(envelope): err(f"turn_sha256 mismatch for {sid} turn {turn_rec.get('turn_number')}")
            if envelope.get("adoption_sha256")!=index.get("adoption_sha256"): err(f"turn adoption hash mismatch for {sid} turn {turn_rec.get('turn_number')}")
            sb=envelope.get("source_binding",{})
            expected={"source_id":sid,"source_identity":generation.get("source_ref"),"target_base":generation.get("target_base"),"rights_mode":generation.get("rights_mode"),"thread_id":generation.get("thread_id"),"generation":gen,"provider":generation.get("provider"),"model":generation.get("model"),"reasoning_effort":generation.get("reasoning_effort"),"execution_custody":"DIRECT_TOP_LEVEL_SESSION","child_thread_created":False,"delegation_used":False,"critical_partition_manifest_sha256":generation.get("critical_partition_manifest_sha256"),"launch_receipt_sha256":generation.get("launch_receipt_sha256")}
            for key,value in expected.items():
                if sb.get(key)!=value: err(f"turn source binding mismatch {sid} turn {turn_rec.get('turn_number')}: {key}")
            tm=envelope.get("turn_metadata",{}); num=turn_rec.get("turn_number")
            if tm.get("turn_number")!=num: err(f"turn number mismatch for {sid}: index {num}")
            phase=tm.get("phase"); rc=phases.get(phase)
            if rc is None: err(f"unknown/stale phase for {sid} turn {num}: {phase}")
            else:
                if tm.get("phase_contract_sha256")!=rc.get("phase_contract_sha256"): err(f"stale phase contract digest for {sid} turn {num}")
                if tm.get("phase_authorization")!=rc.get("phase_authorization"): err(f"phase authorization mismatch for {sid} turn {num}")
                try: instruction_path=safe_ref(root,tm.get("instruction_ref"))
                except Exception as exc: err(f"instruction ref invalid for {sid} turn {num}: {exc}")
                else:
                    if not instruction_path.is_file(): err(f"instruction evidence missing for {sid} turn {num}")
                    else:
                        instruction_text=instruction_path.read_text(encoding="utf-8")
                        if file_sha256(instruction_path)!=tm.get("instruction_sha256"): err(f"instruction hash drift for {sid} turn {num}")
                        if str(rc.get("instruction")) not in instruction_text: err(f"instruction does not contain current phase contract for {sid} turn {num}")
                        if str(sid) not in instruction_text or str(generation.get("source_ref")) not in instruction_text or str(generation.get("target_base")) not in instruction_text or f"generation={gen}" not in instruction_text: err(f"instruction lacks source/ref/target/generation binding for {sid} turn {num}")
                        if num==1:
                            if "thread_id=PENDING_DIRECT_LAUNCH" not in instruction_text: err(f"turn-1 instruction lacks pending-direct-launch marker for {sid}")
                            if isinstance(launch_receipt,dict):
                                if launch_receipt.get("turn_1_prompt_ref")!=tm.get("instruction_ref") or launch_receipt.get("turn_1_prompt_sha256")!=tm.get("instruction_sha256"): err(f"turn-1 instruction does not match launch receipt for {sid}")
                        else:
                            if str(generation.get("thread_id")) not in instruction_text or str(prior_hash) not in instruction_text: err(f"instruction lacks exact thread/predecessor binding for {sid} turn {num}")
            if contract_version == 3:
                expected_phase = "EVIDENCE_ASSESSMENT" if num == 1 else "EVIDENCE_CONTINUATION"
            else:
                expected_phase = "EXHAUSTIVE_DISCOVERY" if num == 1 else "OMISSION_AND_ADVERSARIAL_CHALLENGE" if num == 2 else "TARGET_INTEGRATION_DEEPENING" if num == 3 else "ADAPTIVE_CONTINUATION"
            if phase!=expected_phase: err(f"turn phase sequence mismatch for {sid} turn {num}: expected {expected_phase}")
            if num==1:
                if tm.get("prior_turn_sha256") is not None: err(f"turn 1 prior_turn_sha256 must be null for {sid}")
            else:
                if not isinstance(tm.get("prior_turn_sha256"),str) or tm.get("prior_turn_sha256")!=prior_hash: err(f"turn {num} prior_turn_sha256 does not match exact predecessor for {sid}")
            evidence=envelope.get("evidence",{})
            try: evidence_path=safe_ref(root,evidence.get("ref"))
            except Exception as exc: err(f"turn evidence ref invalid for {sid} turn {num}: {exc}")
            else:
                if not evidence_path.is_file(): err(f"turn evidence missing for {sid} turn {num}")
                elif file_sha256(evidence_path)!=evidence.get("sha256"): err(f"turn evidence hash drift for {sid} turn {num}")
            env_checkpoints = evidence.get("checkpoints", []) if isinstance(evidence.get("checkpoints"), list) else []
            if contract_version == 3 and env_checkpoints: ensure_v3_checkpoint_schema()
            for c_entry in env_checkpoints:
                if not isinstance(c_entry, dict): continue
                c_seq = c_entry.get("checkpoint_sequence")
                if not isinstance(c_seq, int) or c_seq <= turn_checkpoint_last_seq:
                    err(f"turn {num} checkpoint sequence not strictly monotonic for {sid}: {c_seq} after {turn_checkpoint_last_seq}")
                if isinstance(c_seq, int) and turn_checkpoint_last_seq and c_seq != turn_checkpoint_last_seq + 1:
                    err(f"turn {num} checkpoint sequence not contiguous for {sid}: {c_seq} after {turn_checkpoint_last_seq}")
                if isinstance(c_seq, int) and not turn_checkpoint_last_seq and c_seq != 1:
                    err(f"turn {num} checkpoint chain must start at sequence 1 for {sid}: got {c_seq}")
                try: c_path = safe_ref(root, c_entry.get("checkpoint_ref"))
                except Exception as exc: err(f"turn {num} checkpoint ref invalid for {sid}: {exc}"); continue
                if not c_path.is_file(): err(f"turn {num} checkpoint file missing for {sid}: {c_entry.get('checkpoint_ref')}")
                else:
                    if file_sha256(c_path) != c_entry.get("checkpoint_sha256"): err(f"turn {num} checkpoint file hash drift for {sid}: {c_entry.get('checkpoint_ref')}")
                    try: c_data = json.loads(c_path.read_text(encoding="utf-8"))
                    except Exception as exc: err(f"turn {num} checkpoint unreadable for {sid}: {exc}"); continue
                    if contract_version == 3 and not isinstance(c_data, dict):
                        err(f"turn {num} checkpoint payload must be an object for {sid}: {c_entry.get('checkpoint_ref')}")
                        continue
                    if isinstance(c_data, dict):
                        if c_data.get("checkpoint_sequence") != c_seq:
                            err(f"turn {num} checkpoint sequence in payload ({c_data.get('checkpoint_sequence')}) != envelope ({c_seq}) for {sid}")
                        for c_err in validate_checkpoint_contract(root, c_data, checkpoint_schema, sid, generation.get("source_ref"), generation.get("thread_id"), expected_turn_number=num, expected_source_identity=source.get("identity"), expected_source_version=source.get("pin"), expected_critical_partitions=critical):
                            err(f"turn {num} checkpoint {sid} seq {c_seq}: {c_err}")
                        if turn_checkpoint_prior_data is not None and turn_checkpoint_prior_sha is not None:
                            for c_err in validate_checkpoint_resume(turn_checkpoint_prior_data, c_data, turn_checkpoint_prior_sha):
                                err(f"turn {num} checkpoint {sid} seq {c_seq}: {c_err}")
                        turn_checkpoint_prior_data = c_data
                        turn_checkpoint_prior_sha = file_sha256(c_path)
                        if isinstance(c_seq, int) and c_seq > turn_checkpoint_last_seq:
                            turn_checkpoint_last_seq = c_seq
            payload=envelope.get("turn_payload",{}); inspected=payload.get("inspected_locators",[])
            inspected_keys=set()
            for loc in inspected if isinstance(inspected,list) else []:
                if not isinstance(loc,dict): continue
                if loc.get("source_ref")!=generation.get("source_ref"): err(f"foreign source locator for {sid} turn {num}")
                inspected_keys.add(locator_key(loc))
            contribs=payload.get("extracted_contributions",[]) if isinstance(payload.get("extracted_contributions"),list) else []
            ids=[c.get("contribution_id") for c in contribs if isinstance(c,dict)]
            if len(ids)!=len(contribs) or len(ids)!=len(set(ids)): err(f"duplicate/missing contribution id for {sid} turn {num}")
            for c in contribs:
                if not isinstance(c,dict): continue
                if c.get("rights_mode")!=generation.get("rights_mode"): err(f"contribution rights mismatch for {sid} turn {num}")
                for loc in c.get("source_locators",[]):
                    if isinstance(loc,dict) and locator_key(loc) not in inspected_keys: err(f"contribution locator was not inspected for {sid} turn {num}")
            covered=set(payload.get("covered_critical_partitions",[])); uninspected=set(payload.get("uninspected_critical_partitions",[])); critical_set=set(critical)
            if covered|uninspected != critical_set or covered & uninspected: err(f"critical partition accounting mismatch for {sid} turn {num}")
            if contract_version == 3:
                # Bind each declared covered partition to the locators this
                # turn actually inspected, rather than accepting coverage as
                # an unconnected list of names.
                partition_evidence = payload.get("partition_evidence", [])
                rows = partition_evidence if isinstance(partition_evidence, list) else []
                mapped = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    partition = row.get("partition")
                    if isinstance(partition, str):
                        mapped.append(partition)
                    locators = row.get("inspected_locators")
                    if not isinstance(locators, list) or not locators:
                        err(f"partition evidence lacks inspected locators for {sid} turn {num}: {partition}")
                        continue
                    for locator in locators:
                        if not isinstance(locator, dict) or locator_key(locator) not in inspected_keys:
                            err(f"partition evidence locator was not inspected for {sid} turn {num}: {partition}")
                if len(mapped) != len(rows) or len(mapped) != len(set(mapped)) or set(mapped) != covered:
                    err(f"covered partition evidence mapping mismatch for {sid} turn {num}")
            disposition=payload.get("disposition_status"); final_disposition=disposition
            if disposition=="CONVERGED":
                if tm.get("phase_authorization")!="CONVERGENCE_PERMITTED_IF_EXHAUSTED": err(f"forbidden-phase convergence for {sid} turn {num}")
                if uninspected or payload.get("material_omissions_remaining") is not False or not inspected: err(f"false convergence with open gaps for {sid} turn {num}")
            elif tm.get("phase_authorization")=="CONVERGENCE_FORBIDDEN" and payload.get("material_omissions_remaining") is False and not uninspected:
                # Exhaustion may be observed, but the forbidden phase still cannot declare convergence.
                pass
            prior_hash=envelope.get("turn_sha256")
        state=generation.get("state")
        if state=="CONVERGED" and final_disposition!="CONVERGED": err(f"generation marked CONVERGED without converged final envelope for {sid}")
        if state=="ACTIVE" and final_disposition=="CONVERGED": err(f"generation remains ACTIVE after converged final envelope for {sid}")
    if len(post_keys)!=len(set(post_keys)) or len(post_threads)!=len(set(post_threads)): err("post-enforcement generation keys/threads are duplicated")
    if set(legacy_threads) & set(post_threads): err("thread appears in both legacy and post-enforcement generation sets")
    represented_owners=set(legacy_threads)|set(post_threads)
    for sid,source in sources.items():
        if source.get("thread") and source.get("thread") not in represented_owners: err(f"active source owner lacks legacy/post-enforcement generation record: {sid}")
    return errors
