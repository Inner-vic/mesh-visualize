"""Truthful fixed-view cards from real camera images and actual mesh samples."""
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from view_camera import basis as camera_basis,settings as camera_settings,require_equal_axes

PALETTE={1:(59,130,246),2:(234,179,8),4:(180,83,9),16:(219,39,119),
         17:(6,182,212),23:(249,115,22),24:(22,163,74),25:(139,92,246)}
NAMES={1:'沥青',2:'水泥',4:'砖石路',16:'减速带',17:'井盖',23:'桥梁接缝',
       24:'可移动障碍物',25:'不可移动障碍物'}
FONT_CANDIDATES=[Path('C:/Windows/Fonts/msyh.ttc'),Path('/System/Library/Fonts/PingFang.ttc'),
                 Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]

def font(size):
    for path in FONT_CANDIDATES:
        if path.is_file():return ImageFont.truetype(str(path),size)
    raise ValueError('CJK font unavailable; install Noto Sans CJK or configure FONT_CANDIDATES')

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def colors(labels):
    result=np.full((len(labels),3),140,dtype=np.uint8)
    for label,color in PALETTE.items():result[labels==label]=color
    return result

def read_mesh(path):
    a=np.load(path,allow_pickle=False)
    if a.ndim!=2 or a.shape[1]!=5 or not len(a) or not np.isfinite(a).all():
        raise ValueError('Invalid actual mesh sample array: '+str(path))
    if np.any(a[:,3]!=np.floor(a[:,3])) or a[:,3].min()<0 or a[:,3].max()>26:
        raise ValueError('Invalid mesh class IDs')
    return a

def rotation(q):
    w,x,y,z=np.array([q[k] for k in ['w','x','y','z']],dtype=float)
    norm=np.linalg.norm([w,x,y,z])
    if not norm>0:raise ValueError('Invalid camera quaternion')
    w,x,y,z=np.array([w,x,y,z])/norm
    return np.array([[1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y)],
                     [2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x)],
                     [2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)]])

def project(points,sensor):
    # Same VCS -> camera and equidistant distortion convention as supplied plugin.
    cam=sensor['sensor_param']['cam']
    if cam['dist_model']!='equidistant' or cam['proj_model']!='pinhole':
        raise ValueError('Unsupported camera projection convention')
    r=rotation(cam['q_vcs_cam']);t=np.array([cam['t_vcs_cam'][k] for k in ['x','y','z']])
    xyz=(points[:,:3]-t)@r
    valid=xyz[:,2]>.1
    safe=np.maximum(xyz[:,2],.1)
    x,y=xyz[:,0]/safe,xyz[:,1]/safe
    radius=np.hypot(x,y);theta=np.arctan(radius)
    dist=cam['dist_param']
    td=theta*(1+sum(dist[f'k{i}']*theta**(2*i) for i in range(1,5)))
    scale=np.divide(td,radius,out=np.ones_like(radius),where=radius>1e-8)
    p=cam['proj_param']
    u,v=p['fu']*x*scale+p['cu'],p['fv']*y*scale+p['cv']
    res=cam['resolution']
    valid&=(u>=0)&(u<res['ru'])&(v>=0)&(v<res['rv'])&(points[:,3]!=26)
    return u,v,xyz[:,2],valid

def nearest_pixels(u,v,depth,label,width,height):
    x,y=np.rint(u).astype(int),np.rint(v).astype(int)
    valid=(x>=0)&(x<width)&(y>=0)&(y<height)
    x,y,depth,label=x[valid],y[valid],depth[valid],label[valid]
    cells=y*width+x
    if not len(cells):return x,y,label
    order=np.lexsort((label,depth,cells))
    cells=cells[order];first=np.r_[True,cells[1:]!=cells[:-1]]
    chosen=order[first]
    return x[chosen],y[chosen],label[chosen]

def overlay(photo,points,sensor,size):
    image=photo.resize(size,Image.Resampling.LANCZOS).convert('RGB')
    cam=sensor['sensor_param']['cam'];res=cam['resolution']
    if photo.size!=(res['ru'],res['rv']):raise ValueError('Camera resolution differs from calibration')
    u,v,z,mask=project(points,sensor)
    x,y,labels=nearest_pixels(u[mask]*size[0]/res['ru'],v[mask]*size[1]/res['rv'],
                            z[mask],points[mask,3].astype(int),*size)
    original=np.asarray(image).copy();paint=colors(labels)
    original[y,x]=(original[y,x]*.35+paint*.65).astype('uint8')
    return Image.fromarray(original),int(mask.sum())

def view_transform(all_points,elevation_deg=30.,azimuth_deg=8.,zscale=1.):
    require_equal_axes(zscale)
    basis=camera_basis(elevation_deg,azimuth_deg)
    stretch=np.ones(3)
    coords=all_points[:,:3]@basis
    low=coords[:,:2].min(0);high=coords[:,:2].max(0)
    return basis,stretch,low,high


def mesh_view(points,transform,size,xyz_bounds):
    basis,zscale,low,high=transform;width,height=size
    scale=min((width-120)/max(high[0]-low[0],.1),(height-100)/max(high[1]-low[1],.1))
    def pos(xyz):
        coords=(np.asarray(xyz)*zscale)@basis
        return np.column_stack(((coords[:,0]-low[0])*scale+(width-(high[0]-low[0])*scale)/2,
                                height-55-(coords[:,1]-low[1])*scale,coords[:,2]))
    im=Image.new('RGB',size,'#f1f5f9');draw=ImageDraw.Draw(im)
    xmin,ymin,zmin,xmax,ymax,zmax=xyz_bounds
    for x in np.arange(np.ceil(xmin/5)*5,xmax+.1,5):
        q=pos([[x,ymin,zmin],[x,ymax,zmin]])
        draw.line([tuple(q[0,:2]),tuple(q[1,:2])],fill='#bdcbd7',width=1)
        draw.text(tuple(q[0,:2]),f'{x:g}m',font=font(17),fill='#4b647b')
    for y in np.arange(np.ceil(ymin/2)*2,ymax+.1,2):
        q=pos([[xmin,y,zmin],[xmax,y,zmin]])
        draw.line([tuple(q[0,:2]),tuple(q[1,:2])],fill='#d2dce5',width=1)
    coords=pos(points[:,:3]);mask=points[:,3]!=26
    x,y,labels=nearest_pixels(coords[mask,0],coords[mask,1],coords[mask,2],points[mask,3].astype(int),width,height)
    pixels=np.asarray(im).copy();pixels[y,x]=colors(labels)
    im=Image.fromarray(pixels);draw=ImageDraw.Draw(im)
    draw.text((18,15),'连续表面采样点 · X/Y/Z 单位 m · 等倍率 1:1:1',font=font(20),fill='#263e55')
    draw.text((18,height-34),'同一视角 / 同一尺度；未构造或平滑三角网面',font=font(19),fill='#4b647b')
    return im

def context_files(vis_dir,base):
    vis=Path(vis_dir);base=str(base)
    files={key:vis/(base+suffix) for key,suffix in {
        'camera':'_image.jpg','mesh_gt':'_mesh_gt.npy','mesh_pred':'_mesh_pred.npy',
        'sensor':'_sensor_param.json','metadata':'_paths.json'}.items()}
    for key,path in files.items():
        if not path.is_file():raise ValueError('Scene card requires '+key+': '+str(path))
    return files

def make_card(vis_dir,base,output,index=None,elevation_deg=30.,azimuth_deg=8.,zscale=1.):
    require_equal_axes(zscale)
    camera_config=camera_settings(elevation_deg,azimuth_deg)
    vis=Path(vis_dir);base=str(base);output=Path(output)
    files=context_files(vis,base)
    meta=json.loads(files['metadata'].read_text(encoding='utf-8'))
    sensor=json.loads(files['sensor'].read_text(encoding='utf-8'))
    if sensor['scene_name']!=meta['scene_name']:raise ValueError('Scene/calibration identity mismatch')
    if meta['datalink_frame']['frame_index']!=7:raise ValueError('Scene card requires registered frame 7')
    gt,pred=read_mesh(files['mesh_gt']),read_mesh(files['mesh_pred'])
    photo=Image.open(files['camera']);photo.load()
    combined=np.concatenate([gt[:,:3],pred[:,:3]])
    transform=view_transform(combined,elevation_deg,azimuth_deg)
    bounds=[*combined.min(0),*combined.max(0)]
    size=(936,526)
    gt_overlay,n_gt=overlay(photo,gt,sensor,size)
    pred_overlay,n_pred=overlay(photo,pred,sensor,size)
    card=Image.new('RGB',(2000,2010),'#ffffff');draw=ImageDraw.Draw(card)
    draw.text((48,24),'2.5D Mesh｜实车场景与重建结果',font=font(42),fill='#142b43')
    draw.text((48,86),f'场景 {meta["scene_name"]}  /  frame 7  /  源编号 {base}',font=font(23),fill='#4b647b')
    def title(x,y,value):draw.text((x,y),value,font=font(28),fill='#1d3c59')
    title(48,138,'实车前视原图（仅等比缩小，未增强）')
    card.paste(photo.resize(size,Image.Resampling.LANCZOS),(48,184))
    title(1032,138,'图例与原始点数（GT / PRED）')
    for offset,(label,name) in enumerate(NAMES.items()):
        y=198+offset*48
        draw.rectangle((1036,y+5,1057,y+26),fill=PALETTE[label])
        ng,npred=int((gt[:,3]==label).sum()),int((pred[:,3]==label).sum())
        draw.text((1074,y),f'{label:02d} {name}',font=font(24),fill='#233d55')
        draw.text((1508,y),f'{ng:,} / {npred:,}',font=font(23),fill='#233d55')
    draw.text((1034,607),'点数用于说明类别支持，不是逐点准确率。',font=font(23),fill='#526b82')
    draw.text((1034,650),'下方投影沿用原插件的 VCS 与相机标定约定。',font=font(22),fill='#526b82')
    title(48,752,'GT：真实 Mesh 表面采样点')
    title(1032,752,'PRED：模型 Mesh 表面采样点')
    card.paste(mesh_view(gt,transform,size,bounds),(48,800))
    card.paste(mesh_view(pred,transform,size,bounds),(1032,800))
    title(48,1366,'GT 投影回原相机图（65% 语义点色）')
    title(1032,1366,'PRED 投影回原相机图（65% 语义点色）')
    card.paste(gt_overlay,(48,1414));card.paste(pred_overlay,(1032,1414))
    draw.text((48,1960),'真实照片 + 真实 Mesh 点；未独立复验标定/时空配准，投影仅用于对应场景位置；不替代正式 M1/M2。',font=font(21),fill='#526b82')
    output.parent.mkdir(parents=True,exist_ok=True);card.save(output)
    return {'scene_name':meta['scene_name'],'source_index':base,'frame_index':7,
            'path':str(output),'sha256':sha(output),'size':[2000,2010],'camera':camera_config,'axis_scale_xyz':[1.,1.,1.],'z_display_scale':1.,
            'sources':{key:{'filename':path.name,'sha256':sha(path)} for key,path in files.items()},
            'camera_projection':'supplied plugin equidistant convention; not independently recalibrated',
            'point_counts':{'gt':len(gt),'pred':len(pred),'camera_visible_gt':n_gt,'camera_visible_pred':n_pred},
            'transformations':['camera proportional downscale, no contrast adjustment',
                'fixed common orthographic view, equal XYZ scale 1:1:1',
                'nearest visible sample per output pixel, no triangulation/interpolation',
                'camera overlay opacity .65, supplied camera calibration'],
            'palette':{str(k):{'name':NAMES[k],'rgb':list(v)} for k,v in PALETTE.items()}}
