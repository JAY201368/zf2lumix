"""Offline Nikon Zf -> S5M2-compatible RW2 conversion."""
from pathlib import Path
import argparse, hashlib, json, math, os, shutil, subprocess, sys, tempfile, time, zlib
import cv2, numpy as np, rawpy
from PIL import Image
from rw2 import codec_parameters, prepare_metadata, assemble
from platform_support import run_tool, exiftool_command, encoder_path

VERSION='1.0.1'
HOME=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
PROFILES=json.loads((HOME/'assets/profiles.json').read_text(encoding='utf-8'))

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def metadata(path):
 fields=['Make','Model','ISO','Orientation','ExposureTime','ExposureProgram','FNumber','FocalLength','FocalLengthIn35mmFormat','LensModel','DateTimeOriginal','CreateDate','SubSecTimeOriginal','OffsetTime','OffsetTimeOriginal','OffsetTimeDigitized','ExposureCompensation','MeteringMode','Flash']
 cmd=exiftool_command(HOME)+['-config','','-charset','filename=UTF8','-j','-n',*['-'+f for f in fields],str(path)]
 result=run_tool(cmd,capture_output=True,timeout=45)
 if result.returncode:raise ValueError('无法读取拍摄信息：'+result.stderr.strip())
 m=json.loads(result.stdout)[0]
 if m.get('Model','').strip() not in ['NIKON Z f','NIKON Zf']:raise ValueError('目前仅支持 Nikon Zf 的 NEF 文件')
 iso=m.get('ISO')
 if not isinstance(iso,(int,float)) or not math.isfinite(iso) or not 1<=iso<=1000000:raise ValueError('NEF 中没有有效的 ISO 信息')
 m['ISO']=int(iso)
 # Zero/missing orientation is not a valid EXIF orientation.
 if m.get('Orientation') not in range(1,9):m['Orientation']=1
 return m

def anchors(iso):
 arr=np.array(PROFILES['iso_anchors'],float);x=float(np.clip(iso,arr[0],arr[-1]));i=int(np.searchsorted(arr,x))
 if i==0:return int(arr[0]),int(arr[0]),0.
 if i==len(arr):return int(arr[-1]),int(arr[-1]),0.
 lo,hi=arr[i-1],arr[i];return int(lo),int(hi),float(np.log2(x/lo)/np.log2(hi/lo))

def scene_profile(scene,iso):
 lo,hi,t=anchors(iso);a=PROFILES['scenes'][scene][str(lo)];b=PROFILES['scenes'][scene][str(hi)]
 result={'matrix':(1-t)*np.array(a['matrix'])+t*np.array(b['matrix'])}
 for field in ['source_wb','target_wb']:
  x=np.array(a[field]);x=x/x[1];y=np.array(b[field]);y=y/y[1]
  result[field]=np.exp((1-t)*np.log(x)+t*np.log(y))
 result['template']=a['template'] if t<.5 else b['template']
 return result

def choose_profile(iso,wb,mode='auto'):
 wb=np.asarray(wb[:3],float);wb/=wb[1]
 if not np.isfinite(wb).all() or np.any(wb<=0):raise ValueError('NEF 拍摄白平衡无效')
 day=scene_profile('daylight',iso);warm=scene_profile('lowlight',iso)
 a=np.log(day['source_wb'][[0,2]]);b=np.log(warm['source_wb'][[0,2]])
 projection=float(np.dot(np.log(wb[[0,2]])-a,b-a)/np.dot(b-a,b-a))
 t=float(np.clip(projection,0,1)) if mode=='auto' else {'daylight':0.,'lowlight':1.}[mode]
 # Avoid meaningless floating-point interpolation at exact calibration anchors.
 if t<1e-10:t=0.
 if t>1-1e-10:t=1.
 matrix=((1-t)*day['matrix']+t*warm['matrix']).astype(np.float32)
 reference_wb=np.exp((1-t)*np.log(day['source_wb'])+t*np.log(warm['source_wb']))
 reference_target=np.exp((1-t)*np.log(day['target_wb'])+t*np.log(warm['target_wb']))
 def mapped_wb(w):
  neutral=(1/w)@matrix.astype(float)
  if np.any(neutral<=0):raise ValueError('当前白平衡超出可计算范围')
  out=1/neutral;return out/out[1]
 target=mapped_wb(wb)*(reference_target/mapped_wb(reference_wb));target/=target[1]
 levels=np.rint(target*256).astype(int)
 if np.any(levels<1) or np.any(levels>65535):raise ValueError('目标白平衡系数超出 RW2 范围')
 return matrix,levels,day['template'] if t<.5 else warm['template'],t,projection

def crop_geometry(size,shape):
 # LibRaw's inset crop uses absolute RAW coordinates; the array is visible-only.
 height,width=shape
 x=size.crop_left_margin-size.left_margin;y=size.crop_top_margin-size.top_margin
 w,h=size.crop_width,size.crop_height
 if (height,width)!=(size.height,size.width) or not 4<=width<=6064 or not 4<=height<=4040 or width%2 or height%2 or size.pixel_aspect!=1:
  raise ValueError('NEF 的 RAW 尺寸或像素比例不受支持。')
 if x<0 or y<0 or w<4 or h<4 or w>6048 or h>4032 or x+w>width or y+h>height:
  raise ValueError('NEF 的有效裁切区域缺失或超出 RAW 边界，无法安全转换。')
 # Keep the established 6048x4032 -> 6000x4000 scale for every camera crop.
 # Even dimensions/origins keep the target RGGB phase intact (rounding <= 1 px).
 outw=max(4,2*round(w*6000/6048/2));outh=max(4,2*round(h*4000/4032/2))
 left=4+2*((6000-outw)//4);top=4+2*((4000-outh)//4)
 return {'source_visible_shape':[height,width],
  'source_crop':{'left':size.crop_left_margin,'top':size.crop_top_margin,'width':w,'height':h},
  'source_visible_crop':{'left':x,'top':y,'width':w,'height':h},
  'output_crop':{'left':left,'top':top,'width':outw,'height':outh}}

def cropped_preview(preview,size,crop):
 # LibRaw normally returns the whole sensor, without applying RW2 inset crops.
 if preview.shape[:2]==(size.height,size.width):
  x=crop['left']-size.left_margin;y=crop['top']-size.top_margin
  result=preview[y:y+crop['height'],x:x+crop['width']]
 elif preview.shape[:2]==(crop['height'],crop['width']):result=preview
 else:raise RuntimeError('RAW 预览尺寸不符，未保存输出')
 if result.shape[:2]!=(crop['height'],crop['width']):raise RuntimeError('RAW 预览裁切越界，未保存输出')
 return result

def verify_crop(size,crop):
 if (size.crop_left_margin,size.crop_top_margin,size.crop_width,size.crop_height)!=(crop['left'],crop['top'],crop['width'],crop['height']):
  raise RuntimeError('RAW 裁切信息回读校验失败，未保存输出')

def publish(tmp,output_dir,stem,report):
 # Hard-link publication is atomic and cannot replace an existing output.
 for i in range(1,100000):
  suffix='' if i==1 else f'_{i}'
  out=output_dir/f'{stem}_S5M2{suffix}.RW2';side=out.with_suffix('.json')
  if side.exists():continue
  try:os.link(tmp,out)
  except FileExistsError:continue
  except OSError as e:raise ValueError('无法安全保存输出，请选择支持硬链接的本地磁盘文件夹（Windows 建议使用 NTFS）。') from e
  try:
   report['output']=str(out);report['output_sha256']=sha(out)
   with side.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
  except Exception:
   out.unlink(missing_ok=True)
   raise
  return out
 raise ValueError('同名文件过多，请选择新的输出文件夹')

def convert(source,output_dir,mode='auto',lens_policy='neutral',status=lambda s:None):
 start=time.monotonic();source=Path(source).expanduser().resolve();outdir=Path(output_dir).expanduser().resolve()
 if not source.is_file() or source.suffix.lower()!='.nef':raise ValueError('请选择存在的 .NEF 文件')
 if mode not in ['auto','daylight','lowlight'] or lens_policy not in ['neutral','template']:raise ValueError('无效的转换选项')
 status('读取 NEF 与拍摄信息');m=metadata(source);source_hash=sha(source)
 outdir.mkdir(parents=True,exist_ok=True)
 if shutil.disk_usage(outdir).free<400*1024**2:raise ValueError('输出磁盘剩余空间不足 400 MB')
 warnings=[]
 if not 100<=m['ISO']<=12800:warnings.append('ISO 超出 100–12800 校准范围，使用最近边界的转换参数。')
 with tempfile.TemporaryDirectory(prefix='.zf2lumix-',dir=outdir) as td:
  td=Path(td)
  with rawpy.imread(str(source)) as raw:
   size=raw.sizes;arr=raw.raw_image_visible.copy();black=raw.black_level_per_channel
   if not np.array_equal(raw.raw_pattern,[[0,1],[3,2]]) or raw.white_level!=16383 or len(set(black))!=1 or size.left_margin%2 or size.top_margin%2:
    raise ValueError('目前支持 Zf 14 位 RGGB NEF；此文件的位深、排列或黑电平不同。')
   geometry=crop_geometry(size,arr.shape);crop=geometry['output_crop'];w,h=crop['width'],crop['height']
   source_wb=list(raw.camera_whitebalance)
   matrix,wb,template,t,projection=choose_profile(m['ISO'],source_wb,mode)
   # Bootstrap previews are replaced after reading back the converted RAW.
   boot=raw.postprocess(use_camera_wb=True,no_auto_bright=True,half_size=True,user_flip=0,output_bps=8)
  status('映射颜色与生成目标 RAW')
  rgb=cv2.cvtColor(arr,cv2.COLOR_BayerRGGB2RGB).astype(np.float32)-black[0];del arr
  src=geometry['source_visible_crop'];y,x=src['top'],src['left'];rgb=rgb[y:y+src['height'],x:x+src['width']]
  rgb=cv2.resize(rgb,(w,h),interpolation=cv2.INTER_AREA)
  mapped=rgb@matrix;del rgb
  low=float(np.mean(mapped<0));high=float(np.mean(mapped>15871))
  pixels=np.clip(np.rint(mapped+512),0,16383).astype(np.uint16);del mapped
  # Keep the audited S5M2 sensor/codec geometry. Only the marked inset is image
  # content; edge extension outside it is excluded from all delivered previews.
  pixels=np.pad(pixels,((crop['top'],4008-crop['top']-h),(crop['left'],6008-crop['left']-w),(0,0)),mode='edge')
  mosaic=np.empty((4008,6008),np.uint16)
  for yy,xx,c in [(0,0,0),(0,1,1),(1,0,1),(1,1,2)]:mosaic[yy::2,xx::2]=pixels[yy::2,xx::2,c]
  del pixels
  mosaic.tofile(td/'mosaic.u16')
  prefix=bytearray(zlib.decompress((HOME/'assets/templates'/f'{template}.prefix.z').read_bytes()))
  app=bytearray(zlib.decompress((HOME/'assets/templates'/f'{template}.exif.z').read_bytes()))
  widths,lefts,huff=codec_parameters(prefix)
  prepare_metadata(prefix,app,m,wb,lens_policy,crop)
  (td/'huff.txt').write_text(''.join(f'{v&65535} {v>>16}\n' for v in huff))
  status('编码 RW2');stripes=[]
  for i,(left,width) in enumerate(zip(lefts,widths)):
   cmd=[str(encoder_path(HOME)),str(td/'mosaic.u16'),'6008','4008',str(left),str(width),str(td/'huff.txt'),str(td/f'{i}.bin'),str(td/f'{i}.bits')]
   result=run_tool(cmd,capture_output=True,timeout=180)
   if result.returncode:raise RuntimeError('RAW 编码失败：'+result.stderr.strip())
   stripes.append((td/f'{i}.bin').read_bytes())
  tmp=td/'converted.RW2';tmp.write_bytes(assemble(prefix,app,Image.fromarray(boot).resize((w,h)),stripes));del boot
  status('验证 RAW 并更新照片预览')
  with rawpy.imread(str(tmp)) as raw:
   if not np.array_equal(raw.raw_image,mosaic):raise RuntimeError('RAW 回读校验失败，未保存输出')
   if not np.allclose(raw.camera_whitebalance[:3],wb,atol=.01):raise RuntimeError('白平衡回读校验失败')
   verify_crop(raw.sizes,crop)
   preview=raw.postprocess(use_camera_wb=True,no_auto_bright=True,user_flip=0,output_bps=8)
   preview=cropped_preview(preview,raw.sizes,crop)
  tmp.write_bytes(assemble(prefix,app,Image.fromarray(preview),stripes));del preview,stripes
  with rawpy.imread(str(tmp)) as raw:
   if not np.array_equal(raw.raw_image,mosaic):raise RuntimeError('最终文件回读校验失败，未保存输出')
   verify_crop(raw.sizes,crop)
  if sha(source)!=source_hash:raise RuntimeError('转换过程中源文件发生变化，已停止保存')
  report={'converter':'Zf2Lumix','version':VERSION,'source':str(source),'source_sha256':source_hash,
   'source_metadata':m,'profile_mode':mode,'warm_light_weight':t,'unclamped_wb_projection':projection,
   'profile_version':PROFILES['version'],'template_id':template,'lens_policy':lens_policy,
   'matrix_row_rgb':matrix.tolist(),'source_wb':source_wb,'target_wb_levels':wb.tolist(),
   **geometry,'output_image_size':[w,h],
   'raw_shape':[4008,6008],'decoded_samples':int(mosaic.size),'raw_roundtrip_mismatch_count':0,'crop_roundtrip_verified':True,
   'negative_signal_fraction':low,'over_range_signal_fraction':high,'warnings':warnings,
   'preview':'Generated from converted RAW with LibRaw; approximate browsing preview, not LUMIX Lab STD rendering.',
   'rendering_metadata':'Built-in S5M2 compatibility shell; source exposure/date/orientation and inferred WB. Panasonic model identity required for decoder compatibility.',
   'elapsed_seconds':round(time.monotonic()-start,2)}
  out=publish(tmp,outdir,source.stem,report)
 status('完成');return out,report

def collect(paths):
 items=[];seen=set()
 for value in paths:
  p=Path(value).expanduser().resolve()
  candidates=sorted(p.rglob('*')) if p.is_dir() else [p]
  for f in candidates:
   if f.is_file() and f.suffix.lower()=='.nef' and f.resolve() not in seen:items.append(f.resolve());seen.add(f.resolve())
 return items

def cli(argv=None):
 parser=argparse.ArgumentParser(description='Zf2Lumix: Nikon Zf NEF → S5M2-compatible RW2')
 parser.add_argument('inputs',nargs='+');parser.add_argument('-o','--output',required=True)
 parser.add_argument('--profile',choices=['auto','daylight','lowlight'],default='auto')
 parser.add_argument('--lens-policy',choices=['neutral','template'],default='neutral')
 args=parser.parse_args(argv);items=collect(args.inputs)
 if not items:parser.error('没有找到 NEF 文件')
 errors=0
 for p in items:
  try:
   out,report=convert(p,args.output,args.profile,args.lens_policy,status=lambda s:print(f'{p.name}: {s}',flush=True))
   print(out,flush=True)
   for w in report['warnings']:print('提示：'+w,flush=True)
  except Exception as e:errors+=1;print(f'失败 {p}: {e}',file=sys.stderr,flush=True)
 return 1 if errors else 0

if __name__=='__main__':raise SystemExit(cli())
