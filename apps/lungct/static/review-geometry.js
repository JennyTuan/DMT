export function perpendicularAxis(longAxis,shortAxis,normal,{centered=false}={}){
  const v=longAxis[1].map((value,i)=>value-longAxis[0][i]);
  const n=[normal[1]*v[2]-normal[2]*v[1],normal[2]*v[0]-normal[0]*v[2],normal[0]*v[1]-normal[1]*v[0]];
  const length=Math.hypot(...n);
  if(!length)return shortAxis;
  const unit=n.map(x=>x/length),delta=shortAxis[1].map((value,i)=>value-shortAxis[0][i]);
  const projection=delta.reduce((sum,value,i)=>sum+value*unit[i],0);
  if(!centered)return [shortAxis[0],shortAxis[0].map((value,i)=>value+projection*unit[i])];
  const half=Math.hypot(...delta)*Math.sign(projection||1)/2;
  return [-1,1].map(sign=>shortAxis[0].map((value,i)=>value+delta[i]/2+sign*half*unit[i]));
}
