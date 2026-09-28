import type {FeatureCollection, Point} from 'geojson';
import type {StyleSpecification, SymbolLayerSpecification, ExpressionSpecification} from 'maplibre-gl';
import {encodeOsmId} from './map-identity';
import {relationLabel, coordinates, hasLiteralMeaning, type AtlasRecord} from './feature-model';
import {localizedText,type Locale} from './i18n';

export const FALLBACK_SOURCE = 'atlas-fallback-places';
export const FALLBACK_LAYER = 'atlas-fallback-symbols';
export const INLINE_STAR_SIZES = Array.from({length:17},(_,index)=>index+8);

export function inlineStarName(size:number,selected=false):string {
 return `atlas-meaning-${selected?'selected-':''}inline-${size}`;
}

// Liberty's place labels use numeric text-size stops. Layout expressions are
// evaluated at integer zoom levels, so use the same zoom to choose a sprite.
function nativeTextSize(value:unknown,zoom:number):number {
 if(typeof value==='number')return value;
 if(!Array.isArray(value)||value.length<5||!Array.isArray(value[2])||value[2][0]!=='zoom')return 14;
 if(value[0]==='step'){
  let size=Number(value[2]);
  for(let i=3;i+1<value.length;i+=2){if(zoom<Number(value[i]))break;size=Number(value[i+1]);}
  return Number.isFinite(size)?size:14;
 }
 if(value[0]!=='interpolate')return 14;
 const stops:{zoom:number;size:number}[]=[];
 for(let i=3;i+1<value.length;i+=2)stops.push({zoom:Number(value[i]),size:Number(value[i+1])});
 if(!stops.length||stops.some(stop=>!Number.isFinite(stop.zoom)||!Number.isFinite(stop.size)))return 14;
 if(zoom<=stops[0].zoom)return stops[0].size;
 for(let i=1;i<stops.length;i++){
  const previous=stops[i-1],next=stops[i];
  if(zoom>next.zoom)continue;
  const interpolation=value[1];
  const base=Array.isArray(interpolation)&&interpolation[0]==='exponential'?Number(interpolation[1]):1;
  const progress=base===1?(zoom-previous.zoom)/(next.zoom-previous.zoom):
   (Math.pow(base,zoom-previous.zoom)-1)/(Math.pow(base,next.zoom-previous.zoom)-1);
  return previous.size+(next.size-previous.size)*progress;
 }
 return stops[stops.length-1].size;
}
function inlineStarSize(textSize:unknown,zoom:number):number {
 const size=Math.round(nativeTextSize(textSize,zoom));
 return Math.max(INLINE_STAR_SIZES[0],Math.min(INLINE_STAR_SIZES[INLINE_STAR_SIZES.length-1],size));
}

export function isPlaceLayer(layer:StyleSpecification['layers'][number]):layer is SymbolLayerSpecification {
 return layer.type==='symbol' && layer.source==='openmaptiles' && layer['source-layer']==='place';
}
function osmIds(records:AtlasRecord[]):number[]{
 return [...new Set(records.flatMap(r=>r.external_ids?.osm||[]).map(encodeOsmId).filter((id):id is number=>id!==undefined))];
}
// Replace only the sprite leaf, preserving the original top-level zoom expression.
function replaceDot(value:unknown, replacement:ExpressionSpecification):unknown {
 if(value==='circle_11_black')return replacement;
 return Array.isArray(value)?value.map(part=>replaceDot(part,replacement)):value;
}
export function decorateBasemapPlaces(style:StyleSpecification, all:AtlasRecord[], visible:AtlasRecord[], selected:string|null):StyleSpecification {
 const origin=all.find(r=>r.feature_id===selected);
 const chosen=osmIds(origin?[origin]:[]), active=osmIds(visible), known=osmIds(all);
 const translated=osmIds(all.filter(hasLiteralMeaning));
 const near=osmIds(origin?visible.filter(r=>r.feature_id!==selected&&relationLabel(origin,r)!=='同义归一'):[]);
 const has=(ids:number[]):ExpressionSpecification=>['in',['id'],['literal',ids]];
 const icon:ExpressionSpecification=['case',has(translated),'',has(chosen),'atlas-selected',has(near),'atlas-near',has(active),'atlas-active',has(known),'atlas-other','circle_11_black'];
 return {...style,layers:style.layers.map(layer=>{
  if(!isPlaceLayer(layer))return layer;
  const nativeIcon=layer.layout?.['icon-image'];
  const nativeText=layer.layout?.['text-field'];
  const labelText=(nativeText||'') as string|ExpressionSpecification;
  const formattedText=(size:number):ExpressionSpecification=>['case',has(translated),
   ['format',['image',['case',has(chosen),inlineStarName(size,true),inlineStarName(size)]],{'vertical-align':'center'},' ',{},labelText,{}],labelText];
  const startingSize=inlineStarSize(layer.layout?.['text-size'],0);
  const zoomSteps:(number|ExpressionSpecification)[]=[];
  let previousSize=startingSize;
  for(let zoom=1;zoom<=20;zoom++){
   const size=inlineStarSize(layer.layout?.['text-size'],zoom);
   if(size!==previousSize){zoomSteps.push(zoom,formattedText(size));previousSize=size;}
  }
  return {...layer,layout:{...layer.layout,
   ...(nativeIcon?{'icon-image':replaceDot(nativeIcon,icon),'text-optional':false}:{}),
   ...(nativeText?{'text-field':zoomSteps.length?['step',['zoom'],formattedText(startingSize),...zoomSteps]:formattedText(startingSize)}:{}),
  },paint:{...layer.paint,'text-color':['case',has(chosen),'#315bc9',has(active),'#315bc9',layer.paint?.['text-color']||'#000']}} as SymbolLayerSpecification;
 })};
}
// Only used without the online street basemap. Never duplicate every ES point.
export function fallbackFeatures(visible:AtlasRecord[],selected:string|null,locale:Locale='zh'):FeatureCollection<Point>{
 const chosen=visible.find(r=>r.feature_id===selected);
 const records=[...(chosen?[chosen]:[]),...visible.filter(r=>r!==chosen)].slice(0,100);
 return {type:'FeatureCollection',features:records.map(record=>({type:'Feature',id:record.feature_id,
  geometry:{type:'Point',coordinates:coordinates(record)},properties:{feature_id:record.feature_id,
   label:localizedText(record.names,locale)?.text||record.feature_id,
   icon:hasLiteralMeaning(record)?record.feature_id===selected?'atlas-meaning-selected':'atlas-meaning':record.feature_id===selected?'atlas-selected':'atlas-active'}}))};
}
export function pinImage(color: string, radius: number, halo = false) {
 const canvas = document.createElement('canvas'); canvas.width = canvas.height = 64;
 const ctx = canvas.getContext('2d')!; ctx.scale(2, 2);
 if(halo) {ctx.beginPath(); ctx.arc(16,16,14,0,Math.PI*2); ctx.fillStyle='#e8bb5780'; ctx.fill();}
 ctx.beginPath(); ctx.arc(16,16,radius,0,Math.PI*2); ctx.fillStyle=color; ctx.fill();
 ctx.lineWidth=2; ctx.strokeStyle='#fff'; ctx.stroke();
 return ctx.getImageData(0,0,64,64);
}
export function meaningImage(selected=false,size=32) {
 const canvas=document.createElement('canvas');canvas.width=canvas.height=size*2;
 const ctx=canvas.getContext('2d')!;ctx.scale(size/16,size/16);
 const inline=size!==32,starScale=inline?1.2:1;
 if(selected){ctx.beginPath();ctx.arc(16,16,inline?15.6:15,0,Math.PI*2);ctx.fillStyle='#e8bb5780';ctx.fill();}
 ctx.beginPath();ctx.arc(16,16,inline?14:12,0,Math.PI*2);ctx.fillStyle=selected?'#315bc9':'#fff';ctx.fill();
 ctx.lineWidth=2;ctx.strokeStyle=selected?'#fff':'#315bc9';ctx.stroke();
 const edge=(value:number)=>16+(value-16)*starScale;
 ctx.beginPath();ctx.moveTo(16,edge(9));ctx.lineTo(edge(18),edge(14));ctx.lineTo(edge(23),16);ctx.lineTo(edge(18),edge(18));ctx.lineTo(16,edge(23));ctx.lineTo(edge(14),edge(18));ctx.lineTo(edge(9),16);ctx.lineTo(edge(14),edge(14));ctx.closePath();ctx.fillStyle=selected?'#fff':'#315bc9';ctx.fill();
 return ctx.getImageData(0,0,canvas.width,canvas.height);
}
