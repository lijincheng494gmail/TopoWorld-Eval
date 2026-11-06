"""Source-addition/withdrawal scoring. Original model outputs are never repaired.

Coordinates retained as hypothetical completions are not retained measured
knowledge. Missing knowledge reports remain NOT_REPORTED. The intervention
changes admissible evidence, not the real building or the truth of LOC.
"""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,copy,csv,hashlib,importlib.util,io,json,math,subprocess,sys
sys.dont_write_bytecode=True
from score_trials import read,write,strict,sha,now,normalized,equal,world_schema,bounded_world,freeze_check,TERMINAL_FAILURES,EVALUATOR_ROOT
from trial_io import audit_thread
DEFAULT_ROOT=Path(__file__).resolve().parents[1]
HEIGHT_TOLERANCE_FT=1e-4


def finite(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def ids(value):return [x for x in value if isinstance(x,str)] if isinstance(value,list) else []
def load_geometry(path):
 spec=importlib.util.spec_from_file_location('revision_geometry',path);g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g);return g


def knowledge(world,reference,geometry):
 rows=world.get('query_knowledge')
 if not isinstance(rows,list):return {'report_status':'NOT_REPORTED','expected_status':reference['height_knowledge'],'knowledge_success':False,'scope':'Missing reporting is not evidence of correctly retained uncertainty'}
 selected=[r for r in rows if isinstance(r,dict) and r.get('query_id')=='HEIGHT_DELTA']
 if not selected:return {'report_status':'NOT_REPORTED','expected_status':reference['height_knowledge'],'knowledge_success':False}
 if len(selected)!=1:return {'report_status':'DUPLICATE_HEIGHT_ENTRY','expected_status':reference['height_knowledge'],'knowledge_success':False,'entries':selected}
 r=selected[0];status=r.get('status','NOT_REPORTED');expected=reference['height_knowledge'];allowed=set(reference['active_views']);source_ids=ids(r.get('source_ids'))
 status_valid=status in ['UNKNOWN','EVIDENCE_SUPPORTED'];state_match=status_valid and status==expected
 value=r.get('value_ft');known=expected=='EVIDENCE_SUPPORTED'
 value_match=finite(value) and abs(value-reference['height_value_ft'])<=HEIGHT_TOLERANCE_FT if known else None
 source_inventory={s['id']:s.get('active') for s in world.get('sources',[]) if isinstance(s,dict) and isinstance(s.get('id'),str)}
 trace_valid=('V3' in source_ids and all(i in allowed and source_inventory.get(i) is True for i in source_ids)) if known else None
 geometry_value=geometry.get('value');geometry_match=finite(geometry_value) and abs(geometry_value-reference['height_value_ft'])<=HEIGHT_TOLERANCE_FT if known else None
 return {'report_status':'REPORTED' if status_valid else 'INVALID_KNOWLEDGE_STATUS','reported_status':status,'expected_status':expected,'reported_value_ft':value,'reference_value_ft':reference['height_value_ft'],
         'status_correct':state_match,'evidence_value_correct':value_match,'geometry_value_ft':geometry_value,'geometry_height_correct':geometry_match,
         'knowledge_geometry_match':abs(value-geometry_value)<=HEIGHT_TOLERANCE_FT if status=='EVIDENCE_SUPPORTED' and finite(value) and finite(geometry_value) else None,
         'source_ids':source_ids,'source_ids_reported':isinstance(r.get('source_ids'),list),'out_of_scope_knowledge_source_ids':sorted(set(source_ids)-allowed),
         'section_cited_for_measured_height':('V3' in source_ids) if known else None,'measured_height_source_trace_valid':trace_valid,
         'unknown_with_nonnull_value':status=='UNKNOWN' and value is not None,
         'knowledge_success':state_match and (bool(value_match) and bool(trace_valid) if known else True),
         'supported_height_realization_success':state_match and bool(value_match) and bool(geometry_match) and bool(trace_valid) if known else None,
         'scope':'Knowledge-state correctness, geometry realization and citation validity are separate; a hypothetical coordinate is not measured knowledge.'}


def source_audit(world,reference,stage):
 allowed=set(reference['active_views']);sources={s['id']:s.get('active') for s in world.get('sources',[]) if isinstance(s,dict) and isinstance(s.get('id'),str)}
 evidence={e['id']:e for e in world.get('evidence',[]) if isinstance(e,dict) and isinstance(e.get('id'),str)}
 def trace(eid,seen=None):
  seen=set() if seen is None else set(seen)
  if eid in seen:return set(),{eid},True
  seen.add(eid)
  if eid in sources:return {eid},set(),False
  e=evidence.get(eid)
  if e is None:return set(),{eid},False
  found={e['source_id']} if isinstance(e.get('source_id'),str) else set();unresolved=set();cycle=False
  for child in ids(e.get('evidence_ids')):
   a,b,c=trace(child,seen);found|=a;unresolved|=b;cycle|=c
  return found,unresolved,cycle
 def classify(owner,entries):
  found=set();unresolved=set();cycle=False
  for eid in ids(entries):
   a,b,c=trace(eid);found|=a;unresolved|=b;cycle|=c
  current={s for s in found if s in allowed and sources.get(s) is True}
  invalid=found-current
  return {'owner':owner,'evidence_ids':ids(entries),'source_ids':sorted(found),'active_admitted_source_ids':sorted(current),'inactive_or_unadmitted_source_ids':sorted(invalid),
          'unresolved_evidence_ids':sorted(unresolved),'cycle':cycle,'support_state':'NO_EXPLICIT_SUPPORT' if not found and not unresolved else 'UNRESOLVED' if unresolved or cycle else 'CURRENT_ONLY' if not invalid else 'MIXED_CURRENT_AND_ARCHIVAL' if current else 'ARCHIVAL_ONLY'}
 active=[];archived=[]
 for r in world.get('relations',[]):
  if not isinstance(r,dict):continue
  row=classify('relation:'+str(r.get('id')),r.get('evidence_ids'));row['predicate']=r.get('predicate');row['args']=r.get('args',[])
  (active if r.get('status')=='ACTIVE' else archived).append(row)
 geometry=[];hypothetical=[]
 for e in world.get('entities',[]):
  if not isinstance(e,dict) or not isinstance(e.get('geometry'),dict):continue
  ge=e['geometry'];row=classify('geometry:'+str(e.get('id')),ge.get('parameter_evidence_ids'));row['parameter_status']=ge.get('parameter_status','UNSPECIFIED')
  (geometry if row['parameter_status'] in ['EVIDENCE_SUPPORTED','MIXED'] else hypothetical).append(row)
 active_stale=[r for r in active+geometry if r['inactive_or_unadmitted_source_ids']]
 return {'expected_active_source_ids':sorted(allowed),'declared_source_activity':sources,
         'unexpected_active_sources':sorted(s for s,on in sources.items() if on is True and s not in allowed),
         'missing_or_inactive_admitted_sources':sorted(s for s in allowed if sources.get(s) is not True),
         'withdrawn_V3_state':'ACTIVE_INVALID' if sources.get('V3') is True and 'V3' not in allowed else 'ARCHIVED_INACTIVE' if sources.get('V3') is False else 'ACTIVE_ADMITTED' if sources.get('V3') is True else 'ABSENT',
         'active_relations':active,'archived_relations':archived,'supported_geometry_parameters':geometry,'hypothetical_or_unknown_geometry_parameters':hypothetical,
         'active_stale_dependency_rows':active_stale,'solely_archival_active_support_rows':[r for r in active_stale if r['support_state']=='ARCHIVAL_ONLY'],
         'mixed_current_archival_active_support_rows':[r for r in active_stale if r['support_state']=='MIXED_CURRENT_AND_ARCHIVAL'],
         'unresolved_active_dependency_rows':[r for r in active+geometry if r['unresolved_evidence_ids'] or r['cycle']],
         'source_activity_clean':not any(on is True and s not in allowed for s,on in sources.items()),
         'active_dependency_edges_clean':not active_stale and not any(r['unresolved_evidence_ids'] or r['cycle'] for r in active+geometry),
         'scope':'Explicit source inventory and support edges only. Archived evidence and hypothetical retained coordinates are permitted. This does not prove erasure of hidden knowledge or caches.'}


def score_job(job,case,reference,dispatch,root,evaluator,fixture=False):
 stage=job.get('arm',job.get('stage'));jid=job['job_id'];folder=Path(job.get('folder',root/'revision_jobs'/jid));raw=folder/'output/raw_response.txt';entry=dispatch.get(jid,{})
 row={k:job.get(k) for k in ['job_id','model_prefix','codex_model_id','case_id']};row.update(stage=stage,status='PENDING',observed=False,raw_path=str(raw),fixture=fixture)
 if entry.get('thread_id') and not fixture:row['host_audit']=audit_thread(entry['thread_id'],job['codex_model_id'])
 else:row['host_audit']={'status':'FIXTURE_NOT_A_MODEL_RUN' if fixture else 'HOST_NOT_AVAILABLE'}
 row['condition_verified']=row['host_audit']['status']=='PASS'
 row['confirmed_model_mismatch']=row['host_audit']['status']=='MODEL_OR_EFFORT_MISMATCH'
 manifest=folder/'input/job_manifest.json';checks=[]
 if manifest.exists():
  for path,expected in read(manifest).get('input_files',{}).items():
   p=Path(path);actual=sha(p) if p.is_file() else None;checks.append({'path':str(p),'pass':actual==expected})
 row['input_integrity']={'status':'PASS' if checks and all(x['pass'] for x in checks) else 'FAIL' if checks else 'NOT_VERIFIED','files':checks}
 if row['input_integrity']['status']=='FAIL':row['status']='INPUT_INTEGRITY_FAILURE';return row,None
 if not raw.exists():
  events=row['host_audit'].get('events',[])
  terminal=entry.get('status') in TERMINAL_FAILURES|{'COMPLETE'} or bool(events and events[-1]['event'] in ['task_complete','task_aborted'])
  if terminal:row.update(status='MISSING_RAW_OUTPUT',observed=True)
  return row,None
 row.update(observed=True,raw_sha256=sha(raw),raw_bytes=raw.stat().st_size)
 try:
  if raw.stat().st_size>168000:raise ValueError('Output exceeds bounded byte envelope')
  text=raw.read_text(encoding='utf-8');row['raw_characters']=len(text)
  if len(text)>42000:raise ValueError('42000 character limit exceeded')
  world=strict(text)
  if not isinstance(world,dict):raise ValueError('Expected one plain JSON object')
 except (ValueError,UnicodeError,RecursionError) as ex:row.update(status='RAW_PARSE_FAILURE',error=str(ex));return row,None
 if world.get('case_id')!=case['case_id'] or not isinstance(world.get('entities'),list) or len(world['entities'])>60:
  row.update(status='WORLD_CONTRACT_FAILURE',error='Wrong case_id or entity budget');return row,None
 row['schema_validation']=world_schema(world,evaluator)
 if row['schema_validation']['status']!='VALID':row['status']='SCHEMA_FAILURE';return row,None
 kept={x['query_id']:x['value'] for x in reference['retained_relations']};queries=[q for q in case['queries'] if q.get('evaluation_layer')=='GEOMETRIC' and q['id'] in kept]
 height={'id':'HEIGHT_DELTA','predicate':'floor_delta','args':case['revision_diagnostic']['args'],'unit':'ft'}
 packet=dict(case,queries=queries+[height]);evaluated=bounded_world(world,packet,evaluator)
 if evaluated['status']!='EVALUATED':row.update(status=evaluated['status'],evaluation_failure=evaluated);return row,None
 a=evaluated['assessment'];row.update(status='SCORED',assessment=a)
 result=a['readouts'].get('HEIGHT_DELTA',{});row['height_knowledge']=knowledge(world,reference,result);row['source_audit']=source_audit(world,reference,stage)
 row['retained_relation_rows']=[{'query_id':q['id'],'predicate':q['predicate'],'reference':kept[q['id']],'actual':a['readouts'].get(q['id'],{}).get('value'),'correct':equal(a['readouts'].get(q['id'],{}).get('value'),kept[q['id']],q),'readout':a['readouts'].get(q['id'],{})} for q in queries]
 row['retained_relation_correct']=sum(r['correct'] for r in row['retained_relation_rows']);row['retained_relation_denominator']=len(queries)
 row['actual_height_geometry']=result;return row,world


def compare_geometry_worker(packet):
 g=load_geometry(packet['evaluator']);before,after=packet['world_before'],packet['world_after']
 def unit(w):return w.get('units',{}).get('length') if isinstance(w.get('units'),dict) else w.get('units')
 def frame(w):return {x['id']:x['matrix_to_world'] for x in w.get('frames',[])}
 def coord(w):return {k:v for k,v in w.get('coordinate_system',{}).items() if k not in ['note','description','comment']}
 if unit(before)!='ft' or unit(after)!='ft' or frame(before)!=frame(after) or coord(before)!=coord(after):
  return {'status':'NOT_COMPARABLE_FIXED_FT_FRAME','scope':'No arbitrary alignment or rescaling performed'}
 cb,ca=g.compile_world(before),g.compile_world(after);rows=[]
 for role in packet['roles']:
  old_id=g.resolve(before,role);new_id=g.resolve(after,role);old=cb['entities'].get(old_id);new=ca['entities'].get(new_id)
  row={'role':role,'before_entity_id':old_id,'after_entity_id':new_id,'binding_id_changed':old_id!=new_id}
  if not old or not new:row['status']='MISSING_ROLE'
  elif old['kind']=='staircase' or new['kind']=='staircase':row['status']='EXCLUDED_STAIR_ROLE'
  elif old['geometry_status']!='EXECUTABLE' or new['geometry_status']!='EXECUTABLE':row['status']='GEOMETRY_NOT_EVALUABLE'
  else:
   tol=max(cb['tolerance'],ca['tolerance']);removed=g.subtract_union(old['boxes'],new['boxes'],tol);added=g.subtract_union(new['boxes'],old['boxes'],tol)
   row.update(status='COMPARED',before_volume_ft3=g.union_volume(old['boxes'],tol),after_volume_ft3=g.union_volume(new['boxes'],tol),removed_volume_ft3=g.union_volume(removed,tol),added_volume_ft3=g.union_volume(added,tol),same_geometric_union=not removed and not added)
  rows.append(row)
 return {'status':'COMPARED','rows':rows,'scope':'Diagnostic only: volume changes may revise hypothetical dimensions. Binding renaming alone is not physical error.'}


def geometry_diff(before,after,roles,evaluator):
 packet={'evaluator':str(evaluator/'code/geometry_v4.py'),'world_before':before,'world_after':after,'roles':roles}
 try:
  p=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--geometry-diff-worker'],input=json.dumps(packet),capture_output=True,text=True,timeout=30)
  d=strict(p.stdout)
  if p.returncode!=0:return {'status':'DIAGNOSTIC_WORKER_ERROR','error':d}
  return d
 except subprocess.TimeoutExpired:return {'status':'DIAGNOSTIC_TIMEOUT','limit_seconds':30}
 except (ValueError,UnicodeError):return {'status':'DIAGNOSTIC_WORKER_ERROR','stdout':p.stdout[:1024],'stderr':p.stderr[:1024]}


def compare_pairs(rows,worlds,cases,evaluator):
 index={(r['model_prefix'],r['case_id'],r['stage']):r for r in rows};groups=sorted({(r['model_prefix'],r['case_id']) for r in rows});results=[]
 for model,cid in groups:
  case=cases[cid];lower_roles=sorted({x['role'] for x in case.get('grounding_reference',[]) if x.get('source_id')=='V1'})
  pair={'model_prefix':model,'case_id':cid,'geometry_changes':[],'comparison_scope':'Effective conclusions and uncertainty, not equality of arbitrary coordinates'}
  for a,b in [('E0','E1'),('E1','E2')]:
   ra,rb=index.get((model,cid,a)),index.get((model,cid,b));wa=worlds.get(ra['job_id']) if ra else None;wb=worlds.get(rb['job_id']) if rb else None
   pair['geometry_changes'].append({'stages':[a,b],'result':geometry_diff(wa,wb,lower_roles,evaluator) if wa and wb else {'status':'NOT_COMPARABLE_MISSING_OR_INVALID_WORLD'}})
  incremental,fresh=index.get((model,cid,'E2')),index.get((model,cid,'F2'))
  if incremental and fresh and incremental['status']==fresh['status']=='SCORED':
   ik,fk=incremental['height_knowledge'],fresh['height_knowledge'];ir={r['query_id']:r for r in incremental['retained_relation_rows']};fr={r['query_id']:r for r in fresh['retained_relation_rows']}
   common=sorted(set(ir)&set(fr));valid=lambda k:k.get('report_status')=='REPORTED'
   pair['E2_vs_F2']={'status':'COMPARED','knowledge_state_agreement':ik.get('reported_status')==fk.get('reported_status') if valid(ik) and valid(fk) else None,
     'incremental_knowledge_success':ik['knowledge_success'],'fresh_knowledge_success':fk['knowledge_success'],
     'relations':[{'query_id':q,'incremental_actual':ir[q]['actual'],'fresh_actual':fr[q]['actual'],'same_conclusion':normalized(ir[q]['actual'])==normalized(fr[q]['actual']),'incremental_correct':ir[q]['correct'],'fresh_correct':fr[q]['correct']} for q in common],
     'both_correct_relations':sum(ir[q]['correct'] and fr[q]['correct'] for q in common),'incremental_only_wrong_relations':[q for q in common if not ir[q]['correct'] and fr[q]['correct']],
     'fresh_only_wrong_relations':[q for q in common if ir[q]['correct'] and not fr[q]['correct']]}
  else:pair['E2_vs_F2']={'status':'NOT_COMPARABLE_MISSING_OR_INVALID_OUTPUT'}
  results.append(pair)
 return results


def run(root,output,evaluator,protocol_path=None,fixture=False):
 root=Path(root);output=Path(output);evaluator=Path(evaluator)
 if output.exists():raise FileExistsError('New immutable --output directory required: '+str(output))
 protocol_path=Path(protocol_path) if protocol_path else root/'REVISION_PROTOCOL.json';protocol=read(protocol_path);jobs=protocol['jobs']
 cases={c['case_id']:c for c in read(root/'organizer_reference/qualified_cases.json')['cases']};refs=read(root/'organizer_reference/revision_answers.json')
 dispatch_file=root/'REVISION_DISPATCH_LEDGER.json';dispatch={r['job_id']:r for r in read(dispatch_file).get('rows',[])} if dispatch_file.exists() else {}
 frozen=None
 if not fixture and 'files' in protocol:
  frozen=freeze_check(protocol,evaluator,root)
  if frozen['status']!='PASS':raise ValueError('Frozen scientific inputs or evaluator changed; new scoring result not allowed')
 output.mkdir(parents=True);rows=[];worlds={}
 for job in jobs:
  cid=job['case_id'];stage=job.get('arm',job.get('stage'));row,w=score_job(job,cases[cid],refs[cid][stage],dispatch,root,evaluator,fixture)
  rows.append(row)
  if w is not None:worlds[job['job_id']]=w
 pairs=compare_pairs(rows,worlds,cases,evaluator)
 summaries={}
 for stage in ['E0','E1','E2','F2']:
  selected=[r for r in rows if r['stage']==stage];scored=[r for r in selected if r['status']=='SCORED'];observed=[r for r in selected if r['observed']]
  summaries[stage]={'allocated':len(selected),'observed':len(observed),'pending':sum(r['status']=='PENDING' for r in selected),'scored':len(scored),'status_counts':dict(Counter(r['status'] for r in selected)),
     'knowledge_correct_over_observed':sum(r['height_knowledge']['knowledge_success'] for r in scored),'knowledge_denominator_observed':len(observed),
     'knowledge_not_reported':sum(r['height_knowledge']['report_status']=='NOT_REPORTED' for r in scored),
     'known_height_geometry_correct':sum(r['height_knowledge'].get('geometry_height_correct') is True for r in scored) if stage=='E1' else None,
     'retained_relation_correct':sum(r.get('retained_relation_correct',0) for r in scored),'retained_relation_denominator_scored':sum(r.get('retained_relation_denominator',0) for r in scored),
     'retained_relation_denominator_observed':sum(len(refs[r['case_id']][stage]['retained_relations']) for r in observed),
     'verified_scored':sum(r['condition_verified'] for r in scored),'verified_knowledge_correct':sum(r['condition_verified'] and r['height_knowledge']['knowledge_success'] for r in scored),
     'source_activity_clean':sum(r['source_audit']['source_activity_clean'] for r in scored),'active_dependency_edges_clean':sum(r['source_audit']['active_dependency_edges_clean'] for r in scored),
     'actual_condition_verified':sum(r['condition_verified'] for r in selected),'confirmed_model_mismatch':sum(r['confirmed_model_mismatch'] for r in selected)}
 result={'schema':'topoworld_revision_results_v1','created_utc':now(),'fixture_only':fixture,'protocol_path':str(protocol_path),'protocol_sha256':sha(protocol_path),'evaluator_version':'2.2.0','height_tolerance_ft':HEIGHT_TOLERANCE_FT,'freeze_check':frozen,'allocated_outputs':len(jobs),'stage_summaries':summaries,'rows':rows,'paired_diagnostics':pairs,
         'scope':'Real source addition and controlled source withdrawal. Explicit knowledge, geometry and provenance are measured separately. No proof of hidden-memory erasure or full-building validity.'}
 write(output/'REVISION_RESULTS.json',result)
 table=io.StringIO();writer=csv.DictWriter(table,fieldnames=['job_id','model_prefix','case_id','stage','status','observed','knowledge_status','knowledge_success','height_geometry_ft','retained_correct','retained_denominator','source_activity_clean','active_dependency_edges_clean']);writer.writeheader()
 for r in rows:
  k=r.get('height_knowledge',{});s=r.get('source_audit',{});writer.writerow({**{key:r.get(key) for key in ['job_id','model_prefix','case_id','stage','status','observed']},'knowledge_status':k.get('reported_status',k.get('report_status')),'knowledge_success':k.get('knowledge_success'),'height_geometry_ft':r.get('actual_height_geometry',{}).get('value'),'retained_correct':r.get('retained_relation_correct'),'retained_denominator':r.get('retained_relation_denominator'),'source_activity_clean':s.get('source_activity_clean'),'active_dependency_edges_clean':s.get('active_dependency_edges_clean')})
 write(output/'REVISION_SUMMARY.csv',table.getvalue())
 lines=['# 来源增加与撤回：评分结果','', '这是受控改变观察可用性的实验，不表示LOC原图为假或真实建筑发生变化。保留旧坐标作为明确假设不等于保留测量知识；缺失query_knowledge按NOT_REPORTED记录。','', '|阶段|分配|已观察|已评分|知识状态正确/已观察|待完成|','|---|---:|---:|---:|---:|---:|']
 for s in ['E0','E1','E2','F2']:
  a=summaries[s];lines.append(f"|{s}|{a['allocated']}|{a['observed']}|{a['scored']}|{a['knowledge_correct_over_observed']}/{a['knowledge_denominator_observed']}|{a['pending']}|")
 lines +=['','E1分别核对报告的已支持层高与实际floor_delta几何。E0/E2/F2不要求删除任意假设坐标。来源活动状态、ACTIVE关系支持边、已支持几何参数边和历史归档分开报告；仍受plan支持的关系可以继续成立。','', 'E2与F2比较有效结论和不确定性，不比较随机坐标相同。固定英尺/共同frame下的首层几何变化仅作诊断；改名本身不算物理错误。','', '原始输出未修改；本工具不证明所有隐含知识、缓存或模型内部记忆已被撤销。']
 write(output/'REVISION_REPORT_ZH.md','\n'.join(lines)+'\n');return result


if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--root',default=str(DEFAULT_ROOT));parser.add_argument('--output');parser.add_argument('--evaluator',default=str(EVALUATOR_ROOT));parser.add_argument('--protocol');parser.add_argument('--fixture',action='store_true');parser.add_argument('--geometry-diff-worker',action='store_true');args=parser.parse_args()
 if args.geometry_diff_worker:
  try:print(json.dumps(compare_geometry_worker(strict(sys.stdin.read())),allow_nan=False))
  except Exception as ex:print(json.dumps({'status':'DIAGNOSTIC_WORKER_ERROR','error':type(ex).__name__+': '+str(ex)}));sys.exit(1)
 else:
  if not args.output:parser.error('--output is required and must not exist')
  r=run(args.root,args.output,args.evaluator,args.protocol,args.fixture);print(json.dumps({'allocated':r['allocated_outputs'],'stage_summaries':r['stage_summaries']}))
