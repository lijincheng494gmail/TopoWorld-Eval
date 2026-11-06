"""One bounded world evaluation in a disposable process; no output repair."""
from pathlib import Path
import importlib.util
import json
import sys

sys.dont_write_bytecode=True


def compact(value,depth=0):
    if depth>24:return {'diagnostic_truncated':'depth limit'}
    if isinstance(value,list):
        rows=[compact(x,depth+1) for x in value[:32]]
        if len(value)>32:rows.append({'diagnostic_remaining_items':len(value)-32})
        return rows
    if isinstance(value,dict):return {k:compact(v,depth+1) for k,v in value.items()}
    if isinstance(value,str) and len(value)>2400:return value[:2400]+' [diagnostic text truncated]'
    return value


def main():
    import resource
    limits={}
    try:resource.setrlimit(resource.RLIMIT_CPU,(25,30));limits['cpu_seconds']=25
    except (ValueError,OSError):limits['cpu_seconds']='UNAVAILABLE'
    try:resource.setrlimit(resource.RLIMIT_AS,(1536*1024**2,1536*1024**2));limits['address_space_bytes']=1536*1024**2
    except (ValueError,OSError):limits['address_space_bytes']='UNAVAILABLE'
    packet=json.load(sys.stdin)
    path=Path(packet['evaluator'])
    spec=importlib.util.spec_from_file_location('frozen_topoworld_geometry_22',path)
    g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
    result=g.assess(packet['world'],packet['case'])
    result.pop('compiled_entities',None)
    verification=result['verification']
    checks=verification.pop('checks',[])
    from collections import Counter
    verification['check_inventory']=dict(Counter(r.get('check','UNKNOWN') for r in checks))
    verification['classification_inventory']=dict(Counter(r.get('classification','UNKNOWN') for r in checks if 'classification' in r))
    verification['definite_material_obstruction_rows']=sum(bool(r.get('hard_violation')) for r in checks)
    verification['check_count']=len(checks)
    verification['violation_count']=len(verification.get('violations',[]))
    verification['unknown_count']=len(verification.get('not_evaluable',[]))
    result['worker_resource_limits']=limits
    result['diagnostic_compaction']='Lists retain first 32 diagnostic elements plus omitted count. Scalar verdicts and scoring values are not compacted.'
    print(json.dumps({'ok':True,'assessment':compact(result)},ensure_ascii=False,allow_nan=False))


if __name__=='__main__':
    try:main()
    except BaseException as exc:
        print(json.dumps({'ok':False,'error':type(exc).__name__+': '+str(exc)}))
        raise SystemExit(1)
