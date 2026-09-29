'use client';
import {connectionOverlay} from '../lib/connection-overlay';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import {Button} from '../components/ui/button';
import {coordinates,displayName} from '../lib/feature-model';
import {FALLBACK_SOURCE,FALLBACK_LAYER,INLINE_STAR_SIZES,inlineStarName,isPlaceLayer,decorateBasemapPlaces,fallbackFeatures,pinImage,meaningImage} from '../lib/map-symbols';
import {useEffect,useRef,useState} from 'react';
import type {AtlasRecord} from '../lib/feature-model';
import type {Map as MapType,StyleSpecification,GeoJSONSource,Popup as PopupType} from 'maplibre-gl';
import {basemapTarget,type MapPlaceTarget} from '../lib/map-identity';
import {useLocale} from '../components/locale-provider';
import {localizedText,translate} from '../lib/i18n';

type Props={all:AtlasRecord[];visible:AtlasRecord[];selected:string|null;focusRequest:{id:string;sequence:number;animate?:boolean}|null;onSelect:(id:string)=>void;onMapPlace:(target:MapPlaceTarget)=>void;onMapBackgroundClick:()=>void;lines:boolean;highlightedConnection:string|null;mobileDetail:'hidden'|'peek'|'expanded'};
const STREET_STYLE='https://tiles.openfreemap.org/styles/liberty';
const fallbackStyle:StyleSpecification={version:8,glyphs:'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',sources:{world:{type:'geojson',data:'/world.geojson',attribution:'<a href="https://www.naturalearthdata.com/about/terms-of-use/">Natural Earth</a>'}},layers:[{id:'sea',type:'background',paint:{'background-color':'#dcebf1'}},{id:'land',type:'fill',source:'world',paint:{'fill-color':'#f5f7ed'}},{id:'boundaries',type:'line',source:'world',paint:{'line-color':'#bac8ce','line-width':0.65}}]};
function mobilePanelHeight(state:Props['mobileDetail']){
 if(typeof window==='undefined'||window.innerWidth>=768||state==='hidden')return 0;
 return state==='expanded'?Math.min(window.innerHeight*.72,680):Math.min(118,window.innerHeight-90);
}
function mobileFocusOffset(state:Props['mobileDetail']):[number,number]{return [0,-mobilePanelHeight(state)/2];}

export default function MapView({all,visible,selected,focusRequest,onSelect,onMapPlace,onMapBackgroundClick,lines,highlightedConnection,mobileDetail}:Props){
 const {locale,t}=useLocale();
 const container=useRef<HTMLDivElement>(null),map=useRef<MapType|null>(null);
 const hoverPopup=useRef<PopupType|null>(null);
 const lastFocusSequence=useRef(0);
 const originalStyle=useRef<StyleSpecification>(fallbackStyle);
 const [ready,setReady]=useState(false),[failed,setFailed]=useState(false),[offline,setOffline]=useState(false);
 const mapCallback=useRef(onMapPlace);
 const backgroundCallback=useRef(onMapBackgroundClick);
 const localeRef=useRef(locale);
 const recordsRef=useRef(all);
 const recordIdsRef=useRef(new Set(all.map(record=>record.feature_id)));
 useEffect(()=>{mapCallback.current=onMapPlace;backgroundCallback.current=onMapBackgroundClick;recordsRef.current=all;recordIdsRef.current=new Set(all.map(record=>record.feature_id));},[onMapPlace,onMapBackgroundClick,all]);
 useEffect(()=>{localeRef.current=locale;},[locale]);
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
    originalStyle.current=await response.json() as StyleSpecification;
    style=originalStyle.current;
   }catch{if(disposed)return;setOffline(true);}
   if(disposed||!container.current)return;
   lib.setWorkerUrl(typeof workerUrl==='string'?workerUrl:'/maplibre/maplibre-gl-worker.mjs');
   const instance=new lib.Map({container:container.current,center:[35,25],zoom:Math.max(0,Math.min(1.5,Math.log2(Math.min(container.current.clientWidth-40,container.current.clientHeight-180)/180))),minZoom:0,maxZoom:20,renderWorldCopies:false,attributionControl:false,canvasContextAttributes:{antialias:true},style});
   map.current=instance;
   // Follow actual viewport/container changes; the overlay drawer leaves these unchanged.
   resizeObserver=new ResizeObserver(()=>instance.resize());
   resizeObserver.observe(container.current);
   instance.addControl(new lib.NavigationControl({showCompass:false}),'top-right');
   instance.addControl(new lib.AttributionControl({compact:true}),'bottom-right');
   instance.addControl(new lib.ScaleControl({maxWidth:100,unit:'metric'}),'bottom-left');
   instance.on('style.load',()=>{
    if(disposed)return;
    instance.setProjection({type:'globe'});
    instance.setSky({'sky-color':'#dce8f4','horizon-color':'#edf5fd','fog-color':'#edf5fd','sky-horizon-blend':0.5,'horizon-fog-blend':0.5,'atmosphere-blend':['interpolate',['linear'],['zoom'],0,0.8,4,0]});
    instance.addSource('connections',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    instance.addSource('connection-focus',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    // Keep semantic links below street/place labels.
    const firstLabel=instance.getStyle().layers.find(layer=>layer.type==='symbol')?.id;
    instance.addLayer({id:'connections',type:'line',source:'connections',layout:{'line-join':'round','line-cap':'round'},paint:{'line-color':'#6fa6e1','line-width':2.5,'line-opacity':['interpolate',['linear'],['zoom'],0,0.9,12,0.9,14,0],'line-dasharray':[3,3]}},firstLabel);
    instance.addLayer({id:'connections-hit',type:'line',source:'connections',maxzoom:14,paint:{'line-color':'#6fa6e1','line-width':14,'line-opacity':0.001}},firstLabel);
    for(const [id,color,radius,halo] of [['atlas-other','#95a6b3',4,false],['atlas-active','#4267c6',7,false],['atlas-near','#a5b9e8',7,false],['atlas-selected','#315bc9',9,true]] as const){instance.addImage(id,pinImage(color,radius,halo),{pixelRatio:2});}
    instance.addImage('atlas-meaning',meaningImage(),{pixelRatio:2});
    instance.addImage('atlas-meaning-selected',meaningImage(true),{pixelRatio:2});
    for(const size of INLINE_STAR_SIZES){
     instance.addImage(inlineStarName(size),meaningImage(false,size),{pixelRatio:2});
     instance.addImage(inlineStarName(size,true),meaningImage(true,size),{pixelRatio:2});
    }
    const placeLayers=instance.getStyle().layers.filter(isPlaceLayer).map(layer=>layer.id);
    if(!placeLayers.length){
     instance.addSource(FALLBACK_SOURCE,{type:'geojson',data:{type:'FeatureCollection',features:[]}});
     instance.addLayer({id:FALLBACK_LAYER,type:'symbol',source:FALLBACK_SOURCE,layout:{
      'icon-image':['get','icon'],'icon-allow-overlap':false,'text-optional':false,
      'text-field':['get','label'],'text-font':['Noto Sans Regular'],'text-size':12,
      'text-anchor':'left','text-offset':[1.15,0],'text-allow-overlap':false,
     },paint:{'text-color':'#315bc9','text-halo-color':'#fff','text-halo-width':1}});
    }
    instance.addLayer({id:'connection-focus-label',type:'symbol',source:'connection-focus',layout:{
     'text-field':['get','label'],'text-font':['Noto Sans Regular'],'text-size':14,
     'text-anchor':'bottom','text-offset':[0,-0.7],'text-allow-overlap':true,
    },paint:{'text-color':'#315bc9','text-halo-color':'#fff','text-halo-width':2.5}});
    const hitLayers=placeLayers.length?placeLayers:[FALLBACK_LAYER];
    const linkedTarget=(feature:ReturnType<typeof instance.queryRenderedFeatures>[number])=>{
     const id=feature.properties?.feature_id;
     return typeof id==='string'&&recordIdsRef.current.has(id)?id:null;
    };
    instance.on('click',event=>{
     const hits=instance.queryRenderedFeatures(event.point,{layers:hitLayers});
     const own=hits.find(feature=>feature.layer.id===FALLBACK_LAYER);
     if(own){
      const record=recordsRef.current.find(r=>r.feature_id===own.properties.feature_id);
      if(record)mapCallback.current({name:displayName(record,localeRef.current),osm:record.external_ids?.osm[0],featureId:record.feature_id});
      return;
     }
     for(const hit of hits){const target=basemapTarget(hit,localeRef.current);if(target){mapCallback.current(target);return;}}
     backgroundCallback.current();
    });
    instance.on('mousemove',event=>{
     const link=instance.queryRenderedFeatures(event.point,{layers:['connections-hit']})[0];
     const target=link&&linkedTarget(link);
     instance.getCanvas().style.cursor=instance.queryRenderedFeatures(event.point,{layers:hitLayers}).length?'pointer':'';
     if(target){
      const label=String(link.properties?.label||target);
      if(!hoverPopup.current)hoverPopup.current=new lib.Popup({closeButton:false,closeOnClick:false,offset:12,className:'connection-target-tooltip'});
      hoverPopup.current.setLngLat(event.lngLat).setText(label);
      if(!hoverPopup.current.isOpen())hoverPopup.current.addTo(instance);
     }else{
      hoverPopup.current?.remove();
     }
    });
    instance.on('mouseout',()=>{hoverPopup.current?.remove();instance.getCanvas().style.cursor='';});
    setReady(true);
   });
   instance.on('load',()=>{if(!disposed){clearTimeout(timeout);setFailed(false);}});
   instance.on('error',()=>{if(!disposed)setFailed(true);});
  }
  initialize().catch(()=>{if(!disposed)setFailed(true);});
  return()=>{disposed=true;resizeObserver?.disconnect();controller.abort();clearTimeout(timeout);hoverPopup.current?.remove();map.current?.remove();map.current=null;};
 },[]);

 useEffect(()=>{
  if(!ready||!map.current)return;
  for(const layer of decorateBasemapPlaces(originalStyle.current,all,visible,selected).layers){
   if(!isPlaceLayer(layer))continue;
   const originalLayer=originalStyle.current.layers.find(original=>original.id===layer.id);
   if(originalLayer&&isPlaceLayer(originalLayer)&&originalLayer.layout?.['icon-image']){
    map.current.setLayoutProperty(layer.id,'icon-image',layer.layout?.['icon-image']);
    map.current.setLayoutProperty(layer.id,'text-optional',false);
   }
   map.current.setLayoutProperty(layer.id,'text-field',layer.layout?.['text-field']);
   map.current.setPaintProperty(layer.id,'text-color',layer.paint?.['text-color']);
  }
 },[ready,all,visible,selected]);

 useEffect(()=>{
  if(!ready||!map.current)return;
  const controls=map.current.getContainer();
  for(const [selector,key] of [['.maplibregl-ctrl-zoom-in','zoomIn'],['.maplibregl-ctrl-zoom-out','zoomOut']] as const){
   const button=controls.querySelector<HTMLButtonElement>(selector);
   if(button){button.title=translate(locale,key);button.setAttribute('aria-label',translate(locale,key));}
  }
 },[ready,locale]);

 useEffect(()=>{
  if(!ready||!map.current?.getSource('connections'))return;
  (map.current.getSource(FALLBACK_SOURCE) as GeoJSONSource|undefined)?.setData(fallbackFeatures(visible,selected,locale));
  const origin=all.find(r=>r.feature_id===selected);
  const overlay=lines&&origin?connectionOverlay(origin,visible,locale):null;
  hoverPopup.current?.remove();
  (map.current.getSource('connections') as GeoJSONSource)?.setData(overlay?.arcs||{type:'FeatureCollection',features:[]});
 },[ready,all,visible,selected,lines,locale]);

 useEffect(()=>{
  if(!ready||!map.current?.getSource('connections'))return;
  const focus=lines&&selected?visible.find(record=>record.feature_id===highlightedConnection&&record.feature_id!==selected):undefined;
  map.current.setPaintProperty('connections','line-opacity',focus?[
   'interpolate',['linear'],['zoom'],0,['case',['==',['get','feature_id'],focus.feature_id],0.95,0.1],
   12,['case',['==',['get','feature_id'],focus.feature_id],0.95,0.1],14,0,
  ]:['interpolate',['linear'],['zoom'],0,0.9,12,0.9,14,0]);
  map.current.setPaintProperty('connections','line-width',focus?['case',['==',['get','feature_id'],focus.feature_id],4,2]:2.5);
  (map.current.getSource('connection-focus') as GeoJSONSource)?.setData({type:'FeatureCollection',features:focus?[{
   type:'Feature',geometry:{type:'Point',coordinates:coordinates(focus)},
   properties:{label:localizedText(focus.names,locale)?.text||displayName(focus)},
  }]:[]});
 },[ready,visible,selected,lines,highlightedConnection,locale]);

 function duration(){return window.matchMedia('(prefers-reduced-motion: reduce)').matches?0:900;}
 useEffect(()=>{
  if(!ready||!map.current||!focusRequest||focusRequest.sequence===lastFocusSequence.current)return;
  const place=all.find(record=>record.feature_id===focusRequest.id);
  if(!place)return;
  lastFocusSequence.current=focusRequest.sequence;
  const zoom=place.kind==='country'?4:place.kind==='state'||place.kind==='province'?5:['town','village'].includes(place.kind)?9:['city','metropolis','ancient_city'].includes(place.kind)?7:6;
  // The sidebar overlays the canvas, so center the destination in the uncovered map area.
  const panelOpen=container.current?.closest('.atlas-app')?.getAttribute('data-panel-open')==='true';
  const sidebarWidth=panelOpen&&window.innerWidth>=768?document.getElementById('meaning-sidebar')?.getBoundingClientRect().width||0:0;
  if(window.innerWidth<768){
   // Offset this focus above the sheet without retaining map padding for later zooms.
   const camera={center:coordinates(place),zoom,pitch:0,bearing:0,padding:0,offset:mobileFocusOffset(mobileDetail)};
   if(focusRequest.animate){
    if(map.current.getZoom()>=2)map.current.flyTo({...camera,duration:duration()});
    else map.current.easeTo({...camera,duration:duration()});
   }
   else map.current.easeTo({...camera,duration:0});
  }
  else map.current.flyTo({center:coordinates(place),zoom,offset:[sidebarWidth/2,0],duration:duration()});
 },[ready,focusRequest,all,mobileDetail]);
 return <>
  <div ref={container} className="map-canvas" aria-label={t('map')}/>
  <a className="map-github-link" href="https://github.com/mirinda123/place-literally" target="_blank" rel="noopener noreferrer" aria-label="GitHub" title="GitHub">
   <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82A7.65 7.65 0 0 1 8 3.73c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>
  </a>
  <nav className="map-keyboard-places" aria-label={t('mapPlaces')}><span>{t('keyboardHint')}</span>{visible.slice(0,100).map(record=><Button key={record.feature_id} variant="ghost" aria-pressed={selected===record.feature_id} onClick={()=>onSelect(record.feature_id)}>{localizedText(record.names,locale)?.text||record.feature_id}</Button>)}</nav>
  {(failed||offline)&&<div className="map-load-notice" role="status">{t(offline?'offline':'mapError')}</div>}
 </>;
}
