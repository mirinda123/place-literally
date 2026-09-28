import bezierSpline from '@turf/bezier-spline';
import type {Feature,LineString,MultiLineString} from 'geojson';

type Point=[number,number];
const wrap=(lon:number)=>((lon+180)%360+360)%360-180;

/** A surface arc with a deliberate sideways bend, split at the date line. */
export function connectionArc(start:Point,end:Point):Feature<LineString|MultiLineString>{
 const finish:[number,number]=[start[0]+((((end[0]-start[0])+540)%360)-180),end[1]];
 const meanLat=(start[1]+finish[1])/2;
 const scale=Math.max(0.25,Math.cos(meanLat*Math.PI/180));
 const dx=(finish[0]-start[0])*scale,dy=finish[1]-start[1];
 const distance=Math.hypot(dx,dy);
 if(distance<1e-8)return {type:'Feature',properties:{},geometry:{type:'LineString',coordinates:[start,end]}};
 const bend=Math.min(20,Math.max(0.45,distance*0.23));
 const direction=(start[0]+start[1])<(finish[0]+finish[1])?1:-1;
 const control:Point=[(start[0]+finish[0])/2+direction*(-dy/distance)*bend/scale,
                      Math.max(-85,Math.min(85,(start[1]+finish[1])/2+direction*(dx/distance)*bend))];
 const path=bezierSpline({type:'Feature',properties:{},geometry:{type:'LineString',coordinates:[start,control,finish]}},
                         {resolution:10000,sharpness:0.85}).geometry.coordinates as Point[];
 const segments:Point[][]=[[ [wrap(path[0][0]),path[0][1]] ]];
 for(let i=1;i<path.length;i++){
  const a=path[i-1],b=path[i];
  const wa=Math.floor((a[0]+180)/360),wb=Math.floor((b[0]+180)/360);
  if(wa!==wb){
   const boundary=(b[0]>a[0]?180:-180)+360*wa;
   const fraction=(boundary-a[0])/(b[0]-a[0]);
   const latitude=a[1]+fraction*(b[1]-a[1]);
   segments[segments.length-1].push([b[0]>a[0]?180:-180,latitude]);
   segments.push([[b[0]>a[0]?-180:180,latitude]]);
  }
  segments[segments.length-1].push([wrap(b[0]),b[1]]);
 }
 return {type:'Feature',properties:{},geometry:segments.length===1?
  {type:'LineString',coordinates:segments[0]}:{type:'MultiLineString',coordinates:segments}};
}
