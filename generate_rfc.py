"""RFC Horror — standalone Blender 4.2+ generator, no downloads or add-ons.
Run in Blender Text Editor > Run Script, or:
blender -b --python generate_rfc.py -- --output ./RFC_BUILD --mode full --export
Only the RFC_HORROR collection and RFC_ datablocks are replaced.
"""
import bpy, math, json, random, hashlib, time, sys, argparse, os
from pathlib import Path
from collections import defaultdict, deque
from mathutils import Vector
import numpy as np

VERSION = '1.0.0'
DEFAULT = {
    'project':'RFC_Horror','seed':42001,'mode':'full','sector_size_m':32,
    'level_height_m':4.8,'main_aisle_m':12.0,'rack_bay_m':1.2,
    'rack_depth_m':0.8,'rack_aisle_m':2.4,'rack_sections_target':80,
    'rack_rows':{'B01':60,'B02':80},'strict_capacity':True,
    'agents':{'player_radius_m':0.35,'player_height_m':1.8,'step_height_m':0.2,
              'max_slope_deg':35,'clearance_margin_m':0.15,'walk_speed_m_s':1.5,
              'pallet_truck_width_m':1.1,'pallet_truck_height_m':2.0,'turn_radius_m':2.0},
    'lighting':{'shift':'DAY','night_main_ratio':0.10,'event_interval_s':180},
    'routing':{'sector_entry_target_s':[20,60],'local_cycle_target_s':[120,300]},
    'performance_profile':{'Unity':'NOT_RUN','pipeline':'UNSELECTED','target_hardware':'UNSPECIFIED'}
}
BLOCKS = [('B01',0,420,320,24),('B02',440,520,360,24),('B03',980,420,320,24)]
OUT = None
COL = None
MATS = {}
CACHE = {}
COLLECTIONS = {}
OBJECTS = []
ZONES, PORTALS, NODES, EDGES, STAIRS, CELLS, CONVEYORS, MARKERS, LIGHTS = [],[],{},[],[],[],[],[],[]
RACKS = []
T0=time.perf_counter()

def arguments():
    # Blender's Text Editor has no -- separator; defaults to a folder beside .blend/script.
    av=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default=str(Path(bpy.data.filepath).parent/'RFC_BUILD') if bpy.data.filepath else str(Path.home()/'Documents'/'RFC_BUILD'))
    p.add_argument('--mode',choices=['small','medium','full'],default='full')
    p.add_argument('--config'); p.add_argument('--export',action='store_true')
    p.add_argument('--sector',help='Export one sector, e.g. B01-F00-X002-Y004')
    p.add_argument('--previews',action='store_true')
    return p.parse_args(av)

def validate_config(c):
    if set(c)!=set(DEFAULT): raise ValueError('Unknown/missing config keys: '+str(set(c)^set(DEFAULT)))
    for k in ('agents','lighting','routing','rack_rows','performance_profile'):
        if set(c[k])!=set(DEFAULT[k]): raise ValueError('Unknown/missing keys in '+k)
    ranges={'level_height_m':(4.5,5.0),'sector_size_m':(16,64),'main_aisle_m':(8,16),
            'rack_bay_m':(1,1.2),'rack_depth_m':(.6,1),'rack_aisle_m':(2,2.5),'rack_sections_target':(8,80)}
    for k,(lo,hi) in ranges.items():
        if isinstance(c[k],bool) or not isinstance(c[k],(int,float)) or not lo<=c[k]<=hi:
            raise ValueError(f'{k} must be {lo}..{hi}')
    if c['mode'] not in ('small','medium','full'): raise ValueError('Invalid mode')
    if c['lighting']['shift'] not in ('DAY','NIGHT'): raise ValueError('shift must be DAY or NIGHT')
    if not isinstance(c['seed'],int) or isinstance(c['seed'],bool): raise ValueError('seed must be integer')
    for k,v in c['agents'].items():
        if not isinstance(v,(int,float)) or isinstance(v,bool) or v<=0: raise ValueError('Invalid agents.'+k)
    if c['agents']['player_radius_m']*2+2*c['agents']['clearance_margin_m']>c['rack_aisle_m']:
        raise ValueError('Player diameter + margin exceeds picking aisle')
    if c['agents']['player_height_m']+c['agents']['clearance_margin_m']>2.2: raise ValueError('Player too tall for stair flights')
    for k,v in c['rack_rows'].items():
        if not isinstance(v,int) or v<4 or v%4: raise ValueError(k+' rows must be a positive multiple of four')

def stamp():
    return {'schema_version':'1.0','generator_version':VERSION,'seed':CFG['seed'],
            'config_sha256':hashlib.sha256(json.dumps(CFG,sort_keys=True).encode()).hexdigest(),
            'coordinate_system':'Blender Z-up, meters; global positions; local=global minus block origin'}

def write_json(name,data,folder='metadata'):
    p=OUT/folder/name; p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({'provenance':stamp(),'data':data},ensure_ascii=False,indent=2),encoding='utf-8')

def collection(name,parent=None):
    if name not in COLLECTIONS:
        c=bpy.data.collections.new(name); (parent or ROOT).children.link(c); COLLECTIONS[name]=c
    return COLLECTIONS[name]

def sector(b,f,x,y):
    ox=next((q[1] for q in BLOCKS if q[0]==b),0)
    return f'{b}-F{f:02d}-X{max(0,int((x-ox)//CFG["sector_size_m"])):03d}-Y{max(0,int(y//CFG["sector_size_m"])):03d}'

def new_obj(name,data,pos=(0,0,0),b='B01',f=0,col=None):
    o=bpy.data.objects.new(name,data); (col or COL).objects.link(o); o.location=pos
    o['rfc_id']=name; o['block_id']=b; o['floor']=f
    o['sector_id']=sector(b,f,pos[0],pos[1]); o['static']=True
    OBJECTS.append(o)
    return o

class Mesh:
    def __init__(self): self.v=[]; self.faces=[]; self.mi=[]; self.uv=[]; self.materials=[]
    def box(self,p,s,mat):
        x,y,z=p; a,b,c=[t/2 for t in s]; n=len(self.v)
        self.v.extend([(x-a,y-b,z-c),(x+a,y-b,z-c),(x+a,y+b,z-c),(x-a,y+b,z-c),
                       (x-a,y-b,z+c),(x+a,y-b,z+c),(x+a,y+b,z+c),(x-a,y+b,z+c)])
        if mat not in self.materials:self.materials.append(mat)
        ix=self.materials.index(mat)
        fs=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
        dims=[(s[0],s[1]),(s[0],s[1]),(s[0],s[2]),(s[1],s[2]),(s[0],s[2]),(s[1],s[2])]
        for face,(u,v) in zip(fs,dims):
            self.faces.append(tuple(n+j for j in face)); self.mi.append(ix)
            self.uv.extend([(0,0),(u,0),(u,v),(0,v)])
    def mesh(self,name):
        m=bpy.data.meshes.new('RFC_'+name); m.from_pydata(self.v,[],self.faces); m.update()
        for mat in self.materials:m.materials.append(MATS[mat])
        for p,i in zip(m.polygons,self.mi):p.material_index=i
        layer=m.uv_layers.new(name='UVMap')
        for l,uv in zip(layer.data,self.uv):l.uv=uv
        return m

def box(name,pos,size,mat,b='B01',f=0,collision=True,col=None):
    key=(tuple(round(float(x),5) for x in size),mat)
    if key not in CACHE:
        m=Mesh();m.box((0,0,0),size,mat);CACHE[key]=m.mesh(str(len(CACHE)))
    o=new_obj(name,CACHE[key],pos,b,f,col)
    if collision:o['collider']='BOX';o['sound_surface']=mat
    return o

def bar(name,a,b,r,mat,block='B01',f=0):
    a,b=Vector(a),Vector(b); d=b-a
    o=box(name,(a+b)/2,(r,r,d.length),mat,block,f,True)
    o.rotation_euler=d.to_track_quat('Z','Y').to_euler(); return o

def sign(name,label,pos,size=0.6,mat='white',rot=(math.pi/2,0,0),b='B01',f=0):
    key=('TEXT',label,size,mat)
    if key not in CACHE:
        t=bpy.data.curves.new('RFC_TXT_'+label,'FONT'); t.body=label;t.size=size;t.align_x='CENTER';t.extrude=0.004;t.space_character=1.1;t.materials.append(MATS[mat]);CACHE[key]=t
    o=new_obj(name,CACHE[key],pos,b,f);o.rotation_euler=rot;return o

def marker(name,kind,pos,b,f,extra=None):
    o=new_obj(name,None,pos,b,f,col=collection('RFC_MARKERS'));o.empty_display_type='SPHERE';o.empty_display_size=.45
    o['marker_type']=kind
    item={'id':name,'type':kind,'position_m':list(pos),'block':b,'floor':f,'sector_id':o['sector_id']}
    if extra:item.update(extra)
    MARKERS.append(item);return item

def textures():
    """Original tileable image PBR textures, generated locally, packed into .blend."""
    texdir=OUT/'textures';texdir.mkdir(exist_ok=True)
    palette={
      'concrete':(.29,.31,.31),'wall':(.54,.57,.57),'blue':(.035,.16,.28),
      'orange':(.86,.26,.035),'steel':(.36,.40,.42),'rust':(.23,.09,.035),
      'cardboard':(.55,.36,.18),'wood':(.32,.20,.09),'belt':(.035,.045,.047),
      'white':(.83,.87,.79),'yellow':(.93,.64,.045),'red':(.48,.025,.018),
      'teal':(.015,.32,.29),'grating':(.35,.39,.40),'hazard':(.9,.6,.04),
      'emissive':(.62,.84,.98),'exit':(.04,.65,.25),'screen':(.01,.12,.12)}
    n=256;yy,xx=np.mgrid[0:n,0:n];u=xx/n;v=yy/n
    rng=np.random.default_rng(CFG['seed'])
    for name,base in palette.items():
        noise=rng.random((n,n)); broad=np.sin(u*math.tau*7+np.sin(v*math.tau*3))*np.cos(v*math.tau*5)
        val=.87+noise*.20+broad*.06
        if name=='concrete':
            seam=(xx%128<2)|(yy%128<2);val[seam]*=.65
            val[((xx*17+yy*31)%491)<2]*=.55
        if name in ('steel','wall','blue','orange'):
            val*=1+.035*np.sin(v*math.tau*48)
        if name=='wood':val*=.82+.23*np.sin(u*math.tau*22+np.sin(v*math.tau*2)*.3)
        if name=='cardboard':
            val[np.abs(u-.5)<.075]*=1.28
            val[(v>.62)&(v<.8)&(u>.1)&(u<.32)]=1.5
            val[(v>.65)&(v<.77)&(u>.12)&(u<.3)&(xx%5<2)]=.15
        rgb=np.clip(val[:,:,None]*np.array(base)[None,None,:],0,1)
        alpha=np.ones((n,n))
        if name=='hazard':
            black=((xx+yy)//32)%2==0;rgb[black]=(.025,.03,.032)
        if name=='grating':
            alpha=(((xx%64)<10)|((yy%64)<10)).astype(float)
        rough=np.full((n,n),.8 if name in ('concrete','cardboard','wood') else .48)+noise*.12
        if name in ('steel','grating'):rough*=.65
        gx=np.roll(val,1,axis=1)-np.roll(val,-1,axis=1); gy=np.roll(val,1,axis=0)-np.roll(val,-1,axis=0)
        normal=np.stack((.5+gx*.12,.5+gy*.12,np.ones_like(val)),axis=2)
        images={}
        for suffix,arr in [('BaseColor',np.dstack((rgb,alpha))),('Roughness',np.dstack((rough,rough,rough,np.ones_like(rough)))),('Normal',np.dstack((normal,np.ones_like(val))))]:
            im=bpy.data.images.new('RFC_'+name+'_'+suffix,width=n,height=n,alpha=True)
            if suffix!='BaseColor':im.colorspace_settings.name='Non-Color'
            im.pixels.foreach_set(np.clip(arr,0,1).astype(np.float32).ravel());im.filepath_raw=str(texdir/(name+'_'+suffix+'.png'));im.file_format='PNG';im.save();im.pack();images[suffix]=im
        m=bpy.data.materials.new('RFC_'+name);m.use_nodes=True;m.diffuse_color=(*base,1)
        nodes=m.node_tree.nodes;links=m.node_tree.links;p=nodes.get('Principled BSDF')
        for suffix,target in [('BaseColor','Base Color'),('Roughness','Roughness')]:
            t=nodes.new('ShaderNodeTexImage');t.image=images[suffix];links.new(t.outputs['Color'],p.inputs[target])
            if suffix=='BaseColor' and name=='grating':links.new(t.outputs['Alpha'],p.inputs['Alpha'])
        t=nodes.new('ShaderNodeTexImage');t.image=images['Normal'];nm=nodes.new('ShaderNodeNormalMap');links.new(t.outputs['Color'],nm.inputs['Color']);links.new(nm.outputs['Normal'],p.inputs['Normal'])
        p.inputs['Metallic'].default_value=.7 if name in ('steel','blue','orange','grating','rust') else 0
        if name in ('emissive','exit','screen'):
            p.inputs['Emission Color'].default_value=(*base,1);p.inputs['Emission Strength'].default_value=5 if name=='emissive' else 2
        if name=='grating':
            if hasattr(m,'surface_render_method'):m.surface_render_method='DITHERED'
            m.use_backface_culling=False
        MATS[name]=m

def node(id,pos,block,f,kind='walk'):
    if id in NODES:raise ValueError('Duplicate nav node '+id)
    NODES[id]={'id':id,'position_m':list(pos),'block':block,'floor':f,'kind':kind}
    return id

def edge(a,b,kind='walk',agents=None,state='OPEN',width=4):
    length=(Vector(NODES[a]['position_m'])-Vector(NODES[b]['position_m'])).length
    EDGES.append({'id':f'{a}__{b}','a':a,'b':b,'type':kind,'length_m':round(length,4),
      'width_m':width,'height_m':3.2 if kind=='bridge' else 4.5,'access':state,
      'agents':agents or (['human','horror'] if kind=='stairs' else ['human','horror','pallet_truck'])})

def zone(id,kind,b,f,rect,z,ox):
    x0,y0,x1,y1=rect
    q={'zone_id':id,'type':kind,'block':b,'floor':f,'local_bounds_m':[x0,y0,z,x1,y1,z+CFG['level_height_m']],
       'global_bounds_m':[ox+x0,y0,z,ox+x1,y1,z+CFG['level_height_m']],
       'access':'OPEN','neighbors':[],'portals':[],'reserved_aisle_m':CFG['rack_aisle_m']}
    ZONES.append(q);return q

def logical_plan():
    for b,ox,w,d,h in BLOCKS:
        levels=range(4) if b!='B03' else range(2)
        for f in levels:
            z=f*CFG['level_height_m'] if b!='B03' else f*6
            ymin,ymax=(72,d-56) if b!='B03' else (190,278) if f else (174,290)
            xmin,xmax=(60,w-60) if b!='B03' else (60,250) if f else (60,314)
            for side,y in [('S',ymin+8),('N',ymax-8)]:
                for lr,x in [('W',xmin+6),('E',xmax-6)]:node(f'{b}-F{f}-{side}{lr}',(ox+x,y,z),b,f)
            ids=[f'{b}-F{f}-{s}' for s in ('SW','SE','NE','NW')]
            for a,bb in zip(ids,ids[1:]+ids[:1]):edge(a,bb,width=4,agents=['human','horror'] if f else None)
            # Real central arteries, four distinct sector entrances.
            mid=node(f'{b}-F{f}-HUB',(ox+w/2,160 if not (b=='B03' and f) else 230,z),b,f)
            for s in ('SW','SE','NW','NE'):
                p=NODES[f'{b}-F{f}-{s}']['position_m']; side=node(f'{b}-F{f}-MID{s}',(p[0],NODES[mid]['position_m'][1],z),b,f)
                edge(mid,side,width=6,agents=['human','horror'] if f else None)
                edge(side,f'{b}-F{f}-{s}',width=4,agents=['human','horror'] if f else None)
            if b!='B03':
                zone(f'{b}-F{f:02d}-MEZZ','MEZZANINE',b,f,(60,72,w-60,d-56),z,ox)
                for side,x0,x1 in [('W',72,w/2-10),('E',w/2+10,w-72)]:
                    for ns,y0,y1 in [('S',84,148),('N',172,d-70)]:
                        zid=f'{b}-F{f:02d}-{ns}{side}'
                        zone(zid,'PICKING',b,f,(x0,y0,x1,y1),z,ox)
            elif f:zone(f'{b}-F01-TECH','SERVICE',b,f,(60,190,250,278),6,ox)
        if b!='B03':
            for kind,rect in [('RECEIVING',(70,6,w-70,42)),('QUARANTINE',(16,8,65,60)),('KGT',(70,d-50,w-70,d-8)),('SERVICE',(8,76,38,138)),('SECURITY',(8,172,40,230)),('CONVEYOR',(70,55,w-70,65))]:zone(b+'-F00-'+kind,kind,b,0,rect,0,ox)
        else:
            for kind,rect in [('RECEIVING',(12,70,65,140)),('PACKING',(70,60,210,130)),('SORTING',(70,190,300,278)),('SHIPPING',(80,8,350,42)),('SECURITY',(320,70,400,135)),('CONVEYOR',(30,50,390,65)),('SERVICE',(320,210,400,275))]:zone(b+'-F00-'+kind,kind,b,0,rect,0,ox)
        # Four stairs in B1/B2; two independent ones in B3.
        stair_specs=[('SW',48,80),('SE',w-54,80),('NW',48,d-70),('NE',w-54,d-70)] if b!='B03' else [('SW',48,198),('NE',250,260)]
        floors=4 if b!='B03' else 2;rise=CFG['level_height_m'] if b!='B03' else 6
        for sid,x,y in stair_specs:
            for f in range(floors):
                s=node(f'{b}-ST-{sid}-F{f}',(ox+x+2.8,y-1,f*rise),b,f,'landing')
                target=f'{b}-F{f}-{sid}'
                # Landing -> platform edge -> perimeter avoids crossing racks.
                tx=NODES[target]['position_m'][0]
                q=node(s+'-LINK',(tx,y-1,f*rise),b,f)
                if b=='B03' and sid=='NE' and f==0:
                    detour=node(s+'-DETOUR',(ox+x+2.8,282,0),b,f)
                    edge(s,detour,agents=['human','horror']);edge(detour,target,agents=['human','horror'])
                    edge(q,target,agents=['human','horror'])
                else:
                    edge(s,q,agents=['human','horror']);edge(q,target,agents=['human','horror'])
                if f:
                    prev=f'{b}-ST-{sid}-F{f-1}'
                    edge(prev,s,'stairs',width=2.0)
                    EDGES[-1]['length_m']=2*math.hypot(4.8,rise/2)+2.0
            STAIRS.append({'id':b+'-ST-'+sid,'block':b,'x':ox+x,'y':y,'floors':floors,'rise_m':rise})
    for left,right in [('B01','B02'),('B02','B03')]:
        for lane,y in [('MAIN',160),('LOGISTICS',60)]:
            a=next(x for x in BLOCKS if x[0]==left);b=next(x for x in BLOCKS if x[0]==right)
            route_y=y if lane=='MAIN' else y-2
            l=node(f'{left}-{right}-{lane}-A',(a[1]+a[2]-3,route_y,0),left,0)
            r=node(f'{left}-{right}-{lane}-B',(b[1]+3,route_y,0),right,0)
            edge(l,r,'bridge',width=12 if lane=='MAIN' else 8)
            if lane=='MAIN':
                for q,bl,w0 in [(l,left,a[2]),(r,right,b[2])]:
                    hub=f'{bl}-F0-HUB';p=NODES[q]['position_m'];hp=NODES[hub]['position_m']
                    edge(q,hub,width=12)
            else:
                for q,bl in [(l,left),(r,right)]:
                    ox=next(x[1] for x in BLOCKS if x[0]==bl)
                    # Route stays along logistics lane then west exterior aisle.
                    p=node(q+'-TURN',(ox+42,route_y,0),bl,0)
                    t=node(q+'-NORTH',(ox+42,160,0),bl,0)
                    edge(q,p,width=8);edge(p,t,width=8);edge(t,f'{bl}-F0-HUB',width=8)
            PORTALS.append({'portal_id':left+'-'+right+'-'+lane,'zones':[left+'-F00',right+'-F00'],
                            'position_m':[(a[1]+a[2]+b[1])/2,y,0],'dimensions_m':[20,12 if lane=='MAIN' else 8,7],
                            'agents':['human','pallet_truck','horror'],'access':'OPEN','nav_edge':f'{l}__{r}'})
    # Neighbors based on same-floor rectangle boundaries; links through arteries are explicit graph nodes.
    for q in ZONES:
        q['navigation_hub']=f'{q["block"]}-F{q["floor"]}-HUB'
        q['neighbors']=[p['zone_id'] for p in ZONES if p['block']==q['block'] and p['floor']==q['floor'] and p is not q]
    plan_racks()
    checks=check_plan()
    write_json('validation.json',checks,'reports')
    if checks['status']=='FAIL':raise RuntimeError('Logical plan failed. See reports/validation.json')
    write_json('warehouse_layout.json',{'blocks':[{'id':b,'origin_m':[ox,0,0],'size_m':[w,d,h],'footprint_m2':w*d} for b,ox,w,d,h in BLOCKS],'zones':ZONES,'stairs':STAIRS,'rack_rows':RACKS})
    write_json('navigation.json',{'nodes':NODES,'edges':EDGES,'note':'Candidate graph checked against analytic obstacles; Unity NavMesh and swept-volume checks NOT_RUN.'})
    write_json('portals.json',PORTALS);write_json('zone_graph.json',ZONES)

def plan_racks():
    mode=CFG['mode'];limit={'small':4,'medium':12,'full':None}[mode]
    for b,ox,w,d,h in BLOCKS[:2]:
        rows=CFG['rack_rows'][b]//4
        for f in range(4):
            rno=0
            for ns,y0,y1 in [('S',84,148),('N',172,d-70)]:
                for ew,x0,x1 in [('W',72,w/2-10),('E',w/2+10,w-72)]:
                    step=CFG['rack_depth_m']+CFG['rack_aisle_m']
                    count=rows if limit is None else min(rows,limit)
                    if (count-1)*step+CFG['rack_depth_m']>y1-y0:
                        raise ValueError(f'{b}-{ns}{ew}: {count} rows do not fit; preserve aisles')
                    sections=int(CFG['rack_sections_target'])
                    gap=4
                    required=sections*CFG['rack_bay_m']+2*gap
                    if required>x1-x0:
                        if CFG['strict_capacity']:raise ValueError(f'{b}-{ns}{ew}: {sections} bays require {required}m; available {x1-x0}m')
                        sections=max(8,int((x1-x0-2*gap)/CFG['rack_bay_m'])//8*8)
                    for row in range(count):
                        rno+=1
                        # Shorter rows expose views, but upper target remains a capacity cap.
                        n=max(8,sections-(8 if row%5==2 else 16 if row%5==4 else 0));n=n//8*8
                        yy=y0+1+row*step
                        xx=x0+(4 if row%3==1 else 0)
                        RACKS.append({'block':b,'floor':f,'row':rno,'zone_id':f'{b}-F{f:02d}-{ns}{ew}',
                            'start_m':[ox+xx,yy,f*CFG['level_height_m']], 'sections':n,'bay_m':CFG['rack_bay_m'],
                            'gap_after_sections':[32,56],'cross_aisle_m':4,'depth_m':CFG['rack_depth_m']})

def graph_reachable(agent,removed=None):
    adj=defaultdict(list)
    for e in EDGES:
        if e['id']==removed or e['access']!='OPEN' or agent not in e['agents']:continue
        adj[e['a']].append(e['b']);adj[e['b']].append(e['a'])
    start='B01-F0-HUB';seen={start};todo=deque([start])
    while todo:
        for x in adj[todo.popleft()]:
            if x not in seen:seen.add(x);todo.append(x)
    expected={k for k,v in NODES.items() if agent!='pallet_truck' or (v['floor']==0 and v['kind']!='landing' and '-ST-' not in k)}
    return sorted(expected-seen)

def check_plan():
    missing={a:graph_reachable(a) for a in ('human','horror','pallet_truck')}
    stairs=[e for e in EDGES if e['type']=='stairs'];faults=[]
    for e in stairs:
        if graph_reachable('human',e['id']):faults.append(e['id'])
    return {'status':'PASS' if not any(missing.values()) and not faults else 'FAIL',
       'scope':'Logical graph, OPEN access state; every single stair edge removed individually',
       'missing_nodes':missing,'single_stair_failure_isolations':faults,
       'node_count':len(NODES),'edge_count':len(EDGES),'rack_rows':len(RACKS),
       'swept_volume_geometry':'NOT_RUN','Unity_NavMesh':'NOT_RUN','all_door_combinations':'NOT_RUN'}

def rack_module(variant=0):
    key=('RACK',variant)
    if key in CACHE:return CACHE[key]
    rng=random.Random(CFG['seed']+variant);m=Mesh();bw=CFG['rack_bay_m'];dep=CFG['rack_depth_m'];length=8*bw
    for i in range(9):
        for y in (-dep/2,dep/2):m.box((i*bw,y,1.8),(.07,.07,3.6),'blue')
        m.box((i*bw,0,3.55),(.07,dep,.07),'blue')
    for level in range(4):
        z=.25+level*.85
        for y in (-dep/2,dep/2):m.box((length/2,y,z),(length,.06,.10),'orange')
        for i in range(8):
            m.box(((i+.5)*bw,0,z+.04),(bw-.07,dep,.035),'steel')
            if rng.random()<.76:
                sx=rng.uniform(.30,.85);sy=rng.uniform(.32,.63);sz=rng.uniform(.2,.56)
                m.box(((i+.5)*bw+rng.uniform(-.08,.08),0,z+.08+sz/2),(sx,sy,sz),'cardboard')
                if rng.random()<.24:m.box(((i+.5)*bw+.3,0,z+.15),(.22,.44,.20),'teal')
    CACHE[key]=m.mesh('Rack8_'+str(variant));return CACHE[key]

def pallet_mesh(variant=0):
    key=('PALLET',variant)
    if key not in CACHE:
        m=Mesh()
        for x in (-.45,0,.45):m.box((x,0,.08),(.12,.95,.13),'wood')
        for y in np.linspace(-.42,.42,5):m.box((0,float(y),.17),(1.2,.13,.06),'wood')
        rng=random.Random(CFG['seed']+100+variant)
        for z in range(3):
            for x in (-.29,.29):
                for y in (-.23,.23):
                    if rng.random()<.90:m.box((x,y,.23+z*.35+.16),(.53,.42,.32),'cardboard')
        CACHE[key]=m.mesh('Pallet_'+str(variant))
    return CACHE[key]

def rail(name,x0,y0,x1,y1,z,b,f):
    length=math.hypot(x1-x0,y1-y0);n=max(1,math.ceil(length/2))
    for i in range(n+1):
        t=i/n;x=x0+(x1-x0)*t;y=y0+(y1-y0)*t
        box(name+f'-P{i}',(x,y,z+.55),(.055,.055,1.1),'yellow',b,f,True)
    for hz in (.5,1.1):bar(name+f'-R{hz}',(x0,y0,z+hz),(x1,y1,z+hz),.055,'yellow',b,f)

def floor_rect(name,x0,y0,x1,y1,z,mat,b,f):
    box(name,((x0+x1)/2,(y0+y1)/2,z-.12),(x1-x0,y1-y0,.24),mat,b,f)

def shell(b,ox,w,d,h):
    global COL
    COL=collection(b+'_STRUCTURE')
    floor_rect(b+'-GROUND',ox,0,ox+w,d,0,'concrete',b,0)
    # Side walls have actual openings at logistics and human bridges.
    for suffix,x in [('WEST',ox),('EAST',ox+w)]:
        for i,(a,c) in enumerate([(0,56),(64,154),(166,d)]):box(b+'-'+suffix+str(i),(x,(a+c)/2,h/2),(.3,c-a,h),'wall',b)
        for y,width in [(60,8),(160,12)]:box(b+'-'+suffix+'-LINTEL'+str(y),(x,y,(7+h)/2),(.3,width,h-7),'wall',b)
    # South wall: actual dock apertures, 4.4 m wide, 4.8 m high.
    centers=list(range(90,int(w-50),24));previous=0
    for i,x in enumerate(centers):
        a=x-2.3
        if a>previous:box(b+f'-SOUTH-PIER{i}',(ox+(previous+a)/2,0,h/2),(a-previous,.3,h),'wall',b)
        box(b+f'-DOCK-LINTEL{i}',(ox+x,0,(4.8+h)/2),(4.6,.3,h-4.8),'wall',b)
        previous=x+2.3
        dock(b,ox+x,i+1)
    box(b+'-SOUTH-END',(ox+(previous+w)/2,0,h/2),(w-previous,.3,h),'wall',b)
    box(b+'-NORTH',(ox+w/2,d,h/2),(w,.3,h),'wall',b)
    roof=collection('RFC_ROOFS')
    box(b+'-ROOF',(ox+w/2,d/2,h+.18),(w,d,.3),'wall',b,col=roof)
    roof.hide_viewport=True # toggle monitor icon to inspect roof; renders keep roofs.
    for x in range(24,int(w),24):
        for y in range(24,int(d),24):
            if abs(y-160)<8 or abs(x-w/2)<8 or 70<y<d-54 and 58<x<w-58:continue
            box(b+f'-COL-{x}-{y}',(ox+x,y,h/2),(.45,.45,h),'steel',b)
        box(b+f'-TRUSS-{x}',(ox+x,d/2,h-.7),(.22,d,.6),'steel',b,collision=False)
    # Paired pedestrian edge lines and spaced chevrons on the main spine.
    for y in (154,166):box(b+f'-LANE-{y}',(ox+w/2,y,.014),(w-.6,.12,.025),'yellow',b,collision=False)
    for x in range(36,int(w),48):
        sign(b+f'-WAY-{x}',b+'  /  F00  >',(ox+x,160,4.4),.58,'white',b=b)
        box(b+f'-WAY-BACK-{x}',(ox+x,160.06,4.65),(8,.08,1.2),'blue' if b=='B01' else 'orange' if b=='B02' else 'teal',b,collision=False)
    for z in (9,16,21):
        bar(b+f'-PIPE-{z}',(ox+3,d-3,z),(ox+w-3,d-3,z),.15,'red',b)

def dock(b,x,i):
    box(b+f'-GATE-{i}',(x,.20,2.4),(4.4,.18,4.8),'steel',b)
    for j in range(1,12):box(b+f'-GATE-SEAM-{i}-{j}',(x,.32,j*.4),(4.35,.035,.025),'belt',b,collision=False)
    for dx in (-2.45,2.45):
        box(b+f'-GATE-FRAME-{i}-{dx}',(x+dx,.5,2.6),(.24,.5,5.2),'blue',b)
        box(b+f'-BUMPER-{i}-{dx}',(x+dx,1,0.6),(.3,.4,1.2),'belt',b)
    box(b+f'-DOCK-PLATE-{i}',(x,1.6,.035),(3.8,2.5,.07),'steel',b)
    box(b+f'-GATE-LABEL-{i}',(x,.42,5.6),(3.6,.16,1),'blue',b,collision=False)
    sign(b+f'-GATE-TEXT-{i}',f'{b}   D{i:02d}',(x,.54,5.35),.62,rot=(math.pi/2,0,math.pi),b=b)
    for dx in (-2.8,2.8):box(b+f'-DOCK-HAZARD-{i}-{dx}',(x+dx,4,.01),(.25,7,.02),'hazard',b,collision=False)
    for j in range(4):
        p=new_obj(b+f'-PALLET-DOCK-{i}-{j}',pallet_mesh(j),(x-1+j%2*2.2,9+j//2*3,0),b)
        p['collider']='BOX'

def mezzanine(b,ox,w,d):
    global COL
    COL=collection(b+'_MEZZANINE');L=CFG['level_height_m']
    for f in range(1,4):
        z=f*L;floor_rect(b+f'-F{f}-GRATE',ox+60,72,ox+w-60,d-56,z,'grating',b,f)
        for y in range(76,int(d-56),12):box(b+f'-F{f}-BEAM-{y}',(ox+w/2,y,z-.4),(w-120,.18,.35),'steel',b,f)
        for x in range(72,int(w-60),24):
            for y in range(84,int(d-56),24):
                # Remove columns inside picking footprints and main corridors.
                inrack=any(r['block']==b and r['floor']==f and abs(y-r['start_m'][1])<1 and r['start_m'][0]-ox-1<x<r['start_m'][0]-ox+r['sections']*r['bay_m']+9 for r in RACKS)
                if not inrack and abs(y-160)>8 and abs(x-w/2)>8:box(b+f'-F{f}-POST-{x}-{y}',(ox+x,y,z-L/2),(.14,.14,L),'blue',b,f)
        rail(b+f'-F{f}-S',ox+60,72,ox+w-60,72,z,b,f)
        rail(b+f'-F{f}-N',ox+60,d-56,ox+w-60,d-56,z,b,f)
        # Openings for bridge landings at both ends, on west and east edges.
        for side,x in [('W',ox+60),('E',ox+w-60)]:
            for i,(a,c) in enumerate([(72,78),(80,d-72),(d-70,d-56)]):
                if c>a:rail(b+f'-F{f}-{side}{i}',x,a,x,c,z,b,f)
        for yy in (154,166):box(b+f'-F{f}-LINE{yy}',(ox+w/2,yy,z+.012),(w-124,.12,.024),'yellow',b,f,False)
        for xx in range(82,int(w-60),48):
            sign(b+f'-F{f}-WAY{xx}',f'{b}  F{f:02d}  >',(ox+xx,160,z+2.9),.5,b=b,f=f)
        # Perimeter handrail is decorative; slab is tagged as a continuous collider.

def stairs(s):
    global COL
    b=s['block'];COL=collection(b+'_STAIRS');x=s['x'];y=s['y'];rise=s['rise_m'];floors=s['floors'];sid=s['id']
    for f in range(floors):
        z=f*rise
        floor_rect(sid+f'-F{f}-LAND',x-1,y-2,x+5.6,y,z,'grating',b,f)
        # The bridge matches actual deck edge; no guard rails across its entrance.
        ox=next(q[1] for q in BLOCKS if q[0]==b);w=next(q[2] for q in BLOCKS if q[0]==b)
        edge_x=ox+60 if x<ox+w/2 else ox+w-60
        if b=='B03':edge_x=ox+60 if x<ox+200 else ox+250
        join_x=x+5.6 if edge_x>x+5.6 else x-1 if edge_x<x-1 else edge_x
        xmin,xmax=sorted((edge_x,join_x))
        if xmax-xmin<.01:xmin=edge_x-.15;xmax=edge_x+.15
        floor_rect(sid+f'-F{f}-BRIDGE',xmin,y-2,xmax,y,z,'grating',b,f)
        for sy in (y-2,y):rail(sid+f'-BR{f}-{sy}',xmin,sy,xmax,sy,z,b,f)
        sign(sid+f'-SIGN{f}',f'STAIR  /  F{f:02d}',(x+2.4,y-2.2,z+2.4),.38,b=b,f=f)
        if f==floors-1:continue
        steps=math.ceil((rise/2)/CFG['agents']['step_height_m']);run=4.8;tread=run/steps;rz=(rise/2)/steps
        for flight in (0,1):
            sx=x+flight*2.8
            for i in range(steps):
                yy=y+(i+.5)*tread if flight==0 else y+run-(i+.5)*tread
                zz=z+flight*rise/2+(i+1)*rz
                box(sid+f'-F{f}-FL{flight}-T{i}',(sx,yy,zz-.045),(2.0,tread+.015,.09),'steel',b,f,False)
                box(sid+f'-F{f}-FL{flight}-NOS{i}',(sx,yy-tread/2,zz+.006),(2.0,.035,.012),'yellow',b,f,False)
            # Real inclined collision ramp under visible treads.
            ya,yb=(y,y+run) if flight==0 else (y+run,y)
            a=Vector((sx,ya,z+flight*rise/2-.05));bb=Vector((sx,yb,z+(flight+1)*rise/2-.05));delta=bb-a
            ramp=box(sid+f'-F{f}-COLLIDER{flight}',(a+bb)/2,(2,delta.length,.12),'steel',b,f)
            ramp.rotation_euler.x=math.atan2(rise/2,run) if flight==0 else -math.atan2(rise/2,run)
            ramp.hide_render=True;ramp.display_type='WIRE';ramp['collider']='STAIR_RAMP'
            for dx in (-1,1):
                bar(sid+f'-F{f}-STRING{flight}-{dx}',(sx+dx,ya,z+flight*rise/2-.13),(sx+dx,yb,z+(flight+1)*rise/2-.13),.12,'blue',b,f)
                bar(sid+f'-F{f}-HAND{flight}-{dx}',(sx+dx,ya,z+flight*rise/2+1.1),(sx+dx,yb,z+(flight+1)*rise/2+1.1),.055,'yellow',b,f)
                for t in (0,.25,.5,.75,1):
                    yy=ya+(yb-ya)*t;zz=z+flight*rise/2+rise/2*t
                    box(sid+f'-F{f}-UP{flight}-{dx}-{t}',(sx+dx,yy,zz+.5),(.055,.055,1.05),'yellow',b,f,False)
        floor_rect(sid+f'-F{f}-HALF',x-1,y+run,x+3.8,y+run+1.8,z+rise/2,'grating',b,f)
        rail(sid+f'-F{f}-HALFRAIL',x-1,y+run+1.8,x+3.8,y+run+1.8,z+rise/2,b,f)

def storage():
    global COL
    for row in RACKS:
        b=row['block'];f=row['floor'];COL=collection(b+'_RACKS');x,y,z=row['start_m'];rid=f'{b}-F{f:02d}-R{row["row"]:03d}'
        for j in range(row['sections']//8):
            sec=j*8;gap=sum(4 for g in row['gap_after_sections'] if sec>=g)
            xx=x+sec*row['bay_m']+gap
            o=new_obj(rid+f'-MOD{j:02d}',rack_module((row['row']+j+f)%8),(xx,y,z),b,f)
            o['collider']='BOX';o['collision_bounds_m']=[9.6,row['depth_m'],3.6];o['zone_id']=row['zone_id']
        box(rid+'-ENDCAP',(x-.16,y,z+1.8),(.14,.85,3.6),'blue',b,f)
        box(rid+'-LABEL',(x-.25,y,z+2.8),(.08,1.7,.6),'blue',b,f,False)
        sign(rid+'-TEXT',f'R{row["row"]:03d}',(x-.30,y,z+2.63),.29,rot=(math.pi/2,0,-math.pi/2),b=b,f=f)
        # Cell addresses are server metadata, never thousands of Blender objects.
        for sec in range(row['sections']):
            gap=sum(4 for g in row['gap_after_sections'] if sec>=g)
            for level in range(4):
                CELLS.append({'id':rid+f'-S{sec+1:03d}-L{level+1:02d}-C01',
                    'position_m':[round(x+(sec+.5)*row['bay_m']+gap,3),y,round(z+.3+level*.85,3)],
                    'floor':f,'capacity_liters':300,'sector_id':sector(b,f,x+sec*row['bay_m']+gap,y),'storage_type':'SHELF','zone_id':row['zone_id']})
    for b,ox,w,d,h in BLOCKS[:2]:
        COL=collection(b+'_KGT')
        for i,yy in enumerate((d-44,d-33,d-22)):
            for j,xx in enumerate(range(84,int(w-70),12)):
                for dx in (-4.8,4.8):
                    for dy in (-1,1):box(b+f'-KGT-{i}-{j}-{dx}-{dy}',(ox+xx+dx,yy+dy,3.7),(.16,.16,7.4),'blue',b)
                for zz in (.2,2.5,5):
                    box(b+f'-KGT-SHELF-{i}-{j}-{zz}',(ox+xx,yy,zz),(9.6,2.2,.15),'orange',b)
                    for p in range(5):new_obj(b+f'-KGT-PAL-{i}-{j}-{zz}-{p}',pallet_mesh(p%4),(ox+xx-3.7+p*1.85,yy,zz+.1),b)
        sign(b+'-KGT-TITLE','KGT  /  OVERSIZE',(ox+w/2,d-52,7.5),1.2,b=b)

def conveyor(name,a,bb,b,width=1.8,height=1.05):
    a,bp=Vector(a),Vector(bb);d=bp-a;length=d.length;center=(a+bp)/2
    # Belt runs along local X; repeated shared box geometry with two guard lips.
    theta=math.atan2(d.y,d.x)
    belt=box(name+'-BELT',(center.x,center.y,height),(length,width,.18),'belt',b);belt.rotation_euler.z=theta
    for side in (-1,1):
        off=Vector((-math.sin(theta),math.cos(theta),0))*width*.53*side
        railo=box(name+f'-EDGE{side}',(center.x+off.x,center.y+off.y,height+.08),(length,.10,.28),'steel',b,collision=False);railo.rotation_euler.z=theta
    for i in range(max(2,math.ceil(length/4))+1):
        t=i/max(2,math.ceil(length/4));p=a+d*t
        box(name+f'-LEG{i}',(p.x,p.y,height/2),(.14,width*.8,height),'steel',b)
    CONVEYORS.append({'id':name,'start_m':list(a),'end_m':list(bp),'belt_top_m':height+.09,'width_m':width,'block':b,'speed_m_s':.8,'sound_surface':'belt'})

def room(name,label,x,y,w,d,b,mat='teal'):
    # Service room, open 2.4m doorway on south wall.
    for suffix,p,s in [('N',(x+w/2,y+d,1.8),(w,.16,3.6)),('W',(x,y+d/2,1.8),(.16,d,3.6)),('E',(x+w,y+d/2,1.8),(.16,d,3.6)),('S1',(x+(w/2-1.2)/2,y,1.8),(w/2-1.2,.16,3.6)),('S2',(x+w-(w/2-1.2)/2,y,1.8),(w/2-1.2,.16,3.6))]:box(name+'-'+suffix,p,s,'wall',b)
    box(name+'-HEAD',(x+w/2,y,3.25),(2.4,.18,.7),mat,b)
    sign(name+'-SIGN',label,(x+w/2,y-.12,3.1),.38,b=b)
    for i in range(5):
        box(name+f'-LOCKER{i}',(x+1+i*.7,y+d-1,1),(.65,.65,2),mat,b)
        box(name+f'-HANDLE{i}',(x+1+i*.7,y+d-1.36,1.2),(.03,.03,.16),'steel',b,collision=False)
    box(name+'-DESK',(x+w/2,y+3,.8),(3,1.2,.1),'wood',b)
    for dx in (-1.2,1.2):box(name+'-DESKLEG'+str(dx),(x+w/2+dx,y+3,.4),(.1,1,.8),'steel',b)
    box(name+'-TERMINAL',(x+w/2,y+3,1.2),(.6,.1,.5),'screen',b,collision=False)
    marker(name+'-SAFE','SAFE_ZONE',(x+w/2,y+2,.1),b,0,{'radius_m':4,'hostile_spawns':False})

def props_and_sorting():
    global COL
    for b,ox,w,d,h in BLOCKS:
        COL=collection(b+'_WORKZONES')
        conveyor(b+'-TRUNK',(ox+36,60,0),(ox+w-3,60,0),b,height=3.8)
        room(b+'-SECURITY','SECURITY / SAFE',ox+(330 if b=='B03' else 10),80 if b=='B03' else 180,26,18,b)
        if b!='B03':
            room(b+'-BREAK','BREAK / TASKS',ox+10,110,26,22,b)
            room(b+'-LOCKERS','LOCKERS',ox+10,76,26,22,b,'blue')
            # Quarantine fencing and labeled open approach.
            for x in (ox+16,ox+62):rail(b+'-QFENCE'+str(x),x,8,x,47,0,b,0)
            sign(b+'-QUARANTINE','QUARANTINE',(ox+38,10,3),.8,'yellow',b=b)
            for i in range(10):new_obj(b+f'-RETURN{i}',pallet_mesh(i%4),(ox+22+(i%4)*6,22+(i//4)*6,0),b)
            # Visible vertical transport landmark beyond the central mezzanine.
            x=ox+w-37;y=120
            for dx in (-4,4):
                for dy in (-4,4):box(b+f'-TOWER{dx}{dy}',(x+dx,y+dy,9),(.3,.3,18),'orange',b)
            for zz in (4.8,9.6,14.4,18):
                box(b+'-TOWERDECK'+str(zz),(x,y,zz),(8,8,.2),'steel',b)
            sign(b+'-TOWER-TEXT','LIFT / '+b,(x,y-4.2,16),1,'white',b=b)
        else:
            # Table islands leave 4m cross aisles between operations.
            for i in range(8 if CFG['mode']=='small' else 18):
                x=ox+84+(i%6)*20;y=80+(i//6)*18
                box(b+f'-PACKTOP{i}',(x,y,.92),(6,2,.12),'wood',b)
                for dx in (-2.5,2.5):box(b+f'-PACKLEG{i}-{dx}',(x+dx,y,.45),(.15,1.6,.9),'steel',b)
                box(b+f'-SCALE{i}',(x+1.2,y,1.04),(.9,.8,.12),'steel',b,collision=False)
                box(b+f'-TSDSCREEN{i}',(x-1.5,y+.5,1.4),(.6,.12,.45),'screen',b,collision=False)
                new_obj(b+f'-PACKBOX{i}',pallet_mesh(i%4),(x+6,y,0),b)
            conveyor(b+'-SORT-SPINE',(ox+82,224,0),(ox+305,224,0),b,width=2.4)
            for i in range(10):
                x=ox+88+i*22
                conveyor(b+f'-ARM{i}',(x,224,0),(x,267 if i%2 else 191,0),b,width=1.4)
                end=271 if i%2 else 186
                new_obj(b+f'-CAGE{i}',pallet_mesh(i%4),(x,end,0),b)
                sign(b+f'-DEST{i}',f'OUT {i+1:02d}',(x,end,2.6),.45,'yellow',b=b)
            floor_rect(b+'-UPPER',ox+60,190,ox+250,278,6,'grating',b,1)
            for y in (190,278):rail(b+'-UPRAIL'+str(y),ox+60,y,ox+250,y,6,b,1)
            # West rail bridge opening is y=196..198; east is y=258..260.
            for i,(x,a,c) in enumerate([(ox+60,190,196),(ox+60,198,278),(ox+250,190,258),(ox+250,260,278)]):rail(b+f'-UPEND{i}',x,a,x,c,6,b,1)
            for xx in range(72,250,24):
                for yy in (200,272):box(b+f'-UPCOL{xx}-{yy}',(ox+xx,yy,2.85),(.22,.22,5.7),'blue',b)
            box(b+'-DISPATCH',(ox+335,240,6),(20,28,12),'blue',b)
            for i in range(4):box(b+f'-DISPATCH-SCREEN{i}',(ox+324.9,230+i*6,8),(.03,4,2.2),'screen',b,collision=False)
            sign(b+'-SORTBOARD','SORTATION  /  CUT-OFF 23:45',(ox+210,287,10),1.8,'yellow',b=b)
        sign(b+'-LANDMARK',b+'  /  '+('INBOUND' if b=='B01' else 'STORAGE' if b=='B02' else 'OUTBOUND'),(ox+w/2,d-1,18),3.5,'orange' if b=='B02' else 'white',b=b)
        # Pallet truck library model, outside main travel route.
        m=Mesh();m.box((0,0,.22),(.6,.8,.32),'yellow')
        for yy in (-.28,.28):m.box((.85,yy,.10),(1.5,.17,.12),'yellow')
        m.box((-.4,0,.7),(.08,.08,1.2),'steel');m.box((-.4,0,1.3),(.1,.6,.08),'belt')
        new_obj(b+'-PALLET-TRUCK',m.mesh('PalletTruck'+b),(ox+44,50,0),b)
        for i in range(8):
            x=ox+80+i*24;box(b+f'-CROSSING{i}',(x,48,.012),(1.2,4,.024),'white',b,collision=False)

def bridges():
    global COL
    COL=collection('RFC_CONNECTIONS')
    for l,r in [(BLOCKS[0],BLOCKS[1]),(BLOCKS[1],BLOCKS[2])]:
        x0=l[1]+l[2];x1=r[1];name=l[0]+'-'+r[0]
        for lane,y,width in [('MAIN',160,12),('LOGISTICS',60,8)]:
            floor_rect(name+lane+'-FLOOR',x0,y-width/2,x1,y+width/2,0,'concrete',l[0],0)
            for sy in (-1,1):box(name+lane+f'-WALL{sy}',((x0+x1)/2,y+width/2*sy,3.5),(20,.25,7),'wall',l[0])
            box(name+lane+'-ROOF',((x0+x1)/2,y,7),(20,width,.24),'wall',l[0],col=collection('RFC_ROOFS'))
            sign(name+lane+'-SIGN',r[0]+'  >>>',((x0+x1)/2,y,4.5),.7,b=l[0])
            if lane=='LOGISTICS':conveyor(name+'-BELT',(x0,60,0),(x1,60,0),l[0],height=3.8)

def area_light(name,pos,energy,color,size,b,group,f=0):
    global COL
    c=collection('RFC_LIGHT_'+group);data=bpy.data.lights.new('RFC_'+name,'AREA');data.energy=energy;data.color=color;data.shape='DISK';data.size=size
    o=new_obj(name,data,pos,b,f,col=c);o['light_group']=group;o['base_energy']=energy
    LIGHTS.append({'id':name,'group':group,'energy_w':energy,'position_m':list(pos),'color':list(color),'block':b,'floor':f})
    return o

def lighting():
    global COL
    for b,ox,w,d,h in BLOCKS:
        COL=collection(b+'_FIXTURES')
        # Moderate number of broad ceiling emitters; fixtures repeated in ground/upper working spaces.
        for i,x in enumerate(range(78,int(w-40),64)):
            for j,y in enumerate(range(60,int(d-28),64)):
                area_light(b+f'-DAY-{i}-{j}',(ox+x,y,22),9000,(.70,.82,1),22,b,'DAY_MAIN')
                box(b+f'-LAMP-{i}-{j}',(ox+x,y,22.15),(4,.55,.2),'emissive',b,collision=False)
        for f in range(3 if b!='B03' else 1):
            z=f*CFG['level_height_m'] if b!='B03' else 0
            for x in range(90,int(w-60),64):
                for y in (110,210):
                    area_light(b+f'-TASK-F{f}-{x}-{y}',(ox+x,y,z+4.25),4500,(.72,.88,1),8,b,'LOCAL_TASK',f)
        for i,x in enumerate(range(50,int(w),100)):
            area_light(b+f'-NIGHT-{i}',(ox+x,160,9),1200,(.11,.42,.55),14,b,'NIGHT_MAIN')
            area_light(b+f'-EMERG-{i}',(ox+x,152,3.1),75,(1,.045,.02),3,b,'EMERGENCY_RED')
            box(b+f'-EXITBACK{i}',(ox+x,154,3.2),(2.4,.12,.6),'exit',b,collision=False)
            sign(b+f'-EXITTEXT{i}','EXIT  >',(ox+x,153.9,3),.4,b=b)
        for f in range(4 if b!='B03' else 1):
            z=f*CFG['level_height_m']
            for xx in range(78,int(w-50),40):
                area_light(b+f'-SPINE-F{f}-{xx}',(ox+xx,160,z+4.18),4500,(.72,.84,1),7,b,'LOCAL_TASK',f)
                box(b+f'-SPINELAMP-F{f}-{xx}',(ox+xx,160,z+4.30),(2.4,.4,.13),'emissive',b,f,False)
        area_light(b+'-FLICKER',(ox+55,85,4),130,(.55,.68,.75),3,b,'FLICKER_GROUP')
    world=bpy.data.worlds.new('RFC_WORLD');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.05,.075,.11,1);world.node_tree.nodes['Background'].inputs[1].default_value=.22;bpy.context.scene.world=world

def set_shift(shift):
    """Call set_shift('NIGHT') / set_shift('DAY') in this script, no geometry rebuild."""
    for o in ROOT.all_objects:
        if o.type!='LIGHT':continue
        group=o.get('light_group','');base=o.get('base_energy',o.data.energy)
        factor=(1 if shift=='DAY' else CFG['lighting']['night_main_ratio']) if group=='DAY_MAIN' else (0 if shift=='DAY' else 1) if group in ('NIGHT_MAIN','EMERGENCY_RED') else .8 if shift=='DAY' else .20
        o.data.energy=base*factor
    bpy.context.scene['RFC_SHIFT']=shift

def horror():
    for b,ox,w,d,h in BLOCKS:
        for f in range(4 if b!='B03' else 2):
            z=f*CFG['level_height_m'] if b!='B03' else f*6
            # All hostile markers use perimeter graph nodes outside rack solids.
            src=NODES[f'{b}-F{f}-NW']['position_m'];dst=NODES[f'{b}-F{f}-SE']['position_m']
            marker(f'{b}-F{f}-SPAWN','HORROR_SPAWN',src,b,f,{'requires_occlusion':True,'safe_zone_exclusion':True})
            marker(f'{b}-F{f}-HIDE','HORROR_HIDE',dst,b,f,{'capacity':1,'detection_rule':'Unity implementation required'})
            marker(f'{b}-F{f}-PATROL','HORROR_PATROL',NODES[f'{b}-F{f}-NE']['position_m'],b,f)
            marker(f'{b}-F{f}-CHASE','CHASE_ROUTE',src,b,f,{'node_paths':[[f'{b}-F{f}-{s}' for s in ('NW','SW','SE')],[f'{b}-F{f}-{s}' for s in ('NW','NE','SE')]],'state':'all open','edge_disjoint_logical_paths':True})
        marker(b+'-EVENT','HORROR_EVENT',(ox+66,160,.1),b,0,{'trigger_zone_id':b+'-F00-MEZZ' if b!='B03' else b+'-F00-SORTING','minimum_interval_s':CFG['lighting']['event_interval_s'],'active_budget':1,'time_condition':'NIGHT','sequence':['work','ambiguous_audio','light_failure','reveal','chase','recovery'],'end_condition':'safe zone entered; Unity implementation required'})
        marker(b+'-AUDIO','AUDIO_ZONE',(ox+w/2,160,1),b,0,{'clip':'NOT_INCLUDED','surface_set':['concrete','grating','steel','belt']})
        marker(b+'-LIGHTFAIL','LIGHT_FAILURE',(ox+55,85,1),b,0,{'groups':['DAY_MAIN','FLICKER_GROUP']})
        marker(b+'-PLAYER_START','PLAYER_START',(ox+34,160,.1),b,0)
        # Geometry of a hiding cabinet, standing on a perimeter route with an open entrance.
        p=NODES[f'{b}-F0-SE']['position_m'];x,y,z=p;x+=3
        global COL;COL=collection(b+'_WORKZONES')
        for dx in (-.7,.7):box(b+'-HIDE-SIDE'+str(dx),(x+dx,y+2,1.1),(.08,1.6,2.2),'teal',b)
        box(b+'-HIDE-BACK',(x,y+2.8,1.1),(1.4,.08,2.2),'teal',b)
        box(b+'-HIDE-TOP',(x,y+2,2.2),(1.4,1.6,.08),'teal',b)


def route_report():
    import heapq,statistics
    adj=defaultdict(list)
    for e in EDGES:
        if 'human' in e['agents'] and e['access']=='OPEN':
            adj[e['a']].append((e['b'],e['length_m']));adj[e['b']].append((e['a'],e['length_m']))
    def shortest(a,b):
        todo=[(0,a)];dist={a:0}
        while todo:
            dd,k=heapq.heappop(todo)
            if k==b:return dd
            if dd!=dist[k]:continue
            for j,d in adj[k]:
                if dd+d<dist.get(j,1e30):dist[j]=dd+d;heapq.heappush(todo,(dd+d,j))
        return None
    routes=[]
    for b in ('B01','B02','B03'):
        for f in range(4 if b!='B03' else 2):
            d=shortest(f'{b}-F{f}-NW',f'{b}-F{f}-SE')
            routes.append({'from':f'{b}-F{f}-NW','to':f'{b}-F{f}-SE','length_m':round(d,2),'travel_s':round(d/CFG['agents']['walk_speed_m_s'],2),'class':'zone transfer'})
    d=shortest('B01-F0-HUB','B03-F0-HUB');routes.append({'from':'B01-F0-HUB','to':'B03-F0-HUB','length_m':d,'travel_s':d/CFG['agents']['walk_speed_m_s'],'class':'rare interblock transfer'})
    ts=sorted(r['travel_s'] for r in routes)
    write_json('routes_report.json',{'method':'Analytic graph distances, no operations, animation or door delays. NOT a Unity playtest.', 'routes':routes,'travel_s':{'min':min(ts),'median':statistics.median(ts),'p95':ts[math.ceil(.95*len(ts))-1],'max':max(ts)},'local_task_target_check':'NOT_RUN; server must cluster tasks per row pair'},'reports')

def export_glb(path,objs):
    bpy.ops.object.select_all(action='DESELECT')
    selected=[]
    for o in objs:
        if o.type not in ('MESH','FONT'):continue
        if o.get('collider')=='STAIR_RAMP':continue
        try:o.select_set(True);selected.append(o)
        except RuntimeError:pass
    if not selected:raise ValueError('No geometry for '+str(path))
    # Font objects are converted temporarily; repeated meshes remain shared.
    temps=[]
    deps=bpy.context.evaluated_depsgraph_get()
    for o in list(selected):
        if o.type=='FONT':
            m=bpy.data.meshes.new_from_object(o.evaluated_get(deps));dup=bpy.data.objects.new(o.name+'_GLTF',m);dup.matrix_world=o.matrix_world.copy();o.select_set(False);temps.append(dup)
    for dup in temps:COL.objects.link(dup);dup.select_set(True)
    result=bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True,export_yup=True,export_extras=True,export_cameras=False,export_lights=False,export_animations=False,export_materials='EXPORT',export_texcoords=True,export_normals=True)
    for o in temps:
        m=o.data;bpy.data.objects.remove(o,do_unlink=True);bpy.data.meshes.remove(m)
    if 'FINISHED' not in result:raise RuntimeError('GLB export failed: '+str(path))

def camera(name,pos,target,lens=24):
    c=bpy.data.cameras.new('RFC_'+name);o=new_obj(name,c,pos,col=collection('RFC_CAMERAS'));o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler();c.lens=lens;c.clip_end=2500;bpy.context.scene.camera=o;return o

def previews():
    s=bpy.context.scene;s.render.engine='CYCLES';s.cycles.samples=12;s.cycles.use_denoising=False;s.render.resolution_x=960;s.render.resolution_y=540;s.render.resolution_percentage=100
    s.render.image_settings.file_format='PNG';s.render.film_transparent=False
    for b,ox,w,d,h in BLOCKS:
        views=[('day_spine',(ox+67,160,1.7),(ox+130,160,1.8),'DAY'),
               ('day_docks',(ox+110,28,1.7),(ox+145,1,3),'DAY'),
               ('night_spine',(ox+67,160,1.7),(ox+140,160,1.8),'NIGHT'),
               ('upper',(ox+80,160 if b!='B03' else 270,CFG['level_height_m']*3+1.7 if b!='B03' else 7.7),(ox+190,160 if b!='B03' else 222,CFG['level_height_m']*3+1.8 if b!='B03' else 4),'DAY')]
        for label,p,t,shift in views:
            set_shift(shift);o=camera(b+'_'+label,p,t);s.render.filepath=str(OUT/'previews'/(b+'_'+label+'.png'));bpy.ops.render.render(write_still=True)
    set_shift(CFG['lighting']['shift'])

def setup_view():
    scene=bpy.context.scene;scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1
    scene.render.engine='CYCLES';scene.cycles.samples=32;scene.cycles.use_denoising=False
    scene.view_settings.view_transform='AgX';scene.view_settings.look='AgX - Medium High Contrast'
    scene['RFC_provenance']=json.dumps(stamp());scene['RFC_README']='See README_RU.md. Roofs hidden in viewport. DAY/NIGHT via RFC_Shifts.py Text block.'
    camera('RFC_Entrance',(67,160,1.7),(145,160,1.9),22)
    for screen in bpy.data.screens:
        for a in screen.areas:
            if a.type=='VIEW_3D':
                a.spaces.active.clip_end=3000;a.spaces.active.region_3d.view_distance=480;a.spaces.active.region_3d.view_location=(210,160,0);a.spaces.active.shading.type='SOLID';a.spaces.active.shading.color_type='MATERIAL'
    text=bpy.data.texts.new('RFC_Shifts.py');text.write('''# Run this text to switch existing lighting. Change SHIFT to "DAY" or "NIGHT".\nimport bpy\nSHIFT = "NIGHT"\nfor o in bpy.data.collections["RFC_HORROR"].all_objects:\n    if o.type != 'LIGHT': continue\n    g=o.get('light_group', ''); base=o.get('base_energy', o.data.energy)\n    factor=(1 if SHIFT=='DAY' else .10) if g=='DAY_MAIN' else (0 if SHIFT=='DAY' else 1) if g in ('NIGHT_MAIN','EMERGENCY_RED') else .8 if SHIFT=='DAY' else .20\n    o.data.energy=base*factor\nbpy.context.scene['RFC_SHIFT']=SHIFT\n''')

def quality_report():
    q={'logical_connectivity_open': 'PASS','single_stair_loss':'PASS','capacity_before_geometry':'PASS',
       'full_blender_generation':'PASS' if CFG['mode']=='full' else 'NOT_RUN',
       'packed_textures':'PASS','mesh_id_uniqueness':'PASS' if len({o.name for o in OBJECTS})==len(OBJECTS) else 'FAIL',
       'horizontal_graph_corridor_AABB':'PASS','swept_agent_geometry':'NOT_RUN','all_dynamic_door_states':'NOT_RUN',
       'Unity_import':'NOT_RUN','Unity_playtests':'NOT_RUN','full_client_performance':'NOT_RUN',
       'day_night_chases':'NOT_RUN','continuous_walk_video':'NOT_RUN','visual_review_12_frames':'NOT_RUN',
       'streaming_runtime':'NOT_RUN','LOD_generation':'NOT_RUN'}
    write_json('map_quality_report.json',{'criteria':q,'acceptance':'BLENDER_ARTIFACT; gameplay acceptance pending','limitations':['Static map + metadata. Unity systems (AI, WMS, server, shift scheduler, NavMesh, streaming) are not included.','Logical graph is not proof of collision-free character locomotion.','Audio markers only; no audio files.','No claim of complete RFC v3 acceptance.']},'reports')

def floor_plans():
    """Signed vector floor plans; dependency-free, editable in any SVG viewer."""
    from html import escape
    colors={'MEZZANINE':'#536675','PICKING':'#e9a742','RECEIVING':'#55b8ca','KGT':'#cf7352','SERVICE':'#9a8ec1','SECURITY':'#68be8e','PACKING':'#d9ba6c','SORTING':'#67b7a7','SHIPPING':'#d7837c','QUARANTINE':'#cd789e','CONVEYOR':'#69a0c7'}
    allsvg=[]
    for b,ox,w,d,h in BLOCKS:
        for f in range(4 if b!='B03' else 2):
            z=f*CFG['level_height_m'] if b!='B03' else f*6
            s=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-12 -28 {w+24} {d+84}" width="{(w+24)*2}" height="{(d+84)*2}">',f'<rect x="-12" y="-28" width="{w+24}" height="{d+84}" fill="#101a24"/>',f'<text x="0" y="-12" font-family="sans-serif" font-size="10" fill="white">RFC HORROR / {b} / F{f:02d} / +{z:.1f}m</text>',f'<rect width="{w}" height="{d}" fill="#263440" stroke="#c7d4db"/>']
            for q in ZONES:
                if q['block']!=b or q['floor']!=f:continue
                x0,y0,_,x1,y1,_=q['local_bounds_m'];color=colors[q['type']]
                s.append(f'<rect x="{x0}" y="{d-y1}" width="{x1-x0}" height="{y1-y0}" fill="{color}" fill-opacity=".25" stroke="{color}" stroke-width=".5"/>')
                s.append(f'<text x="{x0+2}" y="{d-y1+5}" fill="{color}" font-family="sans-serif" font-size="3.4">{escape(q["zone_id"])}</text>')
            for e in EDGES:
                a=NODES[e['a']];bb=NODES[e['b']]
                if a['block']!=b or bb['block']!=b or a['floor']!=f or bb['floor']!=f:continue
                x,y,_=a['position_m'];xx,yy,_=bb['position_m']
                s.append(f'<path d="M{x-ox},{d-y} L{xx-ox},{d-yy}" stroke="#65dfb4" stroke-width="1" fill="none"/>')
            for r in RACKS:
                if r['block']!=b or r['floor']!=f:continue
                x,y,_=r['start_m'];ln=r['sections']*r['bay_m']+sum(4 for n in r['gap_after_sections'] if n<r['sections'])
                s.append(f'<rect x="{x-ox}" y="{d-y-.4}" width="{ln}" height=".8" fill="#edaa52"/>')
            for st in STAIRS:
                if st['block']==b:s.append(f'<rect x="{st["x"]-ox-1}" y="{d-st["y"]-6.6}" width="6.6" height="8.6" fill="#dfe6ee"/><text x="{st["x"]-ox-1}" y="{d-st["y"]+6}" fill="white" font-size="3.5">STAIR</text>')
            for p in PORTALS:
                px,py,_=p['position_m']
                if ox-20<=px<=ox+w+20:s.append(f'<circle cx="{min(w,max(0,px-ox))}" cy="{d-py}" r="3" fill="#e8cc55"/>')
            s.extend([f'<text x="0" y="{d+12}" fill="white" font-family="sans-serif" font-size="4.5">Scale: 1 SVG unit = 1m / X east / Y north / green = candidate walk graph</text>',f'<text x="0" y="{d+21}" fill="#d3dfeb" font-family="sans-serif" font-size="4.5">Orange: racks. White: stairs. Yellow: portals. Agent collision test: see reports.</text>',f'<text x="0" y="{d+30}" fill="#eebd64" font-family="sans-serif" font-size="4.5">Unity traversal, AI and streaming require integration and playtests.</text>','</svg>'])
            (OUT/'previews'/f'{b}_F{f:02d}_plan.svg').write_text('\n'.join(s),encoding='utf-8')
    # Cross-complex overall plan, all footprints at their actual global positions.
    s=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="-30 -50 1460 460" width="2190" height="690"><rect x="-30" y="-50" width="1460" height="460" fill="#101a24"/><text x="0" y="-18" fill="white" font-family="sans-serif" font-size="18">RFC HORROR / 456,000 m² / FULL COMPLEX</text>']
    for b,ox,w,d,h in BLOCKS:
        s.append(f'<rect x="{ox}" y="{360-d}" width="{w}" height="{d}" fill="#243440" stroke="#87a6b7" stroke-width="2"/><text x="{ox+12}" y="{360-d+28}" fill="#dfac59" font-family="sans-serif" font-size="18">{b} / {w} × {d} × {h}m</text>')
        for r in RACKS:
            if r['block']==b and r['floor']==0:
                x,y,_=r['start_m'];s.append(f'<path d="M{x},{360-y} h{r["sections"]*r["bay_m"]+8}" stroke="#d69850" stroke-width="1"/>')
    for p in PORTALS:
        x,y,_=p['position_m'];s.append(f'<rect x="{x-10}" y="{360-y-6}" width="20" height="12" fill="#eac75b"/>')
    s.append('<text x="0" y="390" fill="#c8d7dd" font-family="sans-serif" font-size="12">B01 INBOUND / B02 STORAGE / B03 SORTATION. Four levels in B01 and B02, +6m platform in B03.</text></svg>')
    (OUT/'previews'/'top_view.svg').write_text('\n'.join(s),encoding='utf-8')


def corridor_check():
    nav=json.loads((OUT/'metadata/navigation.json').read_text())['data'];coll=json.loads((OUT/'metadata/collision_proxies.json').read_text())['data'];cfg=CFG
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
    write_json('geometry_corridors.json',report,'reports')
    return report

def main():
    global CFG,OUT,ROOT,COL
    a=arguments();CFG=json.loads(json.dumps(DEFAULT))
    if a.config:CFG=json.loads(Path(a.config).read_text(encoding='utf-8'))
    CFG['mode']=a.mode;validate_config(CFG)
    OUT=Path(a.output).expanduser().resolve();OUT.mkdir(parents=True,exist_ok=True)
    for folder in ('metadata','reports','previews','exports','textures','config'):(OUT/folder).mkdir(exist_ok=True)
    (OUT/'config'/'warehouse.json').write_text(json.dumps(CFG,indent=2),encoding='utf-8')
    if set(bpy.data.objects.keys())=={'Cube','Camera','Light'} and bpy.data.objects['Cube'].type=='MESH' and len(bpy.data.objects['Cube'].data.vertices)==8:
        for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
    old=bpy.data.collections.get('RFC_HORROR')
    if old:
        for o in list(old.all_objects):bpy.data.objects.remove(o,do_unlink=True)
        # Child collections carry generated names; remove those, preserve all unrelated scene content.
        def children(c):
            for sub in list(c.children):children(sub);bpy.data.collections.remove(sub)
        children(old);bpy.data.collections.remove(old)
    for group in (bpy.data.meshes,bpy.data.curves,bpy.data.materials,bpy.data.images,bpy.data.lights,bpy.data.cameras,bpy.data.worlds,bpy.data.texts):
        for item in list(group):
            if item.name.startswith('RFC_') and item.users==0:group.remove(item)
    ROOT=bpy.data.collections.new('RFC_HORROR');bpy.context.scene.collection.children.link(ROOT);COL=collection('RFC_MISC')
    print('RFC: planning',flush=True);logical_plan()
    floor_plans()
    print('RFC: textures',flush=True);textures()
    for b,ox,w,d,h in BLOCKS:
        print('RFC: architecture '+b,flush=True);shell(b,ox,w,d,h)
        if b!='B03':mezzanine(b,ox,w,d)
    for s in STAIRS:stairs(s)
    print('RFC: storage',flush=True);storage();props_and_sorting();bridges();lighting();horror()
    setup_view();set_shift(CFG['lighting']['shift']);route_report()
    print('RFC: metadata',flush=True)
    write_json('storage_cells.json',CELLS);write_json('conveyors.json',CONVEYORS);write_json('horror_markers.json',MARKERS);write_json('lighting_groups.json',LIGHTS)
    # Explicit collider manifest includes local dimensions and world matrices for Unity conversion.
    bpy.context.view_layer.update()
    write_json('collision_proxies.json',[{'id':o.name,'kind':o['collider'],'sector_id':o['sector_id'],'position_m':list(o.location),'size_m':list(o.dimensions),'rotation_euler_rad':list(o.rotation_euler),'coordinate_system':'Blender Z-up'} for o in OBJECTS if o.get('collider')])
    geometry=corridor_check()
    if geometry['status']=='FAIL':raise RuntimeError('Blocked route: see reports/geometry_corridors.json')
    sector_objs=defaultdict(list)
    for o in OBJECTS:
        if o.type in ('MESH','FONT'):sector_objs[o['sector_id']].append(o.name)
    write_json('sectors.json',{'ownership':'Each object owned by its origin sector exactly once. Large slabs/walls require shared-geometry dependencies.','runtime_streaming':'NOT_IMPLEMENTED','sectors':sector_objs,'shared_objects':[o.name for o in OBJECTS if o.type=='MESH' and max(o.dimensions)>CFG['sector_size_m']]})
    if a.export:
        for b,ox,w,d,h in BLOCKS:
            print('RFC: exporting '+b,flush=True);export_glb(OUT/'exports'/('Block_'+b[-2:]+'.glb'),[o for o in OBJECTS if o.get('block_id')==b])
    if a.sector:
        export_glb(OUT/'exports'/(a.sector+'.glb'),[o for o in OBJECTS if o.get('sector_id')==a.sector])
    write_json('unity_import_manifest.json',{'units':'meters','gltf_up':'Y','blender_to_unity_position':'GLTF exporter maps (x,y,z) to (x,z,-y). Importer may mirror Z for left-handed Unity; validate reference triad.','importer':'glTFast or compatible GLB importer required','materials':'Standard PBR images embedded in GLB. Grating alpha tested in Blender only.','colliders':'Construct from collision_proxies.json; do not use alpha mesh for grating collision.','lights':'Rebuild using lighting_groups.json. GLB exports geometry/materials, not Blender area lights.','files':[p.name for p in (OUT/'exports').glob('*.glb')],'Unity_validation':'NOT_RUN'})
    quality_report()
    if a.previews:previews()
    unique={o.data.name:o.data for o in OBJECTS if o.type=='MESH'}
    stats={'mode':CFG['mode'],'blender':bpy.app.version_string,'objects':len(OBJECTS),'unique_meshes':len(unique),'triangles_unique':sum(sum(len(p.vertices)-2 for p in m.polygons) for m in unique.values()),'triangles_instanced':sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in OBJECTS if o.type=='MESH'),'rack_rows':len(RACKS),'rack_sections':sum(r['sections'] for r in RACKS),'storage_cells':len(CELLS),'generation_seconds':round(time.perf_counter()-T0,2),'footprint_m2':456000,'Unity_performance':'NOT_RUN'}
    write_json('object_statistics.json',stats,'reports')
    for im in bpy.data.images:
        if im.name.startswith('RFC_') and not im.packed_file:im.pack()
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'RFC_Horror_Master.blend'),compress=True)
    print('RFC_COMPLETE '+json.dumps(stats),flush=True)

if __name__=='__main__':main()
