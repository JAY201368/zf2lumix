"""Strict 33-grid .cube loader for the independent rendering backend."""
from dataclasses import dataclass
import math
from pathlib import Path
import shlex
import numpy as np


@dataclass(frozen=True)
class CubeLUT:
    title: str
    values: np.ndarray  # sequential RGB rows, red index changes fastest
    domain_min: tuple[float, float, float]
    domain_max: tuple[float, float, float]

    def sample(self, rgb):
        """Vectorized trilinear interpolation, in recovered R->G->B order."""
        rgb=np.asarray(rgb,dtype=np.float32)
        if rgb.shape[-1:]!=(3,) or not np.isfinite(rgb).all():
            raise ValueError('LUT input must be finite RGB')
        low=np.asarray(self.domain_min,dtype=np.float32)
        high=np.asarray(self.domain_max,dtype=np.float32)
        at=np.clip((rgb-low)/(high-low),0,1)*np.float32(32)
        cell=np.minimum(at.astype(np.int32),31);f=at-cell.astype(np.float32)
        index=cell[...,2]*1089+cell[...,1]*33+cell[...,0]
        def row(offset):
            a=self.values[index+offset];b=self.values[index+offset+1]
            return a+(b-a)*f[...,0,None]
        p=row(0)+(row(33)-row(0))*f[...,1,None]
        q=row(1089)+(row(1122)-row(1089))*f[...,1,None]
        return p+(q-p)*f[...,2,None]


def read_cube(path):
    path=Path(path)
    if path.stat().st_size>16*1024*1024:raise ValueError('Cube file exceeds 16 MiB limit')
    title=path.stem;size=None;low=(0.,0.,0.);high=(1.,1.,1.);rows=[];seen=set()
    for line_no,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        try:tokens=shlex.split(line,comments=True,posix=True)
        except ValueError as error:raise ValueError(f'Line {line_no}: {error}') from error
        if not tokens:continue
        key=tokens[0]
        if key in ('TITLE','LUT_3D_SIZE','DOMAIN_MIN','DOMAIN_MAX'):
            if rows or key in seen:raise ValueError(f'Line {line_no}: repeated or late header {key}')
            seen.add(key)
            if key=='TITLE':
                if len(tokens)!=2:raise ValueError('TITLE requires one quoted string')
                title=tokens[1]
            elif key=='LUT_3D_SIZE':
                if tokens!=['LUT_3D_SIZE','33']:raise ValueError('Only LUT_3D_SIZE 33 is supported')
                size=33
            else:
                if len(tokens)!=4:raise ValueError(f'{key} requires three values')
                values=tuple(float(v) for v in tokens[1:])
                if not all(math.isfinite(v) for v in values):raise ValueError('Non-finite domain')
                if key=='DOMAIN_MIN':low=values
                else:high=values
        else:
            if size is None:raise ValueError(f'Line {line_no}: expected LUT_3D_SIZE 33 before data')
            if len(tokens)!=3:raise ValueError(f'Line {line_no}: expected RGB data')
            try:row=tuple(float(v) for v in tokens)
            except ValueError as error:raise ValueError(f'Line {line_no}: unsupported directive or invalid RGB') from error
            if not all(math.isfinite(v) and abs(v)<=np.finfo(np.float32).max for v in row):raise ValueError('LUT values must be finite float32')
            rows.append(row)
            if len(rows)>33**3:raise ValueError('Too many LUT entries')
    if size!=33 or len(rows)!=33**3:raise ValueError('33-grid LUT requires exactly 35937 RGB rows')
    low32=np.asarray(low,dtype=np.float32);high32=np.asarray(high,dtype=np.float32)
    if not np.isfinite(low32).all() or not np.isfinite(high32).all() or not np.all(high32>low32):
        raise ValueError('Every DOMAIN_MAX must be greater than DOMAIN_MIN in float32')
    if not np.isfinite(high32-low32).all():raise ValueError('Domain range exceeds float32')
    values=np.asarray(rows,dtype=np.float32);values.flags.writeable=False
    return CubeLUT(title,values,tuple(low32.tolist()),tuple(high32.tolist()))


def apply_layers(rgb,layers):
    if len(layers)>2:raise ValueError('At most two LUT layers are supported')
    value=np.asarray(rgb,dtype=np.float32)
    if value.shape[-1:]!=(3,) or not np.isfinite(value).all():raise ValueError('Expected finite RGB')
    value=np.clip(value,0,1)
    for table,strength in layers:
        if not math.isfinite(strength) or not 0<=strength<=1:raise ValueError('Strength must be in [0,1]')
        if strength:
            alpha=np.float32(strength)
            value=np.clip(alpha*table.sample(value)+(np.float32(1)-alpha)*value,0,1)
    return value


def metal_buffers(layers, *, input_max=4095, output_max=16383):
    """Pack the file-LUT Metal interface, preserving each layer's domain."""
    import struct
    if len(layers)>2:raise ValueError('At most two LUT layers are supported')
    if any(not isinstance(v,int) or isinstance(v,bool) or not 1<=v<=65535 for v in (input_max,output_max)):
        raise ValueError('LUT code maxima must be integers in [1,65535]')
    strengths=[0.,0.];domains=[(0.,0.,0.,1.,1.,1.)]*2;tables=[bytes(16),bytes(16)]
    for index,(table,strength) in enumerate(layers):
        if not isinstance(table,CubeLUT) or not math.isfinite(strength) or not 0<=strength<=1:
            raise ValueError('Expected a parsed cube and strength in [0,1]')
        strengths[index]=strength;domains[index]=(*table.domain_min,*table.domain_max)
        tables[index]=np.column_stack((table.values,np.zeros(33**3,dtype=np.float32))).astype('<f4').tobytes()
    return struct.pack('<16f',input_max,output_max,*strengths,*domains[0],*domains[1]),*tables
