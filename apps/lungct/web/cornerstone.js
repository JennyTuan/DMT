import {cache, Enums, imageLoader, init, RenderingEngine, utilities} from '@cornerstonejs/core';

const scheme='lungct:';
const maxCacheBytes=96*1024*1024;
const viewportIds=['axial','coronal'];

export function createViewer(){
  init({rendering:{webGlContextCount:1}});
  cache.setMaxCacheSize(maxCacheBytes);
  const engine=new RenderingEngine('lungct');
  const pending=new Map();

  function viewport(id){
    let view=engine.getViewport(id);
    if(!view){
      engine.enableElement({
        viewportId:id,
        type:Enums.ViewportType.STACK,
        element:document.getElementById(id+'Viewport'),
        defaultOptions:{background:[0.04,0.04,0.05]},
      });
      view=engine.getViewport(id);
    }
    return view;
  }

  async function loadFrame(imageId, geometry){
    const response=await fetch(imageId.slice(scheme.length));
    if(!response.ok)throw Error('影像加载失败');
    const pixels=new Float32Array(await response.arrayBuffer());
    if(pixels.length!==geometry.dimensions[0]*geometry.dimensions[1])throw Error('影像尺寸与登记序列不符');
    utilities.genericMetadataProvider.add(imageId,{
      type:Enums.MetadataModules.GENERAL_SERIES,
      metadata:{modality:'CT'},
    });
    return imageLoader.createAndCacheLocalImage(imageId,{
      ...geometry,
      scalarData:pixels,
      targetBuffer:{type:'Float32Array'},
      onCacheAdd(image){
        image.windowCenter=-600;image.windowWidth=1500;
        image.isPreScaled=true;
      },
    });
  }

  function prepare(imageId, geometry){
    const image=cache.getImage(imageId);
    if(image)return Promise.resolve(image);
    if(!pending.has(imageId)){
      const request=loadFrame(imageId,geometry).finally(()=>pending.delete(imageId));
      pending.set(imageId,request);
    }
    return pending.get(imageId);
  }

  const stacks=new Map();
  async function display(id,imageIds,index,center,width){
    const view=viewport(id);
    if(stacks.get(id)!==imageIds){
      await view.setStack(imageIds,index);
      stacks.set(id,imageIds);
    }else if(view.getCurrentImageIdIndex()!==index){
      await view.setImageIdIndex(index);
    }
    windowImage(id,center,width);
    view.render();
  }
  function windowImage(id,center,width){
    const view=engine.getViewport(id);
    if(!view?.getCurrentImageId())return;
    const voiRange=utilities.windowLevel.toLowHighRange(width,center);
    const previous=view.getProperties().voiRange;
    if(previous?.lower===voiRange.lower&&previous?.upper===voiRange.upper)return;
    view.setProperties({voiRange});
    view.render();
  }
  function camera(zoom,pan){
    const view=engine.getViewport('axial');
    if(!view?.getCurrentImageId())return;
    let changed=false;
    if(Math.abs(view.getZoom()-zoom)>1e-5){view.setZoom(zoom);changed=true;}
    const previous=view.getPan();
    if(Math.hypot(pan[0]-previous[0],pan[1]-previous[1])>.01){view.setPan(pan);changed=true;}
    if(changed)view.render();
  }
  function resize(){
    if(viewportIds.some(id=>{
      const view=engine.getViewport(id),element=view?.element;
      return element?.clientWidth&&element.clientHeight;
    }))engine.resize(true,true);
  }
  function clear(){
    for(const id of viewportIds)if(engine.getViewport(id))engine.disableElement(id);
    stacks.clear();
  }
  return {
    imageId:url=>scheme+url,
    prepare,display,windowImage,camera,resize,clear,
    point:(id,world)=>viewport(id).worldToCanvas(world),
    world:(id,point)=>viewport(id).canvasToWorld(point),
  };
}
