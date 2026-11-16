"""Validate the packaged Unity project without pretending to run Unity.
python tools/verify_unity_project.py
Optional syntax pass: pip install tree-sitter tree-sitter-c-sharp
Geometry-center regeneration: python tools/prepare_unity_colliders.py (requires NumPy).
"""
from pathlib import Path
import json,hashlib,re,struct
repo=Path(__file__).resolve().parents[1];p=repo/'UnityProject';checks={}
manifest=json.loads((p/'Packages/manifest.json').read_text())['dependencies']
assert manifest['com.unity.cloud.gltfast']=='6.21.0' and manifest['com.unity.inputsystem']=='1.20.1'
assert 'com.unity.render-pipelines.universal'not in manifest
checks['pinned_packages_builtin_pipeline']='PASS'
guids={}
for asset in (p/'Assets').rglob('*'):
 if asset.suffix=='.meta':continue
 meta=Path(str(asset)+'.meta');assert meta.exists(),asset
 match=re.search(r'^guid: ([0-9a-f]{32})$',meta.read_text(),re.M);assert match,meta
 g=match[1];assert g not in guids,(g,asset,guids.get(g));guids[g]=asset
scene=(p/'Assets/RFC/Scenes/RFC_Walk.unity').read_text()
refs=re.findall(r'guid: ([0-9a-f]{32})',scene)
assert len(refs)==1 and guids[refs[0]].name=='RfcBootstrap.cs'
assert 'SceneRoots:'in scene and '{fileID: 1001}'in scene
checks['asset_meta_and_scene_script_guids']='PASS'
build=(p/'ProjectSettings/EditorBuildSettings.asset').read_text()
assert 'Assets/RFC/Scenes/RFC_Walk.unity'in build
sg=re.search(r'guid: ([0-9a-f]{32})',build)[1];assert guids[sg].name=='RFC_Walk.unity'
assert 'activeInputHandler: 1'in(p/'ProjectSettings/ProjectSettings.asset').read_text()
checks['build_scene_and_input_settings']='PASS'
for b in range(1,4):
 a=repo/'exports'/f'Block_{b:02d}.glb';f=p/'Assets/StreamingAssets/RFC'/f'Block_{b:02d}.glb.bytes'
 raw=f.read_bytes();assert hashlib.sha256(raw).digest()==hashlib.sha256(a.read_bytes()).digest()
 magic,version,size=struct.unpack_from('<4sII',raw);assert magic==b'glTF' and version==2 and size==len(raw)
 checks[f'block_{b}_raw_glb_integrity']='PASS'
coll=json.loads((p/'Assets/StreamingAssets/RFC/collision_proxies.json').read_text())['data']
assert len(coll)==14040 and sum(c['kind']=='STAIR_RAMP'for c in coll)==52
assert len({c['id']for c in coll})==len(coll)
assert all(len(c['position_m'])==len(c['size_m'])==len(c['rotation_euler_rad'])==3 and min(c['size_m'])>0 for c in coll)
checks['collider_schema_and_ids']='PASS'
light=json.loads((p/'Assets/StreamingAssets/RFC/lighting_groups.json').read_text())['data'];assert light and any(c['group']=='LOCAL_TASK'for c in light)
checks['lighting_metadata']='PASS'
geom=json.loads((p/'COLLIDER_VALIDATION.json').read_text());assert geom['status']=='PASS' and geom['max_visual_bounds_error_m']<.002
checks['glb_collider_coordinate_alignment']='PASS'
syntax='NOT_RUN'
try:
 from tree_sitter import Parser,Language
 import tree_sitter_c_sharp
 parser=Parser(Language(tree_sitter_c_sharp.language()))
 for source in (p/'Assets').rglob('*.cs'):
  parsed=parser.parse(source.read_bytes());assert not parsed.root_node.has_error,source
 syntax='PASS'
except ImportError:pass
checks['CSharp_syntax_tree']=syntax
report={'integration_version':'1.0.0','target':'Unity 6 / Built-in / desktop','checks':checks,'geometry':geom,
 'source_semantics':'Import API and X reflection checked against official glTFast 6.21.0 package source. Unity 6000.0.62f1 verified in official release API.',
 'Unity_editor_present':False,'Unity_compilation':'NOT_RUN','Unity_PlayMode':'NOT_RUN','Unity_material_rendering':'NOT_RUN',
 'character_stairs_and_routes':'NOT_RUN','standalone_build':'NOT_RUN','GPU_CPU_FPS':'NOT_RUN',
 'acceptance':'PROJECT_PREPARED; requires first run and validation in Unity Editor. No working-build claim.',
 'feature_scope':{'player_and_gravity':'IMPLEMENTED_NOT_RUN','model_import':'IMPLEMENTED_NOT_RUN','collider_creation':'IMPLEMENTED_NOT_RUN','day_night_and_flashlight':'IMPLEMENTED_NOT_RUN','visibility_culling':'IMPLEMENTED_NOT_RUN','streaming':'NOT_IMPLEMENTED','AI':'NOT_IMPLEMENTED','multiplayer':'NOT_IMPLEMENTED'}}
# Preserve a completed syntax pass when the optional parser is not installed locally.
oldpath=p/'VALIDATION.json'
if syntax=='NOT_RUN'and oldpath.exists():
 old=json.loads(oldpath.read_text())
 if old.get('checks',{}).get('CSharp_syntax_tree')=='PASS':report['previous_syntax_check']='PASS in preparation environment; current optional parser unavailable'
oldpath.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
