import sys,unittest,json,zlib,struct,tempfile,io
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from converter import HOME,PROFILES,choose_profile,collect,publish,crop_geometry,cropped_preview,verify_crop
from rw2 import root,IFD,prepare_metadata,assemble

class ConverterTests(unittest.TestCase):
 def test_calibration_anchors(self):
  for scene in ['daylight','lowlight']:
   for iso,item in PROFILES['scenes'][scene].items():
    matrix,wb,key,t,_=choose_profile(int(iso),item['source_wb'])
    self.assertTrue(np.allclose(matrix,item['matrix']))
    self.assertTrue(np.array_equal(wb,np.rint(np.array(item['target_wb'])/item['target_wb'][1]*256)))
    self.assertEqual(t,0 if scene=='daylight' else 1)
 def test_interpolated_wb_and_iso(self):
  a=PROFILES['scenes']['daylight']['800']['source_wb'];b=PROFILES['scenes']['lowlight']['800']['source_wb']
  m,wb,key,t,_=choose_profile(800,np.sqrt(np.array(a)*b))
  self.assertAlmostEqual(t,.5,places=10);self.assertTrue(np.isfinite(m).all());self.assertTrue((wb>0).all())
  for iso in [50,640,102400]:
   m,wb,*_=choose_profile(iso,a);self.assertTrue(np.isfinite(m).all())
 def test_orientation_exposure_and_maker_wb(self):
  p=bytearray(zlib.decompress((HOME/'assets/templates/daylight_800.prefix.z').read_bytes()))
  a=bytearray(zlib.decompress((HOME/'assets/templates/daylight_800.exif.z').read_bytes()))
  meta={'ISO':102400,'Orientation':6,'ExposureTime':.025,'DateTimeOriginal':'2026:10:16 12:34:56'}
  prepare_metadata(p,a,meta,[700,256,420],'neutral')
  d=root(p);self.assertEqual(d.get(0x112),6);self.assertEqual(d.get(0x37),102400)
  ex=IFD(p,d.get(0x8769));self.assertEqual(ex.get(0x8827),65535);self.assertEqual(ex.get(0x8831),102400)
  aj=root(a,6);ex=IFD(a,6+aj.get(0x8769),6);maker=IFD(a,ex.tags[0x927c][3]+12,6)
  self.assertEqual(maker.get(0xd1),102400);self.assertEqual(maker.get(0x30),6);self.assertEqual(maker.get(0x8004),2800)
  self.assertEqual(maker.get(0x8a),0)
 def test_publish_never_overwrites(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);tmp=td/'test.tmp';tmp.write_bytes(b'rawpayload')
   first=td/'test_S5M2.RW2';first.write_bytes(b'existing')
   out=publish(tmp,td,'test',{})
   self.assertEqual(out.name,'test_S5M2_2.RW2');self.assertEqual(first.read_bytes(),b'existing')
   self.assertEqual(out.read_bytes(),b'rawpayload')
 def test_discovery_case_and_dedup(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);(p/'a.NEF').touch();(p/'b.nef').touch();(p/'c.jpg').touch()
   self.assertEqual(len(collect([p,p/'a.NEF'])),2)

 def size(self,width=6064,height=4040,left=8,top=4,w=6048,h=4032,margin_left=0,margin_top=0):
  return SimpleNamespace(width=width,height=height,left_margin=margin_left,top_margin=margin_top,
   crop_left_margin=left,crop_top_margin=top,crop_width=w,crop_height=h,pixel_aspect=1.)

 def test_full_frame_and_camera_crops_keep_scale_and_bayer_phase(self):
  for size,expected in [(self.size(),(6000,4000)),
   (self.size(width=4048,w=4032),(4000,4000)),
   (self.size(height=3408,h=3400),(6000,3374)),
   (self.size(width=3984,height=2656,left=8,top=4,w=3968,h=2640),(3936,2620))]:
   with self.subTest(size=size):
    g=crop_geometry(size,(size.height,size.width));c=g['output_crop']
    self.assertEqual((c['width'],c['height']),expected)
    self.assertTrue(all(v%2==0 for v in c.values()))
    self.assertLessEqual(c['left']+c['width'],6004);self.assertLessEqual(c['top']+c['height'],4004)
    self.assertLessEqual(abs(c['width']-size.crop_width*125/126),1)
    self.assertLessEqual(abs(c['height']-size.crop_height*125/126),1)

 def test_crop_absolute_coordinates_and_invalid_bounds(self):
  g=crop_geometry(self.size(left=12,top=8,margin_left=4,margin_top=4),(4040,6064))
  self.assertEqual(g['source_visible_crop'],{'left':8,'top':4,'width':6048,'height':4032})
  for size in [self.size(left=65535),self.size(w=0),self.size(w=6064),self.size(top=20),
   self.size(left=2,margin_left=4),self.size(width=6063)]:
   with self.subTest(size=size),self.assertRaises(ValueError):crop_geometry(size,(size.height,size.width))

 def test_square_preview_crops_pixels_without_stretching(self):
  # Distinct columns expose the old 3:2 resize and any wrong crop origin.
  a=np.tile(np.arange(12,dtype=np.uint8)[None,:,None],(8,1,3))
  size=SimpleNamespace(height=8,width=12,left_margin=0,top_margin=0)
  crop={'left':4,'top':2,'width':4,'height':4}
  np.testing.assert_array_equal(cropped_preview(a,size,crop),a[2:6,4:8])
  with self.assertRaises(RuntimeError):cropped_preview(a[:3],size,crop)
  verify_crop(self.size(left=1004,top=4,w=4000,h=4000),{'left':1004,'top':4,'width':4000,'height':4000})
  with self.assertRaises(RuntimeError):verify_crop(self.size(),{'left':1004,'top':4,'width':4000,'height':4000})

 def test_crop_metadata_and_all_preview_dimensions(self):
  crop={'left':1004,'top':4,'width':4000,'height':4000}
  for scene in PROFILES['scenes'].values():
   for item in scene.values():
    key=item['template']
    with self.subTest(template=key):
     p=bytearray(zlib.decompress((HOME/f'assets/templates/{key}.prefix.z').read_bytes()))
     a=bytearray(zlib.decompress((HOME/f'assets/templates/{key}.exif.z').read_bytes()))
     prepare_metadata(p,a,{'ISO':100,'Orientation':6},[526,256,415],'neutral',crop)
     self.assertEqual([root(p).get(t) for t in [0x2f,0x30,0x31,0x32]],[4,1004,4004,5004])
     self.assertEqual([root(p).get(t) for t in [0x4,0x5,0x6,0x7]],[4,1004,4004,5004])
     self.assertEqual((root(p).get(0x2),root(p).get(0x3)),(6008,4008))
     ex=IFD(a,6+root(a,6).get(0x8769),6);maker=IFD(a,ex.tags[0x927c][3]+12,6)
     self.assertEqual((maker.get(0x4b),maker.get(0x4c)),(4000,4000))
  # Preview EXIF and actual JPEGs must agree, independently of the sensor size.
  b=assemble(p,a,Image.new('RGB',(400,400)),[b'\0'*8,b'\0'*8]);d=root(b)
  small=d.get(0x2e);full=d.get(0x127)
  with Image.open(io.BytesIO(small)) as image:
   self.assertEqual(image.size,(400,400));ex=image.getexif().get_ifd(0x8769)
   self.assertEqual((ex[0xa002],ex[0xa003]),image.size)
  with Image.open(io.BytesIO(full)) as image:self.assertEqual(image.size,(400,400))

if __name__=='__main__':unittest.main()
