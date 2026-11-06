"""Offline replay from response text through frozen parser, schema and geometry.

No model/API call is implemented. Saved execution-audit labels are metadata,
not newly performed model identity or client-log verification.
"""
from pathlib import Path
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse
import ast
import csv
import datetime
import hashlib
import importlib.util
import json
import os
import platform
import re
import sys
import time

HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
VENDOR=HERE/'vendor/cpython313_darwin_arm64'
if os.environ.get('TOPOWORLD_DISABLE_VENDOR')!='1' and sys.version_info[:2]==(3,13) and sys.platform=='darwin' and platform.machine()=='arm64':
 sys.path.insert(0,str(VENDOR))
 os.environ['PYTHONPATH']=str(VENDOR)+(os.pathsep+os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')
try:
 import jsonschema
except ImportError as e:
 raise SystemExit('Install requirements.txt once in a Python environment, or use the included CPython3.13 macOS-arm64 vendor. Replay itself is offline.') from e

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
_OUTPUT_ROOT=None
_OUTPUT_LIMIT_BYTES=None
def read(p):return json.loads(Path(p).read_text())
def write(p,v):
 p=Path(p)
 if p.exists():raise FileExistsError('New immutable replay output required: '+str(p))
 payload=(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
 if _OUTPUT_ROOT is not None and p.resolve().is_relative_to(_OUTPUT_ROOT):
  used=sum(x.stat().st_size for x in _OUTPUT_ROOT.rglob('*') if x.is_file())
  if used+len(payload)>_OUTPUT_LIMIT_BYTES:
   raise RuntimeError('Replay output budget exceeded before writing '+p.name+': '+str(used+len(payload))+' > '+str(_OUTPUT_LIMIT_BYTES)+' bytes. No complete receipt was written.')
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f:f.write(payload)
def sanitize(x):
 if isinstance(x,dict):return {sanitize(k):sanitize(v) for k,v in x.items()}
 if isinstance(x,list):return [sanitize(v) for v in x]
 if isinstance(x,str) and re.search(r'/(?:Users|home)/[^/]+/',x):
  return 'source_artifact_'+hashlib.sha256(x.encode()).hexdigest()[:16]
 return x
def functions(text):
 tree=ast.parse(text)
 return {x.name:hashlib.sha256(ast.get_source_segment(text,x).encode()).hexdigest() for x in tree.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))}
def signature(row,revision=False):
 static=['status','observed','case_id_matches','parse_status','raw_bytes','raw_characters','schema_validation','query_rows','correct_query_count','query_count','uncertainty_count','uncertainty_correct_count','all_known_queries_correct','all_registered_answers_correct','all_target_relation_and_coverage_success','provenance','grounding','assessment']
 rev=['status','observed','raw_bytes','raw_characters','schema_validation','height_knowledge','source_audit','retained_relation_rows','retained_relation_correct','retained_relation_denominator','actual_height_geometry','assessment']
 result={k:row[k] for k in (rev if revision else static) if k in row}
 if 'assessment' in result:result['assessment']={k:v for k,v in result['assessment'].items() if k!='worker_resource_limits'}
 return sanitize(result)
def semantic_diffs(a,b,path='$',out=None):
 out=[] if out is None else out
 if type(a)!=type(b):out.append({'path':path,'kind':'TYPE','expected':a,'actual':b});return out
 if isinstance(a,dict):
  for k in sorted(set(a)|set(b)):
   if k not in a or k not in b:out.append({'path':path+'.'+k,'kind':'KEY_PRESENCE'})
   else:semantic_diffs(a[k],b[k],path+'.'+k,out)
 elif isinstance(a,list):
  if len(a)!=len(b):out.append({'path':path,'kind':'LENGTH','expected':len(a),'actual':len(b)})
  for i,(x,y) in enumerate(zip(a,b)):semantic_diffs(x,y,path+f'[{i}]',out)
 elif a!=b:out.append({'path':path,'kind':'VALUE','expected':a,'actual':b})
 return out

def verify_package():
 checks=[]
 for x in read(HERE/'data/SOURCE_ARTIFACT_HASHES.json')['artifacts']:
  p=HERE/x['path'];checks.append({'path':x['path'],'pass':p.is_file() and sha(p)==x['export_sha256']})
 for manifest in ['PROMPT_EXPORT_MANIFEST.json','BOOTSTRAP_INDEX_MANIFEST.json']:
  d=read(HERE/'data'/manifest)
  for x in d.get('artifacts',d.get('index_files',[])):
   f=HERE/x['path'];checks.append({'path':x['path'],'pass':f.is_file() and sha(f)==x.get('export_sha256',x.get('sha256'))})
 for x in read(HERE/'data/RAW_EXPORT_MANIFEST.json')['entries']:
  p=HERE/x['path'];checks.append({'path':x['path'],'pass':sha(p)==x['export_sha256'] if x['present'] and p.is_file() else not x['present'] and not p.exists()})
 for x in read(HERE/'data/SCIENTIFIC_SOURCE_ADAPTATIONS.json')['adaptations']:
  checks.append({'path':x['path'],'function_hashes_pass':functions((HERE/x['path']).read_text())==x['function_hashes'],'pass':functions((HERE/x['path']).read_text())==x['function_hashes']})
 assert all(x['pass'] for x in checks),'Exported scientific/input artifact differs from manifest'
 return {'status':'PASS','checks':checks,'checked':len(checks)}

def load_modules(execution):
 modules={}
 for condition in ['v1','N2','CS1']:
  folder=HERE/'frozen'/condition
  sys.path.insert(0,str(folder))
  spec=importlib.util.spec_from_file_location('replay_'+condition,folder/'score_trials.py')
  mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
  mod.EVALUATOR_ROOT=HERE/'evaluator';modules[condition]=mod
  import trial_io
  trial_io.RECORDED_AUDITS={k:v['host_audit'] for k,v in execution.items()}
 sys.modules['score_trials']=modules['v1']
 spec=importlib.util.spec_from_file_location('replay_revision',HERE/'frozen/v1/score_revision.py')
 rev=importlib.util.module_from_spec(spec);spec.loader.exec_module(rev)
 rev.EVALUATOR_ROOT=HERE/'evaluator'
 modules['revision']=rev
 return modules

def summaries(rows):
 groups={}
 for r in rows:
  key=r['family']+'/'+r['condition']+'/'+r.get('arm',r.get('stage'))
  z=groups.setdefault(key,{'allocated':0,'status_counts':Counter(),'contract_valid':0,'known_correct':0,'known_opportunities':0,'unknown_correct':0,'unknown_opportunities':0,'all_known_correct_worlds':0,'registered_geometry_PASS':0,'declared_geometry_PASS':0,'material_obstruction_worlds':0})
  z['allocated']+=1;z['status_counts'][r['status']]+=1;z['contract_valid']+=r['status']=='SCORED'
  if r['revision']:
   z['known_correct']+=r.get('retained_relation_correct',0)
   z['known_opportunities']+=r['retained_allocated_opportunities']
  else:
   z['known_correct']+=r.get('correct_query_count',0);z['known_opportunities']+=r.get('query_count',0)
   z['unknown_correct']+=r.get('uncertainty_correct_count',0);z['unknown_opportunities']+=r.get('uncertainty_count',0)
  a=r.get('assessment',{})
  if a:
   z['all_known_correct_worlds']+=r.get('all_known_queries_correct',False)
   z['registered_geometry_PASS']+=a.get('registered_geometry',{}).get('status')=='PASS_REGISTERED_GEOMETRY'
   z['declared_geometry_PASS']+=a.get('verification',{}).get('status')=='PASS_DECLARED_FRAGMENT'
   z['material_obstruction_worlds']+=a.get('verification',{}).get('definite_material_obstruction_rows',0)>0
 for v in groups.values():v['status_counts']=dict(v['status_counts'])
 return groups

def paired(rows):
 result=[]
 for family in ['GPT','Qwen']:
  for condition in ['v1','N2','CS1']:
   subset=[r for r in rows if r['family']==family and r['condition']==condition and not r['revision']]
   if not subset:continue
   index={(r['model_prefix'],r['case_id'],r['arm']):r for r in subset}
   for first,second in [('R','A'),('A','B')]:
    for restrict in ['ALL_ALLOCATED','BOTH_CONTRACT_VALID']:
     count=Counter()
     for model,cid,arm in sorted(index):
      if arm!=first or (model,cid,second) not in index:continue
      a,b=index[model,cid,first],index[model,cid,second]
      if restrict=='BOTH_CONTRACT_VALID' and (a['status']!='SCORED' or b['status']!='SCORED'):continue
      aq={q['query_id']:q for q in a.get('query_rows',[]) if q['reference_evaluable']}
      bq={q['query_id']:q for q in b.get('query_rows',[]) if q['reference_evaluable']}
      for q in set(aq)&set(bq):
       av,bv=aq[q]['correct'],bq[q]['correct']
       count['both' if av and bv else 'first_only' if av else 'second_only' if bv else 'neither']+=1
     result.append({'family':family,'condition':condition,'first':first,'second':second,'restriction':restrict,'n':sum(count.values()),**{k:count[k] for k in ['both','first_only','second_only','neither']}})
 return result

def run(args):
 global _OUTPUT_ROOT,_OUTPUT_LIMIT_BYTES
 started=time.monotonic()
 output=args.output.resolve()
 if output.exists():raise FileExistsError('Choose a new output directory')
 if args.max_output_mib<=0:raise ValueError('--max-output-mib must be positive')
 slots=read(HERE/'data/SLOTS.json')['slots']
 unknown=set(args.slot or [])-{x['slot_key'] for x in slots}
 if unknown:raise ValueError('Unknown --slot identifier(s): '+', '.join(sorted(unknown)))
 integrity=verify_package()
 output.mkdir(parents=True)
 _OUTPUT_ROOT=output
 _OUTPUT_LIMIT_BYTES=args.max_output_mib*1024**2
 original={}
 original_cases={}
 original_revision_refs=None
 if args.internal_original_map:
  mapping=read(args.internal_original_map)
  original={x['slot_key']:x for x in mapping['slots']}
  for x in mapping['slots']:
   v=x['scorer_variant']
   if v not in original_cases:
    d=read(x['original_case_file']);original_cases[v]={c['case_id']:c for c in (d['cases'] if isinstance(d,dict) else d)}
  original_revision_refs=read(mapping['original_revision_answers'])
 cases={condition:{c['case_id']:c for c in read(HERE/'data/cases'/(condition+'.json'))['cases']} for condition in ['v1','N2','CS1']}
 refs=read(HERE/'data/revision_answers.json')
 audits=read(HERE/'data/execution/RECORDED_EXECUTION_AUDITS.json')['records']
 modules=load_modules(audits)
 expected=read(HERE/'data/EXPECTED_SCIENTIFIC_SIGNATURES.json')['signatures']
 selected=[x for x in slots if not args.slot or x['slot_key'] in args.slot]
 limits={'output_char_limit':42000,'entity_limit':60}
 def one(slot):
  key=slot['slot_key'];variant=slot['scorer_variant'];record=audits[slot['audit_id']]
  raw=Path(original[key]['original_raw_file']) if original else HERE/slot['raw_file']
  job={k:slot[k] for k in ['job_id','model_prefix','codex_model_id','case_id','arm']}
  job['folder']=str(raw.parent.parent)
  entry={'status':slot['dispatch_status']}
  if slot['family']=='GPT':entry['thread_id']=slot['audit_id']
  dispatch={slot['job_id']:entry}
  case=(original_cases if original else cases)[variant][slot['case_id']]
  if slot['revision']:
   reference=(original_revision_refs if original else refs)[slot['case_id']][slot['arm']]
   row,_=modules['revision'].score_job(job,case,reference,dispatch,HERE,HERE/'evaluator',False)
   row['retained_allocated_opportunities']=len(reference['retained_relations'])
  else:row=modules[variant].score_job(job,case,dispatch,HERE,HERE/'evaluator',limits,False)
  row.update(family=slot['family'],condition=slot['condition'],revision=slot['revision'],slot_key=key,evaluator_version='2.2.1',offline_replay=True,new_model_execution=False)
  row['recorded_condition_verified']=record['condition_verified']
  row['recorded_input_integrity_status']=record['original_input_integrity_status']
  if slot['family']=='Qwen':
   for k,v in record.items():
    if k not in ['host_audit','original_input_integrity_status']:row[k]=v
  actual=signature(row,slot['revision'])
  diffs=semantic_diffs(expected[key],actual)
  # Output path metadata is made package-relative, not confused with raw bytes.
  row['raw_path']=slot['raw_file']
  return row,actual,{'slot_key':key,'matches_frozen_scientific_signature':not diffs,'differences':diffs[:30],'difference_count':len(diffs)}
 rows=[];signatures={};matches=[]
 with ThreadPoolExecutor(max_workers=args.workers) as pool:
  pending={pool.submit(one,s):s for s in selected}
  for future in as_completed(pending):
   row,sig,match=future.result();rows.append(row);signatures[row['slot_key']]=sig;matches.append(match)
   if len(rows)%25==0 or len(rows)==len(selected):print(json.dumps({'processed':len(rows),'allocated':len(selected),'signature_mismatches':sum(not x['matches_frozen_scientific_signature'] for x in matches),'seconds':round(time.monotonic()-started,1)}),flush=True)
   if sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>args.max_output_mib*1024**2:raise RuntimeError('Replay output budget exceeded')
 rows.sort(key=lambda r:next(s['slot_number'] for s in slots if s['slot_key']==r['slot_key']))
 mismatches=[x for x in matches if not x['matches_frozen_scientific_signature']]
 result={'evaluator_version':'2.2.1','replay_mode':'ORIGINAL_LOCAL_FILES' if original else 'ANONYMOUS_EXPORTED_RESPONSES','not_new_model_predictions':True,'allocated':len(selected),'rows':rows}
 write(output/'REPLAY_RESULTS.json',sanitize(result))
 write(output/'SCIENTIFIC_SIGNATURES.json',signatures)
 summary={'groups':summaries(rows),'paired':paired(rows)}
 write(output/'RECOMPUTED_TABLES.json',summary)
 write(output/'FROZEN_RESULT_COMPARISON.json',{'status':'PASS' if not mismatches else 'MISMATCHES_FOUND','compared':len(matches),'matched':len(matches)-len(mismatches),'mismatches':mismatches,'comparison_scope':'Original strict parser, Schema, limits, reference query values, complete deterministic assessment/provenance/grounding or revision knowledge/source/retained readouts; worker OS-limit metadata and bookkeeping paths excluded.'})
 write(output/'INPUT_INTEGRITY.json',integrity)
 write(output/'RUN_RECEIPT.json',{'status':'COMPLETE' if not mismatches else 'COMPLETE_WITH_REPORTED_MISMATCHES','python_version':sys.version,'platform':platform.platform(),'jsonschema_version':importlib.metadata.version('jsonschema'),'workers':args.workers,'wall_seconds':time.monotonic()-started,'allocated':len(selected),'raw_scientific_outputs_recomputed':True,'model_API_calls':0,'new_training':False,'original_or_exported_response_files_modified':False,'full_host_logs_reread':False,'execution_audit_source':'preserved metadata, not new host/model identity verification','frozen_signature_matches':len(matches)-len(mismatches),'mismatches':len(mismatches)})
 print(json.dumps({'status':'COMPLETE','rows':len(rows),'mismatches':len(mismatches),'seconds':round(time.monotonic()-started,1)}),flush=True)
 return 0 if not mismatches else 2

if __name__=='__main__':
 import importlib.metadata
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--output',type=Path,required=True,help='A new output directory; existing results are never overwritten')
 ap.add_argument('--workers',type=int,default=2,choices=range(1,5))
 ap.add_argument('--slot',action='append',help='Optional exact slot key; absent means all730 allocations')
 ap.add_argument('--max-output-mib',type=int,default=160)
 ap.add_argument('--internal-original-map',type=Path,help=argparse.SUPPRESS)
 raise SystemExit(run(ap.parse_args()))
