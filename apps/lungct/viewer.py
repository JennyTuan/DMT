from io import BytesIO
import numpy as np
from PIL import Image
from .geometry import from_dict, patient_to_pixel, direction


def locate(series, point):
    g=from_dict(series['geometry']); index,x,y=patient_to_pixel(g,point)
    return dict(index=index,x=x,y=y,slice_key=series['slice_keys'][index],
                left=direction(-np.asarray(g.row)),right=direction(g.row),
                top=direction(-np.asarray(g.column)),bottom=direction(g.column))


def image_png(array, center=-600, width=1500):
    if not np.isfinite([center,width]).all() or width<=0: raise ValueError('窗宽窗位无效')
    gray=np.clip((array-(center-width/2))/width*255,0,255).astype(np.uint8)
    output=BytesIO();Image.fromarray(gray).save(output,format='PNG');output.seek(0)
    return output


def coronal(volume,g,patient_y=None):
    """Readonly patient-LPS coronal locator. Nearest source sampling, no quantification."""
    corners=np.array([g.pixel_to_patient(z,x,y) for z in (0,len(volume)-1) for x in (0,g.columns-1) for y in (0,g.rows-1)])
    low=corners.min(axis=0);high=corners.max(axis=0)
    spacing=max(min(g.spacing),float(max(high[0]-low[0],high[2]-low[2]))/768)
    xs=np.arange(low[0],high[0]+spacing*.25,spacing)
    zs=np.arange(high[2],low[2]-spacing*.25,-spacing)
    patient_y=float((low[1]+high[1])/2 if patient_y is None else patient_y)
    if not np.isfinite(patient_y): raise ValueError('冠状定位坐标无效')
    zz,xx=np.meshgrid(zs,xs,indexing='ij')
    pts=np.stack((xx,np.full_like(xx,patient_y),zz),axis=-1)-g.origins[0]
    dz=float(np.median(np.diff(g.locations)))
    zi=np.rint(pts @ g.normal/dz).astype(int)
    yi=np.rint(pts @ g.column/g.spacing[0]).astype(int)
    xi=np.rint(pts @ g.row/g.spacing[1]).astype(int)
    valid=(zi>=0)&(zi<len(volume))&(yi>=0)&(yi<g.rows)&(xi>=0)&(xi<g.columns)
    result=np.full(zi.shape,-1024,dtype=np.float32)
    result[valid]=volume[zi[valid],yi[valid],xi[valid]]
    return result,dict(x_min=float(low[0]),z_max=float(high[2]),spacing=spacing,patient_y=patient_y,width=len(xs),height=len(zs))
