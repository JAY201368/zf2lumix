"""Restricted, bounds-checked writer for our audited S5M2 RawFormat 8 templates."""
import io, struct
from fractions import Fraction
from PIL import Image

SIZES={1:1,2:1,3:2,4:4,5:8,7:1,9:4,10:8,11:4,12:8}
class IFD:
 def __init__(self,b,start,base=0):
  self.b=b;self.base=base;self.start=start;self.tags={}
  n=struct.unpack_from('<H',b,start)[0]
  if n>1000 or start+2+12*n+4>len(b):raise ValueError('无效的模板目录')
  for i in range(n):
   e=start+2+12*i;t,typ,c,v=struct.unpack_from('<HHII',b,e)
   size=SIZES[typ]*c;pos=e+8 if size<=4 else base+v
   self.tags[t]=(e,typ,c,pos,size)
  self.next=struct.unpack_from('<I',b,start+2+12*n)[0]
 def get(self,t):
  e,typ,c,p,size=self.tags[t]
  if p+size>len(self.b):raise ValueError(f'模板数据越界：{t:x}')
  if typ in [3,4,9]:return struct.unpack_from('<'+{3:'H',4:'I',9:'i'}[typ],self.b,p)[0]
  return bytes(self.b[p:p+size])
 def set(self,t,value):
  if t not in self.tags:return
  e,typ,c,p,size=self.tags[t]
  if typ in [3,4,9]:data=struct.pack('<'+{3:'H',4:'I',9:'i'}[typ],int(value));assert c==1
  elif typ in [5,10]:
   f=Fraction(str(value)).limit_denominator(1000000);data=struct.pack('<'+('II' if typ==5 else 'ii'),f.numerator,f.denominator);assert c==1
  elif typ==2:
   data=str(value).encode('ascii','replace')+b'\0'
   # Keep original allocation and MakerNote-relative offsets intact.
   if len(data)<=size:data=data.ljust(size,b'\0')
   else:data=data[:size-1]+b'\0'
  elif typ in [1,7]:
   data=bytes(value)
   if len(data)!=size:raise ValueError('模板固定长度字段不匹配')
  else:return
  self.b[p:p+size]=data
 def blob_pointer(self,t,offset,size):
  e,typ,_,_,_=self.tags[t];assert typ==7
  struct.pack_into('<II',self.b,e+4,size,offset-self.base)

def root(b,base=0):return IFD(b,base+struct.unpack_from('<I',b,base+4)[0],base)

def update_standard(d,m):
 for t,k,default in [(0x112,'Orientation',1),(0x132,'DateTimeOriginal',''),(0x829a,'ExposureTime',0),
  (0x829d,'FNumber',0),(0x8822,'ExposureProgram',1),(0x8827,'ISO',100),(0x8831,'ISO',100),
  (0x9003,'DateTimeOriginal',''),(0x9004,'CreateDate',''),(0x9204,'ExposureCompensation',0),
  (0x9207,'MeteringMode',0),(0x9209,'Flash',0),(0x920a,'FocalLength',0),
  (0xa405,'FocalLengthIn35mmFormat',0),(0x9290,'SubSecTimeOriginal',''),
  (0x9291,'SubSecTimeOriginal',''),(0x9292,'SubSecTimeOriginal',''),
  (0x9010,'OffsetTime',''),(0x9011,'OffsetTimeOriginal',''),(0x9012,'OffsetTimeDigitized','')]:
  value=m.get(k,default)
  if t==0x8827:value=min(int(value),65535)
  d.set(t,value)
 # Do not pretend the template's camera serial is the source camera's serial.
 d.set(0xa431,'');d.set(0x13b,'');d.set(0x8298,'')

def thumbnail(app,image):
 d=root(app,6)
 if not d.next:return
 t=IFD(app,6+d.next,6)
 if 0x201 not in t.tags or 0x202 not in t.tags:return
 p=6+t.get(0x201);limit=t.get(0x202)
 thumb=image.copy();thumb.thumbnail((160,120))
 buf=io.BytesIO();thumb.save(buf,format='JPEG',quality=65);data=buf.getvalue()
 if len(data)>limit:raise ValueError('缩略图超过模板预留空间')
 app[p:p+limit]=data+b'\0'*(limit-len(data));t.set(0x202,len(data));t.set(0x112,d.get(0x112))
 t.set(0x100,thumb.width);t.set(0x101,thumb.height)

def prepare_metadata(prefix,app,m,wb,lens_policy,crop=None):
 d=root(prefix);update_standard(d,m);d.set(0x37,m['ISO'])
 if crop is not None:
  x,y,w,h=[crop[k] for k in ['left','top','width','height']]
  if min(x,y)<4 or min(w,h)<4 or x+w>6004 or y+h>4004 or any(v%2 for v in [x,y,w,h]):raise ValueError('无效的目标裁切区域')
  # Adobe uses Sensor*Border for its default crop; LibRaw uses Crop*. Keep both
  # descriptions identical while SensorWidth/Height and codec stripes stay fixed.
  for t,v in [(0x4,y),(0x5,x),(0x6,y+h),(0x7,x+w),(0x2f,y),(0x30,x),(0x31,y+h),(0x32,x+w)]:d.set(t,v)
 old_wb=[d.get(t) for t in [0x24,0x25,0x26]]
 for t,v in zip([0x24,0x25,0x26],wb):d.set(t,int(v))
 update_standard(IFD(prefix,d.get(0x8769)),m)
 # Known geometric correction table: neutral values and fresh checksums.
 if lens_policy=='neutral' and 0x119 in d.tags:
  data=bytearray(d.get(0x119))
  for i in [2,4,5,8,9,11]:struct.pack_into('<h',data,i*2,0)
  struct.pack_into('<H',data,14,struct.unpack_from('<H',data,14)[0]&0xfff0)
  def checksum(start,n,step):
   c=0
   for i in range(n):c=(73*c+data[start+i*step])%0xffef
   return c
  for dst,start,n,step in [(2,4,12,1),(28,16,12,1),(0,2,14,2),(30,3,14,2)]:struct.pack_into('<H',data,dst,checksum(start,n,step))
  d.set(0x119,data)
 a=root(app,6);update_standard(a,m);ex=IFD(app,6+a.get(0x8769),6);update_standard(ex,m)
 if 0x927c in ex.tags:
  _,_,_,p,_=ex.tags[0x927c]
  if app[p:p+12]!=b'Panasonic\0\0\0':raise ValueError('不支持的模板 MakerNote')
  maker=IFD(app,p+12,6)
  if crop is not None:maker.set(0x4b,w);maker.set(0x4c,h)
  maker.set(0x89,1) # Standard / STD
  maker.set(0xd1,m['ISO'])
  orientation=m.get('Orientation',1)
  maker.set(0x30,orientation if orientation in [1,3,6,8] else 1)
  if 0x8f in maker.tags:maker.set(0x8f,bytes([{1:0,3:2,6:1,8:3}.get(orientation,0)]))
  for t,new,old in zip([0x8004,0x8005,0x8006],wb,old_wb):
   if t in maker.tags:
    value=round(maker.get(t)*int(new)/old)
    if not 1<=value<=65535:raise ValueError('目标白平衡超出 MakerNote 范围')
    maker.set(t,value)
  maker.set(0x25,b'\0'*maker.tags[0x25][4])
  maker.set(0x52,'')
  if lens_policy=='neutral':
   maker.set(0x51,m.get('LensModel','Nikon lens'))
   maker.set(0x8a,0)
   for t in [0xc4,0xc5,0xe4]:maker.set(t,0)
 # Preserve WB mode/shift controls: coefficients above already use the
 # calibration's complete rendering convention. No second WB adjustment here.

def jpeg(image,app=None,quality=90):
 buf=io.BytesIO();image.save(buf,format='JPEG',quality=quality,subsampling=0)
 data=buf.getvalue()
 if app is not None:
  app=bytearray(app);thumbnail(app,image)
  if len(app)+2>65535:raise ValueError('EXIF 预览块过大')
  data=data[:2]+b'\xff\xe1'+struct.pack('>H',len(app)+2)+app+data[2:]
 return data

def assemble(prefix,app,image,stripes):
 b=bytearray(prefix);d=root(b)
 # Match original small/full preview roles; all pixels come from this NEF.
 small=image.copy();small.thumbnail((1920,1280))
 app=bytearray(app);a=root(app,6);ex=IFD(app,6+a.get(0x8769),6)
 ex.set(0xa002,small.width);ex.set(0xa003,small.height)
 for tag,data in [(0x2e,jpeg(small,app)),(0x127,jpeg(image))]:
  while len(b)%16:b.append(0)
  d.blob_pointer(tag,len(b),len(data));b.extend(data)
 offsets=[];bits=[]
 for data in stripes:
  while len(b)%16:b.append(0)
  offsets.append(len(b));bits.append(len(data)*8);b.extend(data)
 for t,values in [(0x44,offsets),(0x46,bits)]:
  p=d.tags[t][3];n=struct.unpack_from('<H',b,p)[0]
  if n!=len(values):raise ValueError('条带数量不一致')
  struct.pack_into('<'+'I'*n,b,p+2,*values)
 d.set(0x118,offsets[0]);return b

def codec_parameters(prefix):
 d=root(prefix)
 def vals(t,fmt):
  v=d.get(t);n=struct.unpack_from('<H',v)[0];return list(struct.unpack_from('<'+fmt*n,v,2))
 if d.get(0x2d)!=8 or d.get(0xa)!=14 or d.get(0x3b)!=65535:raise ValueError('不支持的 RAW 编码模板')
 if any(d.get(t)!=0 for t in range(0x3c,0x40)) or any(vals(0x41,'H')):raise ValueError('模板预测模式不受支持')
 if any(v&31 for v in vals(0x39,'I')) or any(vals(0x3a,'I')):raise ValueError('模板线性化不受支持')
 widths=vals(0x47,'H');lefts=vals(0x45,'I');heights=vals(0x48,'H')
 if sum(widths)!=6008 or heights!=[4008]*len(widths) or lefts!=[sum(widths[:i]) for i in range(len(widths))]:raise ValueError('模板尺寸无效')
 return widths,lefts,vals(0x40,'I')
