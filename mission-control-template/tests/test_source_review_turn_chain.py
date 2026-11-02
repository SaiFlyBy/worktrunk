from __future__ import annotations
import copy, hashlib, json, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from source_review_turn_chain import canonical_sha256, envelope_hash, file_sha256, validate_turn_chain, validate_cleanup_manifest

def _find_schema(name: str) -> dict:
    candidates = [
        ROOT / 'schemas' / name,
        ROOT / 'control' / 'revisions' / 'PROVENANCE_EXPANSION_20260901' / name
    ]
    for c in candidates:
        if c.is_file():
            return json.loads(c.read_text(encoding='utf-8'))
    raise FileNotFoundError(f"Schema not found: {name}")

TURN_SCHEMA=_find_schema('SOURCE_REVIEW_TURN_CONTRACT_SCHEMA.json')
CHAIN_SCHEMA=_find_schema('SOURCE_REVIEW_TURN_CHAIN_INDEX_SCHEMA.json')
LAUNCH_SCHEMA=_find_schema('DIRECT_LAUNCH_RECEIPT_SCHEMA.json')
CHECKPOINT_SCHEMA=_find_schema('SOURCE_REVIEW_CHECKPOINT_SCHEMA.json')
SOURCE_ID='reference-method'
SOURCE_REF='example/reference@0123456789abcdef0123456789abcdef01234567'
THREAD='codex://threads/reference-direct-generation-2'
PHASES=[
 ('EXHAUSTIVE_DISCOVERY','CONVERGENCE_FORBIDDEN','Partition the full source into critical subsystems/sections; inspect broadly; enumerate capabilities, exact evidence locators, target overlap/gaps, rights implications, and explicitly record uninspected critical partitions. Do not claim convergence.'),
 ('OMISSION_AND_ADVERSARIAL_CHALLENGE','CONVERGENCE_FORBIDDEN','Attack Round 1. Read every weak/uninspected critical partition, tests/failure paths/appendices, challenge ALREADY_SATISFIED/REJECT/direct-reuse decisions, and find second-order capabilities.'),
 ('TARGET_INTEGRATION_DEEPENING','CONVERGENCE_PERMITTED_IF_EXHAUSTED','Against current target authority, turn surviving capabilities into concrete direct-reuse/adapt/combine decisions, source contribution records, cross-source combination candidates, target owners, hostile tests, obligations and mutation implications.'),
 ('ADAPTIVE_CONTINUATION','CONVERGENCE_PERMITTED_IF_EXHAUSTED','Repeat focused omission/integration turns in the SAME source thread while any material omission, unresolved high-value question, or uninspected critical partition remains. There is no fixed maximum turn count.'),
]
CRITICAL=['architecture','validation','target-integration']

def write_json(path: Path,value):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def build_valid_chain():
    td=tempfile.TemporaryDirectory(prefix='mcv16-turn-chain-'); root=Path(td.name)
    target_base='0123456789abcdef0123456789abcdef01234567'
    source=root/'evidence'/'source.txt'; source.parent.mkdir(parents=True); source.write_text('architecture\nvalidation\ntarget integration\n',encoding='utf-8')
    rounds=[]
    for idx,(name,auth,instruction) in enumerate(PHASES,1):
        rounds.append({'round':idx if idx<4 else '4+','name':name,'instruction':instruction,'phase_authorization':auth,'phase_contract_sha256':canonical_sha256({'name':name,'instruction':instruction,'phase_authorization':auth})})
    phase_index=[{'name':r['name'],'phase_contract_sha256':r['phase_contract_sha256']} for r in rounds]
    plan={'target_base':target_base,'agent_policy':{'model':'gpt-5.6-luna','reasoning_effort':'max'},'round_contracts':rounds,'sources':[{'source_id':SOURCE_ID,'identity':'example/reference','pin':'0123456789abcdef0123456789abcdef01234567','current_usage_mode':'LICENSE_PERMITTED_REUSE','thread':THREAD,'provider':'mailbox.codex'}],'retired_review_threads':[],'owner_map':{'state':'AUTHORITATIVE_ACTIVE_SOURCE_CUSTODY','sources':[{'source_id':SOURCE_ID,'active_thread':THREAD,'active_provider':'mailbox.codex','active_generation':2,'envelope_regime':'POST_ENFORCEMENT_V2','retired_threads':[]}]}}
    adoption={'round_contracts_sha256':canonical_sha256(phase_index),'policy':{k:True for k in ['no_retroactive_turn_hash_fabrication','direct_top_level_sessions_only','child_thread_creation_forbidden','delegation_from_review_session_forbidden','turn_envelopes_append_only','prior_hash_required_after_turn_one','phase_instruction_digest_required','source_pinned_locator_hash_required','evidence_hash_required']}}
    adoption_path=root/'adoption.json'; write_json(adoption_path,adoption)
    adoption_sha=file_sha256(adoption_path); crit_sha=canonical_sha256(CRITICAL)
    prompt1=root/'evidence'/'prompt1.txt'
    prompt1.write_text(f'source={SOURCE_ID}\nref={SOURCE_REF}\ntarget_base={target_base}\ngeneration=2\nthread_id=PENDING_DIRECT_LAUNCH\nphase={PHASES[0][2]}\n',encoding='utf-8')

    birth_evidence=root/'evidence'/'session_birth.json'
    write_json(birth_evidence,{
        'schema':'flyby/provider-session-birth-evidence/1',
        'thread_id':THREAD,
        'provider':'mailbox.codex',
        'birth_type':'DIRECT_TOP_LEVEL_START',
        'approval_policy':'never',
        'sandbox_policy':'danger-full-access',
        'child_thread_created':False,
        'delegation_used':False,
        'session_birth_lines':[
            {'type':'turn_context','payload':{'approval_policy':'never','sandbox_policy':'danger-full-access'}},
            {'type':'response_item','payload':{'type':'message','role':'assistant'}}
        ]
    })
    birth_sha=file_sha256(birth_evidence)

    from source_review_turn_chain import launch_receipt_hash
    receipt={
        'schema':'flyby/mission-control-direct-launch-receipt/1',
        'source_id':SOURCE_ID,
        'source_ref':SOURCE_REF,
        'generation':2,
        'target_base':target_base,
        'assigned_thread_id':THREAD,
        'provider':'mailbox.codex',
        'model':'gpt-5.6-luna',
        'reasoning_effort':'max',
        'approval_policy':'never',
        'sandbox_policy':'danger-full-access',
        'execution_custody':'DIRECT_TOP_LEVEL_SESSION',
        'child_thread_created':False,
        'delegation_used':False,
        'launch_api':'mailbox.codex.start',
        'launch_observed_at':'2026-09-02T00:00:00Z',
        'turn_1_prompt_ref':'evidence/prompt1.txt',
        'turn_1_prompt_sha256':file_sha256(prompt1),
        'session_birth_evidence_ref':'evidence/session_birth.json',
        'session_birth_evidence_sha256':birth_sha,
        'receipt_sha256':None
    }
    receipt['receipt_sha256']=launch_receipt_hash(receipt)
    receipt_path=root/'receipt.json'; write_json(receipt_path,receipt)
    receipt_sha=file_sha256(receipt_path)
    turns=[]; prior=None
    for num in (1,2,3):
        phase,auth,instruction=PHASES[num-1]
        prompt=root/'evidence'/f'prompt{num}.txt'
        if num > 1:
            prompt.write_text(f'source={SOURCE_ID}\nref={SOURCE_REF}\ntarget_base={target_base}\ngeneration=2\nthread_id={THREAD}\nprior_turn_sha256={prior}\nphase={instruction}\n',encoding='utf-8')
        evidence=root/'evidence'/f'evidence{num}.json'; write_json(evidence,{'turn':num,'source_id':SOURCE_ID})
        covered=CRITICAL[:num]; uninspected=CRITICAL[num:]
        loc={'source_ref':SOURCE_REF,'path':'evidence/source.txt','locator':f'L{num}','content_sha256':file_sha256(source)}
        env={'contract_version':'flyby/source-review-turn-contract/2.1','adoption_sha256':adoption_sha,'source_binding':{'source_id':SOURCE_ID,'source_identity':SOURCE_REF,'rights_mode':'LICENSE_PERMITTED_REUSE','thread_id':THREAD,'generation':2,'target_base':target_base,'launch_receipt_sha256':receipt_sha,'provider':'mailbox.codex','model':'gpt-5.6-luna','reasoning_effort':'max','execution_custody':'DIRECT_TOP_LEVEL_SESSION','child_thread_created':False,'delegation_used':False,'critical_partition_manifest_sha256':crit_sha},'turn_metadata':{'turn_number':num,'phase':phase,'phase_authorization':auth,'phase_contract_sha256':rounds[num-1]['phase_contract_sha256'],'instruction_ref':f'evidence/prompt{num}.txt','instruction_sha256':file_sha256(prompt),'prior_turn_sha256':prior},'evidence':{'ref':f'evidence/evidence{num}.json','sha256':file_sha256(evidence),'kind':'TURN_OUTPUT'},'turn_payload':{'disposition_status':'CONVERGED' if num==3 else 'IN_PROGRESS','covered_critical_partitions':covered,'uninspected_critical_partitions':uninspected,'material_omissions_remaining':False if num==3 else True,'inspected_locators':[loc],'extracted_contributions':[{'contribution_id':f'{SOURCE_ID}::M{num}','mechanism_id':f'M{num}','source_locators':[loc],'rights_mode':'LICENSE_PERMITTED_REUSE','reuse_class':'PARAPHRASED_SYNTHESIS','concrete_derivation':'target-native derivation','obligations':['retain attribution'],'runtime_intercept':{'phase':'PROVENANCE_CONTROL','execution_order':num,'state_in':['source_evidence'],'state_out':[f'target_{num}'],'composition_mode':'PIPELINE_TRANSFORM'}}],'verdict_rationale':'complete' if num==3 else 'continue'},'turn_sha256':None}
        env['turn_sha256']=envelope_hash(env); tp=root/f'turn{num}.json'; write_json(tp,env); turns.append({'turn_number':num,'ref':tp.name,'sha256':file_sha256(tp)}); prior=env['turn_sha256']
    index={'schema':'flyby/source-review-turn-chain-index/1','adoption_ref':'adoption.json','adoption_sha256':adoption_sha,'legacy_pre_enforcement':[],'post_enforcement_generations':[{'source_id':SOURCE_ID,'source_ref':SOURCE_REF,'target_base':target_base,'launch_receipt_ref':'receipt.json','launch_receipt_sha256':receipt_sha,'thread_id':THREAD,'generation':2,'provider':'mailbox.codex','model':'gpt-5.6-luna','reasoning_effort':'max','rights_mode':'LICENSE_PERMITTED_REUSE','execution_custody':'DIRECT_TOP_LEVEL_SESSION','critical_partitions':CRITICAL,'critical_partition_manifest_sha256':crit_sha,'turns':turns,'state':'CONVERGED'}]}
    return td,root,plan,adoption,index

def rewrite_turn(root,index,num,mutator,recompute_self=True):
    rec=index['post_enforcement_generations'][0]['turns'][num-1]; path=root/rec['ref']; env=json.loads(path.read_text(encoding='utf-8')); mutator(env)
    if recompute_self: env['turn_sha256']=envelope_hash(env)
    write_json(path,env); rec['sha256']=file_sha256(path)
    return env

def errors_for(mutator=None):
    td,root,plan,adoption,index=build_valid_chain()
    try:
        if mutator: mutator(root,plan,adoption,index)
        return validate_turn_chain(root,TURN_SCHEMA,CHAIN_SCHEMA,LAUNCH_SCHEMA,adoption,plan,index)
    finally: td.cleanup()

def test_valid_three_turn_chain_passes(): assert errors_for()==[]

def test_forbidden_phase_convergence_rejected():
    def m(root,plan,adoption,index):
        rewrite_turn(root,index,1,lambda e:e['turn_payload'].update({'disposition_status':'CONVERGED','uninspected_critical_partitions':[],'covered_critical_partitions':CRITICAL,'material_omissions_remaining':False}))
    assert any('forbidden-phase convergence' in e for e in errors_for(m))

def test_open_gap_convergence_rejected():
    def m(root,plan,adoption,index): rewrite_turn(root,index,3,lambda e:e['turn_payload'].update({'uninspected_critical_partitions':['validation'],'covered_critical_partitions':['architecture','target-integration'],'material_omissions_remaining':True}))
    assert any('false convergence with open gaps' in e for e in errors_for(m))

def test_turn3_null_predecessor_rejected():
    def m(root,plan,adoption,index): rewrite_turn(root,index,3,lambda e:e['turn_metadata'].__setitem__('prior_turn_sha256',None))
    assert any('prior_turn_sha256 does not match exact predecessor' in e for e in errors_for(m))

def test_turn3_zero_predecessor_rejected():
    def m(root,plan,adoption,index): rewrite_turn(root,index,3,lambda e:e['turn_metadata'].__setitem__('prior_turn_sha256','0'*64))
    assert any('prior_turn_sha256 does not match exact predecessor' in e for e in errors_for(m))

def test_turn3_wrong_predecessor_rejected():
    def m(root,plan,adoption,index): rewrite_turn(root,index,3,lambda e:e['turn_metadata'].__setitem__('prior_turn_sha256','f'*64))
    assert any('prior_turn_sha256 does not match exact predecessor' in e for e in errors_for(m))

def test_stale_phase_digest_rejected():
    def m(root,plan,adoption,index): rewrite_turn(root,index,2,lambda e:e['turn_metadata'].__setitem__('phase_contract_sha256','0'*64))
    assert any('stale phase contract digest' in e for e in errors_for(m))

def test_foreign_locator_rejected():
    def m(root,plan,adoption,index): rewrite_turn(root,index,2,lambda e:e['turn_payload']['inspected_locators'][0].__setitem__('source_ref','foreign@deadbeef'))
    assert any('foreign source locator' in e for e in errors_for(m))

def test_duplicate_contribution_id_rejected():
    def m(root,plan,adoption,index):
        def edit(e): e['turn_payload']['extracted_contributions'].append(copy.deepcopy(e['turn_payload']['extracted_contributions'][0]))
        rewrite_turn(root,index,2,edit)
    assert any('duplicate/missing contribution id' in e for e in errors_for(m))

def test_rights_mismatch_rejected():
    def m(root,plan,adoption,index): rewrite_turn(root,index,2,lambda e:e['turn_payload']['extracted_contributions'][0].__setitem__('rights_mode','OWNER_AUTHORIZED_REUSE'))
    assert any('contribution rights mismatch' in e for e in errors_for(m))

def test_missing_evidence_rejected():
    def m(root,plan,adoption,index): (root/'evidence'/'evidence2.json').unlink()
    assert any('turn evidence missing' in e for e in errors_for(m))

def test_child_or_delegated_review_rejected():
    def m(root,plan,adoption,index):
        def edit(e): e['source_binding'].update({'child_thread_created':True,'delegation_used':True})
        rewrite_turn(root,index,2,edit)
    errs=errors_for(m); assert any('turn envelope schema' in e or 'source binding mismatch' in e for e in errs)

def test_duplicate_source_owner_rejected():
    def m(root,plan,adoption,index): plan['sources'].append(copy.deepcopy(plan['sources'][0]))
    assert any('plan source ids are missing or duplicated' in e for e in errors_for(m))

def test_replacement_without_matching_tombstone_rejected():
    def m(root,plan,adoption,index): plan['sources'][0]['retired_thread']='codex://threads/old-owner'
    assert any('lacks same-source tombstone' in e for e in errors_for(m))

def test_tombstoned_active_thread_rejected():
    def m(root,plan,adoption,index): plan['retired_review_threads']=[{'source_id':SOURCE_ID,'thread':THREAD,'state':'TOMBSTONED_INVALID_EVIDENCE','may_satisfy_source_review':False}]
    assert any('active source owner is tombstoned' in e or 'owner map tombstone set mismatch' in e for e in errors_for(m))

def sync_receipt_and_turns(root, index, receipt):
    from source_review_turn_chain import launch_receipt_hash
    receipt['receipt_sha256']=launch_receipt_hash(receipt)
    receipt_path=root/'receipt.json'
    write_json(receipt_path,receipt)
    r_sha=file_sha256(receipt_path)
    gen_rec=index['post_enforcement_generations'][0]
    gen_rec['launch_receipt_sha256']=r_sha
    target_base=gen_rec['target_base']
    sid=gen_rec['source_id']
    sref=gen_rec['source_ref']
    thread=gen_rec['thread_id']
    gen=gen_rec['generation']
    prior=None
    for turn_rec in gen_rec['turns']:
        num=turn_rec['turn_number']
        tp=root/turn_rec['ref']
        env=json.loads(tp.read_text(encoding='utf-8'))
        env['source_binding']['launch_receipt_sha256']=r_sha
        env['turn_metadata']['prior_turn_sha256']=prior
        phase,auth,instruction=PHASES[num-1]
        prompt=root/'evidence'/f'prompt{num}.txt'
        if num==1:
            prompt.write_text(f'source={sid}\nref={sref}\ntarget_base={target_base}\ngeneration={gen}\nthread_id=PENDING_DIRECT_LAUNCH\nphase={instruction}\n',encoding='utf-8')
        else:
            prompt.write_text(f'source={sid}\nref={sref}\ntarget_base={target_base}\ngeneration={gen}\nthread_id={thread}\nprior_turn_sha256={prior}\nphase={instruction}\n',encoding='utf-8')
        env['turn_metadata']['instruction_sha256']=file_sha256(prompt)
        env['turn_sha256']=envelope_hash(env)
        write_json(tp,env)
        turn_rec['sha256']=file_sha256(tp)
        prior=env['turn_sha256']

def test_launch_receipt_missing_birth_evidence_rejected():
    def m(root,plan,adoption,index):
        (root/'evidence'/'session_birth.json').unlink()
    assert any('session birth evidence missing' in e for e in errors_for(m))

def test_launch_receipt_tampered_birth_evidence_hash_rejected():
    def m(root,plan,adoption,index):
        receipt_path=root/'receipt.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['session_birth_evidence_sha256']='0'*64
        sync_receipt_and_turns(root,index,receipt)
    assert any('session birth evidence file hash drift' in e for e in errors_for(m))

def test_forged_direct_top_level_with_child_birth_rejected():
    def m(root,plan,adoption,index):
        birth_path=root/'evidence'/'session_birth.json'
        data=json.loads(birth_path.read_text(encoding='utf-8'))
        data['session_birth_lines'].append({'type':'response_item','payload':{'type':'function_call_output','name':'create_thread'}})
        write_json(birth_path,data)
        receipt_path=root/'receipt.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['session_birth_evidence_sha256']=file_sha256(birth_path)
        sync_receipt_and_turns(root,index,receipt)
    assert any('child thread birth detected' in e for e in errors_for(m))

def test_forged_direct_top_level_with_fork_thread_rejected():
    def m(root,plan,adoption,index):
        birth_path=root/'evidence'/'session_birth.json'
        data=json.loads(birth_path.read_text(encoding='utf-8'))
        data['session_birth_lines'].append({'type':'response_item','payload':{'type':'function_call_output','name':'fork_thread'}})
        write_json(birth_path,data)
        receipt_path=root/'receipt.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['session_birth_evidence_sha256']=file_sha256(birth_path)
        sync_receipt_and_turns(root,index,receipt)
    assert any('child thread birth detected' in e for e in errors_for(m))

def test_forbidden_on_request_approval_policy_in_birth_lines_rejected():
    def m(root,plan,adoption,index):
        birth_path=root/'evidence'/'session_birth.json'
        data=json.loads(birth_path.read_text(encoding='utf-8'))
        data['session_birth_lines']=[{'type':'turn_context','payload':{'approval_policy':'on-request','sandbox_policy':'danger-full-access'}}]
        write_json(birth_path,data)
        receipt_path=root/'receipt.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['session_birth_evidence_sha256']=file_sha256(birth_path)
        sync_receipt_and_turns(root,index,receipt)
    assert any('forbidden policy detected' in e or 'approval_policy' in e for e in errors_for(m))

def test_forbidden_workspace_write_sandbox_policy_in_birth_lines_rejected():
    def m(root,plan,adoption,index):
        birth_path=root/'evidence'/'session_birth.json'
        data=json.loads(birth_path.read_text(encoding='utf-8'))
        data['session_birth_lines']=[{'type':'turn_context','payload':{'approval_policy':'never','sandbox_policy':'workspace-write'}}]
        write_json(birth_path,data)
        receipt_path=root/'receipt.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['session_birth_evidence_sha256']=file_sha256(birth_path)
        sync_receipt_and_turns(root,index,receipt)
    assert any('forbidden policy detected' in e or 'sandbox_policy' in e for e in errors_for(m))

def test_birth_evidence_thread_mismatch_rejected():
    def m(root,plan,adoption,index):
        birth_path=root/'evidence'/'session_birth.json'
        data=json.loads(birth_path.read_text(encoding='utf-8'))
        data['thread_id']='codex://threads/forged-thread-id'
        write_json(birth_path,data)
        receipt_path=root/'receipt.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['session_birth_evidence_sha256']=file_sha256(birth_path)
        sync_receipt_and_turns(root,index,receipt)
    assert any('birth evidence thread mismatch' in e for e in errors_for(m))

def test_jsonl_birth_evidence_format_supported_and_validated():
    def m(root,plan,adoption,index):
        birth_path=root/'evidence'/'session_birth.json'
        jsonl_content=(
            json.dumps({'type':'turn_context','payload':{'approval_policy':'never','sandbox_policy':'danger-full-access'}})+'\n'+
            json.dumps({'type':'response_item','payload':{'type':'message','role':'assistant'}})+'\n'
        )
        birth_path.write_text(jsonl_content,encoding='utf-8')
        receipt_path=root/'receipt.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['session_birth_evidence_sha256']=file_sha256(birth_path)
        sync_receipt_and_turns(root,index,receipt)
    assert errors_for(m)==[]

def test_jsonl_birth_evidence_with_child_birth_rejected():
    def m(root,plan,adoption,index):
        birth_path=root/'evidence'/'session_birth.json'
        jsonl_content=(
            json.dumps({'type':'turn_context','payload':{'approval_policy':'never','sandbox_policy':'danger-full-access'}})+'\n'+
            json.dumps({'type':'response_item','payload':{'type':'function_call_output','name':'create_thread'}})+'\n'
        )
        birth_path.write_text(jsonl_content,encoding='utf-8')
        receipt_path=root/'receipt.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['session_birth_evidence_sha256']=file_sha256(birth_path)
        sync_receipt_and_turns(root,index,receipt)
    assert any('child thread birth detected' in e for e in errors_for(m))

def build_valid_checkpoint(root: Path, seq: int = 1, turn_num: int = 1) -> tuple[dict, str, str]:
    chk = {
        "schema": "flyby/source-review-checkpoint/1",
        "checkpoint_id": f"chk-{SOURCE_ID}-t{turn_num}-{seq:02d}",
        "source_id": SOURCE_ID,
        "source_ref": SOURCE_REF,
        "source_identity": "example/reference",
        "source_version": "0123456789abcdef0123456789abcdef01234567",
        "thread": THREAD,
        "turn_number": turn_num,
        "checkpoint_sequence": seq,
        "previous_checkpoint_sha256": None,
        "authority_status": "NON_AUTHORITATIVE_SCRATCH",
        "convergence_status": "IN_PROGRESS",
        "completion_flag": False,
        "license_and_rights_evidence": {
            "license_locator": "LICENSE.txt#L1-L20",
            "rights_state": "LICENSE_PERMITTED_REUSE",
            "declared_permissions": ["commercial_use", "modification"],
            "third_party_notices_required": False
        },
        "coverage_cursor": {
            "inspected_partition": "architecture",
            "inspected_paths": ["src/arch.py"],
            "inspected_commit_or_version": "0123456789abcdef0123456789abcdef01234567",
            "completed_partitions": ["architecture"],
            "remaining_partitions": ["validation", "target-integration"]
        },
        "mechanism_candidates": [
            {
                "candidate_id": f"cand-{seq}",
                "name": "PipelineStep",
                "finding_class": "SOURCE_FACT",
                "evidence_locator": "src/arch.py#L10-L40",
                "target_applicability": "Target pipeline execution"
            }
        ],
        "mc_reinterpretation_hypotheses": [
            {
                "hypothesis_id": f"hyp-{seq}",
                "finding_class": "ENGINEERING_INFERENCE",
                "target_mechanism_name": "TargetStep",
                "independent_design_notes": "Clean-room target implementation"
            }
        ],
        "rejected_or_non_adoptable": [],
        "failure_and_adversarial_notes": [
            {
                "kind": "ADVERSARIAL_CHALLENGE",
                "locator": "tests/test_arch.py#L1-L10",
                "note": "Challenge pipeline failure handling during next tranche",
                "impact": "May require an additional hostile target test"
            }
        ],
        "confidence_and_open_questions": {
            "confidence_rating": "HIGH",
            "open_questions": []
        },
        "unresolved_rights_issues": [],
        "next_read_cursor": {
            "target_next_partition": "validation",
            "target_next_paths": ["tests/test_arch.py"],
            "stop_condition": "Inspect validation test suite and checkpoint"
        }
    }
    path = root / 'evidence' / 'checkpoints' / f'chk_{turn_num}_{seq}.json'
    write_json(path, chk)
    return chk, f'evidence/checkpoints/chk_{turn_num}_{seq}.json', file_sha256(path)

def test_valid_checkpoint_in_turn_evidence_passes():
    def m(root, plan, adoption, index):
        chk, ref, sha = build_valid_checkpoint(root, seq=1, turn_num=3)
        rewrite_turn(root, index, 3, lambda e: e['evidence'].update({
            'checkpoints': [{'checkpoint_sequence': 1, 'checkpoint_ref': ref, 'checkpoint_sha256': sha}]
        }))
    assert errors_for(m) == []

def test_valid_generation_checkpoint_passes():
    def m(root, plan, adoption, index):
        chk, ref, sha = build_valid_checkpoint(root, seq=1, turn_num=1)
        index['post_enforcement_generations'][0]['checkpoints'] = [
            {'checkpoint_sequence': 1, 'ref': ref, 'sha256': sha}
        ]
    assert errors_for(m) == []

def test_checkpoint_non_monotonic_sequence_rejected():
    def m(root, plan, adoption, index):
        chk1, ref1, sha1 = build_valid_checkpoint(root, seq=2, turn_num=1)
        chk2, ref2, sha2 = build_valid_checkpoint(root, seq=1, turn_num=1)
        index['post_enforcement_generations'][0]['checkpoints'] = [
            {'checkpoint_sequence': 2, 'ref': ref1, 'sha256': sha1},
            {'checkpoint_sequence': 1, 'ref': ref2, 'sha256': sha2}
        ]
    assert any('checkpoint sequence not strictly monotonic' in e for e in errors_for(m))

def test_checkpoint_authority_status_must_be_non_authoritative_scratch():
    def m(root, plan, adoption, index):
        chk, ref, _ = build_valid_checkpoint(root, seq=1, turn_num=1)
        chk['authority_status'] = 'CANONICAL_AUTHORITY'
        p = root / ref
        write_json(p, chk)
        sha = file_sha256(p)
        index['post_enforcement_generations'][0]['checkpoints'] = [
            {'checkpoint_sequence': 1, 'ref': ref, 'sha256': sha}
        ]
    assert any('checkpoint authority_status must be NON_AUTHORITATIVE_SCRATCH' in e for e in errors_for(m))

def test_checkpoint_thread_mismatch_rejected():
    def m(root, plan, adoption, index):
        chk, ref, _ = build_valid_checkpoint(root, seq=1, turn_num=1)
        chk['thread'] = 'codex://threads/foreign-thread'
        p = root / ref
        write_json(p, chk)
        sha = file_sha256(p)
        index['post_enforcement_generations'][0]['checkpoints'] = [
            {'checkpoint_sequence': 1, 'ref': ref, 'sha256': sha}
        ]
    assert any('checkpoint thread mismatch' in e for e in errors_for(m))

def test_checkpoint_missing_coverage_cursor_rejected():
    def m(root, plan, adoption, index):
        chk, ref, _ = build_valid_checkpoint(root, seq=1, turn_num=1)
        chk.pop('coverage_cursor')
        p = root / ref
        write_json(p, chk)
        sha = file_sha256(p)
        index['post_enforcement_generations'][0]['checkpoints'] = [
            {'checkpoint_sequence': 1, 'ref': ref, 'sha256': sha}
        ]
    assert any('checkpoint coverage_cursor' in e or 'coverage_cursor' in e for e in errors_for(m))

def test_checkpoint_missing_next_read_cursor_rejected():
    def m(root, plan, adoption, index):
        chk, ref, _ = build_valid_checkpoint(root, seq=1, turn_num=1)
        chk.pop('next_read_cursor')
        p = root / ref
        write_json(p, chk)
        sha = file_sha256(p)
        index['post_enforcement_generations'][0]['checkpoints'] = [
            {'checkpoint_sequence': 1, 'ref': ref, 'sha256': sha}
        ]
    assert any('checkpoint next_read_cursor' in e or 'next_read_cursor' in e for e in errors_for(m))

def test_checkpoint_missing_rights_evidence_rejected():
    def m(root, plan, adoption, index):
        chk, ref, _ = build_valid_checkpoint(root, seq=1, turn_num=1)
        chk.pop('license_and_rights_evidence')
        p = root / ref
        write_json(p, chk)
        sha = file_sha256(p)
        index['post_enforcement_generations'][0]['checkpoints'] = [
            {'checkpoint_sequence': 1, 'ref': ref, 'sha256': sha}
        ]
    assert any('checkpoint license_and_rights_evidence' in e or 'license_and_rights_evidence' in e for e in errors_for(m))

def test_checkpoint_alone_cannot_satisfy_convergence():
    def m(root, plan, adoption, index):
        # A checkpoint claims convergence proposed, but turn 3 is unconverged
        chk, ref, sha = build_valid_checkpoint(root, seq=1, turn_num=1)
        chk['convergence_status'] = 'CONVERGENCE_PROPOSED'
        p = root / ref
        write_json(p, chk)
        sha = file_sha256(p)
        index['post_enforcement_generations'][0]['checkpoints'] = [
            {'checkpoint_sequence': 1, 'ref': ref, 'sha256': sha}
        ]
        # Make turn 3 remain IN_PROGRESS while generation state claims CONVERGED
        rewrite_turn(root, index, 3, lambda e: e['turn_payload'].update({
            'disposition_status': 'IN_PROGRESS',
            'material_omissions_remaining': True
        }))
    assert any('generation marked CONVERGED without converged final envelope' in e for e in errors_for(m))


def _install_checkpoint_chain(root, index, mutate_second=None):
    chk1, ref1, sha1 = build_valid_checkpoint(root, seq=1, turn_num=1)
    chk2, ref2, _ = build_valid_checkpoint(root, seq=2, turn_num=1)
    chk2['previous_checkpoint_sha256'] = sha1
    chk2['coverage_cursor']['inspected_partition'] = chk1['next_read_cursor']['target_next_partition']
    chk2['coverage_cursor']['inspected_paths'] = list(chk1['next_read_cursor']['target_next_paths'])
    chk2['coverage_cursor']['completed_partitions'] = ['architecture','validation']
    chk2['coverage_cursor']['remaining_partitions'] = ['target-integration']
    chk2['next_read_cursor'] = {'target_next_partition':'target-integration','target_next_paths':['src/target.py'],'stop_condition':'Inspect target integration and checkpoint'}
    if mutate_second:
        mutate_second(chk1, chk2)
    p2=root/ref2; write_json(p2,chk2); sha2=file_sha256(p2)
    index['post_enforcement_generations'][0]['checkpoints']=[
        {'checkpoint_sequence':1,'ref':ref1,'sha256':sha1},
        {'checkpoint_sequence':2,'ref':ref2,'sha256':sha2}
    ]

def test_checkpoint_lineage_and_resume_after_compaction_passes():
    def m(root,plan,adoption,index): _install_checkpoint_chain(root,index)
    assert errors_for(m)==[]

def test_checkpoint_tampered_previous_digest_rejected():
    def m(root,plan,adoption,index):
        _install_checkpoint_chain(root,index,lambda a,b: b.update(previous_checkpoint_sha256='0'*64))
    assert any('previous_checkpoint_sha256 does not match exact predecessor' in e for e in errors_for(m))

def test_checkpoint_forward_cursor_jump_rejected():
    def m(root,plan,adoption,index):
        _install_checkpoint_chain(root,index,lambda a,b: b['coverage_cursor'].update(inspected_partition='target-integration',inspected_paths=['src/target.py']))
    assert any('resume cursor' in e for e in errors_for(m))

def test_checkpoint_backward_cursor_jump_rejected():
    def m(root,plan,adoption,index):
        _install_checkpoint_chain(root,index,lambda a,b: b['coverage_cursor'].update(inspected_partition='architecture',inspected_paths=['src/arch.py']))
    assert any('resume cursor' in e for e in errors_for(m))

def test_checkpoint_non_contiguous_sequence_rejected():
    def m(root,plan,adoption,index):
        chk1, ref1, sha1 = build_valid_checkpoint(root,seq=1,turn_num=1)
        chk3, ref3, _ = build_valid_checkpoint(root,seq=3,turn_num=1)
        chk3['previous_checkpoint_sha256']=sha1
        chk3['coverage_cursor']['inspected_partition']=chk1['next_read_cursor']['target_next_partition']
        chk3['coverage_cursor']['inspected_paths']=list(chk1['next_read_cursor']['target_next_paths'])
        p3=root/ref3; write_json(p3,chk3); sha3=file_sha256(p3)
        index['post_enforcement_generations'][0]['checkpoints']=[{'checkpoint_sequence':1,'ref':ref1,'sha256':sha1},{'checkpoint_sequence':3,'ref':ref3,'sha256':sha3}]
    assert any('checkpoint sequence must be contiguous' in e for e in errors_for(m))

def test_checkpoint_missing_source_identity_rejected():
    def m(root,plan,adoption,index):
        chk,ref,_=build_valid_checkpoint(root); chk.pop('source_identity'); p=root/ref; write_json(p,chk); index['post_enforcement_generations'][0]['checkpoints']=[{'checkpoint_sequence':1,'ref':ref,'sha256':file_sha256(p)}]
    assert any('source_identity' in e for e in errors_for(m))

def test_checkpoint_stale_source_version_rejected():
    def m(root,plan,adoption,index):
        chk,ref,_=build_valid_checkpoint(root); chk['source_version']='stale-version'; p=root/ref; write_json(p,chk); index['post_enforcement_generations'][0]['checkpoints']=[{'checkpoint_sequence':1,'ref':ref,'sha256':file_sha256(p)}]
    assert any('source_version stale/mismatch' in e for e in errors_for(m))

def test_checkpoint_belongs_to_different_source_rejected():
    def m(root,plan,adoption,index):
        chk,ref,_=build_valid_checkpoint(root); chk['source_id']='different-source'; p=root/ref; write_json(p,chk); index['post_enforcement_generations'][0]['checkpoints']=[{'checkpoint_sequence':1,'ref':ref,'sha256':file_sha256(p)}]
    assert any('checkpoint source_id mismatch' in e for e in errors_for(m))

def test_checkpoint_mechanism_without_locator_rejected():
    def m(root,plan,adoption,index):
        chk,ref,_=build_valid_checkpoint(root); chk['mechanism_candidates'][0].pop('evidence_locator'); p=root/ref; write_json(p,chk); index['post_enforcement_generations'][0]['checkpoints']=[{'checkpoint_sequence':1,'ref':ref,'sha256':file_sha256(p)}]
    assert any('evidence_locator' in e for e in errors_for(m))

def test_incomplete_checkpoint_cannot_set_completion_flag():
    def m(root,plan,adoption,index):
        chk,ref,_=build_valid_checkpoint(root); chk['completion_flag']=True; p=root/ref; write_json(p,chk); index['post_enforcement_generations'][0]['checkpoints']=[{'checkpoint_sequence':1,'ref':ref,'sha256':file_sha256(p)}]
    assert any('completion_flag cannot be true' in e for e in errors_for(m))

def test_cleanup_attempt_to_delete_protected_authority_evidence_rejected():
    schema=json.loads((ROOT/'schemas'/'SOURCE_REVIEW_CLEANUP_SCHEMA.json').read_text(encoding='utf-8'))
    manifest={'schema':'flyby/source-review-cleanup/1','source_id':SOURCE_ID,'source_ref':SOURCE_REF,'adjudication_complete':True,'final_review_ref':'control/reviews/final.json','final_review_sha256':'1'*64,'temporary_source_payloads':[{'ref':'scratch/source-clone','kind':'SOURCE_CLONE'}],'retained_evidence':[{'ref':'control/reviews/final.json','artifact_class':'AUTHORITY_EVIDENCE','reason':'authoritative adjudicated review','protected':True}],'delete_candidates':['control/reviews/final.json']}
    errs=validate_cleanup_manifest(manifest,schema)
    assert any('protected authority evidence' in e for e in errs)

def test_cleanup_before_adjudication_rejected():
    schema=json.loads((ROOT/'schemas'/'SOURCE_REVIEW_CLEANUP_SCHEMA.json').read_text(encoding='utf-8'))
    manifest={'schema':'flyby/source-review-cleanup/1','source_id':SOURCE_ID,'source_ref':SOURCE_REF,'adjudication_complete':False,'final_review_ref':'control/reviews/final.json','final_review_sha256':'1'*64,'temporary_source_payloads':[{'ref':'scratch/source-clone','kind':'SOURCE_CLONE'}],'retained_evidence':[],'delete_candidates':['scratch/source-clone']}
    assert any('before adjudication' in e for e in validate_cleanup_manifest(manifest,schema))


def test_incomplete_review_marked_converged_rejected():
    def m(root,plan,adoption,index):
        chk,ref,_=build_valid_checkpoint(root)
        chk['convergence_status']='CONVERGENCE_PROPOSED'
        chk['completion_flag']=True
        p=root/ref; write_json(p,chk)
        index['post_enforcement_generations'][0]['checkpoints']=[{'checkpoint_sequence':1,'ref':ref,'sha256':file_sha256(p)}]
    assert any('remaining source partitions' in e for e in errors_for(m))

def test_cleanup_agent_authored_review_must_be_protected():
    schema=json.loads((ROOT/'schemas'/'SOURCE_REVIEW_CLEANUP_SCHEMA.json').read_text(encoding='utf-8'))
    manifest={'schema':'flyby/source-review-cleanup/1','source_id':SOURCE_ID,'source_ref':SOURCE_REF,'adjudication_complete':True,'final_review_ref':'reviews/final.md','final_review_sha256':'2'*64,'temporary_source_payloads':[{'ref':'scratch/source-download','kind':'SOURCE_DOWNLOAD'}],'retained_evidence':[{'ref':'reviews/final.md','artifact_class':'AGENT_AUTHORED_REVIEW','reason':'durable adjudicated reviewer report','protected':False}],'delete_candidates':[]}
    assert any('AGENT_AUTHORED_REVIEW must be protected' in e for e in validate_cleanup_manifest(manifest,schema))


def test_checkpoint_missing_source_version_rejected():
    def m(root,plan,adoption,index):
        chk,ref,_=build_valid_checkpoint(root); chk.pop('source_version'); p=root/ref; write_json(p,chk); index['post_enforcement_generations'][0]['checkpoints']=[{'checkpoint_sequence':1,'ref':ref,'sha256':file_sha256(p)}]
    assert any('source_version' in e for e in errors_for(m))

def test_checkpoint_cannot_skip_critical_partitions_to_complete():
    def m(root,plan,adoption,index):
        chk,ref,_=build_valid_checkpoint(root)
        chk['coverage_cursor']['remaining_partitions']=[]
        chk['convergence_status']='CONVERGENCE_PROPOSED'
        chk['completion_flag']=True
        p=root/ref; write_json(p,chk)
        index['post_enforcement_generations'][0]['checkpoints']=[{'checkpoint_sequence':1,'ref':ref,'sha256':file_sha256(p)}]
    assert any('critical partition accounting' in e for e in errors_for(m))

def test_cleanup_adjudicated_source_payloads_must_be_scheduled():
    schema=json.loads((ROOT/'schemas'/'SOURCE_REVIEW_CLEANUP_SCHEMA.json').read_text(encoding='utf-8'))
    manifest={'schema':'flyby/source-review-cleanup/1','source_id':SOURCE_ID,'source_ref':SOURCE_REF,'adjudication_complete':True,'final_review_ref':'reviews/final.md','final_review_sha256':'3'*64,'temporary_source_payloads':[{'ref':'scratch/source-clone','kind':'SOURCE_CLONE'}],'retained_evidence':[],'delete_candidates':[]}
    assert any('remain unscheduled after adjudication' in e for e in validate_cleanup_manifest(manifest,schema))


def test_turn_evidence_checkpoint_lineage_tamper_rejected_without_generation_index():
    def m(root,plan,adoption,index):
        chk1,ref1,sha1=build_valid_checkpoint(root,seq=1,turn_num=3)
        chk2,ref2,_=build_valid_checkpoint(root,seq=2,turn_num=3)
        chk2['previous_checkpoint_sha256']='0'*64
        chk2['coverage_cursor']['inspected_partition']=chk1['next_read_cursor']['target_next_partition']
        chk2['coverage_cursor']['inspected_paths']=list(chk1['next_read_cursor']['target_next_paths'])
        chk2['coverage_cursor']['completed_partitions']=['architecture','validation']
        chk2['coverage_cursor']['remaining_partitions']=['target-integration']
        p2=root/ref2; write_json(p2,chk2); sha2=file_sha256(p2)
        rewrite_turn(root,index,3,lambda e:e['evidence'].update({'checkpoints':[
            {'checkpoint_sequence':1,'checkpoint_ref':ref1,'checkpoint_sha256':sha1},
            {'checkpoint_sequence':2,'checkpoint_ref':ref2,'checkpoint_sha256':sha2}
        ]}))
    assert any('previous_checkpoint_sha256 does not match exact predecessor' in e for e in errors_for(m))

def test_turn_evidence_checkpoint_chain_cannot_start_at_sequence_two():
    def m(root,plan,adoption,index):
        chk,ref,_=build_valid_checkpoint(root,seq=2,turn_num=3)
        chk['previous_checkpoint_sha256']='1'*64
        p=root/ref; write_json(p,chk); sha=file_sha256(p)
        rewrite_turn(root,index,3,lambda e:e['evidence'].update({'checkpoints':[{'checkpoint_sequence':2,'checkpoint_ref':ref,'checkpoint_sha256':sha}]}))
    assert any('checkpoint chain must start at sequence 1' in e for e in errors_for(m))

def main():
    tests=[(n,o) for n,o in sorted(globals().items()) if n.startswith('test_') and callable(o)]
    for name,test in tests: test(); print(name+': PASS')
    print(f'{len(tests)} source review turn-chain tests passed')
    return 0
if __name__=='__main__': raise SystemExit(main())
