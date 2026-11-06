"""Geometry instrument v4, measurement correction evaluator 2.2.1.

No images, direct answers or reference files are used to derive geometric
predicates. Geometry is exact for the declared box model, not an unmeasured
building. This version separates owner identity, checks supported landing
bridges and finite straight-run assemblies, and uses material unions for
structural interfaces. Ancestor files and submitted geometry remain unchanged.
"""
from copy import deepcopy
from itertools import combinations, product
import math

EPS = 1e-7
MAX_BOXES = 4096
SPACE_KINDS = {'room', 'corridor', 'balcony'}
OPENING_KINDS = {'door_opening', 'window_opening', 'opening', 'stair_opening'}
NONPHYSICAL_KINDS = {'semantic_type', 'depiction', 'observation'}
SOLID_KINDS = {'wall', 'floor_slab', 'staircase', 'obstacle'}


def finite_number(x):
    return isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x)


def vector(x, n=3):
    return isinstance(x, list) and len(x) == n and all(finite_number(v) for v in x)


def box(minimum, maximum):
    if not vector(minimum) or not vector(maximum) or any(a >= b for a, b in zip(minimum, maximum)):
        raise ValueError('A box needs finite min < max on all three axes')
    return {'min': [float(x) for x in minimum], 'max': [float(x) for x in maximum]}


def volume(b):
    return math.prod(max(0.0, b['max'][i] - b['min'][i]) for i in range(3))


def intersection(a, b, tol=EPS):
    lo = [max(a['min'][i], b['min'][i]) for i in range(3)]
    hi = [min(a['max'][i], b['max'][i]) for i in range(3)]
    if any(hi[i] - lo[i] <= tol for i in range(3)):
        return None
    return {'min': lo, 'max': hi}


def occupied_intersection(a, b, tol=EPS):
    pairs = []
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            hit = intersection(x, y, tol)
            if hit is not None:
                pairs.append({'a_component': i, 'b_component': j, 'intersection': hit})
    return pairs


def subtract_box(a, b, tol=EPS):
    """Return a disjoint partition of A minus B; at most six axis-aligned boxes."""
    cut = intersection(a, b, tol)
    if cut is None:
        return [deepcopy(a)]
    remaining = deepcopy(a); pieces = []
    for k in range(3):
        if cut['min'][k] - remaining['min'][k] > tol:
            p = deepcopy(remaining); p['max'][k] = cut['min'][k]; pieces.append(p)
            remaining['min'][k] = cut['min'][k]
        if remaining['max'][k] - cut['max'][k] > tol:
            p = deepcopy(remaining); p['min'][k] = cut['max'][k]; pieces.append(p)
            remaining['max'][k] = cut['max'][k]
    return pieces


def subtract_union(boxes, cuts, tol=EPS):
    pieces = deepcopy(boxes)
    for cut in cuts:
        pieces = [p for current in pieces for p in subtract_box(current, cut, tol)]
        if len(pieces) > MAX_BOXES:
            raise ValueError('Component budget exceeded during exact box subtraction')
    return pieces


def union_volume(boxes, tol=EPS):
    partition = []
    for b in boxes:
        partition.extend(subtract_union([b], partition, tol))
        if len(partition) > MAX_BOXES:
            raise ValueError('Union partition budget exceeded')
    return sum(volume(p) for p in partition)


def contains_union(container, contained, tol=EPS):
    return not subtract_union(contained, container, tol)


def point_in_boxes(point, boxes, tol=EPS):
    return any(all(b['min'][i] - tol <= point[i] <= b['max'][i] + tol for i in range(3)) for b in boxes)


def xy_point_on_floor(point, entity, tol=EPS):
    floor = entity['raw'].get('floor_z')
    if not finite_number(floor):
        return None
    return abs(point[2] - floor) <= tol and any(
        b['min'][0] - tol <= point[0] <= b['max'][0] + tol and
        b['min'][1] - tol <= point[1] <= b['max'][1] + tol for b in entity['boxes'])


def bounds(boxes):
    if not boxes:
        return None
    return {'min': [min(b['min'][i] for b in boxes) for i in range(3)],
            'max': [max(b['max'][i] for b in boxes) for i in range(3)]}


def frame_matrix(frame_id, frames):
    identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    if frame_id in [None, 'world']:
        return identity
    if frame_id not in frames:
        raise ValueError('Unknown geometry frame: ' + str(frame_id))
    m = frames[frame_id].get('matrix_to_world')
    if not isinstance(m, list) or len(m) != 4 or not all(vector(r, 4) for r in m) or m[3] != [0, 0, 0, 1]:
        raise ValueError('Frame needs a finite 4x4 affine matrix')
    axes = []
    for r in m[:3]:
        nonzero = [i for i, x in enumerate(r[:3]) if abs(x) > EPS]
        if len(nonzero) != 1 or abs(abs(r[nonzero[0]]) - 1) > EPS:
            raise ValueError('Only signed axis permutation plus translation is supported')
        axes.append(nonzero[0])
    if len(set(axes)) != 3:
        raise ValueError('Frame matrix does not define three independent axes')
    return m


def transform_point(p, m):
    return [sum(m[i][k] * p[k] for k in range(3)) + m[i][3] for i in range(3)]


def transform_box(b, m):
    corners = [transform_point(p, m) for p in product(*zip(b['min'], b['max']))]
    return {'min': [min(p[i] for p in corners) for i in range(3)],
            'max': [max(p[i] for p in corners) for i in range(3)]}


def stair_boxes(g):
    start, end = g.get('start'), g.get('end')
    width, thickness, steps = g.get('width'), g.get('thickness'), g.get('steps')
    if not vector(start) or not vector(end) or not finite_number(width) or not finite_number(thickness):
        raise ValueError('stair_run needs finite start/end/width/thickness')
    if width <= 0 or thickness <= 0 or not isinstance(steps, int) or isinstance(steps, bool) or not 2 <= steps <= 128:
        raise ValueError('stair_run needs positive dimensions and 2..128 integer steps')
    moved = [i for i in [0, 1] if abs(end[i] - start[i]) > EPS]
    if len(moved) != 1 or end[2] <= start[2]:
        raise ValueError('stair_run supports one horizontal run axis and rising Z')
    axis = moved[0]; across = 1-axis; boxes = []
    for i in range(steps):
        p0 = start[axis] + (end[axis]-start[axis])*i/steps
        p1 = start[axis] + (end[axis]-start[axis])*(i+1)/steps
        z = start[2] + (end[2]-start[2])*(i+1)/steps
        lo = [0., 0., z-thickness]; hi = [0., 0., z]
        lo[axis], hi[axis] = min(p0,p1), max(p0,p1)
        lo[across], hi[across] = start[across]-width/2, start[across]+width/2
        boxes.append(box(lo, hi))
    return boxes, {'start': list(start), 'end': list(end), 'width': width,
                   'thickness': thickness, 'steps': steps, 'run_axis': axis,
                   'riser': (end[2]-start[2])/steps,
                   'tread_depth': abs(end[axis]-start[axis])/steps}


def compile_world(world):
    """Compile precisely the supplied geometry. No reference-based repairs."""
    issues=[]; entities={}
    def issue(eid,code,detail,status='NOT_EVALUABLE'):
        issues.append({'entity_id':eid,'code':code,'detail':detail,'status':status})
    if not isinstance(world,dict):
        return {'status':'INVALID','entities':{},'entity_list':[],'issues':[{'code':'NOT_A_WORLD','status':'INVALID'}], 'tolerance':EPS,'policy':{},'units':None}
    policy=world.get('verification_policy',{})
    if not isinstance(policy,dict):policy={};issue(None,'INVALID_POLICY','verification_policy must be object','INVALID')
    if world.get('schema')!='topoworld_executable_v1':issue(None,'SCHEMA_VERSION','Expected topoworld_executable_v1','INVALID')
    tol=policy.get('geometry_tolerance',policy.get('tolerance',EPS))
    if not finite_number(tol) or tol<=0 or tol>.01:tol=EPS;issue(None,'INVALID_TOLERANCE','Using arithmetic tolerance 1e-7','INVALID')
    frame_rows=world.get('frames',[])
    if not isinstance(frame_rows,list):frame_rows=[];issue(None,'INVALID_FRAMES','frames must be list','INVALID')
    frames={f['id']:f for f in frame_rows if isinstance(f,dict) and isinstance(f.get('id'),str)}
    rows=world.get('entities',[])
    if not isinstance(rows,list) or len(rows)>256:rows=[];issue(None,'ENTITY_BUDGET_OR_TYPE','Need list of at most256 entities','INVALID')
    for raw in rows:
        if not isinstance(raw,dict) or not isinstance(raw.get('id'),str) or not raw['id'] or raw['id'] in entities:
            issue(None,'INVALID_ENTITY_ID','Missing/duplicate entity ID','INVALID');continue
        eid=raw['id']; kind=raw.get('kind','unknown'); geometry=raw.get('geometry') or {'type':'unknown'}
        if not isinstance(geometry,dict):geometry={'type':'unknown'};issue(eid,'INVALID_GEOMETRY_TYPE','geometry must be object','INVALID')
        if kind not in SPACE_KINDS|OPENING_KINDS|NONPHYSICAL_KINDS|SOLID_KINDS|{'landing','unknown'}:
            issue(eid,'UNSUPPORTED_ENTITY_KIND',str(kind),'INVALID')
        item={'id':eid,'kind':kind,'owner':raw.get('owner','UNKNOWN'),'host_id':raw.get('host_id'),
              'boxes':[],'raw_boxes':[],'bounds':None,'stair':None,'geometry_status':'NOT_EVALUABLE',
              'raw':deepcopy(raw),'geometry_parameter_status':geometry.get('parameter_status','UNSPECIFIED')}
        entities[eid]=item
        if kind in NONPHYSICAL_KINDS and geometry.get('type','unknown')=='unknown':
            item['geometry_status']='NOT_APPLICABLE';continue
        try:
            kindg=geometry.get('type','unknown'); stair=None
            if kindg=='box':parts=[box(geometry.get('min'),geometry.get('max'))]
            elif kindg=='box_union':
                data=geometry.get('boxes')
                if not isinstance(data,list) or not data or len(data)>MAX_BOXES:raise ValueError('box_union needs1..4096 boxes')
                parts=[box(b.get('min'),b.get('max')) for b in data]
            elif kindg=='stair_run':parts,stair=stair_boxes(geometry)
            elif kindg=='unknown':issue(eid,'UNKNOWN_GEOMETRY','No executable occupied region');continue
            else:issue(eid,'UNSUPPORTED_PRIMITIVE',str(kindg));continue
            m=frame_matrix(geometry.get('frame','world'),frames)
            parts=[transform_box(b,m) for b in parts]
            if stair:
                stair['start']=transform_point(stair['start'],m);stair['end']=transform_point(stair['end'],m)
                if stair['end'][2]<=stair['start'][2]:raise ValueError('Transformed stairs must still rise in world Z')
            item.update(boxes=parts,raw_boxes=deepcopy(parts),bounds=bounds(parts),stair=stair,geometry_status='EXECUTABLE')
        except (ValueError,TypeError,KeyError,IndexError) as exc:
            item['geometry_status']='INVALID';issue(eid,'INVALID_GEOMETRY',str(exc),'INVALID')
    # Explicit void subtraction applies to walls and slabs, never to room identity.
    for eid,e in entities.items():
        ids=e['raw'].get('opening_ids',[])
        if not ids or e['geometry_status']!='EXECUTABLE':continue
        cuts=[]; valid=True
        for oid in ids:
            o=entities.get(oid)
            if o is None or o['kind'] not in OPENING_KINDS or o['geometry_status']!='EXECUTABLE':
                issue(eid,'OPENING_NOT_EXECUTABLE',str(oid));valid=False;continue
            if o.get('host_id')!=eid and eid not in o['raw'].get('host_ids',[]):
                issue(eid,'OPENING_HOST_MISMATCH',str(oid),'VIOLATION');continue
            if not contains_union(e['raw_boxes'],o['boxes'],tol):
                # A cut may deliberately extend beyond wall thickness; require
                # overlap but report that stronger full inclusion is absent.
                if not occupied_intersection(e['raw_boxes'],o['boxes'],tol):
                    issue(eid,'DETACHED_OPENING',str(oid),'VIOLATION');continue
            cuts.extend(o['boxes'])
        if valid:
            try:e['boxes']=subtract_union(e['boxes'],cuts,tol);e['bounds']=bounds(e['boxes'])
            except ValueError as exc:e['geometry_status']='NOT_EVALUABLE';issue(eid,'SUBTRACTION_BUDGET',str(exc))
        else:e['geometry_status']='NOT_EVALUABLE'
    statuses=[e['geometry_status'] for e in entities.values()]
    if not entities:issue(None,'EMPTY_WORLD','No physical world was supplied','NOT_EVALUABLE')
    status='INVALID' if any(i['status']=='INVALID' for i in issues) else 'PARTIAL' if not entities or any(s=='NOT_EVALUABLE' for s in statuses) else 'EXECUTABLE'
    return {'status':status,'entities':entities,'entity_list':list(entities.values()),'issues':issues,'tolerance':tol,
            'policy':deepcopy(policy),'units':world.get('units'),
            'scope':'Exact finite box-union occupancy with explicit void cuts and parameterized horizontal treads; no general meshes or structural-engineering certificate'}


def answer(value,status='DETERMINATE',**proof):
    if value=='TRUE':value=True
    elif value=='FALSE':value=False
    return {'value':value,'status':status,'proof':proof}


def resolve(world, role):
    mapping=world.get('task_bindings',{})
    if not isinstance(mapping,dict):return None
    binding=mapping.get(role,role)
    return binding if isinstance(binding,str) else None


def projection_intersects(a,b,plane='XZ',tol=EPS):
    axes={'XY':(0,1),'XZ':(0,2),'YZ':(1,2),'ZY':(2,1)}.get(plane)
    if axes is None:return None
    return any(all(min(x['max'][i],y['max'][i])-max(x['min'][i],y['min'][i])>=-tol for i in axes) for x in a for y in b)


def _face_rectangle(b,axis):
    other=[i for i in range(3) if i!=axis]
    return {'min':[b['min'][i] for i in other]+[0.],
            'max':[b['max'][i] for i in other]+[1.]}


def _union_boundary_faces(boxes,axis,tol):
    """Exposed boundary patches, removing artificial internal tile faces.

    Each patch is represented in a 2D chart extruded over [0,1] for the existing
    exact union operations. These chart boxes are not physical scene geometry.
    """
    faces=[]
    for b in boxes:
        for side in ['min','max']:
            coordinate=b[side][axis];cuts=[]
            for other in boxes:
                beyond=(other['min'][axis]<coordinate-tol and other['max'][axis]>=coordinate-tol
                        if side=='min' else
                        other['max'][axis]>coordinate+tol and other['min'][axis]<=coordinate+tol)
                if beyond:cuts.append(_face_rectangle(other,axis))
            exposed=subtract_union([_face_rectangle(b,axis)],cuts,tol)
            faces.extend({'coordinate':coordinate,'side':side,'rectangle':p} for p in exposed)
            if len(faces)>MAX_BOXES:raise ValueError('Boundary patch budget exceeded')
    return faces


def _covered_face_planes(aperture,axis,faces,tol,side=None):
    """Find a coplanar union covering the entire aperture projection."""
    target=_face_rectangle(aperture,axis)
    eligible=[f for f in faces if (side is None or f['side']==side) and
              aperture['min'][axis]-tol<=f['coordinate']<=aperture['max'][axis]+tol]
    result=[]
    for coordinate in sorted({f['coordinate'] for f in eligible}):
        patches=[f['rectangle'] for f in eligible if abs(f['coordinate']-coordinate)<=tol]
        if contains_union(patches,[target],tol):result.append(coordinate)
    return result


def _opening_components(boxes,tol):
    """Group volume/face-connected boxes; edge-only contact is not a portal.

    A rectangular component is represented by its bounding box only after exact
    union coverage is established. A real L-shaped hole is never filled in.
    """
    left=set(range(len(boxes)));components=[]
    while left:
        seed=min(left);left.remove(seed);group=[seed];pending=[seed]
        while pending:
            i=pending.pop()
            for j in sorted(left):
                overlap=[min(boxes[i]['max'][k],boxes[j]['max'][k])-max(boxes[i]['min'][k],boxes[j]['min'][k]) for k in range(3)]
                if min(overlap)>=-tol and sum(v>tol for v in overlap)>=2:
                    left.remove(j);group.append(j);pending.append(j)
        members=[boxes[i] for i in group];bound=bounds(members)
        rectangular=contains_union(members,[bound],tol)
        components.append({'boxes':[bound] if rectangular else members,'rectangular':rectangular})
    return components


def _aperture_normal_axes(aperture,wall,tol,wall_faces=None):
    """Normals come from locally traversed exposed wall faces, not list order."""
    axes=[]
    for axis in [0,1]:
        faces=wall_faces[axis] if wall_faces is not None else _union_boundary_faces(wall['raw_boxes'],axis,tol)
        lows=_covered_face_planes(aperture,axis,faces,tol,'min')
        highs=_covered_face_planes(aperture,axis,faces,tol,'max')
        if any(hi-lo>tol for lo in lows for hi in highs):axes.append(axis)
    return axes


def aperture_fits_wall(opening,wall,tol=EPS):
    """Traverse a local wall thickness with full in-plane union coverage.

    Normal overshoot remains allowed. Unrelated host components, their order
    and internal subdivision do not determine the local wall orientation.
    """
    if not opening['boxes']:return False
    wall_faces={axis:_union_boundary_faces(wall['raw_boxes'],axis,tol) for axis in [0,1]}
    return all(_aperture_normal_axes(aperture,wall,tol,wall_faces)
               for component in _opening_components(opening['boxes'],tol) for aperture in component['boxes'])


def _need(compiled,ids):
    for eid in ids:
        if eid not in compiled['entities']:return answer('NOT_FOUND','NOT_FOUND',entity_ids=ids,reason='Required physical entity missing')
        if compiled['entities'][eid]['geometry_status']!='EXECUTABLE':return answer('UNKNOWN','NOT_EVALUABLE',entity_ids=ids,reason='Required geometry not executable')
    return None


def stair_connection(compiled,stair_id,rooms=None):
    entities=compiled['entities'];tol=compiled['tolerance'];s=entities.get(stair_id)
    if s is None:return answer('NOT_FOUND','NOT_FOUND',reason='Stair missing')
    if s['geometry_status']!='EXECUTABLE' or s['stair'] is None:return answer('UNKNOWN','NOT_EVALUABLE',reason='A staircase needs executable stair_run to verify tread/endpoints')
    raw=s['raw']; interfaces=raw.get('endpoint_interfaces',raw.get('endpoint_interface_ids',[]));declared=raw.get('connects_rooms',[])
    if len(interfaces)!=2 or len(declared)!=2:return answer('UNKNOWN','NOT_EVALUABLE',reason='Need two explicit landing IDs and room IDs')
    missing=_need(compiled,[stair_id]+interfaces+declared)
    if missing:return missing
    requested=rooms or declared;floor_bridge=[]
    missing=_need(compiled,list(requested))
    if missing:return missing
    if set(requested)!=set(declared):
        # A question about floors may name the slab supporting a declared room.
        # Admit only the explicit room.host_id bridge plus actual endpoint/slab
        # incidence. Same height or a similar ID is not an identity conversion.
        if not all(entities[i]['kind']=='floor_slab' for i in requested):
            if all(entities[i]['kind'] in SPACE_KINDS for i in requested):
                return answer('FALSE',entity_ids=[stair_id]+list(requested),calculation='Requested spaces differ from declared endpoint spaces',declared_rooms=declared)
            return answer('UNKNOWN','NOT_EVALUABLE',reason='Requested endpoint type has no supported room-to-floor interpretation')
        host_ids=[entities[r]['raw'].get('host_id') for r in declared]
        if len(set(host_ids))!=2 or set(host_ids)!=set(requested):
            return answer('UNKNOWN','NOT_EVALUABLE',reason='No explicit one-to-one endpoint-room host bridge to requested slabs',declared_rooms=declared,requested_slabs=list(requested))
        for point,room_id,slab_id in zip([s['stair']['start'],s['stair']['end']],declared,host_ids):
            slab=entities[slab_id];top=slab['bounds']['max'][2]
            on_top=abs(point[2]-top)<=tol
            in_footprint=any(abs(b['max'][2]-top)<=tol and all(b['min'][i]-tol<=point[i]<=b['max'][i]+tol for i in [0,1]) for b in slab['boxes'])
            floor_bridge.append({'room':room_id,'slab':slab_id,'endpoint':point,'room_host_matches':True,
                                 'endpoint_on_slab_top':on_top,'endpoint_on_retained_slab_footprint':in_footprint})
        if not all(b['endpoint_on_slab_top'] and b['endpoint_on_retained_slab_footprint'] for b in floor_bridge):
            return answer('FALSE',entity_ids=[stair_id]+list(requested),calculation='Explicit host bridge exists but endpoint/slab geometry disagrees',floor_host_bridge_checks=floor_bridge)
    tests=[]
    for point,iid,rid in zip([s['stair']['start'],s['stair']['end']],interfaces,declared):
        landing=entities[iid];room=entities[rid]
        floor=xy_point_on_floor(point,room,tol)
        if floor is None:return answer('UNKNOWN','NOT_EVALUABLE',reason='Room floor_z missing',entity_ids=[rid])
        tests.append({'endpoint':point,'interface':iid,'room':rid,
                      'landing_kind':landing['kind']=='landing',
                      'landing_host_matches':landing.get('host_id')==rid,
                      'endpoint_inside_landing':point_in_boxes(point,landing['boxes'],tol),
                      'endpoint_on_room_floor':floor,
                      'landing_touches_stair_footprint':any(all(min(a['max'][i],b['max'][i])-max(a['min'][i],b['min'][i])>=-tol for i in [0,1]) for a in landing['boxes'] for b in s['boxes'])})
    owners=[entities[r]['owner'] for r in declared]
    known=[o for o in owners+[s['owner']] if o not in [None,'UNKNOWN','unknown']]
    owner_compatible=not known or len(set(known))==1
    rise=s['stair']['riser'];width=s['stair']['width'];depth=s['stair']['tread_depth']
    policy=compiled['policy'];max_riser=policy.get('max_riser');min_width=policy.get('min_width',policy.get('minimum_width'));min_tread=policy.get('min_tread_depth')
    policy_tests={'riser_positive':rise>0,'tread_depth_positive':depth>0,'width_positive':width>0}
    if finite_number(max_riser):policy_tests['riser_within_declared_policy']=rise<=max_riser+tol
    if finite_number(min_width):policy_tests['width_within_declared_policy']=width>=min_width-tol
    if finite_number(min_tread):policy_tests['tread_depth_within_declared_policy']=depth>=min_tread-tol
    good=all(all(v for k,v in test.items() if k not in ['endpoint','interface','room']) for test in tests) and owner_compatible and all(policy_tests.values())
    return answer('TRUE' if good else 'FALSE',entity_ids=[stair_id]+interfaces+declared,
                  calculation='Expanded tread occupancy, endpoint-on-floor and landing incidence; no connects truth value read',
                  endpoint_tests=tests,owner_compatible=owner_compatible,policy_tests=policy_tests,
                  requested_endpoint_entities=list(requested),floor_host_bridge_checks=floor_bridge,
                  scope='Structural/private interface connection; full human path/clearance is separate')


def window_host(compiled,window_id,room_id):
    missing=_need(compiled,[window_id,room_id])
    if missing:return missing
    entities=compiled['entities'];w=entities[window_id];room=entities[room_id];wall_id=w.get('host_id');wall=entities.get(wall_id);tol=compiled['tolerance']
    if w['kind']!='window_opening' or room['kind'] not in SPACE_KINDS:return answer('UNKNOWN','NOT_EVALUABLE',reason='window_host requires a window opening and spatial room')
    if wall is None:return answer('UNKNOWN','NOT_EVALUABLE',reason='Window host wall missing')
    if wall['geometry_status']!='EXECUTABLE' or wall['kind']!='wall':return answer('UNKNOWN','NOT_EVALUABLE',reason='Executable wall required')
    fits_wall=aperture_fits_wall(w,wall,tol)
    face_tests=[];per_patch=[]
    room_faces={axis:_union_boundary_faces(room['boxes'],axis,tol) for axis in [0,1]}
    wall_faces={axis:_union_boundary_faces(wall['raw_boxes'],axis,tol) for axis in [0,1]}
    for component in _opening_components(w['boxes'],tol):
        for wb in component['boxes']:
            matches=[]
            for axis in _aperture_normal_axes(wb,wall,tol,wall_faces):
                for coordinate in _covered_face_planes(wb,axis,room_faces[axis],tol):
                    matches.append({'axis':axis,'coordinate':coordinate,'coverage':'EXPOSED_COPLANAR_FACE_UNION'})
            per_patch.append(bool(matches));face_tests.extend(matches)
    room_ids=w['raw'].get('room_ids',[]);wall_host=wall.get('host_id')
    host_consistent=wall_host==room_id and room_ids==[room_id]
    void_registered=window_id in wall['raw'].get('opening_ids',[])
    geometric_good=fits_wall and bool(per_patch) and all(per_patch) and void_registered
    proof={'entity_ids':[window_id,wall_id,room_id],
           'calculation':'Window void/wall fit, room-face incidence and registered subtraction; metadata sufficiency separate',
           'fits_wall':fits_wall,'room_face_matches':face_tests,'declared_host_consistent':host_consistent,
           'void_registered':void_registered,'window_room_ids':room_ids,'wall_host_id':wall_host,
           'aperture_patch_coverage':per_patch,'boundary_rule':'EXPOSED_UNION_BOUNDARY_V3'}
    if not geometric_good:return answer('FALSE',**proof)
    if room_ids and room_id not in room_ids:return answer('FALSE',**proof)
    if wall_host not in [None,'UNKNOWN','unknown',room_id]:return answer('FALSE',**proof)
    if wall_host is None or wall_host in ['UNKNOWN','unknown'] or room_ids!=[room_id]:
        return answer('UNKNOWN','NOT_EVALUABLE',**proof,reason='Geometric placement is compatible; explicit unique wall/room parent metadata incomplete')
    good=geometric_good and host_consistent
    return answer('TRUE' if good else 'FALSE',entity_ids=[window_id,wall_id,room_id],
                  calculation='Window void inside uncut wall, room-face incidence and explicit wall subtraction',
                  fits_wall=fits_wall,room_face_matches=face_tests,declared_host_consistent=host_consistent,void_registered=void_registered)


def door_connection(compiled,door_id):
    entities=compiled['entities'];d=entities.get(door_id);tol=compiled['tolerance']
    if not d:return answer('NOT_FOUND','NOT_FOUND')
    rooms=d['raw'].get('room_ids',[])
    if len(rooms)!=2:return answer('UNKNOWN','NOT_EVALUABLE',reason='Door needs two room_ids')
    missing=_need(compiled,[door_id]+rooms)
    if missing:return missing
    wall=entities.get(d.get('host_id'))
    if wall is None or wall['geometry_status']!='EXECUTABLE':return answer('UNKNOWN','NOT_EVALUABLE',reason='Door host wall missing/unexecutable')
    floor=[entities[r]['raw'].get('floor_z') for r in rooms]
    if not all(finite_number(z) for z in floor):return answer('UNKNOWN','NOT_EVALUABLE',reason='Door room floor levels missing')
    checks={'same_floor':abs(floor[0]-floor[1])<=tol,
            'fits_wall':aperture_fits_wall(d,wall,tol),
            'opening_cut':door_id in wall['raw'].get('opening_ids',[]),
            'touches_each_room':all(any(all(min(a['max'][i],b['max'][i])-max(a['min'][i],b['min'][i])>=-tol for i in range(3)) for a in d['boxes'] for b in entities[r]['boxes']) for r in rooms),
            'bottom_at_floor':any(abs(b['min'][2]-floor[0])<=tol for b in d['boxes'])}
    policy=compiled['policy'];height=policy.get('body_height');width=policy.get('min_width',policy.get('minimum_width'))
    dimension_proof=[];components=_opening_components(d['boxes'],tol)
    if not all(checks.values()):
        return answer('FALSE',entity_ids=[door_id]+rooms,calculation='Local wall fit, registered subtraction, same-floor and room incidence',checks=checks)
    if finite_number(height) or finite_number(width):
        if not all(c['rectangular'] for c in components):
            return answer('UNKNOWN','NOT_EVALUABLE',entity_ids=[door_id]+rooms,checks=checks,
                          reason='A nonrectangular portal needs a supported clearance/width profile; no bounding-box shortcut')
        wall_faces={axis:_union_boundary_faces(wall['raw_boxes'],axis,tol) for axis in [0,1]}
        for component in components:
            aperture=component['boxes'][0];axes=_aperture_normal_axes(aperture,wall,tol,wall_faces)
            if len(axes)!=1:
                return answer('UNKNOWN','NOT_EVALUABLE',entity_ids=[door_id]+rooms,checks=checks,
                              normal_candidates=axes,reason='Local aperture normal is not uniquely established by host geometry')
            axis=axes[0];dimension_proof.append({'normal_axis':axis,'width_axis':1-axis,
                'width':aperture['max'][1-axis]-aperture['min'][1-axis],
                'height':aperture['max'][2]-aperture['min'][2]})
        if finite_number(height):checks['opening_height_policy']=all(p['height']>=height-tol for p in dimension_proof)
        if finite_number(width):checks['opening_width_policy']=all(p['width']>=width-tol for p in dimension_proof)
    return answer('TRUE' if all(checks.values()) else 'FALSE',entity_ids=[door_id]+rooms,
                  calculation='Aperture containment/cut, same-floor and room incidence',checks=checks,
                  local_dimensions=dimension_proof,boundary_rule='EXPOSED_UNION_BOUNDARY_V3')


def derived_graph(compiled):
    edges=[];unknown=[]
    for eid,e in compiled['entities'].items():
        if e['kind']=='staircase':r=stair_connection(compiled,eid);rooms=e['raw'].get('connects_rooms',[])
        elif e['kind']=='door_opening':r=door_connection(compiled,eid);rooms=e['raw'].get('room_ids',[])
        else:continue
        if r['status']=='DETERMINATE' and r['value'] is True and len(rooms)==2:
            edges.append({'a':rooms[0],'b':rooms[1],'interface':eid,'owner':e['owner'],'proof':r['proof']})
        elif r['status']!='DETERMINATE':unknown.append({'interface':eid,'result':r})
    return {'edges':edges,'unknown_interfaces':unknown,'scope':'Geometrically admitted interface graph; not complete human navigability'}


def evaluate_query(compiled,world,q):
    pred=q.get('predicate');rawargs=q.get('args',[]);args=[resolve(world,x) for x in rawargs]
    es=compiled['entities'];tol=compiled['tolerance']
    if pred=='floor_delta':
        if len(args)!=2:return answer('UNKNOWN','NOT_EVALUABLE',reason='Need two floor/room entities')
        missing=_need(compiled,args)
        if missing:return missing
        heights=[]
        for eid in args:
            e=es[eid]
            if e['kind'] in SPACE_KINDS:surface=e['bounds']['min'][2]
            elif e['kind']=='floor_slab':surface=e['bounds']['max'][2]
            else:return answer('UNKNOWN','NOT_EVALUABLE',reason='floor_delta needs room or slab geometry')
            declared=e['raw'].get('floor_z')
            if finite_number(declared) and abs(declared-surface)>tol:return answer('UNKNOWN','NOT_EVALUABLE',reason='Declared floor_z conflicts with occupied room/slab boundary',entity_ids=[eid])
            heights.append(surface)
        units=world.get('units',{})
        source=units.get('length') if isinstance(units,dict) else units
        target=q.get('unit',source)
        meters={'m':1.,'meter':1.,'meters':1.,'ft':.3048,'feet':.3048,'in':.0254,'inch':.0254}
        factor=meters.get(source)
        if factor is None and isinstance(units,dict) and finite_number(units.get('meters_per_unit')):factor=units['meters_per_unit']
        if source==target:factor=1.;divisor=1.
        elif factor is not None and target in meters:divisor=meters[target]
        else:return answer('UNKNOWN','NOT_EVALUABLE',reason='Unknown metric scale cannot produce a measured floor delta in requested unit')
        return answer((heights[0]-heights[1])*factor/divisor,entity_ids=args,unit=target,
                      geometric_floor_surfaces=heights,calculation='Difference of actual room lower/slab upper Z boundaries, with declared unit conversion')
    if pred=='same_physical_entity':
        observations={o['id']:o for o in world.get('observations',[])}
        ids=[]
        for arg in args:
            if arg in observations:
                candidates=observations[arg].get('entity_ids',[])
                if len(candidates)!=1:return answer('UNKNOWN','NOT_EVALUABLE',reason='Physical denotation unresolved')
                ids.append(candidates[0])
            else:ids.append(arg)
        if len(ids)!=2 or any(i not in es for i in ids):return answer('NOT_FOUND','NOT_FOUND')
        if ids[0]==ids[1] and es[ids[0]]['kind'] not in NONPHYSICAL_KINDS:return answer('TRUE',entity_ids=ids,calculation='Explicit shared physical instance')
        return answer('UNKNOWN','NOT_EVALUABLE',reason='Different IDs do not establish physical inequality',entity_ids=ids)
    if pred in ['belongs_to','owner']:
        if not args or args[0] not in es:return answer('NOT_FOUND','NOT_FOUND')
        if len(args)==2 and args[1] in es:
            child,host=(es[i] for i in args)
            if child['kind']=='window_opening' and host['kind'] in SPACE_KINDS:return window_host(compiled,*args)
            if host['kind'] not in SPACE_KINDS or child['kind'] in NONPHYSICAL_KINDS:
                return answer('UNKNOWN','NOT_EVALUABLE',reason='belongs_to target sort is ambiguous/unsupported; part_of/type membership is not unique physical host')
            if child.get('host_id') in [None,'UNKNOWN','unknown']:
                return answer('UNKNOWN','NOT_EVALUABLE',reason='Physical attachment host is not explicitly specified; ownership/served space is a different relation')
            missing=_need(compiled,args)
            if missing:return missing
            touches=any(all(min(a['max'][i],b['max'][i])-max(a['min'][i],b['min'][i])>=-tol for i in range(3)) for a in child['boxes'] for b in host['boxes'])
            consistent=child.get('host_id')==args[1] and touches and child['owner']==host['owner']
            return answer('TRUE' if consistent else 'FALSE',entity_ids=args,calculation='Explicit attachment host with matching owner and geometric incidence',touches=touches)
        owner=es[args[0]]['owner']
        if owner in [None,'UNKNOWN','unknown']:return answer('UNKNOWN','NOT_EVALUABLE',reason='Ownership not a geometric inference')
        if len(args)==1:return answer(owner,entity_ids=args,calculation='Explicit semantic ownership, not geometric membership')
        return answer('TRUE' if owner==rawargs[1] else 'FALSE',entity_ids=[args[0]],calculation='Explicit semantic ownership compared within declared household frame')
    if pred=='stair_connects':
        if len(args)!=3:return answer('UNKNOWN','NOT_EVALUABLE',reason='Need staircase and two rooms')
        return stair_connection(compiled,args[0],args[1:])
    if pred=='connected_by':
        if len(args)!=3:return answer('UNKNOWN','NOT_EVALUABLE',reason='Need two spaces and an interface')
        interface=es.get(args[2])
        if not interface:return answer('NOT_FOUND','NOT_FOUND')
        if interface['kind']=='staircase':return stair_connection(compiled,args[2],args[:2])
        if interface['kind']=='door_opening':
            declared=interface['raw'].get('room_ids',[])
            if set(declared)!=set(args[:2]):return answer('FALSE',reason='Door rooms differ from requested spaces')
            return door_connection(compiled,args[2])
        return answer('UNKNOWN','NOT_EVALUABLE',reason='Unsupported interface type')
    if pred=='window_host':
        if len(args)!=2:return answer('UNKNOWN','NOT_EVALUABLE')
        return window_host(compiled,*args)
    if pred in ['upper_public_corridor','no_upper_public_corridor','no_public_corridor']:
        z=q.get('level_z',q.get('floor_z'))
        if not finite_number(z):
            floors=[es[i]['raw'].get('floor_z') for i in args if i in es]
            if len(floors)!=len(args) or not floors or not all(finite_number(x) for x in floors):return answer('UNKNOWN','NOT_EVALUABLE',reason='Need explicit upper-level entities with floor_z')
            z=min(floors)
        completeness=world.get('completeness',{})
        if not (world.get('public_spaces_complete') is True or completeness.get('public_spaces_complete') is True):return answer('UNKNOWN','NOT_EVALUABLE',reason='Public-space inventory not declared complete; absence is not an empty-world success')
        matching=[eid for eid,e in es.items() if e['kind']=='corridor' and e['owner']=='PUBLIC' and e['geometry_status']=='EXECUTABLE' and finite_number(e['raw'].get('floor_z')) and e['raw']['floor_z']>=z-tol]
        uncertain=[eid for eid,e in es.items() if e['kind']=='corridor' and (e['geometry_status']!='EXECUTABLE' or not finite_number(e['raw'].get('floor_z')))]
        if uncertain:return answer('UNKNOWN','NOT_EVALUABLE',unresolved_corridors=uncertain)
        value=bool(matching)
        if pred in ['no_upper_public_corridor','no_public_corridor']:value=not value
        return answer('TRUE' if value else 'FALSE',matching_corridors=matching,calculation='Enumerate explicit executable PUBLIC corridor volumes at given floor height',scope='Generated-scene closed-world inventory, not unseen real architecture')
    if pred in ['interface_reachable','accessible']:
        if len(args)!=2 or any(i not in es for i in args):return answer('NOT_FOUND','NOT_FOUND')
        if any(es[i]['kind'] not in SPACE_KINDS for i in args):return answer('UNKNOWN','NOT_EVALUABLE',reason='This interface graph admits spatial rooms/corridors, not landing/part nodes')
        if pred=='accessible':return answer('UNKNOWN','NOT_EVALUABLE',reason='Full body/motion path witness not implemented; interface graph is a separate predicate')
        graph=derived_graph(compiled);policy=q.get('policy','ALL');edges=[]
        for edge in graph['edges']:
            if isinstance(policy,str) and policy in ['PRIVATE_A','PRIVATE_B'] and edge['owner'] not in [policy[-1]]:continue
            if isinstance(policy,dict) and policy.get('exclude_public'):
                if edge['owner']=='PUBLIC' or any(es[r]['kind']=='corridor' and es[r]['owner']=='PUBLIC' for r in [edge['a'],edge['b']]):continue
            edges.append(edge)
        seen={args[0]};pending=[args[0]]
        while pending:
            current=pending.pop()
            for edge in edges:
                other=edge['b'] if edge['a']==current else edge['a'] if edge['b']==current else None
                if other is not None and other not in seen:seen.add(other);pending.append(other)
        if args[1] not in seen and graph['unknown_interfaces']:return answer('UNKNOWN','NOT_EVALUABLE',reason='Missing interface geometry could change reachability')
        return answer('TRUE' if args[1] in seen else 'FALSE',entity_ids=args,admitted_edges=edges,policy=policy,calculation='Reachability over geometric door/stair interfaces, no declared connectivity edge read')
    if len(args)!=2:return answer('UNKNOWN','NOT_EVALUABLE',reason='Predicate needs two physical geometry arguments')
    missing=_need(compiled,args)
    if missing:return missing
    a,b=(es[i] for i in args);boxes_a,boxes_b=a['boxes'],b['boxes']
    if pred in ['intersects','disjoint']:
        pairs=occupied_intersection(boxes_a,boxes_b,tol);v=bool(pairs)
        if pred=='disjoint':v=not v
        return answer('TRUE' if v else 'FALSE',entity_ids=args,calculation='Exact positive-volume box-component overlap; boundary touch is not collision',overlap_pairs=pairs)
    if pred=='contains':return answer('TRUE' if contains_union(boxes_a,boxes_b,tol) else 'FALSE',entity_ids=args,calculation='Exact box-union subtraction; remaining volume must be empty')
    if pred in ['above','below']:
        if pred=='below':a,b=b,a;boxes_a,boxes_b=boxes_b,boxes_a
        xy=any(all(min(x['max'][i],y['max'][i])-max(x['min'][i],y['min'][i])>tol for i in [0,1]) for x in boxes_a for y in boxes_b)
        value=xy and a['bounds']['min'][2]>=b['bounds']['max'][2]-tol
        return answer('TRUE' if value else 'FALSE',entity_ids=args,xy_overlap=xy,calculation='Vertical interval separation with overlapping XY footprint, not center ordering')
    if pred in ['projection_intersects','projected_crossing']:
        plane=q.get('plane','XZ');v=projection_intersects(boxes_a,boxes_b,plane,tol)
        if v is None:return answer('UNKNOWN','NOT_EVALUABLE',reason='Unsupported projection plane')
        return answer('TRUE' if v else 'FALSE',entity_ids=args,plane=plane,calculation='Nonempty orthographic projection of occupied box unions; never infers3Dcollision')
    return answer('UNKNOWN','NOT_EVALUABLE',reason='Unsupported geometric predicate '+str(pred))


def merge_intervals(intervals,tol=EPS):
    merged=[]
    for lo,hi in sorted(intervals):
        if hi-lo<=tol:continue
        if merged and lo<=merged[-1][1]+tol:merged[-1][1]=max(merged[-1][1],hi)
        else:merged.append([lo,hi])
    return merged


def walking_surface_intrusions(stair,other,tol=EPS):
    """Exact rectangular sweep at the supplied horizontal tread top surfaces.

    A vertical solid crossing immediately above a tread is different from a
    support intersecting its underside. Full-width means a positive-length run
    interval whose cross-run interval is entirely covered by the solid union.
    No body height, center-only sample, or inferred real measurement is used.
    """
    if stair.get('stair') is None:return {'status':'NOT_EVALUABLE','reason':'No parameterized walking tread surfaces'}
    start,end=stair['stair']['start'],stair['stair']['end']
    moved=[i for i in [0,1] if abs(end[i]-start[i])>tol]
    if len(moved)!=1:return {'status':'NOT_EVALUABLE','reason':'Unsupported transformed run direction'}
    run=moved[0];across=1-run;stripes=[];partial=[]
    for index,tread in enumerate(stair['boxes']):
        top=tread['max'][2];rectangles=[]
        for component,solid in enumerate(other['boxes']):
            if solid['min'][2]>top+tol or solid['max'][2]<=top+tol:continue
            r0=max(tread['min'][run],solid['min'][run]);r1=min(tread['max'][run],solid['max'][run])
            a0=max(tread['min'][across],solid['min'][across]);a1=min(tread['max'][across],solid['max'][across])
            if r1-r0>tol and a1-a0>tol:rectangles.append((r0,r1,a0,a1,component,solid['max'][2]))
        if not rectangles:continue
        cuts=sorted({x for r in rectangles for x in r[:2]})
        width=tread['max'][across]-tread['min'][across]
        for lo,hi in zip(cuts,cuts[1:]):
            if hi-lo<=tol:continue
            active=[r for r in rectangles if r[0]<(lo+hi)/2<r[1]]
            intervals=merge_intervals([(r[2],r[3]) for r in active],tol)
            covered=sum(b-a for a,b in intervals)
            row={'tread_index':index,'tread_top_z':top,'run_axis':'XY'[run],
                 'run_interval':[lo,hi],'full_across_interval':[tread['min'][across],tread['max'][across]],
                 'covered_across_intervals':intervals,'covered_width':covered,'tread_width':width,
                 'solid_components':sorted({r[4] for r in active}),
                 'minimum_obstacle_top_z':min(r[5] for r in active)}
            if covered>=width-tol:stripes.append(row)
            elif covered>tol:partial.append(row)
    return {'status':'EVALUATED','full_width_intrusion_stripes':stripes,'partial_width_intrusion_stripes':partial,
            'calculation':'Exact footprint clipping, run-axis breakpoint sweep, and cross-run interval-union coverage',
            'scope':'Free status of the generated tread surfaces only; not complete human motion or alternative-route feasibility'}


def classify_stair_solid_intersection(compiled,world,aid,bid):
    a,b=(compiled['entities'][i] for i in [aid,bid]);tol=compiled['tolerance']
    pairs=occupied_intersection(a['boxes'],b['boxes'],tol)
    row={'check':'stair_solid_intersection','entity_ids':[aid,bid],'occupied_volume_intersects':bool(pairs),
         'overlap_pairs':pairs,'hard_violation':False,'classification':'NO_OCCUPIED_INTERSECTION'}
    if a['kind']=='staircase' and b['kind']=='staircase':
        known=[a['owner'],b['owner']]
        owner_separation=all(o not in [None,'UNKNOWN','unknown'] for o in known) and known[0]!=known[1]
        disjoint_claims=[]
        for relation in world.get('relations',[]):
            rr=[resolve(world,x) for x in relation.get('args',[])]
            if relation.get('status','ACTIVE')=='ACTIVE' and relation.get('predicate')=='disjoint' and set(rr)=={aid,bid} and relation.get('value',True) in [True,'TRUE']:
                disjoint_claims.append(relation.get('id'))
        if pairs:
            forbidden=owner_separation or bool(disjoint_claims)
            row.update(classification='FORBIDDEN_STAIR_STAIR_INTERSECTION' if forbidden else 'JOINT_OR_UNSPECIFIED',hard_violation=forbidden,
                       disjoint_relation_ids=disjoint_claims,different_known_owners=owner_separation,
                       scope='Explicit disjointness/household separation is required; IDs alone do not forbid all overlap')
        return row
    stair,other=(a,b) if a['kind']=='staircase' else (b,a)
    surface=walking_surface_intrusions(stair,other,tol);row['walking_surface']=surface
    full=surface.get('full_width_intrusion_stripes',[])
    partial=surface.get('partial_width_intrusion_stripes',[])
    if full:
        row.update(classification='ABOVE_WALK_SURFACE_INTRUSION',hard_violation=True,
                   scope='An immediately-above solid covers the entire generated tread width over a positive run interval; not a claim about every possible real route')
    elif pairs:
        row.update(classification='JOINT_OR_UNSPECIFIED',
                   detail='Partial edge embedding' if partial else 'Underface/support contact or intersection without a full-width surface obstruction',
                   scope='Numeric intersection retained; joint permissions/complete clearance are not specified, so no hard physical-failure inference')
    return row


def verify_world(world):
    compiled=compile_world(world);checks=[];violations=[];unknown=[]
    for issue in compiled['issues']:
        if issue['status']=='VIOLATION':violations.append({'check':'definite_compiler_geometry_violation','detail':issue})
    for eid,e in compiled['entities'].items():
        if e['kind']=='staircase':r=stair_connection(compiled,eid)
        elif e['kind']=='window_opening':
            rooms=e['raw'].get('room_ids',[])
            r=window_host(compiled,eid,rooms[0]) if len(rooms)==1 else answer('UNKNOWN','NOT_EVALUABLE',reason='Window needs exactlyone declared room')
        elif e['kind']=='door_opening':r=door_connection(compiled,eid)
        else:continue
        row={'check':'interface_geometry','entity_id':eid,'result':r};checks.append(row)
        if r['status']=='DETERMINATE' and r['value'] is False:violations.append(row)
        elif r['status']!='DETERMINATE':unknown.append(row)
    # Retain all numeric intersections, but do not equate every material joint
    # with a forbidden collision. Evaluate the walking-surface condition apart.
    solid=[(eid,e) for eid,e in compiled['entities'].items() if e['kind'] in SOLID_KINDS and e['geometry_status']=='EXECUTABLE']
    for (aid,a),(bid,b) in combinations(solid,2):
        if a['kind']!='staircase' and b['kind']!='staircase':continue
        row=classify_stair_solid_intersection(compiled,world,aid,bid)
        checks.append(row)
        if row['hard_violation']:violations.append(row)
        elif row['classification']=='JOINT_OR_UNSPECIFIED':unknown.append(row)
    claims=[]
    for relation in world.get('relations',[]):
        if relation.get('status','ACTIVE')!='ACTIVE':continue
        pred=relation.get('predicate');q={'predicate':pred,'args':relation.get('args',[])}
        if 'plane' in relation:q['plane']=relation['plane']
        if 'level_z' in relation:q['level_z']=relation['level_z']
        if 'floor_z' in relation:q['floor_z']=relation['floor_z']
        actual=evaluate_query(compiled,world,q);declared=relation.get('value',True)
        if declared=='TRUE':declared=True
        elif declared=='FALSE':declared=False
        row={'relation_id':relation.get('id'),'predicate':pred,'declared':declared,'derived':actual,
             'agreement':actual['value']==declared if actual['status']=='DETERMINATE' else None}
        claims.append(row)
        if row['agreement'] is False:violations.append({'check':'declared_vs_geometry','detail':row})
        elif row['agreement'] is None:unknown.append({'check':'declared_vs_geometry','detail':row})
    return {'execution_status':compiled['status'],'status':'VIOLATION' if violations else 'NOT_EVALUABLE' if compiled['status']!='EXECUTABLE' or unknown else 'PASS_DECLARED_FRAGMENT',
            'checks':checks,'violations':violations,'not_evaluable':unknown,'compiler_issues':compiled['issues'],
            'derived_graph':derived_graph(compiled),'claims':claims,
            'scope':'Geometry instrumentv3: local aperture normals, exposed union boundary coverage, qualified surface intrusions and typed interfaces; not full structural engineering or human navigation'}


# Evaluation policy copied byte-for-byte in substance from evaluator 2.1.0.
ARITHMETIC_TOLERANCE_METERS = 1e-6
ARITHMETIC_TOLERANCE_DECLARED_UNITS = 1e-6
METERS_PER_UNIT = {
    'm': 1.0, 'meter': 1.0, 'meters': 1.0,
    'ft': 0.3048, 'foot': 0.3048, 'feet': 0.3048,
    'in': 0.0254, 'inch': 0.0254, 'inches': 0.0254,
}


def apply_evaluation_policy(world):
    if not isinstance(world, dict):
        return deepcopy(world), {'status': 'NOT_EVALUABLE', 'reason': 'No world object'}
    evaluated = deepcopy(world)
    units = world.get('units')
    raw_label = units.get('length') if isinstance(units, dict) else units
    label = raw_label.strip().lower() if isinstance(raw_label, str) else None
    meters_per_unit = METERS_PER_UNIT.get(label)
    physical = meters_per_unit is not None
    tolerance = (ARITHMETIC_TOLERANCE_METERS / meters_per_unit
                 if physical else ARITHMETIC_TOLERANCE_DECLARED_UNITS)
    policy = {
        'geometry_tolerance': tolerance,
        'policy_origin': 'FROZEN_STRUCTURAL_ARITHMETIC_POLICY_V2',
    }
    original = deepcopy(evaluated.get('verification_policy'))
    evaluated['verification_policy'] = policy
    return evaluated, {
        'status': 'APPLIED',
        'policy_version': '2',
        'unit_label': label,
        'physical_unit_recognized': physical,
        'meters_per_declared_unit': meters_per_unit,
        'tolerance_basis': ('ONE_MICROMETRE_CONVERTED_TO_DECLARED_UNIT'
                            if physical else 'ONE_MILLIONTH_OF_DECLARED_COORDINATE_UNIT'),
        'physical_scale_status': ('DECLARED_PHYSICAL_UNIT' if physical
                                   else 'NO_PHYSICAL_SCALE_ASSUMED'),
        'original_model_policy': original,
        'applied_policy': policy,
        'scene_composition_used_for_policy': False,
        'comfort_clearance_or_building_code': 'NOT_ASSESSED',
        'actual_checks': 'Only arithmetic tolerance is injected. The compiler and predicates retain positive-size, endpoint, floor, host and occupied-geometry checks.',
        'scope': 'Structural geometry and declared interface incidence; no human traversability, minimum usable width, comfortable riser, safety or building-code claim.',
    }


# v4 overrides. Ancestor functions above remain as a traceable implementation
# baseline. Python resolves their calls to these revised typed interfaces.
_ancestor_evaluate_query = evaluate_query
_ancestor_verify_world = verify_world
_ancestor_window_host = window_host
_ancestor_compile_world = compile_world


def compile_world(world):
    evaluated, policy = apply_evaluation_policy(world)
    compiled = _ancestor_compile_world(evaluated)
    compiled['evaluation_policy'] = policy
    return compiled


def _xy_chart(boxes):
    return [{'min': [b['min'][0], b['min'][1], 0.],
             'max': [b['max'][0], b['max'][1], 1.]} for b in boxes]


def _chart_component(boxes, point, tol):
    """Area/edge-connected XY component; a single shared corner is excluded."""
    seed = {i for i, b in enumerate(boxes) if point_in_boxes([point[0], point[1], .5], [b], tol)}
    seen = set(seed); pending = list(seed)
    while pending:
        i = pending.pop()
        for j, b in enumerate(boxes):
            if j in seen: continue
            overlap = [min(boxes[i]['max'][k], b['max'][k]) - max(boxes[i]['min'][k], b['min'][k]) for k in (0, 1)]
            if min(overlap) >= -tol and max(overlap) > tol:
                seen.add(j); pending.append(j)
    return [boxes[i] for i in sorted(seen)]


def _positive_chart_incidence(a, b, tol):
    return any(min(overlap) >= -tol and max(overlap) > tol
               for x in a for y in b
               for overlap in [[min(x['max'][k], y['max'][k]) - max(x['min'][k], y['min'][k]) for k in (0, 1)]])


def _surface_at(entity, z, tol):
    """Material top faces at z, not the top of a component bounding envelope."""
    faces = _union_boundary_faces(entity['boxes'], 2, tol)
    return [f['rectangle'] for f in faces if f['side'] == 'max' and abs(f['coordinate'] - z) <= tol]


def _room_floor(room, tol):
    z = room['raw'].get('floor_z')
    if not finite_number(z): return None, []
    if room['kind'] == 'landing':
        return z, _surface_at(room, z, tol)
    # A declared room is a free-space volume. Its floor footprint is its exposed
    # lower boundary at floor_z, not every projected upper-story component.
    faces = _union_boundary_faces(room['boxes'], 2, tol)
    return z, [f['rectangle'] for f in faces if f['side'] == 'min' and abs(f['coordinate'] - z) <= tol]


def _free_floor_charts(compiled, charts, z):
    """Remove material occupying immediately above a floor surface.

    Supports ending at the floor are retained. No body-height envelope or
    clearance is inferred. Aggregate parents are not counted twice.
    """
    tol=compiled['tolerance'];cuts=[];blocking_ids=[]
    parts={p for e in compiled['entities'].values() for p in e['raw'].get('part_ids',[])}
    for eid,ent in compiled['entities'].items():
        if ent['geometry_status']!='EXECUTABLE' or ent['raw'].get('part_ids'):continue
        if ent['kind'] not in SOLID_KINDS and not (ent['kind']=='landing' and eid in parts):continue
        occupied=[b for b in ent['boxes'] if b['min'][2]<=z+tol and b['max'][2]>z+tol]
        if occupied:cuts.extend(_xy_chart(occupied));blocking_ids.append(eid)
    return subtract_union(charts,cuts,tol),blocking_ids


def _landing_room_bridge(compiled, point, landing, room):
    tol = compiled['tolerance']; z, room_floor = _room_floor(room, tol)
    if z is None or not room_floor:
        return None, {'reason': 'Missing or geometrically inconsistent room floor_z'}
    if abs(point[2] - z) > tol:
        return False, {'reason': 'Endpoint and target room floor have different elevations'}
    free_room_floor,blocking_ids=_free_floor_charts(compiled,room_floor,z)
    # Keep only interface geometry incident at this floor. An unrelated upper
    # tile in a box union must not provide an imaginary planar bridge.
    landing_xy = _xy_chart([b for b in landing['boxes'] if b['min'][2]-tol <= z <= b['max'][2]+tol])
    component = _chart_component(landing_xy, point, tol)
    if not component:
        return False, {'reason': 'Stair endpoint is outside the declared landing'}
    supports = list(room_floor); support_ids = []
    for eid, ent in compiled['entities'].items():
        if ent['geometry_status'] != 'EXECUTABLE': continue
        # Room free space supplies its own declared floor. Outside that room,
        # material floor slabs or a material landing top must provide support.
        if ent['kind'] == 'floor_slab' or eid == landing['id']:
            tops = _surface_at(ent, z, tol)
            supports.extend(tops)
            if tops: support_ids.append(eid)
    supported = []
    for a in component:
        for b in supports:
            hit = intersection(a, b, tol)
            if hit: supported.append(hit)
    free_supported,_=_free_floor_charts(compiled,supported,z)
    connected = _chart_component(free_supported, point, tol)
    reaches = _positive_chart_incidence(connected, free_room_floor, tol)
    return bool(connected) and reaches, {
        'endpoint': point, 'floor_z': z,
        'endpoint_inside_landing': True,
        'supported_component_reaches_room': reaches,
        'material_support_entities': sorted(support_ids),
        'floor_level_obstacle_entities':sorted(blocking_ids),
        'scope': 'Continuous supported floor-level route after subtracting immediate-above material; point-only contacts are rejected; no body-height clearance',
    }


def ownership_identity(compiled, ids):
    """Explicit owner_id only. Legacy owner strings are descriptive metadata."""
    owners = [compiled['entities'][i]['raw'].get('owner_id') for i in ids]
    known = [x for x in owners if isinstance(x, str) and x not in ('', 'UNKNOWN', 'unknown')]
    if len(known) != len(owners):
        return {'status': 'UNKNOWN', 'owner_ids': owners, 'basis': 'Explicit owner_id is incomplete; owner descriptions are not identities'}
    return {'status': 'SAME' if len(set(known)) == 1 else 'DIFFERENT', 'owner_ids': owners,
            'basis': 'Explicit owner_id; reported separately from physical connectivity'}


def stair_connection(compiled, stair_id, rooms=None):
    es = compiled['entities']; tol = compiled['tolerance']; s = es.get(stair_id)
    if s is None: return answer('NOT_FOUND', 'NOT_FOUND', reason='Stair missing')
    if s['raw'].get('part_ids'):
        return compound_stair_connection(compiled, stair_id, rooms)
    if s['geometry_status'] != 'EXECUTABLE' or s['stair'] is None:
        return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Executable stair_run required')
    interfaces = s['raw'].get('endpoint_interfaces', s['raw'].get('endpoint_interface_ids', []))
    declared = s['raw'].get('connects_rooms', [])
    if len(interfaces) != 2 or len(declared) != 2:
        return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Two room and landing endpoint identities required')
    requested = rooms or declared
    missing = _need(compiled, [stair_id] + interfaces + declared + list(requested))
    if missing: return missing
    for rid in declared:
        if es[rid]['kind'] not in SPACE_KINDS | {'landing'}:
            return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Declared endpoint host is not a room/corridor/balcony')
    floor_requested = set(requested) != set(declared)
    if floor_requested:
        if not all(es[r]['kind'] == 'floor_slab' for r in requested):
            return answer('FALSE', reason='Requested rooms differ from declared endpoint rooms')
        hosts = [es[r]['raw'].get('host_id') for r in declared]
        if len(set(hosts)) != 2 or set(hosts) != set(requested):
            return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Explicit room-to-floor host identities do not resolve requested slabs')
    tests = []; unresolved = False
    for point, iid, rid in zip([s['stair']['start'], s['stair']['end']], interfaces, declared):
        landing, room = es[iid], es[rid]
        if landing['kind'] != 'landing':
            return answer('FALSE', reason='Endpoint interface is not a landing', entity_ids=[iid])
        host = landing.get('host_id')
        if iid == rid and room['kind'] == 'landing':
            host_good = True
        elif host in (None, 'UNKNOWN', 'unknown'):
            unresolved = True; host_good = None
        else: host_good = host == rid
        bridge, proof = _landing_room_bridge(compiled, point, landing, room)
        if bridge is None: unresolved = True
        test = {'endpoint': point, 'interface': iid, 'room': rid,
                'landing_host_matches': host_good, 'supported_landing_bridge': bridge, 'bridge_proof': proof}
        if floor_requested:
            slab = es[room['raw']['host_id']]
            surface = _surface_at(slab, point[2], tol)
            test['requested_slab_supports_landing_route'] = _positive_chart_incidence(
                _chart_component(surface, point, tol), _room_floor(room, tol)[1], tol)
        tests.append(test)
    failures = any(t['landing_host_matches'] is False or t['supported_landing_bridge'] is False
                   or t.get('requested_slab_supports_landing_route') is False for t in tests)
    # The physical endpoint bridge does not establish exclusive usage rights.
    return answer('FALSE' if failures else 'UNKNOWN' if unresolved else 'TRUE',
                  'NOT_EVALUABLE' if unresolved and not failures else 'DETERMINATE',
                  entity_ids=[stair_id] + interfaces + declared, endpoint_tests=tests,
                  ownership=ownership_identity(compiled, [stair_id] + declared),
                  calculation='Endpoint-to-room connection through a continuous supported landing component',
                  scope='Structural interface only; ownership permission and full body clearance are separate')


def compound_stair_connection(compiled, stair_id, rooms=None):
    """Finite straight-run/landing assembly; no curved or bounding-box stair."""
    es = compiled['entities']; parent = es[stair_id]; raw = parent['raw']; tol = compiled['tolerance']
    parts = raw.get('part_ids'); declared = raw.get('connects_rooms', []); interfaces = raw.get('endpoint_interfaces', [])
    if not isinstance(parts, list) or not 3 <= len(parts) <= 32 or len(set(parts)) != len(parts):
        return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Compound stair needs 3..32 unique explicit part_ids')
    if len(declared) != 2 or len(set(declared)) != 2 or len(interfaces) != 2:
        return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Compound staircase needs two distinct external rooms and two interfaces')
    missing = _need(compiled, [stair_id] + parts + declared + interfaces + list(rooms or declared))
    if missing: return missing
    if set(rooms or declared) != set(declared):
        return answer('FALSE', reason='Requested endpoint spaces differ from compound endpoints')
    if parent['stair'] is not None or raw.get('geometry', {}).get('type') != 'box_union':
        return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Compound parent is an explicit box_union aggregate, not a single run')
    if any(es[p]['kind'] not in ('staircase', 'landing') or es[p]['raw'].get('part_ids') for p in parts):
        return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Compound supports straight-run leaves and material landings; no nested/curved stairs')
    run_ids = [p for p in parts if es[p]['kind'] == 'staircase']
    if not 2 <= len(run_ids) <= 16 or any(es[p]['stair'] is None for p in run_ids):
        return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Compound needs 2..16 parameterized straight runs')
    for pid in parts:
        part=es[pid]
        if part['kind']=='landing':
            z=part['raw'].get('floor_z')
            exposed_tops=[f['coordinate'] for f in _union_boundary_faces(part['boxes'],2,tol) if f['side']=='max']
            if not finite_number(z) or not exposed_tops or any(abs(top-z)>tol for top in exposed_tops):
                return answer('UNKNOWN','NOT_EVALUABLE',reason='Compound landing parts need explicit floor_z and material boxes with top at that level',landing_id=pid)
    material = [b for p in parts for b in es[p]['boxes']]
    union_matches = contains_union(material, parent['boxes'], tol) and contains_union(parent['boxes'], material, tol)
    if not union_matches:
        return answer('FALSE', entity_ids=[stair_id], reason='Parent occupied union differs from its declared material parts; bounding-box filling is forbidden')
    run_results = {}; edges = []; ports = {}; endpoint_points = {}
    for rid in run_ids:
        run = es[rid]; endpoints = run['raw'].get('connects_rooms', []); ifaces = run['raw'].get('endpoint_interfaces', [])
        result = stair_connection(compiled, rid); run_results[rid] = result
        if result['status'] != 'DETERMINATE' or result['value'] is not True:
            return answer('FALSE' if result['value'] is False else 'UNKNOWN',
                          'DETERMINATE' if result['value'] is False else 'NOT_EVALUABLE',
                          reason='At least one straight-run endpoint/support check failed or is unresolved', run_results=run_results)
        if len(set(endpoints)) != 2:
            return answer('FALSE', reason='A leaf run cannot connect a room/landing to itself')
        if any(e not in declared and (e not in parts or es[e]['kind'] != 'landing') for e in endpoints):
            return answer('FALSE', reason='An intermediate chain endpoint must be an explicitly listed landing')
        if any(i not in parts for i in ifaces):
            return answer('FALSE', reason='All physical endpoint landings must be explicit material parts')
        for endpoint, iface, point in zip(endpoints, ifaces, [run['stair']['start'], run['stair']['end']]):
            ports.setdefault(endpoint, set()).add(iface)
            endpoint_points.setdefault(endpoint, []).append(point)
        edges.append((endpoints[0], endpoints[1], rid))
    adjacency = {}
    for a, b, rid in edges:
        adjacency.setdefault(a, []).append((b, rid)); adjacency.setdefault(b, []).append((a, rid))
    if any(len(adjacency.get(d, [])) != 1 for d in declared) or any(len(v) != 2 for k, v in adjacency.items() if k not in declared):
        return answer('FALSE', reason='Declared runs do not form one nonbranching endpoint-to-endpoint chain', chain_edges=edges)
    seen = {declared[0]}; pending = [declared[0]]
    while pending:
        for other, rid in adjacency.get(pending.pop(), []):
            if other not in seen: seen.add(other); pending.append(other)
    if declared[1] not in seen or len(seen) != len(adjacency) or len(edges) != len(seen)-1:
        return answer('FALSE', reason='Disconnected run, unused branch or cycle in compound chain', chain_edges=edges)
    if any(ports.get(room) != {interface} for room, interface in zip(declared, interfaces)):
        return answer('FALSE', reason='Compound external landing identities disagree with leaf endpoints')
    for node in seen-set(declared):
        points=endpoint_points[node];z,surfaces=_room_floor(es[node],tol)
        if z is None or len(points)!=2:
            return answer('UNKNOWN','NOT_EVALUABLE',reason='Intermediate landing support surface is unresolved')
        free_surfaces,_=_free_floor_charts(compiled,surfaces,z)
        component=_chart_component(free_surfaces,points[0],tol)
        if not point_in_boxes([points[1][0],points[1][1],.5],component,tol):
            return answer('FALSE',reason='Incoming and outgoing runs land on disconnected components of the same landing ID',landing_id=node)
    collisions = []
    for a, b in combinations(run_ids, 2):
        for x, y in ((a, b), (b, a)):
            result = walking_surface_intrusions(es[x], es[y], tol)
            if result.get('full_width_intrusion_stripes'):
                collisions.append({'walked_run': x, 'obstructing_run': y, 'proof': result})
    if collisions:
        return answer('FALSE', reason='A leaf run blocks the walking surface of another run', collisions=collisions)
    return answer('TRUE', entity_ids=[stair_id] + parts, chain_edges=edges, run_results=run_results,
                  material_union_matches=True, calculation='Exact part-union equality and continuous supported straight-run/landing chain',
                  scope='Finite rectilinear multi-run structural staircase; not curved stairs or a full-body path proof')


def _portal_room_sides(opening, wall, room, tol):
    faces = {a: _union_boundary_faces(room['boxes'], a, tol) for a in (0, 1)}
    wall_faces = {a: _union_boundary_faces(wall['raw_boxes'], a, tol) for a in (0, 1)}
    result = []
    for component in _opening_components(opening['boxes'], tol):
        rows = []
        for aperture in component['boxes']:
            matches = []
            for axis in _aperture_normal_axes(aperture, wall, tol, wall_faces):
                for side in ('min', 'max'):
                    coordinates = _covered_face_planes(aperture, axis, faces[axis], tol, side)
                    matches.extend({'axis': axis, 'side': side, 'coordinate': x} for x in coordinates)
            rows.append(matches)
        result.append(rows)
    return result


def _resolve_opening_wall(compiled, opening):
    """Virtual union of explicitly named wall hosts, without rewriting input."""
    ids=list(opening['raw'].get('host_ids',[]))
    primary=opening.get('host_id')
    if primary not in (None,'UNKNOWN','unknown') and primary not in ids:ids.append(primary)
    ids=list(dict.fromkeys(ids))
    if not ids:return None,answer('UNKNOWN','NOT_EVALUABLE',reason='Explicit wall host identity missing')
    missing=_need(compiled,ids)
    if missing:return None,missing
    es=compiled['entities'];hosts=[es[i] for i in ids];tol=compiled['tolerance']
    if any(e['kind']!='wall' for e in hosts):
        return None,answer('FALSE',reason='An explicitly named opening host is not a wall',host_ids=ids)
    intersects=[e for e in hosts if occupied_intersection(e['raw_boxes'],opening['boxes'],tol)]
    registered=bool(intersects) and all(opening['id'] in e['raw'].get('opening_ids',[]) for e in intersects)
    wall={'id':ids[0] if len(ids)==1 else 'HOST_UNION('+','.join(sorted(ids))+')',
          'kind':'wall','host_id':None,'owner':'UNKNOWN','geometry_status':'EXECUTABLE',
          'raw_boxes':[b for e in hosts for b in e['raw_boxes']],
          'boxes':[b for e in hosts for b in e['boxes']],
          'raw':{'opening_ids':[opening['id']] if registered else []},
          'host_entity_ids':ids}
    return wall,None


def _portal_blockage(compiled, opening, ignore=()):
    """Actual opening volume occupied by other material; not body clearance."""
    tol = compiled['tolerance']; cuts = []
    for eid, ent in compiled['entities'].items():
        if eid in ignore or ent['geometry_status'] != 'EXECUTABLE' or ent['kind'] not in SOLID_KINDS:
            continue
        for hit in occupied_intersection(opening['boxes'], ent['boxes'], tol):
            cuts.append({'entity_id': eid, 'intersection': hit['intersection']})
    remaining = subtract_union(opening['boxes'], [r['intersection'] for r in cuts], tol)
    return {'obstructions': cuts, 'remaining_open_volume': union_volume(remaining, tol),
            'completely_filled': bool(opening['boxes']) and not remaining,
            'partially_occupied': bool(cuts) and bool(remaining),
            'scope': 'Declared aperture volume occupancy, not a human-sized path guarantee'}


def door_connection(compiled, door_id):
    es = compiled['entities']; tol = compiled['tolerance']; d = es.get(door_id)
    if not d: return answer('NOT_FOUND', 'NOT_FOUND')
    if d['kind'] not in ('door_opening','opening'): return answer('FALSE', reason='Entity is not a door or ordinary passage opening')
    rooms = d['raw'].get('room_ids', [])
    if len(rooms) != 2 or len(set(rooms)) != 2:
        return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Two distinct room IDs required')
    missing = _need(compiled, [door_id] + rooms)
    if missing: return missing
    if any(es[r]['kind'] not in SPACE_KINDS for r in rooms):
        return answer('FALSE', reason='Door endpoint is not a spatial room')
    wall,error=_resolve_opening_wall(compiled,d)
    if error:return error
    floors = [_room_floor(es[r], tol) for r in rooms]
    if any(z is None or not f for z, f in floors):
        return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Room floor_z missing or inconsistent')
    sides = [_portal_room_sides(d, wall, es[r], tol) for r in rooms]
    opposite = True; missing_sides = False
    for c in range(len(sides[0])):
        for p in range(len(sides[0][c])):
            left, right = sides[0][c][p], sides[1][c][p]
            if not left or not right: missing_sides = True; opposite = False; continue
            match = any(a['axis'] == b['axis'] and a['side'] != b['side']
                        and ((a['side'] == 'max' and a['coordinate'] <= b['coordinate'] + tol)
                             or (b['side'] == 'max' and b['coordinate'] <= a['coordinate'] + tol))
                        for a in left for b in right)
            opposite = opposite and match
    checks = {'same_floor': abs(floors[0][0]-floors[1][0]) <= tol,
              'fits_wall': aperture_fits_wall(d, wall, tol),
              'opening_cut': door_id in wall['raw'].get('opening_ids', []),
              'opposite_exposed_room_sides': opposite,
              'bottom_at_floor': all(any(abs(b['min'][2]-floors[0][0]) <= tol for b in c['boxes'])
                                     for c in _opening_components(d['boxes'], tol))}
    blockage = _portal_blockage(compiled, d, ignore=(door_id,))
    checks['not_completely_filled'] = not blockage['completely_filled']
    # A partial blockage may leave a passage, but no unsupported bounding-box
    # width assumption is used to assert that it does.
    definite_failure = not all(checks.values())
    result = 'FALSE' if definite_failure else 'UNKNOWN' if blockage['partially_occupied'] else 'TRUE'
    return answer(result, 'NOT_EVALUABLE' if result == 'UNKNOWN' else 'DETERMINATE',
                  entity_ids=[door_id, wall['id']] + rooms, checks=checks,
                  room_side_proofs=sides, blockage=blockage,
                  reason='Partial obstruction requires an explicit usable-path profile' if result == 'UNKNOWN' else '',
                  calculation='Registered wall cut with opposite exposed room boundaries at a common floor',
                  scope='Positive aperture structural connection; no complete human-motion assertion')


def window_host(compiled, window_id, room_id):
    missing = _need(compiled, [window_id, room_id])
    if missing: return missing
    es = compiled['entities']; tol = compiled['tolerance']; w, room = es[window_id], es[room_id]
    if w['kind'] != 'window_opening' or room['kind'] not in SPACE_KINDS:
        return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Window opening and spatial room required')
    wall,error=_resolve_opening_wall(compiled,w)
    if error:return error
    sides = _portal_room_sides(w, wall, room, tol)
    checks = {'fits_wall': aperture_fits_wall(w, wall, tol),
              'registered_cut': window_id in wall['raw'].get('opening_ids', []),
              'exposed_room_boundary': bool(sides) and all(bool(patch) for component in sides for patch in component)}
    declared_rooms = w['raw'].get('room_ids', [])
    if declared_rooms: checks['window_room_identity'] = room_id in declared_rooms
    if not all(checks.values()):
        return answer('FALSE', entity_ids=[window_id, wall['id'], room_id], checks=checks, room_side_proofs=sides)
    if not declared_rooms:
        return answer('UNKNOWN', 'NOT_EVALUABLE', checks=checks, reason='Window room identity is not declared')
    return answer('TRUE', entity_ids=[window_id, wall['id'], room_id], checks=checks, room_side_proofs=sides,
                  wall_container_metadata=wall.get('host_id'), owner_description_used=False,
                  calculation='Window wall cut and local exposed room boundary; shared wall container does not override local attachment')


def derived_graph(compiled):
    edges = []; unknown = []
    for eid, ent in compiled['entities'].items():
        if ent['kind'] == 'staircase':
            result = stair_connection(compiled, eid); rooms = ent['raw'].get('connects_rooms', [])
        elif ent['kind'] == 'door_opening' or (ent['kind']=='opening' and len(ent['raw'].get('room_ids',[]))==2):
            result = door_connection(compiled, eid); rooms = ent['raw'].get('room_ids', [])
        else: continue
        if result['status'] == 'DETERMINATE' and result['value'] is True and len(rooms) == 2:
            edges.append({'a': rooms[0], 'b': rooms[1], 'interface': eid,
                          'owner': ent['raw'].get('owner_id', 'UNKNOWN'), 'proof': result['proof']})
        elif result['status'] != 'DETERMINATE': unknown.append({'interface': eid, 'result': result})
    return {'edges': edges, 'unknown_interfaces': unknown,
            'scope': 'Supported structural interface graph; permission requires explicit owner_id/access contract'}


def evaluate_query(compiled, world, q):
    pred = q.get('predicate'); raw_args = q.get('args', [])
    args = [resolve(world, x) for x in raw_args]; es = compiled['entities']; tol = compiled['tolerance']
    if pred in ('identity_assignment', 'different_physical_entity'):
        observations = {o['id']: o for o in world.get('observations', []) if isinstance(o, dict) and 'id' in o}
        assigned = []
        for arg in args:
            ids = observations[arg].get('entity_ids', []) if arg in observations else [arg]
            if len(ids) != 1 or ids[0] not in es:
                return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Observation has no unique declared entity assignment')
            assigned.append(ids[0])
        if len(assigned) != 2: return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Two observations/entities required')
        if pred == 'identity_assignment':
            return answer(assigned[0] == assigned[1], entity_ids=assigned,
                          calculation='Read declared observation-to-instance assignment; physical correctness requires external reference',
                          scope='Generated assignment equality, not an independent physical identity proof')
        if assigned[0] == assigned[1]: return answer('FALSE', entity_ids=assigned)
        distinct = any(r.get('status') == 'ACTIVE' and r.get('predicate') in ('different_entity', 'different_physical_entity')
                       and set(resolve(world, x) for x in r.get('args', [])) == set(assigned)
                       and r.get('value', True) in (True, 'TRUE') for r in world.get('relations', []))
        distinct = distinct or any(set(pair) == set(assigned) for pair in world.get('distinct_instance_ids', []) if isinstance(pair, list))
        return answer('TRUE', entity_ids=assigned, calculation='Explicit distinct-instance assertion') if distinct else answer('UNKNOWN', 'NOT_EVALUABLE', reason='Distinct strings alone do not prove physical inequality')
    if pred == 'same_floor':
        if len(args) != 2: return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Two spaces/floors required')
        missing = _need(compiled, args)
        if missing: return missing
        levels = []
        for eid in args:
            ent = es[eid]
            if ent['kind'] in SPACE_KINDS:
                z, surfaces = _room_floor(ent, tol)
                if z is None or not surfaces: return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Room floor missing/inconsistent')
            elif ent['kind'] == 'floor_slab':
                levels_found = {f['coordinate'] for f in _union_boundary_faces(ent['boxes'], 2, tol) if f['side'] == 'max'}
                if len(levels_found) != 1: return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Slab has multiple top elevations')
                z = next(iter(levels_found))
            else: return answer('UNKNOWN', 'NOT_EVALUABLE', reason='same_floor requires spaces or floor slabs')
            levels.append(z)
        return answer(abs(levels[0]-levels[1]) <= tol, geometric_floor_surfaces=levels)
    if pred in ('door_host', 'host_attached'):
        if len(args) != 2: return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Child and host required')
        missing = _need(compiled, args)
        if missing: return missing
        child, host = [es[a] for a in args]
        if pred == 'door_host' and child['kind'] != 'door_opening': return answer('FALSE', reason='Not a door opening')
        if pred == 'door_host' and host['kind'] in SPACE_KINDS:
            wall,error=_resolve_opening_wall(compiled,child)
            if error:return error
            sides = _portal_room_sides(child, wall, host, tol)
            checks = {'typed_wall_host': wall['kind'] == 'wall',
                      'registered_cut': args[0] in wall['raw'].get('opening_ids', []),
                      'fits_wall': aperture_fits_wall(child, wall, tol),
                      'exposed_room_boundary': bool(sides) and all(bool(patch) for component in sides for patch in component)}
            declared = child['raw'].get('room_ids', [])
            if declared: checks['declared_room_identity'] = args[1] in declared
            if not all(checks.values()): return answer('FALSE', entity_ids=args, checks=checks)
            if not declared: return answer('UNKNOWN', 'NOT_EVALUABLE', checks=checks, reason='Door room identity missing')
            return answer('TRUE', entity_ids=args, checks=checks, room_side_proofs=sides,
                          scope='Door-to-room host incidence; physical passage is connected_by')
        if child['kind'] in ('door_opening', 'window_opening','opening'):
            wall,error=_resolve_opening_wall(compiled,child)
            if error:return error
            all_hosts=wall['host_entity_ids']
            checks = {'typed_wall_host': host['kind'] == 'wall',
                      'explicit_host_matches': args[1] in all_hosts,
                      'registered_cut': args[0] in host['raw'].get('opening_ids', []),
                      'positive_incidence_with_named_host':bool(occupied_intersection(child['boxes'],host['raw_boxes'],tol)),
                      'fits_host_union': host['kind'] == 'wall' and aperture_fits_wall(child, wall, tol)}
            return answer(all(checks.values()), checks=checks, entity_ids=args)
        return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Supported host_attached objects are door/window openings')
    if pred in ('owner', 'owner_identity') or (pred == 'belongs_to' and (len(args) != 2 or args[1] not in es)):
        if not args or args[0] not in es: return answer('NOT_FOUND', 'NOT_FOUND')
        identity = es[args[0]]['raw'].get('owner_id')
        if identity in (None, '', 'UNKNOWN', 'unknown'):
            return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Explicit owner_id is absent; owner is descriptive metadata')
        return answer(identity if len(args) == 1 else identity == raw_args[1],
                      calculation='Explicit owner identity; independent of physical connectivity')
    if pred == 'belongs_to' and len(args) == 2 and all(a in es for a in args):
        child, host = [es[a] for a in args]
        if child['kind'] == 'window_opening' and host['kind'] in SPACE_KINDS:
            return window_host(compiled, *args)
        if host['kind'] not in SPACE_KINDS or child['kind'] in NONPHYSICAL_KINDS:
            return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Physical attachment target sort unsupported')
        if child.get('host_id') in (None, 'UNKNOWN', 'unknown'):
            return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Explicit physical host missing')
        missing = _need(compiled, args)
        if missing: return missing
        touches = any(min(overlap) >= -tol and sum(v > tol for v in overlap) >= 2
                      for a in child['boxes'] for b in host['boxes']
                      for overlap in [[min(a['max'][i], b['max'][i])-max(a['min'][i], b['min'][i]) for i in range(3)]])
        return answer(child.get('host_id') == args[1] and touches, entity_ids=args,
                      calculation='Explicit physical host and positive-area incidence; owner descriptions excluded')
    if pred == 'interface_reachable' and q.get('policy', 'ALL') != 'ALL':
        return answer('UNKNOWN', 'NOT_EVALUABLE', reason='Non-ALL reachability requires separately registered access-permission semantics')
    if pred=='connected_by' and len(args)==3 and args[2] in es and es[args[2]]['kind']=='opening':
        if set(es[args[2]]['raw'].get('room_ids',[]))!=set(args[:2]):
            return answer('FALSE',reason='Passage endpoints differ from requested rooms')
        return door_connection(compiled,args[2])
    if pred=='connected_by' and len(args)==3 and args[2] in es and es[args[2]]['kind'] in ('wall','obstacle'):
        missing=_need(compiled,args)
        if missing:return missing
        if any(es[r]['kind'] not in SPACE_KINDS for r in args[:2]):
            return answer('UNKNOWN','NOT_EVALUABLE',reason='Blocked-interface endpoints must be spatial rooms')
        material=es[args[2]];floors=[_room_floor(es[r],tol) for r in args[:2]]
        if any(z is None or not f for z,f in floors) or abs(floors[0][0]-floors[1][0])>tol:
            return answer('UNKNOWN','NOT_EVALUABLE',reason='Blocked site does not establish a common floor')
        z=floors[0][0]
        at_floor=[b for b in material['boxes'] if b['min'][2]<=z+tol and b['max'][2]>z+tol]
        if material['raw'].get('opening_ids') or not at_floor:
            return answer('UNKNOWN','NOT_EVALUABLE',reason='Uncut floor-level material barrier not established')
        top=min(b['max'][2] for b in at_floor)
        slice_boxes=[{'min':[b['min'][0],b['min'][1],z],'max':[b['max'][0],b['max'][1],top]} for b in at_floor]
        floor_slice=dict(material,boxes=slice_boxes,raw_boxes=slice_boxes)
        sides=[_portal_room_sides(floor_slice,floor_slice,es[r],tol) for r in args[:2]]
        opposite=bool(sides[0]) and all(any(a['axis']==b['axis'] and a['side']!=b['side']
                   and ((a['side']=='max' and a['coordinate']<=b['coordinate']+tol)
                        or (b['side']=='max' and b['coordinate']<=a['coordinate']+tol))
                   for a in left for b in right)
                   for ca,cb in zip(sides[0],sides[1]) for left,right in zip(ca,cb))
        if opposite:
            return answer('FALSE',entity_ids=args,room_side_proofs=sides,
                          calculation='Named interface is an uncut solid barrier at the shared floor between opposite room boundaries',
                          scope='No floor-level structural passage through this named barrier; not global room non-reachability')
        return answer('UNKNOWN','NOT_EVALUABLE',reason='The named material has not been established as a barrier between both requested rooms')
    return _ancestor_evaluate_query(compiled, world, q)


def classify_stair_solid_intersection(compiled, world, aid, bid):
    a, b = [compiled['entities'][i] for i in (aid, bid)]; tol = compiled['tolerance']
    pairs = occupied_intersection(a['boxes'], b['boxes'], tol)
    row = {'check': 'stair_solid_intersection', 'entity_ids': [aid, bid],
           'occupied_volume_intersects': bool(pairs), 'overlap_pairs': pairs,
           'hard_violation': False, 'classification': 'NO_OCCUPIED_INTERSECTION'}
    if a['kind'] == 'staircase' and b['kind'] == 'staircase':
        # Exclusive usage does not itself imply disjoint material. Disjointness
        # is a separate physical assertion, never inferred from owner strings.
        claims = [r.get('id') for r in world.get('relations', [])
                  if r.get('status') == 'ACTIVE' and r.get('predicate') == 'disjoint'
                  and set(resolve(world, x) for x in r.get('args', [])) == {aid, bid}
                  and r.get('value', True) in (True, 'TRUE')]
        if pairs:
            row.update(classification='FORBIDDEN_STAIR_STAIR_INTERSECTION' if claims else 'JOINT_OR_UNSPECIFIED',
                       hard_violation=bool(claims), disjoint_relation_ids=claims,
                       ownership=ownership_identity(compiled, [aid, bid]))
        return row
    stair, other = (a, b) if a['kind'] == 'staircase' else (b, a)
    surface = walking_surface_intrusions(stair, other, tol); row['walking_surface'] = surface
    if surface.get('full_width_intrusion_stripes'):
        row.update(classification='ABOVE_WALK_SURFACE_INTRUSION', hard_violation=True)
    elif pairs:
        row.update(classification='JOINT_OR_UNSPECIFIED',
                   detail='Material overlap retained; a full-width blocked tread is not established')
    return row


def verify_world(world):
    compiled = compile_world(world); checks = []; violations = []; unknown = []
    for issue in compiled['issues']:
        if issue['status'] == 'VIOLATION': violations.append({'check':'definite_compiler_geometry_violation','detail':issue})
    for eid, ent in compiled['entities'].items():
        if ent['kind'] == 'staircase': result = stair_connection(compiled,eid)
        elif ent['kind'] == 'window_opening':
            rooms = ent['raw'].get('room_ids',[])
            result = window_host(compiled,eid,rooms[0]) if len(rooms)==1 else answer('UNKNOWN','NOT_EVALUABLE',reason='Window needs a unique declared room for full-fragment verification')
        elif ent['kind'] == 'door_opening' or (ent['kind']=='opening' and len(ent['raw'].get('room_ids',[]))==2): result = door_connection(compiled,eid)
        else: continue
        row = {'check':'interface_geometry','entity_id':eid,'result':result};checks.append(row)
        if result['status']=='DETERMINATE' and result['value'] is False: violations.append(row)
        elif result['status']!='DETERMINATE': unknown.append(row)
    # Aggregate parents are references to material already present in leaf
    # parts. They must never collide with those same parts a second time.
    es=compiled['entities'];assembly_parts={p for e in es.values() for p in e['raw'].get('part_ids',[])}
    solids=[(eid,e) for eid,e in es.items() if e['geometry_status']=='EXECUTABLE' and not e['raw'].get('part_ids')
            and (e['kind'] in SOLID_KINDS or (e['kind']=='landing' and eid in assembly_parts))]
    for (aid,a),(bid,b) in combinations(solids,2):
        if a['kind']!='staircase' and b['kind']!='staircase':continue
        row=classify_stair_solid_intersection(compiled,world,aid,bid);checks.append(row)
        stair,other=(a,b) if a['kind']=='staircase' else (b,a)
        if (row['classification']=='JOINT_OR_UNSPECIFIED' and other['kind']=='landing'
                and other['id'] in stair['raw'].get('endpoint_interfaces',[])):
            row['classification']='DECLARED_ENDPOINT_SUPPORT_JOINT'
        if row['hard_violation']:violations.append(row)
        elif row['classification']=='JOINT_OR_UNSPECIFIED':unknown.append(row)
    # Full-width obstruction is a property of the union of material, rather
    # than whichever JSON entity happens to contain each half of a wall.
    for sid,stair in solids:
        if stair.get('stair') is None: continue
        boxes=[b for eid,e in solids if eid!=sid for b in e['boxes']]
        if not boxes: continue
        surface=walking_surface_intrusions(stair,{'boxes':boxes},compiled['tolerance'])
        row={'check':'stair_material_union_surface','entity_id':sid,'walking_surface':surface,
             'hard_violation':bool(surface.get('full_width_intrusion_stripes'))}
        checks.append(row)
        if row['hard_violation']:violations.append(row)
    claims=[]
    for relation in world.get('relations',[]):
        if relation.get('status','ACTIVE')!='ACTIVE':continue
        query={k:relation[k] for k in ('predicate','args','plane','level_z','floor_z','policy') if k in relation}
        actual=evaluate_query(compiled,world,query);declared=relation.get('value',True)
        if declared=='TRUE':declared=True
        elif declared=='FALSE':declared=False
        row={'relation_id':relation.get('id'),'predicate':relation.get('predicate'),'declared':declared,
             'derived':actual,'agreement':actual['value']==declared if actual['status']=='DETERMINATE' else None};claims.append(row)
        if row['agreement'] is False: violations.append({'check':'declared_vs_geometry','detail':row})
        elif row['agreement'] is None:unknown.append({'check':'declared_vs_geometry','detail':row})
    return {'execution_status':compiled['status'],
            'status':'VIOLATION' if violations else 'NOT_EVALUABLE' if compiled['status']!='EXECUTABLE' or unknown else 'PASS_DECLARED_FRAGMENT',
            'checks':checks,'violations':violations,'not_evaluable':unknown,'compiler_issues':compiled['issues'],
            'derived_graph':derived_graph(compiled),'claims':claims,
            'scope':('Geometry instrument v4: supported landing bridges, finite multi-run assemblies, explicit identity semantics, '
                     'union-boundary door/window incidence and aperture/tread occupation; not full human navigation or structural engineering')}


def assess(world, case):
    """Stable organizer API. Original world is never rewritten or repaired."""
    schema_validation = validate_schema(world)
    evaluated, policy = apply_evaluation_policy(world)
    compiled = compile_world(evaluated)
    readouts = {}
    for query in case.get('queries', []):
        try: readouts[query['id']] = evaluate_query(compiled, evaluated, query)
        except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
            readouts[query['id']] = answer('UNKNOWN', 'NOT_EVALUABLE', reason=type(exc).__name__+': '+str(exc))
    verification = verify_world(evaluated)
    roles = case.get('required_roles', [])
    required_geo = set(case.get('geometric_required_roles', roles))
    coverage = [{'role': role, 'entity_id': resolve(evaluated, role),
                 'present': resolve(evaluated, role) in compiled['entities'],
                 'geometry_required': role in required_geo,
                 'executable_geometry': compiled['entities'].get(resolve(evaluated, role), {}).get('geometry_status') == 'EXECUTABLE'}
                for role in roles]
    relevant={resolve(evaluated,role) for role in required_geo}
    pending=list(relevant)
    while pending:
        ent=compiled['entities'].get(pending.pop(),{})
        raw=ent.get('raw',{})
        dependencies=[raw.get('host_id')]+[p for key in ('host_ids','part_ids','connects_rooms','endpoint_interfaces','room_ids','opening_ids') for p in raw.get(key,[])]
        for dep in dependencies:
            if dep in compiled['entities'] and dep not in relevant:relevant.add(dep);pending.append(dep)
    def relevant_geometry(row):
        if row.get('check')=='declared_vs_geometry':return False
        ids=set(row.get('entity_ids',[]))|{row.get('entity_id')}
        if row.get('check')=='definite_compiler_geometry_violation':ids.add(row.get('detail',{}).get('entity_id'))
        return bool(ids&relevant)
    target_bad=[r for r in verification['violations'] if relevant_geometry(r)]
    target_unknown=[r for r in verification['not_evaluable'] if relevant_geometry(r)]
    target_coverage=all(r['present'] and r['executable_geometry'] for r in coverage if r['geometry_required'])
    target_status=('INVALID_SERIALIZATION' if schema_validation['status']=='INVALID' else
                   'VIOLATION' if target_bad else 'NOT_EVALUABLE' if not required_geo or not target_coverage or target_unknown else 'PASS_REGISTERED_GEOMETRY')
    return {'evaluator_version': '2.2.1', 'schema_validation':schema_validation, 'execution_status': compiled['status'],
            'evaluation_policy': policy, 'verification': verification, 'readouts': readouts,
            'role_coverage': {'denominator': len(coverage), 'rows': coverage,
                              'present': sum(r['present'] for r in coverage),
                              'geometry_denominator': len(required_geo),
                              'geometry_covered': sum(r['executable_geometry'] for r in coverage if r['geometry_required'])},
            'registered_geometry':{'status':target_status,'scope_entity_ids':sorted(x for x in relevant if isinstance(x,str)),
                                   'violations':target_bad,'not_evaluable':target_unknown,
                                   'scope':'Registered geometric roles and dependency closure; reference-answer agreement is scored separately'},
            'registered_fragment_success':target_status=='PASS_REGISTERED_GEOMETRY',
            'fragment_success': schema_validation['status']=='VALID' and compiled['status'] == 'EXECUTABLE' and verification['status'] == 'PASS_DECLARED_FRAGMENT'
                and all(r['present'] and (not r['geometry_required'] or r['executable_geometry']) for r in coverage),
            'compiled_entities': compiled['entities'],
            'full_building_success': {'status': 'NOT_EVALUABLE', 'reason': 'No exhaustive image grounding or full human-motion proof'}}


def validate_schema(world):
    """Independent serialization result; never repairs a model response."""
    import json
    from pathlib import Path
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return {'status':'NOT_TESTED','reason':'jsonschema is not installed in the calling interpreter'}
    schema=json.loads((Path(__file__).resolve().parents[1]/'schema/executable_world_schema_v1.json').read_text())
    errors=sorted(Draft202012Validator(schema).iter_errors(world),key=lambda e:str(list(e.path)))
    return {'status':'INVALID' if errors else 'VALID',
            'errors':[{'path':list(e.path),'message':e.message} for e in errors]}


# 2.2.1 measurement correction. Original 2.2 code, prompts and trial inputs stay
# frozen. The following interprets precisely the same serialized material/void.
_compile_v22 = compile_world
_portal_room_sides_v22 = _portal_room_sides
_evaluate_query_v22 = evaluate_query


def _component_face_ports(component, axis, faces, tol):
    """Positive-area incidence, not full projection of every cavity box."""
    ports=[]
    for face in faces:
        for part in component:
            if part['min'][axis]-tol<=face['coordinate']<=part['max'][axis]+tol:
                hit=intersection(_face_rectangle(part,axis),face['rectangle'],tol)
                if hit is not None:
                    ports.append({'axis':axis,'side':face['side'],'coordinate':face['coordinate'],'rectangle':hit})
    return ports


def _material_anchor_planes(component, material, normal, tol):
    """Actual jamb/lintel/sill contacts prevent invented floating wall shells."""
    contacts=set()
    for axis in (0,1,2):
        if axis==normal:continue
        opening_faces=_union_boundary_faces(component,axis,tol)
        material_faces=_union_boundary_faces(material,axis,tol)
        for a in opening_faces:
            for b in material_faces:
                if a['side']==b['side'] or abs(a['coordinate']-b['coordinate'])>tol:continue
                if intersection(a['rectangle'],b['rectangle'],tol):
                    contacts.add((axis,a['side'],a['coordinate']))
    merged=[]
    for contact in sorted(contacts):
        if not any(contact[:2]==prior[:2] and abs(contact[2]-prior[2])<=tol for prior in merged):
            merged.append(contact)
    return merged


def _through_component_axes(component,wall,tol):
    """A connected positive-area void reaches both exposed envelope sides.

    A stepped/splayed reveal is a single channel even if no individual tile
    spans the whole thickness. Disconnected blind pockets remain separate.
    """
    if not component or not wall['boxes']:return {}
    if occupied_intersection(component,wall['boxes'],tol):return {}
    result={}
    for axis in (0,1):
        envelope_faces=_union_boundary_faces(wall['raw_boxes'],axis,tol)
        material_faces=_union_boundary_faces(wall['boxes'],axis,tol)
        # Void overshoot may create new sides on the virtual filled envelope.
        # Such sides are not wall-thickness evidence. Admit only planes with
        # actual retained material on that SAME oriented exterior boundary.
        exterior_material=[]
        for a in material_faces:
            if not any(a['side']==b['side'] and abs(a['coordinate']-b['coordinate'])<=tol
                       and intersection(a['rectangle'],b['rectangle'],tol) for b in envelope_faces):continue
            if any(p['min'][axis]-tol<=a['coordinate']<=p['max'][axis]+tol for p in component):
                exterior_material.append({'axis':axis,'side':a['side'],'coordinate':a['coordinate'],
                                          'basis':'RETAINED_MATERIAL_ON_FILLED_ENVELOPE_EXTERIOR'})
        ports=exterior_material
        lows=[p for p in ports if p['side']=='min'];highs=[p for p in ports if p['side']=='max']
        anchors=_material_anchor_planes(component,wall['boxes'],axis,tol)
        if len(anchors)<2:continue
        if any(b['coordinate']-a['coordinate']>tol for a in lows for b in highs):
            result[axis]={'ports':ports,'material_anchor_planes':[list(a) for a in anchors],
                          'rule':'CONNECTED_POSITIVE_AREA_VOID_COMPONENT_SPANS_ENVELOPE'}
    return result


def _resolve_opening_wall(compiled,opening):
    ids=list(opening['raw'].get('host_ids',[]));primary=opening.get('host_id')
    if primary not in (None,'UNKNOWN','unknown') and primary not in ids:ids.append(primary)
    ids=list(dict.fromkeys(ids))
    if not ids:return None,answer('UNKNOWN','NOT_EVALUABLE',reason='Explicit wall host identity missing')
    absent=[i for i in ids if i not in compiled['entities']]
    if absent:return None,answer('UNKNOWN','CONTRACT_INVALID',reason='An explicitly named wall host does not exist',host_ids=ids,missing_host_ids=absent)
    missing=_need(compiled,ids)
    if missing:return None,missing
    es=compiled['entities'];hosts=[es[i] for i in ids]
    if any(e['kind']!='wall' for e in hosts):
        return None,answer('UNKNOWN','CONTRACT_INVALID',reason='An explicitly named opening host is not a wall',host_ids=ids,
                           nonwall_host_ids=[e['id'] for e in hosts if e['kind']!='wall'])
    # Normalize the envelope from *retained physical material* and explicitly
    # registered voids. Both precut wall unions and solid-then-subtract encodings
    # now produce the same envelope and same physical material.
    material=[b for e in hosts for b in e['boxes']]
    registered=set();voids=[]
    for host in hosts:
        for oid in host['raw'].get('opening_ids',[]):
            other=es.get(oid)
            if other is None or other['kind'] not in OPENING_KINDS or other['geometry_status']!='EXECUTABLE':continue
            other_hosts=set(other['raw'].get('host_ids',[]))|{other.get('host_id')}
            if host['id'] not in other_hosts:continue
            registered.add(oid);voids.extend(other['boxes'])
    local_hosts=[h for h in hosts if occupied_intersection(opening['boxes'],h['raw_boxes'],compiled['tolerance'])
                 or _material_anchor_planes(opening['boxes'],h['boxes'],-1,compiled['tolerance'])]
    if not local_hosts or any(opening['id'] not in h['raw'].get('opening_ids',[]) for h in local_hosts):
        registered.discard(opening['id'])
    # Registration is explicit bookkeeping; geometric validity still requires
    # a through channel and real material anchors. This is not unconditional
    # acceptance of registered_cut or reconstruction of missing real walls.
    wall={'id':ids[0] if len(ids)==1 else 'HOST_UNION('+','.join(sorted(ids))+')',
          'kind':'wall','host_id':None,'owner':'UNKNOWN','geometry_status':'EXECUTABLE',
          'raw_boxes':material+voids,'boxes':material,
          'raw':{'opening_ids':sorted(registered)},'host_entity_ids':ids,
          'host_union_version':'MATERIAL_PLUS_REGISTERED_VOID_ENVELOPE_2_2_1'}
    return wall,None


def aperture_fits_wall(opening,wall,tol=EPS):
    if not opening['boxes']:return False
    components=_opening_components(opening['boxes'],tol)
    return bool(components) and all(_through_component_axes(c['boxes'],wall,tol) for c in components)


def _portal_room_sides(opening,wall,room,tol):
    if opening['id']==wall['id']:
        # Existing named-solid-barrier diagnostic is not an opening-host test.
        return _portal_room_sides_v22(opening,wall,room,tol)
    faces={a:_union_boundary_faces(room['boxes'],a,tol) for a in (0,1)}
    result=[]
    for component in _opening_components(opening['boxes'],tol):
        matches=[];axes=_through_component_axes(component['boxes'],wall,tol)
        for axis in axes:
            matches.extend(_component_face_ports(component['boxes'],axis,faces[axis],tol))
        # Consumers require one incident port set per connected channel. They
        # do not require every reveal tile to touch the room directly.
        result.append([matches])
    return result


def compile_world(world):
    compiled=_compile_v22(world);retained=[]
    for issue in compiled['issues']:
        if issue.get('code')=='DETACHED_OPENING':
            opening=compiled['entities'].get(issue.get('detail'))
            if opening:
                host,error=_resolve_opening_wall(compiled,opening)
                if error is None and opening['id'] in host['raw']['opening_ids'] and aperture_fits_wall(opening,host,compiled['tolerance']):
                    retained.append({'entity_id':issue.get('entity_id'),'code':'PRECUT_REGISTERED_OPENING_EQUIVALENT',
                                     'status':'INFORMATIONAL','detail':issue.get('detail'),
                                     'basis':'Registered void plus retained material forms a geometrically anchored through opening'})
                    continue
        retained.append(issue)
    compiled['issues']=retained
    return compiled


def evaluate_query(compiled,world,query):
    pred=query.get('predicate');args=[resolve(world,x) for x in query.get('args',[])];es=compiled['entities'];tol=compiled['tolerance']
    if pred in ('host_attached','door_host') and len(args)==2 and all(a in es for a in args) and es[args[1]]['kind']=='wall':
        child,host=[es[a] for a in args]
        if pred=='door_host' and child['kind']!='door_opening':return answer('FALSE',reason='Not a door opening')
        if child['kind'] in ('door_opening','window_opening','opening'):
            missing=_need(compiled,args)
            if missing:return missing
            union,error=_resolve_opening_wall(compiled,child)
            if error:return error
            contact=bool(occupied_intersection(child['boxes'],host['raw_boxes'],tol)
                         or _material_anchor_planes(child['boxes'],host['boxes'],-1,tol))
            checks={'typed_wall_host':True,'explicit_host_matches':host['id'] in union['host_entity_ids'],
                    'registered_cut':child['id'] in host['raw'].get('opening_ids',[]),
                    'positive_material_or_boundary_incidence':contact,'fits_host_union':aperture_fits_wall(child,union,tol)}
            return answer(all(checks.values()),entity_ids=args,checks=checks,
                          measurement_rule='Retained-material boundary incidence permits explicitly precut registered openings')
    return _evaluate_query_v22(compiled,world,query)


def door_connection(compiled,door_id):
    es=compiled['entities'];tol=compiled['tolerance'];door=es.get(door_id)
    if not door:return answer('NOT_FOUND','NOT_FOUND')
    if door['kind'] not in ('door_opening','opening'):return answer('FALSE',reason='Entity is not a door or ordinary passage opening')
    rooms=door['raw'].get('room_ids',[])
    if len(rooms)!=2 or len(set(rooms))!=2:return answer('UNKNOWN','NOT_EVALUABLE',reason='Two distinct room IDs required')
    missing=_need(compiled,[door_id]+rooms)
    if missing:return missing
    if any(es[r]['kind'] not in SPACE_KINDS for r in rooms):return answer('FALSE',reason='Door endpoint is not a spatial room')
    wall,error=_resolve_opening_wall(compiled,door)
    if error:return error
    floors=[_room_floor(es[r],tol) for r in rooms]
    if any(z is None or not f for z,f in floors):return answer('UNKNOWN','NOT_EVALUABLE',reason='Room floor_z missing or inconsistent')
    z=floors[0][0]
    active_boxes=[{'min':[b['min'][0],b['min'][1],max(z,b['min'][2])],'max':list(b['max'])}
                  for b in door['boxes'] if b['max'][2]>z+tol]
    active=dict(door,boxes=active_boxes)
    components=_opening_components(active_boxes,tol)
    covers_floor=bool(components) and all(any(b['min'][2]<=z+tol and b['max'][2]>z+tol for b in c['boxes']) for c in components)
    sides=[_portal_room_sides(active,wall,es[r],tol) for r in rooms]
    opposite=bool(sides[0])
    for a,b in zip(sides[0],sides[1]):
        for left,right in zip(a,b):
            opposite=opposite and any(x['axis']==y['axis'] and x['side']!=y['side']
                and ((x['side']=='max' and x['coordinate']<=y['coordinate']+tol)
                     or (y['side']=='max' and y['coordinate']<=x['coordinate']+tol)) for x in left for y in right)
    checks={'same_floor':abs(floors[0][0]-floors[1][0])<=tol,
            'fits_wall':aperture_fits_wall(active,wall,tol),
            'opening_cut':door_id in wall['raw'].get('opening_ids',[]),
            'opposite_exposed_room_sides':opposite,'covers_common_floor':covers_floor}
    blockage=_portal_blockage(compiled,active,ignore=(door_id,))
    checks['not_completely_filled']=not blockage['completely_filled']
    failure=not all(checks.values())
    result='FALSE' if failure else 'UNKNOWN' if blockage['partially_occupied'] else 'TRUE'
    return answer(result,'NOT_EVALUABLE' if result=='UNKNOWN' else 'DETERMINATE',
                  entity_ids=[door_id,wall['id']]+rooms,checks=checks,room_side_proofs=sides,blockage=blockage,
                  common_floor_z=z,active_aperture_region='Original opening union intersected with z >= common floor',
                  measurement_rule='Cover the actual common floor; harmless subfloor void overshoot is not a suspended door',
                  scope='Structural above-floor aperture connection only; not complete human motion or clearance')

