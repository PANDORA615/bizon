"""Refresh Unity box centers from GLB geometry and verify alignment. Requires NumPy."""
from pathlib import Path
import json,struct,math,hashlib
import numpy as np
repo=Path(__file__).resolve().parents[1];u=repo/'UnityProject'
# glTF coordinates after the runtime root correction -> canonical Unity world.
Z=np.diag([1.,1.,-1.,1.]);S=np.array([[1,0,0],[0,0,1],[0,1,0]],dtype=float)
def quat(q):
 x,y,z,w=q
 return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
def trs(n):
 if 'matrix'in n:return np.array(n['matrix']).reshape(4,4,order='F')
 m=np.eye(4);m[:3,:3]=quat(n.get('rotation',[0,0,0,1]))@np.diag(n.get('scale',[1,1,1]));m[:3,3]=n.get('translation',[0,0,0]);return m
bounds={};nodes={}
for b in range(1,4):
 raw=(repo/'exports'/f'Block_{b:02d}.glb').read_bytes();ln,ty=struct.unpack_from('<II',raw,12);doc=json.loads(raw[20:20+ln])
 def visit(index,parent):
  n=doc['nodes'][index];world=parent@trs(n);nodes[n.get('name','')]=Z@world
  if 'mesh' in n:
   lows=[];highs=[]
   for pr in doc['meshes'][n['mesh']]['primitives']:
    a=doc['accessors'][pr['attributes']['POSITION']];lows.append(a['min']);highs.append(a['max'])
   lo=np.min(lows,axis=0);hi=np.max(highs,axis=0);center=np.append((lo+hi)/2,1)
   worldcenter=(Z@world@center)[:3]
   corners=np.array([[x,y,z,1]for x in(lo[0],hi[0])for y in(lo[1],hi[1])for z in(lo[2],hi[2])])
   c=(Z@world@corners.T).T[:,:3];bounds[n['name']]={'center':worldcenter,'lo':c.min(axis=0),'hi':c.max(axis=0)}
  for c in n.get('children',[]):visit(c,world)
 for n in doc['scenes'][doc.get('scene',0)]['nodes']:visit(n,np.eye(4))
def euler(v):
 x,y,z=v;cx,sx,cy,sy,cz,sz=math.cos(x),math.sin(x),math.cos(y),math.sin(y),math.cos(z),math.sin(z)
 return np.array([[cz*cy,cz*sy*sx-sz*cx,cz*sy*cx+sz*sx],[sz*cy,sz*sy*sx+cz*cx,sz*sy*cx-cz*sx],[-sy,cy*sx,cy*cx]])
doc=json.loads((repo/'metadata/collision_proxies.json').read_text());corrected=0;missing=[];maxerr=0;errors=[];ramps=[]
for c in doc['data']:
 pos=S@np.array(c['position_m']);rot=S@euler(c['rotation_euler_rad'])@S;size=S@np.array(c['size_m'])
 if c['kind']=='STAIR_RAMP':
  ramps.append(c);continue
 if c['id']not in bounds:missing.append(c['id']);continue
 target=bounds[c['id']];delta=target['center']-pos
 if np.linalg.norm(delta)>.0005:
  c['object_origin_m']=c['position_m'];c['position_m']=(S@target['center']).tolist();pos=target['center'];corrected+=1
 half=np.abs(rot)@size/2
 err=max(np.max(np.abs(pos-half-target['lo'])),np.max(np.abs(pos+half-target['hi'])));maxerr=max(maxerr,float(err))
 if err>.002:errors.append({'id':c['id'],'error_m':float(err),'expected_half':half.tolist(),'visual_lo':target['lo'].tolist(),'visual_hi':target['hi'].tolist()})
assert all(n.endswith('-ROOF') for n in missing),missing
assert not errors,errors[:20]
assert len(ramps)==52,len(ramps)
doc['provenance']['unity_integration_version']='1.0.0';doc['provenance']['collider_center_policy']='Visual GLB bounding-box center, corrected from Blender object origin. Stair ramps retain source center.'
(u/'Assets/StreamingAssets/RFC/collision_proxies.json').write_text(json.dumps(doc,indent=2))
# Spawn capsule: use a conservative AABB against every corrected oriented proxy.
spawn=np.array([66,.12,160]);bad=[]
for c in doc['data']:
 pos=S@np.array(c['position_m']);rot=S@euler(c['rotation_euler_rad'])@S;half=np.abs(rot)@(S@np.array(c['size_m']))/2;lo=pos-half;hi=pos+half
 if hi[1]>.17 and lo[1]<1.92 and lo[0]-.35<spawn[0]<hi[0]+.35 and lo[2]-.35<spawn[2]<hi[2]+.35:bad.append(c['id'])
assert not bad,bad
for b,x,y in [(1,210,160),(2,700,180),(3,1190,160)]:assert np.linalg.norm(nodes[f'B{b:02d}-GROUND'][:3,3]-[x,-.12,y])<.001
result={'status':'PASS','collider_records':len(doc['data']),'visual_boxes_checked':len(doc['data'])-len(ramps)-len(missing),'roof_boxes_reconstructed_at_runtime':missing,'centers_corrected':corrected,'max_visual_bounds_error_m':maxerr,'stair_ramp_count':len(ramps),'spawn_AABB_clearance':'PASS','block_ground_anchors':'PASS','Unity_runtime':'NOT_RUN'}
(u/'COLLIDER_VALIDATION.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
