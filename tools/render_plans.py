"""Optional PNG plan renderer: python tools/render_plans.py BUILD_DIRECTORY
Requires Pillow. The Blender generator itself has no external dependencies.
"""
from pathlib import Path
import sys,json,math
from PIL import Image,ImageDraw,ImageFont
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
def read(name):return json.loads((root/'metadata'/name).read_text())['data']
layout=read('warehouse_layout.json');nav=read('navigation.json');portals=read('portals.json')
font='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
def F(size):
 try:return ImageFont.truetype(font,size)
 except OSError:return ImageFont.load_default()
colors={'MEZZANINE':'#344c60','PICKING':'#a46c31','RECEIVING':'#398c9e','KGT':'#9a5942','SERVICE':'#6c5c8d','SECURITY':'#3d8c66','PACKING':'#9b8348','SORTING':'#397d70','SHIPPING':'#995c56','QUARANTINE':'#925273','CONVEYOR':'#487694'}
for b in layout['blocks']:
 bid=b['id'];ox=b['origin_m'][0];w,d,h=b['size_m'];scale=2.5;pad=40;header=80
 for f in range(4 if bid!='B03' else 2):
  im=Image.new('RGB',(int(w*scale+pad*2),int(d*scale+header+110)),'#101a24');p=ImageDraw.Draw(im)
  def P(x,y):return (int(pad+x*scale),int(header+(d-y)*scale))
  def R(x0,y0,x1,y1,fill,outline=None):p.rectangle((*P(x0,y1),*P(x1,y0)),fill=fill,outline=outline)
  R(0,0,w,d,'#243440','#9cb3c0')
  p.text((pad,18),f'RFC HORROR / {bid} / F{f:02d} / +{(f*4.8 if bid!="B03" else f*6):.1f}m',font=F(25),fill='#e4edf3')
  for z in layout['zones']:
   if z['block']!=bid or z['floor']!=f:continue
   x0,y0,zz,x1,y1,_=z['local_bounds_m'];R(x0,y0,x1,y1,colors[z['type']],'#8aa3ae')
   p.text(P(x0+1,y1-1),z['zone_id'],font=F(10),fill='#e2edf0')
  for r in layout['rack_rows']:
   if r['block']!=bid or r['floor']!=f:continue
   x,y,_=r['start_m']
   for sec in range(r['sections']//8):
    xx=x-ox+sec*8*r['bay_m']+sum(4 for gap in r['gap_after_sections'] if sec*8>=gap)
    R(xx,y-.4,xx+8*r['bay_m'],y+.4,'#efb56b')
  for e in nav['edges']:
   a,bb=[nav['nodes'][e[k]] for k in ('a','b')]
   if a['block']==bb['block']==bid and a['floor']==bb['floor']==f:
    x,y,_=a['position_m'];xx,yy,_=bb['position_m'];p.line([P(x-ox,y),P(xx-ox,yy)],fill='#61dbb2',width=2)
  for s in layout['stairs']:
   if s['block']!=bid:continue
   x=s['x']-ox;y=s['y'];R(x-1,y-2,x+5.6,y+6.6,'#c5d4df')
   p.text(P(x-1,y-3),'STAIR',font=F(10),fill='white')
  p.text((pad,im.height-80),'Orange: racks / Green: candidate walk graph / White: stairs',font=F(16),fill='#c3d6df')
  p.text((pad,im.height-52),'1 m = 2.5 px. Blender Z-up. See validation reports for limits.',font=F(16),fill='#9db2bf')
  im.save(root/'previews'/f'{bid}_F{f:02d}_plan.png')
# Global true-scale overview.
s=1.5;pad=40;head=100
im=Image.new('RGB',(2180,780),'#101a24');p=ImageDraw.Draw(im)
p.text((pad,20),'RFC HORROR / 456 000 m² / FULL COMPLEX',font=F(34),fill='#edf3f5')
def P(x,y):return (int(pad+x*s),int(head+(360-y)*s))
for b in layout['blocks']:
 ox=b['origin_m'][0];w,d,h=b['size_m'];p.rectangle((*P(ox,d),*P(ox+w,0)),fill='#243440',outline='#89a4b6',width=2)
 p.text(P(ox+10,d-12),f'{b["id"]} / {w} × {d} × {h}m',font=F(23),fill='#e9b66b')
 for z in layout['zones']:
  if z['block']==b['id'] and z['floor']==0:
   x0,y0,_,x1,y1,_=z['global_bounds_m'];p.rectangle((*P(x0,y1),*P(x1,y0)),fill=colors[z['type']])
 for r in layout['rack_rows']:
  if r['block']==b['id'] and r['floor']==0:
   x,y,_=r['start_m'];p.line([P(x,y),P(x+r['sections']*r['bay_m']+8,y)],fill='#e7b378',width=2)
 p.line([P(ox,160),P(ox+w,160)],fill='#66d9b5',width=5)
 p.text(P(ox+10,d-12),f'{b["id"]} / {w} × {d} × {h}m',font=F(23),fill='#e9b66b')
for port in portals:
 x,y,_=port['position_m'];p.rectangle((*P(x-10,y+6),*P(x+10,y-6)),fill='#eac761')
p.text((pad,680),'B01 INBOUND   /   B02 STORAGE   /   B03 SORTATION',font=F(24),fill='#d4e2e9')
p.text((pad,723),'4 levels in B01/B02. B03 upper platform +6m. Yellow = connections. Plans show actual world scale.',font=F(20),fill='#8fa9b9')
im.save(root/'previews'/'top_view.png')
