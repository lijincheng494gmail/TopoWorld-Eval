"""Frozen-reference R/A/B scoring; original replies are never modified.

PENDING is not an observed failure. Format failures retain all assigned query
opportunities. Worker subprocesses bound world compilation to 30 wall seconds.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import Counter,defaultdict
import argparse
import csv
import datetime
import hashlib
import io
import json
import math
import subprocess
import sys

sys.dont_write_bytecode=True
from trial_io import audit_thread

DEFAULT_ROOT=Path(__file__).resolve().parents[1]
EVALUATOR_ROOT=Path(__file__).resolve().parents[2]/'evaluator'
IOU_THRESHOLD=.25
TERMINAL_FAILURES={'FAILED_NO_RAW','TIMEOUT','DISPATCH_ERROR','FAILED','ABORTED','CANCELLED','ERROR'}


def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def strict(text):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise ValueError('Duplicate JSON key: '+str(key))
            out[key]=value
        return out
    def bad(value):raise ValueError('Nonfinite JSON constant: '+value)
    parsed=json.loads(text,object_pairs_hook=pairs,parse_constant=bad)
    def finite(value):
        if isinstance(value,float) and not math.isfinite(value):raise ValueError('Overflowed nonfinite JSON number')
        if isinstance(value,list):
            for x in value:finite(x)
        elif isinstance(value,dict):
            for x in value.values():finite(x)
    finite(parsed)
    return parsed


def read(path):return strict(Path(path).read_text(encoding='utf-8'))


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise FileExistsError('Immutable result already exists: '+str(path))
    path.write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def normalized(value):
    if value is True:return 'TRUE'
    if value is False:return 'FALSE'
    return value


def reference_known(query):return normalized(query.get('reference')) not in ('UNKNOWN','NOT_FOUND',None)


def equal(actual,reference,query):
    actual,reference=normalized(actual),normalized(reference)
    if isinstance(reference,(int,float)) and not isinstance(reference,bool):
        return isinstance(actual,(int,float)) and not isinstance(actual,bool) and math.isfinite(actual) and abs(actual-reference)<=query.get('numeric_tolerance',1e-6)
    return actual==reference


def bbox_valid(value):
    return (isinstance(value,list) and len(value)==4 and all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and 0<=x<=1 for x in value)
            and value[0]<value[2] and value[1]<value[3])


def iou(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union>0 else 0.


def grounding(world,case):
    observations=world.get('observations',[]);bindings=world.get('task_bindings',{})
    result=[]
    for target in case.get('grounding_reference',[]):
        role,source=target['role'],target['source_id'];eid=bindings.get(role,role)
        candidates=[o for o in observations if isinstance(o,dict) and o.get('source_id')==source and eid in o.get('entity_ids',[])]
        valid=[o for o in candidates if bbox_valid(o.get('bbox_xyxy'))]
        values=[(iou(o['bbox_xyxy'],target['bbox_xyxy']),o.get('id')) for o in valid]
        best=max(values,key=lambda x:x[0]) if values else (0.,None)
        result.append({'role':role,'source_id':source,'entity_id':eid,'reference_bbox':target['bbox_xyxy'],
                       'best_iou':best[0],'matched_observation_id':best[1],'passes_localization_gate':best[0]>=IOU_THRESHOLD,
                       'candidate_count':len(candidates),'valid_normalized_bbox_candidates':len(valid),
                       'scope':'Approximate 2D bounding-box localization, not segmentation or complete 3D grounding'})
    return result


def freeze_check(plan,evaluator_root,package_root=DEFAULT_ROOT):
    rows=[]
    def inspect(files,base,label):
        if not isinstance(files,dict):raise ValueError('Freeze file map missing: '+label)
        for name,expected in files.items():
            path=Path(name);path=path if path.is_absolute() else base/path
            actual=sha(path) if path.is_file() else None
            rows.append({'scope':label,'path':str(path),'expected_sha256':expected,'actual_sha256':actual,'pass':actual==expected})
    inspect(plan['files'],package_root,'scientific_protocol')
    frozen=read(evaluator_root/'CODE_FREEZE_BEFORE_EXPERIMENTS.json')
    inspect(frozen['files'],evaluator_root,'evaluator_2_2')
    return {'status':'PASS' if rows and all(r['pass'] for r in rows) else 'FAIL','checked':len(rows),'rows':rows,
            'evaluator_freeze_sha256':sha(evaluator_root/'CODE_FREEZE_BEFORE_EXPERIMENTS.json')}


def r_schema(parsed,case):
    from jsonschema import Draft202012Validator
    schema={'type':'object','required':['schema','case_id','answers'],'properties':{
        'schema':{'const':'topoworld_relation_answers_v1'},'case_id':{'const':case['case_id']},
        'answers':{'type':'array','items':{'type':'object','required':['query_id','value','evidence'],'properties':{
            'query_id':{'type':'string'},'value':{'anyOf':[{'type':'boolean'},{'type':'number'},{'enum':['TRUE','FALSE','UNKNOWN','NOT_FOUND']}]},
            'evidence':{'type':'array','items':{'type':'object'}}}}}}}
    errors=[{'path':list(e.path),'message':e.message} for e in Draft202012Validator(schema).iter_errors(parsed)]
    if not errors:
        ids=[a['query_id'] for a in parsed['answers']]
        if len(ids)!=len(set(ids)):errors.append({'path':['answers'],'message':'Repeated query_id'})
        unexpected=sorted(set(ids)-{q['id'] for q in case['queries']})
        if unexpected:errors.append({'path':['answers'],'message':'Unexpected query IDs: '+','.join(unexpected)})
    return {'status':'INVALID' if errors else 'VALID','errors':errors}


def world_schema(parsed,evaluator_root):
    from jsonschema import Draft202012Validator
    schema=read(evaluator_root/'schema/executable_world_schema_v1.json')
    errors=[{'path':list(e.path),'message':e.message} for e in Draft202012Validator(schema).iter_errors(parsed)]
    return {'status':'INVALID' if errors else 'VALID','errors':errors}


def provenance(world,case):
    allowed={v['view_id'] for v in case.get('views',[])}
    sources={s['id']:s['active'] for s in world.get('sources',[])}
    entity_ids={e['id'] for e in world.get('entities',[])}
    observations=world.get('observations',[])
    return {'allowed_source_ids':sorted(allowed),
            'unexpected_active_sources':[s for s,on in sources.items() if on is True and s not in allowed],
            'observations_with_unallowed_sources':[o['id'] for o in observations if o['source_id'] not in allowed],
            'observations_with_unresolved_entities':[o['id'] for o in observations if not o['entity_ids'] or any(e not in entity_ids for e in o['entity_ids'])],
            'scope':'Source inventory and declared bindings; not proof that evidence text accurately describes the image'}


def bounded_world(world,case,evaluator_root):
    packet={'world':world,'case':case,'evaluator':str(evaluator_root/'code/geometry_v4.py')}
    try:
        p=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('score_worker.py'))],
                         input=json.dumps(packet,ensure_ascii=False,allow_nan=False),capture_output=True,text=True,timeout=30)
    except subprocess.TimeoutExpired:
        return {'status':'WORLD_TIMEOUT','error':'30 second wall-time evaluation limit'}
    try:result=strict(p.stdout)
    except ValueError:
        return {'status':'WORKER_ERROR','returncode':p.returncode,'stderr':p.stderr[:8192],'stdout_prefix':p.stdout[:4096]}
    if p.returncode!=0 or result.get('ok') is not True:
        return {'status':'WORKER_ERROR','returncode':p.returncode,'error':result.get('error'),'stderr':p.stderr[:8192]}
    return {'status':'EVALUATED','assessment':result['assessment']}


def score_job(job,case,dispatch,package_root,evaluator_root,limits,fixture=False):
    row={k:job[k] for k in ['job_id','model_prefix','codex_model_id','case_id','arm']}
    folder=Path(job.get('folder',package_root/'jobs'/job['job_id']))
    raw=folder/'output/raw_response.txt';entry=dispatch.get(job['job_id'],{})
    row.update(raw_path=str(raw),dispatch_status=entry.get('status','NOT_DISPATCHED'),observed=False,status='PENDING',fixture=fixture)
    if entry.get('thread_id') and not fixture:
        row['thread_id']=entry['thread_id'];row['host_audit']=audit_thread(entry['thread_id'],job['codex_model_id'])
    else:row['host_audit']={'status':'FIXTURE_NOT_A_MODEL_RUN' if fixture else 'HOST_NOT_AVAILABLE'}
    row['condition_verified']=row['host_audit']['status']=='PASS'
    row['confirmed_model_mismatch']=row['host_audit']['status']=='MODEL_OR_EFFORT_MISMATCH'
    manifest=folder/'input/job_manifest.json'
    input_check=[]
    if manifest.is_file():
        for name,expected in read(manifest).get('input_files',{}).items():
            actual=sha(name) if Path(name).is_file() else None
            input_check.append({'path':name,'pass':actual==expected})
    row['input_integrity']={'status':'PASS' if input_check and all(x['pass'] for x in input_check) else 'NOT_VERIFIED' if not input_check else 'FAIL','files':input_check}
    if row['input_integrity']['status']=='FAIL':
        row.update(status='INPUT_INTEGRITY_FAILURE',observed=False);return row
    if not raw.is_file():
        terminal=entry.get('status') in TERMINAL_FAILURES or entry.get('status')=='COMPLETE'
        events=row['host_audit'].get('events',[])
        if events and events[-1]['event'] in ['task_complete','task_aborted']:terminal=True
        if terminal:row.update(status='MISSING_RAW_OUTPUT',observed=True)
        return finish_queries(row,case,{})
    row.update(observed=True,raw_sha256=sha(raw),raw_bytes=raw.stat().st_size)
    if raw.stat().st_size>limits['output_char_limit']*4:
        row.update(status='OUTPUT_LIMIT_FAILURE',parse_error='UTF-8 file exceeds bounded character-limit byte envelope');return finish_queries(row,case,{})
    try:
        text=raw.read_text(encoding='utf-8');row['raw_characters']=len(text)
        if len(text)>limits['output_char_limit']:raise ValueError('Output character limit exceeded')
        parsed=strict(text)
        if not isinstance(parsed,dict):raise ValueError('Expected one plain JSON object')
    except (ValueError,UnicodeError,RecursionError) as error:
        row.update(status='RAW_PARSE_FAILURE',parse_error=type(error).__name__+': '+str(error));return finish_queries(row,case,{})
    row['parse_status']='VALID_PLAIN_JSON'
    row['case_id_matches']=parsed.get('case_id')==case['case_id']
    if job['arm']=='R':
        schema=r_schema(parsed,case);row['schema_validation']=schema
        if schema['status']!='VALID':row['status']='SCHEMA_FAILURE';return finish_queries(row,case,{})
        answers={a['query_id']:{'value':a['value'],'status':'DIRECT_ANSWER','evidence':a['evidence']} for a in parsed['answers']}
        row['status']='SCORED';return finish_queries(row,case,answers)
    if not row['case_id_matches']:
        row.update(status='SCHEMA_FAILURE',schema_validation={'status':'INVALID','errors':[{'path':['case_id'],'message':'Assigned case_id mismatch'}]})
        return finish_queries(row,case,{})
    if not isinstance(parsed.get('entities'),list) or len(parsed['entities'])>limits['entity_limit']:
        row.update(status='OUTPUT_LIMIT_FAILURE',parse_error='Missing entity array or entity count exceeds limit');return finish_queries(row,case,{})
    schema=world_schema(parsed,evaluator_root);row['schema_validation']=schema
    if schema['status']!='VALID':row['status']='SCHEMA_FAILURE';return finish_queries(row,case,{})
    evaluated=bounded_world(parsed,case,evaluator_root)
    if evaluated['status']!='EVALUATED':
        row.update(status=evaluated['status'],evaluation_failure=evaluated);return finish_queries(row,case,{})
    assessment=evaluated['assessment'];row['schema_validation']=assessment['schema_validation']
    if assessment['schema_validation']['status']!='VALID':
        row['status']='SCHEMA_FAILURE';return finish_queries(row,case,{})
    row['status']='SCORED';row['assessment']=assessment
    row['provenance']=provenance(parsed,case)
    row['grounding']=grounding(parsed,case)
    return finish_queries(row,case,assessment['readouts'])


def finish_queries(row,case,answers):
    if not row['observed']:row['query_rows']=[];return row
    row['query_rows']=[]
    for q in case['queries']:
        result=answers.get(q['id'],{'value':None,'status':'MISSING_OR_INVALID_OUTPUT'})
        row['query_rows'].append({'query_id':q['id'],'predicate':q['predicate'],'evaluation_layer':q.get('evaluation_layer','GEOMETRIC'),
             'reference':q['reference'],'actual':result.get('value'),'readout_status':result.get('status'),
             'correct':equal(result.get('value'),q['reference'],q),'answered':q['id'] in answers,
             'reference_evaluable':reference_known(q),
             'reference_status':q.get('reference_status'),'proof':result.get('proof'),'evidence':result.get('evidence')})
    row['correct_query_count']=sum(q['correct'] for q in row['query_rows'] if q['reference_evaluable'])
    row['query_count']=sum(reference_known(q) for q in case['queries'])
    row['uncertainty_count']=sum(not q['reference_evaluable'] for q in row['query_rows'])
    row['uncertainty_correct_count']=sum(q['correct'] for q in row['query_rows'] if not q['reference_evaluable'])
    row['total_registered_queries']=len(case['queries'])
    row['all_known_queries_correct']=row['correct_query_count']==row['query_count']
    row['all_registered_answers_correct']=all(q['correct'] for q in row['query_rows'])
    role=row.get('assessment',{}).get('role_coverage',{})
    covered=role.get('present',-1)==role.get('denominator',-2) and role.get('geometry_covered',-1)==role.get('geometry_denominator',-2)
    row['all_target_relation_and_coverage_success']=row['arm']!='R' and row['all_known_queries_correct'] and covered and row.get('schema_validation',{}).get('status')=='VALID'
    if row['arm']!='R' and 'grounding' not in row:
        row['grounding']=[{'role':t['role'],'source_id':t['source_id'],'best_iou':0.,'passes_localization_gate':False,
                          'candidate_count':0,'missing_due_to_trial_failure':True} for t in case.get('grounding_reference',[])]
    return row


def aggregate(rows,cases):
    assigned=len(rows);observed=[r for r in rows if r['observed'] and not r.get('confirmed_model_mismatch')]
    mismatched=[r for r in rows if r.get('confirmed_model_mismatch')]
    opportunity=sum(sum(reference_known(q) for q in cases[r['case_id']]['queries']) for r in rows)
    observed_opportunity=sum(sum(reference_known(q) for q in cases[r['case_id']]['queries']) for r in observed)
    correct=sum(r.get('correct_query_count',0) for r in observed)
    pending_opportunity=opportunity-observed_opportunity
    ground=[g for r in observed for g in r.get('grounding',[])]
    geometry=[r['assessment'] for r in observed if r.get('assessment')]
    world_rows=[r for r in observed if r['arm']!='R']
    return {'allocated_trials':assigned,'observed_trials':len(observed),'pending_or_execution_unresolved_trials':assigned-len(observed),
            'confirmed_model_mismatch_quarantined':len(mismatched),'condition_verified_trials':sum(r.get('condition_verified',False) for r in observed),
            'condition_unverified_observed_trials':sum(not r.get('condition_verified',False) for r in observed),
            'status_counts':dict(Counter(r['status'] for r in rows)),
            'allocated_query_opportunities':opportunity,'observed_query_opportunities':observed_opportunity,'correct_queries':correct,
            'query_accuracy_observed':correct/observed_opportunity if observed_opportunity else None,
            'final_all_allocated_accuracy':correct/opportunity if opportunity and not pending_opportunity else None,
            'completion_bounds_not_pending_as_failures':{'lower':correct/opportunity if opportunity else None,
                'upper':(correct+pending_opportunity)/opportunity if opportunity else None},
            'schema_valid_trials':sum(r.get('schema_validation',{}).get('status')=='VALID' for r in observed),
            'all_known_queries_correct_trials':sum(r.get('all_known_queries_correct',False) for r in observed),
            'all_target_relation_and_coverage_success':sum(r.get('all_target_relation_and_coverage_success',False) for r in observed),
            'role_coverage_all_observed_worlds':{
                'required_role_opportunities':sum(len(cases[r['case_id']].get('required_roles',[])) for r in world_rows),
                'roles_present':sum(r.get('assessment',{}).get('role_coverage',{}).get('present',0) for r in world_rows),
                'required_geometry_opportunities':sum(len(cases[r['case_id']].get('geometric_required_roles',[])) for r in world_rows),
                'geometry_covered':sum(r.get('assessment',{}).get('role_coverage',{}).get('geometry_covered',0) for r in world_rows)},
            'uncertainty':{'allocated_opportunities':sum(sum(not reference_known(q) for q in cases[r['case_id']]['queries']) for r in rows),
                           'observed_opportunities':sum(r.get('uncertainty_count',0) for r in observed),
                           'correct':sum(r.get('uncertainty_correct_count',0) for r in observed)},
            'grounding':{'opportunities':len(ground),'mean_iou':sum(x['best_iou'] for x in ground)/len(ground) if ground else None,
                         'passes_iou_0_25':sum(x['passes_localization_gate'] for x in ground),
                         'scope':'Approximate bounding-box localization only; R is not assigned this output'},
            'secondary_world_status_counts':dict(Counter(r['verification']['status'] for r in geometry)),
            'secondary_registered_geometry_status_counts':dict(Counter(r.get('registered_geometry',{}).get('status','UNKNOWN') for r in geometry)),
            'worlds_with_definite_material_obstruction':sum(r['verification'].get('definite_material_obstruction_rows',0)>0 for r in geometry),
            'secondary_assessed_worlds':len(geometry)}


def paired_analysis(rows):
    lookup={(r['model_prefix'],r['case_id'],r['arm']):r for r in rows if r['observed'] and not r.get('confirmed_model_mismatch')}
    pairs=[]
    for model,case,arm in sorted(lookup):
        if arm!='A' or (model,case,'R') not in lookup or (model,case,'B') not in lookup:continue
        r,a,b=[lookup[(model,case,x)] for x in ['R','A','B']]
        rqs={q['query_id']:q for q in r['query_rows']};aqs={q['query_id']:q for q in a['query_rows']};bqs={q['query_id']:q for q in b['query_rows']}
        format_gain=a.get('schema_validation',{}).get('status')!='VALID' and b.get('schema_validation',{}).get('status')=='VALID'
        both_valid=all(x.get('schema_validation',{}).get('status')=='VALID' for x in [a,b])
        pairs.append({'model_prefix':model,'case_id':case,
            'R_correct_A_not_satisfied':sum(q['reference_evaluable'] and q['correct'] and not aqs[i]['correct'] for i,q in rqs.items()),
            'R_correct_A_wrong_both_valid':sum(q['reference_evaluable'] and q['correct'] and not aqs[i]['correct'] for i,q in rqs.items()) if a.get('schema_validation',{}).get('status')=='VALID' else None,
            'A_correct_queries':a['correct_query_count'],'B_correct_queries':b['correct_query_count'],
            'B_minus_A_correct_queries':b['correct_query_count']-a['correct_query_count'],
            'B_rescues':sum(aqs[i]['reference_evaluable'] and not aqs[i]['correct'] and bqs[i]['correct'] for i in aqs),
            'B_new_errors':sum(aqs[i]['reference_evaluable'] and aqs[i]['correct'] and not bqs[i]['correct'] for i in aqs),
            'A_format_status':a.get('schema_validation',{}).get('status',a['status']),
            'B_format_status':b.get('schema_validation',{}).get('status',b['status']),
            'both_worlds_schema_valid':both_valid,'B_format_recovery':format_gain,
            'both_valid_B_minus_A':b['correct_query_count']-a['correct_query_count'] if both_valid else None,
            'scope':'Independent R/A/B tasks paired by building and model; no hidden-state inference'})
    return pairs


def markdown(summary,by_model,by_predicate,pairs,fixture):
    lines=['# TopoWorld 固定任务评分报告','',('状态：管线合成验收；不是模型实验。' if fixture else '状态：原文评分快照；未完成的任务保留为PENDING。'),'',
           f"分配 {summary['allocated_trials']} 项；已观察 {summary['observed_trials']} 项；待完成或执行条件未解决 {summary['pending_or_execution_unresolved_trials']} 项。",
           f"已观察的可判关系查询 {summary['observed_query_opportunities']} 条，正确 {summary['correct_queries']} 条。",
           f"参考本身不确定的查询另计：正确 {summary['uncertainty']['correct']}/{summary['uncertainty']['observed_opportunities']}；不混入可判关系分母。",
           '未完成任务不算已观察失败；格式失败和确已终止但没有输出的任务保留全部题目分母。型号不符的输出隔离，不能算指定型号的成绩。','',
           '| 模型 | 条件 | 已观察/分配 | 查询正确/已观察 | Schema有效 | 已知材料受阻世界/已评价 |',
           '|---|---|---:|---:|---:|---:|']
    for row in by_model:
        s=row['metrics'];lines.append(f"| {row['model_prefix']} | {row['arm']} | {s['observed_trials']}/{s['allocated_trials']} | {s['correct_queries']}/{s['observed_query_opportunities']} | {s['schema_valid_trials']} | {s['worlds_with_definite_material_obstruction']}/{s['secondary_assessed_worlds']} |")
    lines+=['','R正确而A未实现、B相对A的修复与新增错误见PAIRED_ANALYSIS.json。格式恢复与双方Schema均有效时的关系差异分别列出，不能把格式修好全称为几何能力进步。',
            '','| 关系类别 | 正确/已观察 |','|---|---:|']
    for row in by_predicate:lines.append(f"| {row['predicate']} | {row['correct']}/{row['opportunities']} |")
    lines+=['','接地同时保留连续IoU和事先固定的0.25定位门槛；参考为近似框，不称为分割精度。',
            '全世界状态、注册目标几何状态、材料侵入、接口失败与未知分别保存。关系正确数不等于全世界物理正确。',
            '跨模型结果限于本批实际运行的型号/接口；建筑为配对分析单位，同栋内问题不当作独立建筑。',
            '底层权重修订号不可见；host audit保存实际可核对的模型别名与xhigh。',
            '','没有调用模型，没有改写任何原始回复，没有从模型答案生成参考。','']
    return '\n'.join(lines)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--package-root',type=Path,default=DEFAULT_ROOT)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--workers',type=int,default=2)
    ap.add_argument('--fixture',action='store_true');args=ap.parse_args()
    root=args.package_root.resolve();output=args.output.resolve()
    if output.exists():raise FileExistsError('Choose a fresh results directory')
    if not output.is_relative_to(root):raise ValueError('Results must stay under the selected package root')
    plan=read(root/'FROZEN_PROTOCOL.json');cases_data=read(root/'organizer_reference/qualified_cases.json')
    cases={c['case_id']:c for c in (cases_data['cases'] if isinstance(cases_data,dict) else cases_data)}
    for c in cases.values():
        if len({q['id'] for q in c['queries']})!=len(c['queries']):raise ValueError('Duplicate reference query IDs')
        if any(not bbox_valid(g['bbox_xyxy']) for g in c.get('grounding_reference',[])):raise ValueError('Invalid reference localization bbox')
    integrity=freeze_check(plan,EVALUATOR_ROOT,root)
    output.mkdir(parents=True,exist_ok=False);write(output/'FROZEN_INPUT_CHECK.json',integrity)
    if integrity['status']!='PASS':
        write(output/'STATUS.json',{'status':'BLOCKED_FROZEN_INPUT_MISMATCH','created_utc':now(),'actual_model_calls':0})
        print(json.dumps({'status':'BLOCKED_FROZEN_INPUT_MISMATCH','output':str(output)}));return 2
    dispatch_file=root/'DISPATCH_LEDGER.json';dispatch_data=read(dispatch_file) if dispatch_file.exists() else {'rows':[]}
    dispatch={r['job_id']:r for r in dispatch_data['rows']}
    limits={'output_char_limit':plan.get('output_char_limit',42000),'entity_limit':plan.get('entity_limit',plan.get('max_entities',60))}
    with ThreadPoolExecutor(max_workers=max(1,min(args.workers,4))) as pool:
        futures=[pool.submit(score_job,j,cases[j['case_id']],dispatch,root,EVALUATOR_ROOT,limits,args.fixture) for j in plan['jobs']]
        rows=[f.result() for f in futures]
    raw_check=[]
    for row in rows:
        if row.get('raw_sha256'):
            after=sha(row['raw_path']) if Path(row['raw_path']).is_file() else None
            raw_check.append({'job_id':row['job_id'],'sha256_before':row['raw_sha256'],'sha256_after':after,'pass':after==row['raw_sha256']})
    write(output/'RAW_IMMUTABILITY_CHECK.json',{'status':'PASS' if all(r['pass'] for r in raw_check) else 'FAIL','rows':raw_check})
    if any(not r['pass'] for r in raw_check):
        write(output/'STATUS.json',{'status':'BLOCKED_RAW_CHANGED_DURING_SCORING','created_utc':now()})
        print(json.dumps({'status':'BLOCKED_RAW_CHANGED_DURING_SCORING','output':str(output)}));return 2
    summary=aggregate(rows,cases)
    by_model=[]
    for model,arm in sorted({(r['model_prefix'],r['arm']) for r in rows}):
        by_model.append({'model_prefix':model,'arm':arm,'metrics':aggregate([r for r in rows if r['model_prefix']==model and r['arm']==arm],cases)})
    by_building=[{'case_id':cid,'metrics':aggregate([r for r in rows if r['case_id']==cid],cases)} for cid in sorted(cases)]
    predicate=defaultdict(lambda:{'correct':0,'opportunities':0,'uncertainty_correct':0,'uncertainty_opportunities':0})
    for row in rows:
        if row.get('confirmed_model_mismatch'):continue
        for q in row.get('query_rows',[]):
            if q['reference_evaluable']:
                predicate[q['predicate']]['correct']+=q['correct'];predicate[q['predicate']]['opportunities']+=1
            else:
                predicate[q['predicate']]['uncertainty_correct']+=q['correct'];predicate[q['predicate']]['uncertainty_opportunities']+=1
    by_predicate=[{'predicate':k,**v} for k,v in sorted(predicate.items())]
    pairs=paired_analysis(rows)
    model_predicate=defaultdict(lambda:{'correct':0,'opportunities':0,'uncertainty_correct':0,'uncertainty_opportunities':0})
    for row in rows:
        if row.get('confirmed_model_mismatch'):continue
        for q in row.get('query_rows',[]):
            bucket=model_predicate[(row['model_prefix'],row['arm'],q['predicate'])]
            if q['reference_evaluable']:bucket['correct']+=q['correct'];bucket['opportunities']+=1
            else:bucket['uncertainty_correct']+=q['correct'];bucket['uncertainty_opportunities']+=1
    final_status=('PARTIAL_SNAPSHOT' if summary['pending_or_execution_unresolved_trials'] else
                  'FINAL_WITH_UNVERIFIED_CONDITIONS' if summary['condition_unverified_observed_trials'] else 'FINAL')
    result={'created_utc':now(),'status':'FIXTURE_PIPELINE_QUALIFICATION' if args.fixture else final_status,
            'evaluator_version':'2.2.0','raw_outputs_modified':False,'actual_model_calls_by_scorer':0,
            'grounding_iou_threshold':IOU_THRESHOLD,'summary':summary,'by_model_arm':by_model,'by_building':by_building,
            'by_relation_category':by_predicate,'results':rows,
            'by_model_arm_relation':[{'model_prefix':m,'arm':a,'predicate':p,**v} for (m,a,p),v in sorted(model_predicate.items())],
            'scoring_code_sha256':sha(__file__),'worker_code_sha256':sha(Path(__file__).with_name('score_worker.py'))}
    write(output/'RESULTS.json',result);write(output/'PAIRED_ANALYSIS.json',{'pairs':pairs})
    write(output/'HUMAN_READABLE_REPORT_ZH.md',markdown(summary,by_model,by_predicate,pairs,args.fixture))
    table=io.StringIO();writer=csv.DictWriter(table,fieldnames=['job_id','model_prefix','case_id','arm','query_id','predicate','reference','actual','correct','readout_status']);writer.writeheader()
    for row in rows:
        for q in row.get('query_rows',[]):writer.writerow({**{k:row[k] for k in ['job_id','model_prefix','case_id','arm']},**{k:q[k] for k in ['query_id','predicate','reference','actual','correct','readout_status']}})
    write(output/'QUERY_ROWS.csv',table.getvalue())
    write(output/'STATUS.json',{'status':result['status'],'created_utc':now(),'allocated':len(rows),'observed':summary['observed_trials'],
          'pending_or_execution_unresolved':summary['pending_or_execution_unresolved_trials'],'output_bytes':sum(p.stat().st_size for p in output.rglob('*') if p.is_file())})
    print(json.dumps({'status':result['status'],'allocated':len(rows),'observed':summary['observed_trials'],'correct':summary['correct_queries'],
                     'observed_queries':summary['observed_query_opportunities'],'output':str(output)},ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
