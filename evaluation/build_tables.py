"""Aggregate NEWLY REPLAYED row-level scores; no model call or score edits.

The primary reader/scorer is run_reproduction.py. This second step creates
paper tables and an exploratory building-cluster bootstrap from those rows.
"""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,csv,json,hashlib,math
from decimal import Decimal,ROUND_HALF_UP
HERE=Path(__file__).resolve().parent

def read(p):return json.loads(Path(p).read_text())
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def csvfile(p,rows):
 if not rows:return
 with p.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def valid(r):return r['status']=='SCORED' and r.get('schema_validation',{}).get('status')=='VALID'
def norm(x):return 'TRUE' if x is True else 'FALSE' if x is False else str(x).upper()
def pct(n,d):return str((Decimal(n)*100/Decimal(d)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if d else '--'
def quantile(a,p):
 pos=(len(a)-1)*p;i=math.floor(pos);j=math.ceil(pos)
 return a[i]+(a[j]-a[i])*(pos-i)
def stats(rows):
 q=[q for r in rows for q in r.get('query_rows',[]) if q['reference_evaluable']]
 g=[g for r in rows for g in r.get('grounding',[]) if g.get('bbox_evaluable',True)]
 w=[r for r in rows if r.get('arm') in ['A','B']]
 obs=lambda r:r.get('assessment',{}).get('verification',{}).get('definite_material_obstruction_rows',0)>0
 return {'allocated':len(rows),'contract_valid':sum(valid(r) for r in rows),'status_counts':dict(Counter(r['status'] for r in rows)),
 'known_correct':sum(bool(z['correct']) for z in q),'known_opportunities':len(q),'unknown_correct':sum(r.get('uncertainty_correct_count',0) for r in rows),'unknown_opportunities':sum(r.get('uncertainty_count',0) for r in rows),
 'all_known_correct_worlds':sum(bool(r.get('all_known_queries_correct')) for r in w),'worlds':len(w),
 'registered_PASS':sum(bool(r.get('assessment',{}).get('registered_fragment_success')) for r in w),'declared_PASS':sum(bool(r.get('assessment',{}).get('fragment_success')) for r in w),
 'joint_known_registered_coverage':sum(bool(r.get('all_target_relation_and_coverage_success')) and bool(r.get('assessment',{}).get('registered_fragment_success')) for r in w),
 'joint_known_declared_coverage':sum(bool(r.get('all_target_relation_and_coverage_success')) and bool(r.get('assessment',{}).get('fragment_success')) for r in w),
 'material_obstruction_worlds':sum(obs(r) for r in w),'material_obstruction_despite_known_all':sum(obs(r) and bool(r.get('all_known_queries_correct')) for r in w),
 'grounding_evaluable':len(g),'grounding_gate_pass':sum(bool(x.get('passes_localization_gate')) for x in g),'grounding_mean_iou':sum(x.get('best_iou',0) or 0 for x in g)/len(g) if g else None,
 'grounding_NOT_EVALUABLE':sum(not g.get('bbox_evaluable',True) for r in rows for g in r.get('grounding',[]))}
def paired(rows,first,second,only_valid):
 idx={(r['model_prefix'],r['case_id'],r['arm']):r for r in rows};records=[]
 for model,cid in sorted({(r['model_prefix'],r['case_id']) for r in rows}):
  a,b=idx[(model,cid,first)],idx[(model,cid,second)]
  if only_valid and not(valid(a) and valid(b)):continue
  qa={q['query_id']:q for q in a.get('query_rows',[]) if q['reference_evaluable']};qb={q['query_id']:q for q in b.get('query_rows',[]) if q['reference_evaluable']}
  assert set(qa)==set(qb)
  for qi in sorted(qa):
   assert qa[qi]['reference']==qb[qi]['reference']
   records.append({'case_id':cid,'model_prefix':model,'query_id':qi,'predicate':qa[qi]['predicate'],'first_correct':bool(qa[qi]['correct']),'second_correct':bool(qb[qi]['correct']),'first_valid':valid(a),'second_valid':valid(b)})
 by=[]
 for cid in sorted({r['case_id'] for r in records}):
  z=[r for r in records if r['case_id']==cid];by.append({'case_id':cid,'n':len(z),'first_correct':sum(x['first_correct'] for x in z),'second_correct':sum(x['second_correct'] for x in z)})
 n=len(records);ct=Counter((r['first_correct'],r['second_correct']) for r in records);interval=None
 if len(by)>=8:
  manifest=read(HERE/'data/BOOTSTRAP_INDEX_MANIFEST.json');entry=next(e for e in manifest['index_files'] if e['clusters']==len(by));raw=(HERE/entry['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==entry['sha256']
  nums=[r['second_correct']-r['first_correct'] for r in by];dens=[r['n'] for r in by];c=len(by);samples=[]
  for i in range(0,len(raw),c):
   indices=raw[i:i+c];samples.append(sum(nums[k] for k in indices)/sum(dens[k] for k in indices))
  samples.sort();interval=[quantile(samples,.025),quantile(samples,.975)]
 return {'first':first,'second':second,'restriction':'BOTH_CONTRACT_VALID' if only_valid else 'ALL_ALLOCATED','paired_known_opportunities':n,'building_clusters':len(by),'both_correct':ct[(True,True)],'first_only_correct':ct[(True,False)],'second_only_correct':ct[(False,True)],'neither_correct':ct[(False,False)],'second_minus_first':sum(r['second_correct']-r['first_correct'] for r in records)/n if n else None,'building_cluster_percentile_95_interval':interval,'by_building':by,'records':records}
def main(args):
 dest=args.output.resolve();assert not dest.exists(),'Choose a new table directory';dest.mkdir(parents=True)
 result=read(args.results);rows=result['rows'];static=[r for r in rows if not r['revision']];revision=[r for r in rows if r['revision']]
 groups={};per_config={};per_building={};pairs={};errors={};grounding=[];flat=[]
 for r in static:
  keys=[('/'.join([r['family'],r['condition'],r['arm']]),groups),('/'.join([r['family'],r['condition'],r['model_prefix'],r['arm']]),per_config),('/'.join([r['family'],r['condition'],r['case_id'],r['model_prefix'],r['arm']]),per_building)]
  for k,d in keys:d.setdefault(k,[]).append(r)
  for q in r.get('query_rows',[]):
   flat.append({'slot_key':r['slot_key'],'family':r['family'],'condition':r['condition'],'case_id':r['case_id'],'model_prefix':r['model_prefix'],'arm':r['arm'],'status':r['status'],'query_id':q['query_id'],'predicate':q['predicate'],'evaluation_layer':q.get('evaluation_layer'),'reference':q['reference'],'actual':norm(q.get('actual')),'correct':q['correct'],'reference_evaluable':q['reference_evaluable']})
   if q['reference_evaluable'] and not q['correct']:
    kind='Output contract / missing file' if not valid(r) else 'Identity assignment mismatch' if q['predicate']=='identity_assignment' else 'Geometry not evaluable / unknown' if q.get('actual') in [None,'UNKNOWN'] else 'Determinate geometric disagreement'
    errors.setdefault(r['family']+'/'+r['condition'],Counter())[kind]+=1
  for g in r.get('grounding',[]):grounding.append({'slot_key':r['slot_key'],'condition':r['condition'],'family':r['family'],**g})
 groups={k:stats(v) for k,v in groups.items()};per_config={k:stats(v) for k,v in per_config.items()};per_building={k:stats(v) for k,v in per_building.items()}
 for family,condition in sorted({(r['family'],r['condition']) for r in static}):
  z=[r for r in static if (r['family'],r['condition'])==(family,condition)]
  for a,b in [('R','A'),('A','B')]:
   for valid_only in [False,True]:pairs[f'{family}/{condition}/{a}_{b}/'+('valid' if valid_only else 'allocated')]=paired(z,a,b,valid_only)
 stages={}
 for stage in ['E0','E1','E2','F2']:
  z=[r for r in revision if r['stage']==stage];v=[r for r in z if valid(r)]
  stages[stage]={'allocated':len(z),'valid':len(v),'knowledge_success':sum(bool(r.get('height_knowledge',{}).get('knowledge_success')) for r in v),'height_geometry_correct':sum(bool(r.get('height_knowledge',{}).get('geometry_height_correct')) for r in v) if stage=='E1' else None,'retained_correct':sum(r.get('retained_relation_correct',0) for r in z),'retained_scored_opportunities':sum(r.get('retained_relation_denominator',0) for r in v),'retained_allocated_opportunities':sum(r['retained_allocated_opportunities'] for r in z),'status_counts':dict(Counter(r['status'] for r in z))}
 index={(r['model_prefix'],r['case_id'],r['stage']):r for r in revision};rp=[]
 for model,cid in sorted({(r['model_prefix'],r['case_id']) for r in revision}):
  a,b=index[(model,cid,'E2')],index[(model,cid,'F2')]
  if not(valid(a) and valid(b)):continue
  aq={q['query_id']:q for q in a['retained_relation_rows']};bq={q['query_id']:q for q in b['retained_relation_rows']}
  rel=[{'query_id':q,'incremental_actual':aq[q]['actual'],'fresh_actual':bq[q]['actual'],'same_conclusion':norm(aq[q]['actual'])==norm(bq[q]['actual']),'incremental_correct':aq[q]['correct'],'fresh_correct':bq[q]['correct']} for q in sorted(set(aq)&set(bq))]
  rp.append({'model_prefix':model,'case_id':cid,'knowledge_state_agreement':a['height_knowledge'].get('reported_status')==b['height_knowledge'].get('reported_status'),'relations':rel})
 summary={'data_source':'Fresh frozen2.2.1 raw-response replay in the specified REPLAY_RESULTS.json; no existing query CSV is read.','groups':groups,'per_configuration':per_config,'per_building_configuration':per_building,'failure_categories':{k:dict(v) for k,v in errors.items()},'revision':{'stages':stages,'valid':sum(x['valid'] for x in stages.values()),'allocated':len(revision),'knowledge_success':sum(x['knowledge_success'] for x in stages.values()),'E2_F2_valid_pairs':len(rp),'knowledge_state_agreement':sum(x['knowledge_state_agreement'] for x in rp),'retained_conclusion_agreement':sum(z['same_conclusion'] for x in rp for z in x['relations']),'retained_pair_opportunities':sum(len(x['relations']) for x in rp),'pairs':rp}}
 dump(dest/'MAJOR_TABLES.json',summary);dump(dest/'PAIRED_BOOTSTRAP.json',pairs);dump(dest/'GROUNDING_DETAILS.json',grounding)
 csvfile(dest/'ALL_QUERY_READOUTS_FRESH.csv',flat)
 csvfile(dest/'PER_CONFIGURATION.csv',[{'group':k,**{a:b for a,b in v.items() if a!='status_counts'}} for k,v in per_config.items()])
 csvfile(dest/'PER_BUILDING_CONFIGURATION.csv',[{'group':k,**{a:b for a,b in v.items() if a!='status_counts'}} for k,v in per_building.items()])
 csvfile(dest/'PAIR_COUNTS.csv',[{'comparison':k,**{a:b for a,b in v.items() if a not in ['records','by_building']}} for k,v in pairs.items()])
 tex=['% Generated from freshly replayed response scores. Counts include all allocated opportunities.','\\begin{tabular}{llrrr}\\hline','Family & Condition & R & A & B \\\\ \\hline']
 for fam,con in sorted({(r['family'],r['condition']) for r in static}):
  vals=[]
  for arm in ['R','A','B']:
   z=groups[f'{fam}/{con}/{arm}'];vals.append(f"{z['known_correct']}/{z['known_opportunities']} ({pct(z['known_correct'],z['known_opportunities'])}\\%)")
  tex.append(fam+' & '+con+' & '+' & '.join(vals)+' \\\\')
 tex.append('\\hline\\end{tabular}');(dest/'MAIN_RAB.tex').write_text('\n'.join(tex)+'\n')
 provenance={'source_results_sha256':hashlib.sha256(args.results.read_bytes()).hexdigest(),'source_signature_comparison':'FROZEN_RESULT_COMPARISON.json beside the results','metric_fields':{'known_correct':'query_rows[reference_evaluable=true].correct','known_opportunities':'all known query rows, including failed/missing output rows','registered_PASS':'assessment.registered_fragment_success','declared_PASS':'assessment.fragment_success','joint_known_registered_coverage':'all_target_relation_and_coverage_success AND assessment.registered_fragment_success','material_obstruction_worlds':'assessment.verification.definite_material_obstruction_rows >0','paired':'matched model_prefix,case_id,query_id; restriction explicit','revision_knowledge':'height_knowledge.knowledge_success','revision_E2_F2':'normalized equality of retained_relation_rows.actual'},'rounding':'Decimal ROUND_HALF_UP, two decimal percentages; e.g.125/160=78.13%','bootstrap':'data/BOOTSTRAP_INDEX_MANIFEST.json; ordinary building-cluster percentile intervals, exploratory','all_numeric_cells_located_in':'MAJOR_TABLES.json and PAIRED_BOOTSTRAP.json'}
 dump(dest/'NUMERIC_PROVENANCE.json',provenance)
 print(json.dumps({'status':'COMPLETE','rows':len(rows),'known_query_rows':sum(x['reference_evaluable'] for x in flat),'revision':summary['revision']|{'pairs':'in file'}}))
if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--results',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);main(ap.parse_args())
