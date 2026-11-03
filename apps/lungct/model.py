"""Offline detector protocol and MONAI 0.6.9 adapter. No fallback predictions."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from .core import uid, now, owned, digest
from .geometry import patient_to_pixel
from .review import create_finding

POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='lungct-local')
PREPROCESS=dict(bundle_version='0.6.9',orientation='RAS',spacing=[.703125,.703125,1.25],hu_range=[-1024,300],nms=.22,patch=[512,512,192],cuda_amp=True)


class MonaiAdapter:
    def __init__(self,bundle,*,profile='standard'):
        if profile not in ('standard','low-memory'):raise ValueError('未知模型内存配置')
        self.bundle=Path(bundle).resolve();self.profile=profile
        self.preprocessing=deepcopy(PREPROCESS)
        if profile=='low-memory':self.preprocessing['patch']=[256,256,96]

    def metadata(self):
        weights=self.bundle/'models'/'model.pt'
        if not weights.is_file():raise ValueError('WEIGHTS_MISSING')
        try:metadata=json.loads((self.bundle/'configs'/'metadata.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):raise ValueError('MODEL_VERSION') from None
        if metadata.get('version')!='0.6.9':raise ValueError('MODEL_VERSION')
        from . import VERSION
        return dict(name='MONAI/lung_nodule_ct_detection',version='0.6.9',weight_sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),preprocessing_sha256=digest(self.preprocessing),preprocessing=deepcopy(self.preprocessing),execution_profile=self.profile,license='Apache-2.0',software_version=VERSION,adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

    def predict(self,volume,geometry,threshold):
        # Requires a separate compatible environment; imports cannot affect manual mode.
        import torch
        import monai
        from monai.data import MetaTensor
        from monai.transforms import Orientation, Spacing, ScaleIntensityRange
        from monai.networks.nets import resnet
        from monai.apps.detection.networks.retinanet_network import RetinaNet,resnet_fpn_feature_extractor
        from monai.apps.detection.networks.retinanet_detector import RetinaNetDetector
        from monai.apps.detection.utils.anchor_utils import AnchorGeneratorWithAnchorShape
        if monai.__version__!='1.4.0' or torch.__version__.split('+')[0] not in ('2.4.0','2.4.1'):raise ValueError('MODEL_DEPENDENCIES')
        torch.manual_seed(0);np.random.seed(0)
        device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        if device.type=='cuda':torch.cuda.reset_peak_memory_stats()
        backbone=resnet.resnet50(spatial_dims=3,n_input_channels=1,conv1_t_stride=[2,2,1],conv1_t_size=[7,7,7])
        features=resnet_fpn_feature_extractor(backbone,3,False,[1,2],None)
        network=RetinaNet(spatial_dims=3,num_classes=1,num_anchors=3,feature_extractor=features,size_divisible=[16,16,8],use_list_output=False)
        checkpoint=torch.load(self.bundle/'models'/'model.pt',map_location='cpu',weights_only=True)
        network.load_state_dict(checkpoint.get('model',checkpoint),strict=True);network.to(device).eval()
        anchors=AnchorGeneratorWithAnchorShape(feature_map_scales=[1,2,4],base_anchor_shapes=[[6,8,4],[8,6,5],[10,10,6]])
        detector=RetinaNetDetector(network=network,anchor_generator=anchors,spatial_dims=3,num_classes=1,size_divisible=[16,16,8])
        detector.eval()
        detector.set_target_keys(box_key='box',label_key='label')
        detector.set_box_selector_parameters(score_thresh=threshold,topk_candidates_per_level=1000,nms_thresh=.22,detections_per_img=300)
        detector.set_sliding_window_inferer(roi_size=self.preprocessing['patch'],overlap=.25,sw_batch_size=1,mode='constant',device='cpu')
        affine=np.eye(4);affine[:3,0]=np.asarray(geometry.row)*geometry.spacing[1]
        affine[:3,1]=np.asarray(geometry.column)*geometry.spacing[0]
        affine[:3,2]=np.asarray(geometry.normal)*np.median(np.diff(geometry.locations));affine[:3,3]=geometry.origins[0]
        lps_ras=np.diag([-1.,-1.,1.,1.])
        tensor=MetaTensor(torch.tensor(np.array(volume.transpose(2,1,0)[None]),dtype=torch.float32),affine=torch.tensor(lps_ras @ affine,dtype=torch.float64))
        tensor=Spacing(pixdim=PREPROCESS['spacing'],mode='bilinear')(Orientation(axcodes='RAS')(tensor))
        model_to_lps=lps_ras @ np.asarray(tensor.affine.cpu())
        tensor=ScaleIntensityRange(a_min=-1024,a_max=300,b_min=0,b_max=1,clip=True)(tensor)
        with torch.inference_mode(), torch.autocast(device_type=device.type,enabled=device.type=='cuda'):
            pred=detector([tensor.to(device)],use_inferer=True)[0]
        candidates=[]
        for box,score in zip(pred['box'].detach().cpu().numpy(),pred['label_scores'].detach().cpu().numpy()):
            low=np.maximum(box[:3],0);high=np.minimum(box[3:],np.asarray(tensor.shape[1:])-1)
            if np.any(high<=low):continue
            corners=np.array([[x,y,z,1] for x in (low[0],high[0]) for y in (low[1],high[1]) for z in (low[2],high[2])])
            world=(corners @ model_to_lps.T)[:,:3];lo=world.min(0);hi=world.max(0)
            candidates.append(dict(center_lps=((lo+hi)/2).tolist(),box_lps=np.r_[lo,hi].tolist(),score=float(score)))
        import platform
        runtime=dict(python=platform.python_version(),torch=torch.__version__,monai=monai.__version__,
            numpy=np.__version__,device=torch.cuda.get_device_name(0) if device.type=='cuda' else 'CPU',
            cuda=torch.version.cuda,precision='cuda_autocast_float16' if device.type=='cuda' else 'float32')
        if device.type=='cuda':
            runtime.update(cuda_peak_allocated_bytes=torch.cuda.max_memory_allocated(),cuda_peak_reserved_bytes=torch.cuda.max_memory_reserved())
        return dict(candidates=candidates,model_to_lps=model_to_lps.tolist(),runtime=runtime)


class ModelService:
    def start_run(self,project,series,request_key,threshold=.02):
        from .core import code
        code(request_key)
        if not isinstance(threshold,(int,float)) or not np.isfinite(threshold) or not 0<=threshold<=1:raise ValueError('模型阈值无效')
        with self.repo.transaction() as state:
            selected=owned(state,'series',series,project)
            if not selected['eligible'] or state['studies'][selected['study_key']]['selected_series']!=series:raise ValueError('请先选择合格分析序列')
            for run in state['runs'].values():
                if run['project_id']==project and run['series_key']==series and run['request_key']==request_key:
                    if run['threshold']!=threshold:raise ValueError('同一请求键不能更换参数')
                    return deepcopy(run)
            run=dict(run_id=uid('run'),project_id=project,series_key=series,request_key=request_key,threshold=threshold,
                state='queued',complete=False,created_at=now(),input_sha256=selected['input_sha256'],
                model=None,error_code=None,candidate_count=None,finding_ids=[],initial_revisions={},elapsed_seconds=None,message='排队中')
            state['runs'][run['run_id']]=run
        POOL.submit(self._execute_run,project,run['run_id'],self.model)
        return run

    def get_run(self,project,run_id):return deepcopy(owned(self.repo.read(),'runs',run_id,project))

    def _execute_run(self,project,rid,adapter):
        started=time.monotonic()
        try:
            with self.repo.transaction() as state:
                run=owned(state,'runs',rid,project);run.update(state='running',message='正在分析')
            if adapter is None:raise ValueError('MODEL_NOT_CONFIGURED')
            metadata=adapter.metadata()
            with self.repo.transaction() as state:state['runs'][rid]['model']=metadata
            run=self.get_run(project,rid);volume,g=self.volume(project,run['series_key'])
            result=adapter.predict(volume,g,run['threshold'])
            transform=np.asarray(result['model_to_lps'],dtype=float)
            if transform.shape!=(4,4) or not np.isfinite(transform).all() or abs(np.linalg.det(transform))<1e-12:raise ValueError('INVALID_RESULTS')
            if not isinstance(result['candidates'],list):raise ValueError('INVALID_RESULTS')
            for candidate in result['candidates']:
                patient_to_pixel(g,candidate['center_lps'])
                box=np.asarray(candidate['box_lps'],dtype=float);score=candidate['score']
                if box.shape!=(6,) or not np.isfinite(box).all() or np.any(box[3:]<=box[:3]) or not np.isfinite(score) or not 0<=score<=1:raise ValueError('INVALID_RESULTS')
                center=np.asarray(candidate['center_lps'])
                if np.any(center<box[:3]) or np.any(center>box[3:]):raise ValueError('INVALID_RESULTS')
            with self.repo.transaction() as state:
                run=state['runs'][rid];series=state['series'][run['series_key']]
                if 'runtime' in result:run['model']['runtime']=deepcopy(result['runtime'])
                # Temporary branch builds all immutable originals in this single transaction.
                staging=dict(project_id=project,series_key=run['series_key'],study_key=series['study_key'],heads={},version=0)
                original_case_status=state['studies'][series['study_key']]['status']
                for c in result['candidates']:
                    f=create_finding(state,staging,c['center_lps'],'MODEL','ai',rid,c['box_lps'],float(c['score']))
                    run['finding_ids'].append(f['finding_id']);run['initial_revisions'][f['finding_id']]=f['revision']['revision_id']
                state['studies'][series['study_key']]['status']=original_case_status
                run.update(state='succeeded',complete=True,candidate_count=len(result['candidates']),model_to_lps=transform.tolist(),
                    elapsed_seconds=time.monotonic()-started,message='AI 未提示候选，仍需人工浏览' if not result['candidates'] else '分析完成，请逐项人工复核')
        except Exception as error:
            if isinstance(error,MemoryError) or 'out of memory' in str(error).lower():code_value='OUT_OF_MEMORY'
            elif isinstance(error,ImportError):code_value='MODEL_DEPENDENCIES'
            elif str(error) in ('MODEL_NOT_CONFIGURED','WEIGHTS_MISSING','MODEL_VERSION','MODEL_DEPENDENCIES'):code_value=str(error)
            else:code_value='INVALID_RESULTS' if isinstance(error,(ValueError,KeyError,TypeError)) else 'INFERENCE_FAILED'
            text={'MODEL_NOT_CONFIGURED':'未配置检测模型，可继续人工标注','WEIGHTS_MISSING':'检测模型权重缺失，请在本机配置获准权重',
                  'MODEL_DEPENDENCIES':'模型依赖不匹配，请使用登记的模型运行环境','MODEL_VERSION':'模型版本不匹配，请核对 0.6.9 配置',
                  'OUT_OF_MEMORY':'分析失败，未生成可用结果：内存或显存不足'}
            with self.repo.transaction() as state:
                state['runs'][rid].update(state='failed',complete=False,error_code=code_value,candidate_count=None,finding_ids=[],initial_revisions={},
                    elapsed_seconds=time.monotonic()-started,message=text.get(code_value,'分析失败，未生成可用结果'))
