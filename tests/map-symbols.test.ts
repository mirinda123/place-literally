import {test} from 'node:test';
import assert from 'node:assert/strict';
import {featureFilter, createPropertyExpression, v8} from '@maplibre/maplibre-gl-style-spec';
import type {StyleSpecification, SymbolLayerSpecification} from 'maplibre-gl';
import anchors from '../data/map-anchors.json';
import records from '../data/features.json';
import {encodeOsmId} from '../lib/map-identity';
import {decorateBasemapPlaces, fallbackFeatures,INLINE_STAR_SIZES,inlineStarName} from '../lib/map-symbols';

const city:SymbolLayerSpecification={id:'city',type:'symbol',source:'openmaptiles','source-layer':'place',minzoom:3,
 filter:['all',['==',['get','class'],'city'],['<=',['get','rank'],5]],
 layout:{'icon-image':['step',['zoom'],'circle_11_black',9,''],'icon-size':0.4,'icon-allow-overlap':true,
  'text-field':['get','name'],'text-anchor':'bottom','text-size':12,'text-allow-overlap':false},paint:{'text-color':'#000'}};
const country:SymbolLayerSpecification={...city,id:'country',minzoom:0,maxzoom:9,
 filter:['==',['get','class'],'country'],layout:{'text-field':['get','name'],'text-size':14}};
const style:StyleSpecification={version:8,sources:{openmaptiles:{type:'vector',tiles:['https://example.com/{z}/{x}/{y}.pbf']}},
 layers:[city,country,{...city,id:'poi','source-layer':'poi'}]};
const nanjing=records.find(r=>r.feature_id==='nanjing-cn')!;
const id=encodeOsmId(nanjing.external_ids.osm[0])!;
const china=records.find(r=>r.feature_id==='china-cn')!;
const chinaId=encodeOsmId(china.external_ids.osm[0])!;

function icon(layer:SymbolLayerSpecification,zoom:number,featureId=id){
 const expression=createPropertyExpression(layer.layout!['icon-image'],'icon-image',v8.layout_symbol['icon-image'] as unknown as Parameters<typeof createPropertyExpression>[2]);
 assert.equal(expression.result,'success',JSON.stringify(expression.value));
 if(expression.result!=='success')throw Error('Invalid icon expression');
 return expression.value.evaluate({zoom},{id:featureId,type:'Point',properties:{}})?.name||'';
}
function labelSections(layer:SymbolLayerSpecification,featureId=id,name='France',zoom=4){
 const expression=createPropertyExpression(layer.layout!['text-field'],'text-field',v8.layout_symbol['text-field'] as unknown as Parameters<typeof createPropertyExpression>[2]);
 assert.equal(expression.result,'success',JSON.stringify(expression.value));
 if(expression.result!=='success')throw Error('Invalid text expression');
 return expression.value.evaluate({zoom},{id:featureId,type:'Point',properties:{name}},undefined,undefined,
  INLINE_STAR_SIZES.flatMap(size=>[inlineStarName(size),inlineStarName(size,true)])).sections as {text:string;image:{name:string}|null}[];
}

test('native source, zoom gates, rank filters, names and placement survive decoration',()=>{
 const decorated=decorateBasemapPlaces(style,records,[nanjing],nanjing.feature_id);
 assert.equal(decorated.layers.length,style.layers.length);
 assert.equal(decorated.sources,style.sources);
 for(let i=0;i<2;i++){
  const before=style.layers[i] as SymbolLayerSpecification,after=decorated.layers[i] as SymbolLayerSpecification;
  for(const key of ['source','source-layer','minzoom','maxzoom','filter'] as const)assert.deepEqual(after[key],before[key]);
  for(const key of ['text-size','text-anchor','text-allow-overlap'] as const)assert.deepEqual(after.layout?.[key],before.layout?.[key]);
  if(before.layout?.['icon-image'])assert.deepEqual(after.layout?.['icon-size'],before.layout?.['icon-size']);
 }
 assert.equal(decorated.layers[2],style.layers[2]);
 const accepts=featureFilter((decorated.layers[0] as SymbolLayerSpecification).filter,'test').filter;
 assert.equal(accepts({zoom:5},{id,type:'Point',properties:{class:'city',rank:3}}),true);
 assert.equal(accepts({zoom:5},{id,type:'Point',properties:{class:'city',rank:8}}),false);
 assert.equal(accepts({zoom:5},{id,type:'Point',properties:{class:'town',rank:3}}),false);
 assert.equal((decorated.layers[1] as SymbolLayerSpecification).layout?.['icon-image'],undefined);
 assert.equal(labelSections(decorated.layers[0] as SymbolLayerSpecification,42)[0].text,'France');
 assert.equal(city.layout?.['text-optional'],undefined);
});

test('literal city star sits in the native label without duplicating its dot',()=>{
 const idle=decorateBasemapPlaces(style,records,[],null).layers[0] as SymbolLayerSpecification;
 const active=decorateBasemapPlaces(style,records,[nanjing],null).layers[0] as SymbolLayerSpecification;
 const selected=decorateBasemapPlaces(style,records,[nanjing],nanjing.feature_id).layers[0] as SymbolLayerSpecification;
 assert.equal(labelSections(idle)[0].image?.name,inlineStarName(12));
 assert.equal(labelSections(active)[0].image?.name,inlineStarName(12));
 assert.equal(labelSections(selected)[0].image?.name,inlineStarName(12,true));
 assert.equal(labelSections(idle)[2].text,'France');
 assert.equal(icon(idle,5),'');
 assert.equal(icon(active,5),'');
 assert.equal(icon(selected,5),'');
 assert.equal(icon(selected,5,42),'circle_11_black');
 for(const layer of [idle,active,selected]){
  assert.equal(layer.layout?.['text-optional'],false);
  assert.equal(icon(layer,8.9),'');
  assert.equal(icon(layer,9),'');assert.equal(icon(layer,14),'');
 }
});

test('country star is inline only when a literal meaning exists',()=>{
 const layer=decorateBasemapPlaces(style,records,[],null).layers[1] as SymbolLayerSpecification;
 assert.equal(layer.layout?.['icon-image'],undefined);
 assert.equal(labelSections(layer,chinaId)[0].image?.name,inlineStarName(14));
 assert.equal(labelSections(layer,42)[0].text,'France');
 assert.equal(labelSections(decorateBasemapPlaces(style,records,[china],china.feature_id).layers[1] as SymbolLayerSpecification,chinaId)[0].image?.name,inlineStarName(14,true));
 const untranslated={...china,literal_name:null,literal_meanings:[]};
 const blank=decorateBasemapPlaces(style,[untranslated],[],null).layers[1] as SymbolLayerSpecification;
 assert.equal(labelSections(blank,chinaId)[0].text,'France');
 assert.deepEqual(blank.filter,country.filter);
 assert.equal(blank.maxzoom,country.maxzoom);
});

test('inline star tracks the basemap text size at integer zoom levels',()=>{
 const sizedCountry={...country,layout:{...country.layout,'text-size':['interpolate',['linear'],['zoom'],1,9,4,17]}} as SymbolLayerSpecification;
 const sizedStyle={...style,layers:[sizedCountry]};
 const layer=decorateBasemapPlaces(sizedStyle,records,[],null).layers[0] as SymbolLayerSpecification;
 assert.equal(labelSections(layer,chinaId,'China',1)[0].image?.name,inlineStarName(9));
 assert.equal(labelSections(layer,chinaId,'China',2)[0].image?.name,inlineStarName(12));
 assert.equal(labelSections(layer,chinaId,'China',4)[0].image?.name,inlineStarName(17));
 assert.equal(labelSections(layer,42,'Other',4)[0].text,'Other');
});

test('OSM identities still refer to verified basemap anchors',()=>{
 assert.equal(id,anchors.find(a=>a.place_id===nanjing.feature_id)!.feature_id);
});

test('offline fallback is bounded and keeps the selected result',()=>{
 const many=Array.from({length:200},(_,i)=>({...nanjing,feature_id:`place-${i}`}));
 const fallback=fallbackFeatures(many,'place-199');
 assert.equal(fallback.features.length,100);
 assert.equal(fallback.features[0].properties?.feature_id,'place-199');
 assert.equal(fallback.features[0].properties?.icon,'atlas-meaning-selected');
 assert.deepEqual(fallback.features[0].geometry.coordinates,[nanjing.location.lon,nanjing.location.lat]);
});
