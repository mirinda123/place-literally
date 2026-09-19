'use client';
import {greatCircle} from '@turf/great-circle';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import {Globe2, MapPinned} from 'lucide-react';
import {Button} from '../components/ui/button';
import {relationLabel} from '../lib/atlas';
import {PLACE_SOURCE,PLACE_LAYER,placeFeatures,pinImage,replaceBasemapLabels} from '../lib/map-symbols';
import {useEffect,useRef,useState} from 'react';
import type {AtlasRecord} from '../lib/atlas';
import type {Map as MapType,StyleSpecification,GeoJSONSource} from 'maplibre-gl';

type Props={all:AtlasRecord[];visible:AtlasRecord[];selected:string|null;onSelect:(id:string)=>void;fit:number;lines:boolean};
const STREET_STYLE='https://tiles.openfreemap.org/styles/liberty';
const fallbackStyle:StyleSpecification={version:8,glyphs:'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',sources:{world:{type:'geojson',data:'/world.geojson',attribution:'<a href="https://www.naturalearthdata.com/about/terms-of-use/">Natural Earth</a>'}},layers:[{id:'sea',type:'background',paint:{'background-color':'#dcebf1'}},{id:'land',type:'fill',source:'world',paint:{'fill-color':'#f5f7ed'}},{id:'boundaries',type:'line',source:'world',paint:{'line-color':'#bac8ce','line-width':0.65}}]};

export default function MapView({all,visible,selected,onSelect,fit,lines}:Props){
 const container=useRef<HTMLDivElement>(null),map=useRef<MapType|null>(null);
 const [ready,setReady]=useState(false),[failed,setFailed]=useState(false),[offline,setOffline]=useState(false);
 const callback=useRef(onSelect);callback.current=onSelect;
 useEffect(()=>{
  let disposed=false;
  let resizeObserver:ResizeObserver|undefined;
  const controller=new AbortController();
  const timeout=setTimeout(()=>{if(!disposed)setFailed(true);},25000);
  async function initialize(){
   const lib=await import('maplibre-gl');
   let style:StyleSpecification=fallbackStyle;
   try{
    const response=await fetch(STREET_STYLE,{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(10000)])});
    if(!response.ok)throw Error('Street map unavailable');
    style=replaceBasemapLabels(await response.json() as StyleSpecification);
   }catch{if(disposed)return;setOffline(true);}
   if(disposed||!container.current)return;
   lib.setWorkerUrl(workerUrl);
   const instance=new lib.Map({container:container.current,center:[35,25],zoom:Math.max(0,Math.min(1.5,Math.log2(Math.min(container.current.clientWidth-40,container.current.clientHeight-180)/180))),minZoom:0,maxZoom:20,renderWorldCopies:false,attributionControl:false,canvasContextAttributes:{antialias:true},style});
   map.current=instance;
   // Follow actual viewport/container changes; the overlay drawer leaves these unchanged.
   resizeObserver=new ResizeObserver(()=>instance.resize());
   resizeObserver.observe(container.current);
   instance.addControl(new lib.NavigationControl({showCompass:false}),'top-right');
   instance.addControl(new lib.AttributionControl({compact:true,customAttribution:'词源地点：底图地名锚点；古城为近似位置'}),'bottom-right');
   instance.addControl(new lib.ScaleControl({maxWidth:100,unit:'metric'}),'bottom-left');
   instance.on('style.load',()=>{
    if(disposed)return;
    instance.setProjection({type:'globe'});
    instance.setSky({'sky-color':'#dce8f4','horizon-color':'#edf5fd','fog-color':'#edf5fd','sky-horizon-blend':0.5,'horizon-fog-blend':0.5,'atmosphere-blend':['interpolate',['linear'],['zoom'],0,0.8,4,0]});
    instance.addSource('connections',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    // Keep semantic links below street/place labels.
    const firstLabel=instance.getStyle().layers.find(layer=>layer.type==='symbol')?.id;
    instance.addLayer({id:'connections',type:'line',source:'connections',paint:{'line-color':'#315bc9','line-width':2,'line-opacity':0.75,'line-dasharray':[3,3]}},firstLabel);
    instance.addSource(PLACE_SOURCE,{type:'geojson',data:{type:'FeatureCollection',features:[]},maxzoom:18});
    for(const [id,color,radius,halo] of [['atlas-other','#95a6b3',4,false],['atlas-active','#4267c6',7,false],['atlas-near','#a5b9e8',7,false],['atlas-selected','#315bc9',9,true]] as const){instance.addImage(id,pinImage(color,radius,halo),{pixelRatio:2});}
    instance.addLayer({id:PLACE_LAYER,type:'symbol',source:PLACE_SOURCE,layout:{
     'icon-image':['get','icon'],'icon-allow-overlap':true,'text-optional':true,
     'symbol-sort-key':['get','priority'],'icon-padding':0,
     'text-field':['step',['zoom'],['case',['any',['get','active'],['get','country']],['get','label'],''],3,['get','label']],
     'text-font':['Noto Sans Regular'],'text-size':12,'text-anchor':'left','text-offset':[1.15,0],
     'text-max-width':12,'text-padding':4,'text-allow-overlap':false,
    },paint:{'text-color':['get','color'],'text-halo-color':'#ffffff','text-halo-width':2}});
    instance.on('click',PLACE_LAYER,event=>{const id=event.features?.[0]?.properties?.analysis_id;if(typeof id==='string')callback.current(id);});
    instance.on('mouseenter',PLACE_LAYER,()=>{instance.getCanvas().style.cursor='pointer';});
    instance.on('mouseleave',PLACE_LAYER,()=>{instance.getCanvas().style.cursor='';});
    setReady(true);
   });
   instance.on('load',()=>{if(!disposed){clearTimeout(timeout);setFailed(false);}});
   instance.on('error',()=>{if(!disposed)setFailed(true);});
  }
  initialize().catch(()=>{if(!disposed)setFailed(true);});
  return()=>{disposed=true;resizeObserver?.disconnect();controller.abort();clearTimeout(timeout);map.current?.remove();map.current=null;};
 },[]);

 useEffect(()=>{
  if(!ready||!map.current)return;
  (map.current.getSource(PLACE_SOURCE) as GeoJSONSource)?.setData(placeFeatures(all,visible,selected));
  const origin=all.find(r=>r.id===selected);
  const features=lines&&origin?visible.filter(r=>r.id!==selected).map(r=>greatCircle(origin.place.geometry.coordinates,r.place.geometry.coordinates,{npoints:64,properties:{relation:relationLabel(origin,r)}})):[];
  (map.current.getSource('connections') as GeoJSONSource)?.setData({type:'FeatureCollection',features});
 },[ready,all,visible,selected,lines]);

 function duration(){return window.matchMedia('(prefers-reduced-motion: reduce)').matches?0:900;}
 function showGlobe(){if(!map.current||!container.current)return;const availableWidth=container.current.clientWidth-(selected&&window.innerWidth>1050?370:50);const diameter=Math.max(180,Math.min(availableWidth,container.current.clientHeight-170));map.current.flyTo({zoom:Math.log2(diameter/180),center:map.current.getCenter(),pitch:0,bearing:0,padding:0,offset:selected&&window.innerWidth>1050?[-185,0]:[0,0],duration:duration()});}
 function showStreets(){const place=all.find(r=>r.id===selected);if(place)map.current?.flyTo({center:place.place.geometry.coordinates as [number,number],zoom:14,pitch:0,bearing:0,padding:0,offset:window.innerWidth>1050?[-170,0]:[0,-100],duration:duration()});}
 useEffect(()=>{
  if(!fit||!ready||!map.current||!visible.length)return;
  const xs=visible.map(r=>r.place.geometry.coordinates[0]),ys=visible.map(r=>r.place.geometry.coordinates[1]);const pad=window.innerWidth<800?65:100;
  map.current.fitBounds([[Math.min(...xs)-3,Math.min(...ys)-3],[Math.max(...xs)+3,Math.max(...ys)+3]],{padding:{top:100,bottom:pad,left:pad,right:window.innerWidth>1050&&selected?380:pad},maxZoom:4,duration:duration()});
 },[fit,ready]);
 return <>
  <div ref={container} className="map-canvas" aria-label="可拖动和缩放的世界地名地图"/>
  <nav className="map-keyboard-places" aria-label="地图地点，键盘选择"><span>地图上的地点</span>{all.map(record=><Button key={record.id} variant="ghost" aria-pressed={selected===record.id} onClick={()=>onSelect(record.id)}>{record.place.display_name.zh} · {record.place.display_name.en}</Button>)}</nav>
  <div className="map-view-actions"><Button variant="ghost" disabled={!ready} onClick={showGlobe} aria-label="缩小到地球" title="缩小到地球"><Globe2 size={18}/></Button><Button variant="ghost" disabled={!ready||!selected||offline} onClick={showStreets} aria-label="放大到所选地点街区" title="放大到所选地点街区"><MapPinned size={18}/></Button></div>
  {(failed||offline)&&<div className="map-load-notice" role="status">{offline?'街道底图连接失败，暂时显示简化地球。刷新可重试。':'部分地图资源暂时无法加载，请检查网络后刷新。'}</div>}
 </>;
}
