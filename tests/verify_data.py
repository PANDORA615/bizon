import json, math, pathlib, numpy as np, sys, struct
root=pathlib.Path(sys.argv[1])
def read(n,folder='metadata'):return json.loads((root/folder/n).read_text())['data']
nav=read('navigation.json');coll=read('collision_proxies.json');cfg=json.loads((root/'config/warehouse.json').read_text())
centers=np.array([c['position_m'] for c in coll]);sizes=np.array([c['size_m'] for c in coll])
for i,c in enumerate(coll):
 x,y,z=c['rotation_euler_rad'];cx,sx,cy,sy,cz,sz=math.cos(x),math.sin(x),math.cos(y),math.sin(y),math.cos(z),math.sin(z)
 rot=np.array([[cz*cy,cz*sy*sx-sz*cx,cz*sy*cx+sz*sx],[sz*cy,sz*sy*sx+cz*cx,sz*sy*cx-cz*sx],[-sy,cy*sx,cy*cx]])
 sizes[i]=np.abs(rot)@sizes[i]
mins=centers-sizes/2;maxs=centers+sizes/2
viol=[];tested=0
for agent,radius,height in [('human',cfg['agents']['player_radius_m']+cfg['agents']['clearance_margin_m'],cfg['agents']['player_height_m']),('pallet_truck',cfg['agents']['pallet_truck_width_m']/2+cfg['agents']['clearance_margin_m'],cfg['agents']['pallet_truck_height_m'])]:
 for e in nav['edges']:
  if agent not in e['agents'] or e['type']=='stairs':continue
  a=np.array(nav['nodes'][e['a']]['position_m']);b=np.array(nav['nodes'][e['b']]['position_m'])
  if abs(a[2]-b[2])>.01:continue
  tested+=1
  keep=(maxs[:,2]>a[2]+.2)&(mins[:,2]<a[2]+height)&(maxs[:,0]>=min(a[0],b[0])-radius)&(mins[:,0]<=max(a[0],b[0])+radius)&(maxs[:,1]>=min(a[1],b[1])-radius)&(mins[:,1]<=max(a[1],b[1])+radius)
  for ix in np.where(keep)[0]:
   lo=mins[ix,:2]-radius;hi=maxs[ix,:2]+radius;d=b[:2]-a[:2];tl=0.;th=1.
   for axis in (0,1):
    if abs(d[axis])<1e-9:
     if a[axis]<lo[axis] or a[axis]>hi[axis]:tl=2.;break
    else:
     t1=(lo[axis]-a[axis])/d[axis];t2=(hi[axis]-a[axis])/d[axis];tl=max(tl,min(t1,t2));th=min(th,max(t1,t2))
   if tl<=th and th>=0 and tl<=1:viol.append({'agent':agent,'edge':e['id'],'object':coll[ix]['id']})
report={'status':'PASS' if not viol else 'FAIL','method':'Conservative expanded AABB versus straight horizontal graph edges, standing height. Radius includes margin. Stair traversal, pallet-truck length and swept turning NOT_RUN.','tested_edge_agent_pairs':tested,'violations':viol,'stair_collision_validation':'NOT_RUN','vehicle_turning_validation':'NOT_RUN'}
prov=json.loads((root/'metadata/navigation.json').read_text())['provenance']
(root/'reports/geometry_corridors.json').write_text(json.dumps({'provenance':prov,'data':report},indent=2))
print(json.dumps(report,indent=2))
# References, object IDs and GLB binary header integrity.
cells=read('storage_cells.json');assert len({c['id'] for c in cells})==len(cells)
for c in cells:assert c['sector_id'].startswith(c['id'][:3])
for p in (root/'exports').glob('*.glb'):
 raw=p.read_bytes();magic,ver,size=struct.unpack_from('<4sII',raw)
 assert magic==b'glTF' and ver==2 and size==len(raw),(p,'header')
 ln,typ=struct.unpack_from('<II',raw,12);doc=json.loads(raw[20:20+ln]);assert doc['meshes'] and doc['materials']
 for tex in doc.get('images',[]):assert 'bufferView' in tex,tex
 print('GLB_VALID',p.name,len(doc['nodes']),len(doc['meshes']),len(doc.get('images',[])))
print('CELL_IDS_VALID',len(cells))
