"""Fixed-view GT / Prediction / Camera / LiDAR / Gaussian from real artifacts."""
import json
import pickle
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from scene_visualize import font,sha,read_mesh
from view_camera import basis as camera_basis,settings as camera_settings,require_equal_axes

# Original supplied plugin palette; keep identical class colors in all semantic panes.
PALETTE={0:(255,0,0),1:(0,255,0),2:(0,0,255),3:(255,255,0),4:(255,0,255),
         5:(0,255,255),6:(128,128,128),7:(255,128,0),8:(128,0,255),9:(0,128,0),
         10:(255,0,128),11:(128,255,0),12:(0,128,255),13:(128,0,128),14:(255,128,128),
         15:(128,255,128),16:(128,128,255),17:(255,255,128),18:(204,51,51),
         19:(51,204,51),20:(51,51,204),21:(204,204,51),22:(51,204,204),
         23:(204,51,204),24:(77,77,77),25:(179,77,0),26:(0,0,0)}
NAMES={1:'asphalt',2:'cement',3:'epoxy_floor',4:'brick_road',16:'bumper',
       17:'manhole_cover',23:'road_joint',24:'moving_obstacle',25:'fixed_obstacle'}
BG=(17,19,16)

def context_files(vis_dir,base):
    vis=Path(vis_dir);base=str(base)
    files={key:vis/(base+suffix) for key,suffix in {
        'camera':'_image.jpg','mesh_gt':'_mesh_gt.npy','mesh_pred':'_mesh_pred.npy',
        'lidar':'_lidar.pcd.bin.npy','gaussian':'_gaussian.pkl','metadata':'_paths.json'}.items()}
    for key,path in files.items():
        if not path.is_file():raise ValueError('Five-view requires '+key+': '+str(path))
    return files

def read_gaussian(path):
    # The local project evaluation pickle is trusted, matching the supplied plugin.
    with Path(path).open('rb') as stream:raw=pickle.load(stream)
    g={key:np.asarray(raw[key],dtype=float) for key in ['means','scales','rots','semantics','opas']}
    n=len(g['means'])
    if (g['means'].shape!=(n,3) or g['scales'].shape!=(n,3) or g['rots'].shape!=(n,4)
        or g['semantics'].ndim!=2 or len(g['semantics'])!=n or not 1<=g['semantics'].shape[1]<=27
        or g['opas'].size!=n or not n or any(not np.isfinite(v).all() for v in g.values())
        or (g['scales']<=0).any()):raise ValueError('Invalid exported Gaussian parameters')
    g['opas']=g['opas'].reshape(-1)
    if (g['opas']<0).any() or (g['opas']>1).any():raise ValueError('Expected activated opacity in [0,1]')
    q=g['rots'];norm=np.linalg.norm(q,axis=1)
    if (norm<1e-8).any():raise ValueError('Invalid Gaussian quaternion')
    w,x,y,z=(q/norm[:,None]).T
    g['rotation']=np.stack([1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y),
                          2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x),
                          2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)],axis=1).reshape(n,3,3)
    g['labels']=np.argmax(g['semantics'],axis=1)
    return g

def basis(elevation_deg=30.,azimuth_deg=8.):
    return camera_basis(elevation_deg,azimuth_deg)

class View:
    def __init__(self,xyz,size,zscale=1.,top=68,elevation_deg=30.,azimuth_deg=8.):
        require_equal_axes(zscale)
        self.size=size;self.top=top;self.basis=basis(elevation_deg,azimuth_deg);self.stretch=np.ones(3)
        projected=(xyz*self.stretch)@self.basis
        self.low=projected[:,:2].min(0);self.high=projected[:,:2].max(0)
        width,height=size
        self.scale=min((width-68)/max(self.high[0]-self.low[0],.1),
                       (height-top-85)/max(self.high[1]-self.low[1],.1))
    def project(self,xyz):
        p=(np.asarray(xyz)*self.stretch)@self.basis
        width,height=self.size
        return np.column_stack(((p[:,0]-self.low[0])*self.scale+(width-(self.high[0]-self.low[0])*self.scale)/2,
              height-52-(p[:,1]-self.low[1])*self.scale,p[:,2]))

def point_pane(points,view,semantic=True):
    width,height=view.size;out=np.full((height,width,3),BG,dtype=np.uint8)
    p=view.project(points[:,:3]);x,y=np.rint(p[:,0]).astype(int),np.rint(p[:,1]).astype(int)
    valid=(x>=8)&(x<width-8)&(y>=view.top)&(y<height-35)
    if semantic:valid&=points[:,3]!=26
    x,y,z,v=x[valid],y[valid],p[valid,2],points[valid,3]
    if not len(x):
        empty=Image.fromarray(out);ImageDraw.Draw(empty).text((30,90),'无可见点',font=font(23),fill='#bbc2af');return empty
    cell=y*width+x;order=np.lexsort((z,cell));cell=cell[order]
    keep=order[np.r_[True,cell[1:]!=cell[:-1]]]
    if semantic:
        color=np.array([PALETTE.get(int(k),(130,130,130)) for k in v[keep]],dtype=np.uint8)
    else:
        # Zero-intensity points remain visible on black; fixed linear RGB display mapping from (100,140,180) to (245,250,255).
        value=np.clip(v[keep],0,255)/255
        color=np.column_stack((100+145*value,140+110*value,180+75*value)).astype('uint8')
    for dx,dy in [(0,0),(1,0),(0,1),(1,1)]:
        out[y[keep]+dy,x[keep]+dx]=color
    return Image.fromarray(out)

def gaussian_pane(g,size,zscale=1.,threshold=.05,elevation_deg=30.,azimuth_deg=8.):
    valid=g['opas']>=threshold
    means,scales,rots=g['means'][valid],g['scales'][valid],g['rotation'][valid]
    labels,opas=g['labels'][valid],g['opas'][valid]
    if not len(means):raise ValueError('No Gaussian primitives at declared opacity threshold')
    # Bounds include all oriented ellipsoids; scale is the exported semi-axis value.
    ext=np.sqrt(np.sum((rots*scales[:,None,:])**2,axis=2))
    corners=np.array([[x,y,z] for x in [-1,1] for y in [-1,1] for z in [-1,1]])
    limits=(means[:,None,:]+ext[:,None,:]*corners).reshape(-1,3)
    view=View(limits,size,zscale=zscale,top=220,elevation_deg=elevation_deg,azimuth_deg=azimuth_deg)
    im=Image.new('RGB',size,BG);draw=ImageDraw.Draw(im,'RGBA')
    t=np.linspace(0,2*np.pi,33)
    rings=[np.column_stack((np.cos(t),np.sin(t),np.zeros_like(t))),
           np.column_stack((np.cos(t),np.zeros_like(t),np.sin(t))),
           np.column_stack((np.zeros_like(t),np.cos(t),np.sin(t)))]
    depths=view.project(means)[:,2]
    for index in np.argsort(-depths,kind='stable'):
        color=(*PALETTE.get(int(labels[index]),(130,130,130)),int(round(opas[index]*255)))
        for ring in rings:
            xyz=(ring*scales[index])@rots[index].T+means[index]
            pixels=view.project(xyz)[:,:2]
            draw.line([tuple(v) for v in pixels],fill=color,width=1)
    draw=ImageDraw.Draw(im)
    draw.text((16,62),f'opacity ≥ {threshold:g}   ·   {len(means):,} / {len(g["means"]):,} 基元',font=font(21),fill='#d6daca')
    y=98
    unique,counts=np.unique(labels,return_counts=True)
    for idx in np.argsort(-counts)[:5]:
        label,count=int(unique[idx]),int(counts[idx]);color=PALETTE.get(label,(130,130,130))
        draw.rectangle((18,y+5,29,y+18),fill=color)
        draw.text((40,y),f'[{label}] {NAMES.get(label,"class_"+str(label))}  {count:,}',font=font(19),fill='#d6daca');y+=28
    return im,{'exported_count':len(g['means']),'displayed_count':len(means),
               'opacity_threshold':threshold,'class_counts':{str(int(k)):int(v) for k,v in zip(unique,counts)}}

def make_card(vis_dir,base,output,index=None,zscale=1.,opacity_threshold=.05,elevation_deg=30.,azimuth_deg=8.):
    require_equal_axes(zscale)
    camera_config=camera_settings(elevation_deg,azimuth_deg)
    files=context_files(vis_dir,base);meta=json.loads(files['metadata'].read_text(encoding='utf-8'))
    if meta['datalink_frame']['frame_index']!=7:raise ValueError('Expected fixed frame 7')
    gt,pred=read_mesh(files['mesh_gt']),read_mesh(files['mesh_pred'])
    lidar=np.load(files['lidar'],allow_pickle=False)
    if lidar.ndim!=2 or lidar.shape[1]!=4 or not len(lidar) or not np.isfinite(lidar).all():
        raise ValueError('Invalid LiDAR array')
    g=read_gaussian(files['gaussian'])
    if not zscale>0 or not 0<=opacity_threshold<=1:raise ValueError('Invalid display parameters')
    width,height,col=2880,1600,720
    im=Image.new('RGB',(width,height),BG);draw=ImageDraw.Draw(im)
    draw.text((18,14),'2.5D Mesh · GT / Prediction / Camera / LiDAR / Gaussian',font=font(29),fill='#d9ded3')
    draw.text((18,57),f'{meta["scene_name"]}  · frame 7  · source {base}',font=font(19),fill='#9aa590')
    top,bottom=98,1532;panel_h=bottom-top
    shared=View(np.concatenate([gt[:,:3],pred[:,:3]]),(col-8,panel_h),zscale=zscale,elevation_deg=elevation_deg,azimuth_deg=azimuth_deg)
    im.paste(point_pane(gt,shared),(4,top));im.paste(point_pane(pred,shared),(col+4,top))
    camera=Image.open(files['camera']);camera.load();camera=camera.convert('RGB')
    # Preserve the complete image with letterboxing, no cropping or enhancement.
    camera.thumbnail((col-16,482),Image.Resampling.LANCZOS)
    im.paste(camera,(2*col+(col-camera.width)//2,top+58+(482-camera.height)//2))
    lidar_top=top+610
    lidar_size=(col-8,bottom-lidar_top)
    lidar_view=View(lidar[:,:3],lidar_size,zscale=zscale,elevation_deg=elevation_deg,azimuth_deg=azimuth_deg)
    im.paste(point_pane(lidar,lidar_view,semantic=False),(2*col+4,lidar_top))
    gpane,gstats=gaussian_pane(g,(col-8,panel_h),zscale,opacity_threshold,elevation_deg,azimuth_deg)
    im.paste(gpane,(3*col+4,top))
    draw=ImageDraw.Draw(im)
    for x in range(0,width,col):draw.rectangle((x,top,x+col-1,bottom),outline='#3a4036',width=2)
    draw.line((2*col,lidar_top,3*col,lidar_top),fill='#3a4036',width=2)
    for x,y,title,color in [(18,top+12,'GT','#75d77e'),(col+18,top+12,'Prediction','#e78484'),
        (2*col+18,top+12,'Camera','#d8ddd2'),(2*col+18,lidar_top+12,'LiDAR · intensity','#d1b5e0'),
        (3*col+18,top+12,'Gaussian · oriented ellipsoids','#8ec0ec')]:
        draw.text((x,y),title,font=font(24),fill=color)
    draw.text((2*col+18,top+553),'实车前视原图 · 完整画幅 · 未增强',font=font(19),fill='#a8b09e')
    draw.text((2*col+18,lidar_top+48),f'{len(lidar):,} 点 · 原产物已裁剪道路 ROI',font=font(19),fill='#a8b09e')
    xyz_min,xyz_max=lidar[:,:3].min(0),lidar[:,:3].max(0)
    draw.text((2*col+18,bottom-30),f'X {xyz_min[0]:.1f}–{xyz_max[0]:.1f}m  Y {xyz_min[1]:.1f}–{xyz_max[1]:.1f}m',font=font(17),fill='#a8b09e')
    draw.text((18,bottom+13),f'GT/PRED 同视角同尺度 · XYZ 1:1:1 · 俯角 {elevation_deg:g}° / 方位 {azimuth_deg:g}° · Gaussian为导出尺度/旋转的椭球线框，非照片级RGB渲染',font=font(21),fill='#b3bda6')
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True);im.save(output)
    return {'scene_name':meta['scene_name'],'source_index':str(base),'frame_index':7,
            'path':str(output),'sha256':sha(output),'size':[width,height],
            'sources':{key:{'filename':p.name,'sha256':sha(p)} for key,p in files.items()},
            'profile':'five-view/v1','panels':['GT','Prediction','Camera','LiDAR','Gaussian'],
            'shared_gt_pred_camera':True,'camera':camera_config,'axis_scale_xyz':[1.,1.,1.],'z_display_scale':1.,'gaussian':gstats,
            'lidar':{'point_count':len(lidar),'xyz_min':xyz_min.tolist(),'xyz_max':xyz_max.tolist(),
                     'intensity_range':[float(lidar[:,3].min()),float(lidar[:,3].max())]},
            'transformations':['full camera image downscale/letterbox without enhancement',
                'fixed orthographic direction; GT and prediction share fit and scale',
                'separate uniform fitting for smaller LiDAR and Gaussian panes; XYZ scale 1:1:1',
                '2x2 display pixels per input sample; no new sample data',
                'LiDAR intensity 0..255 linearly maps RGB (100,140,180)..(245,250,255)',
                'Gaussian exported scales and wxyz rotations; three ellipsoid great-circle rings',
                'Gaussian wire alpha from exported opacity; no radiance/splat renderer'],
            'palette':{str(k):list(v) for k,v in PALETTE.items()}}
