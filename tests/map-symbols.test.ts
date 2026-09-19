import {test} from 'node:test';
import assert from 'node:assert/strict';
import {featureFilter, createPropertyExpression, v8} from '@maplibre/maplibre-gl-style-spec';
import type {StyleSpecification, SymbolLayerSpecification} from 'maplibre-gl';
import anchors from '../data/map-anchors.json';
import {records} from '../lib/atlas';
import {placeFeatures, replaceBasemapLabels, placeLabelText, placeIconImage, placeSymbolOpacity} from '../lib/map-symbols';

test('Nanjing uses the verified basemap label anchor, and ancient Carthage stays independent',()=>{
 const nanjing=records.find(r=>r.place.id==='nanjing-cn')!;
 const anchor=anchors.find(a=>a.place_id===nanjing.place.id)!;
 assert.deepEqual(nanjing.place.geometry.coordinates,anchor.coordinates);
 assert.ok(Math.abs(anchor.coordinates[0]-118.7788631)<0.00001);
 assert.ok(Math.abs(anchor.coordinates[1]-32.0438284)<0.00001);
 assert.ok(!anchors.some(a=>a.place_id==='carthage-ancient-tn'));
 for(const a of anchors){assert.deepEqual(records.find(r=>r.place.id===a.place_id)!.place.geometry.coordinates,a.coordinates);}
});

test('label replacement excludes only verified IDs in the matching source and preserves the original class filter',()=>{
 const layer:SymbolLayerSpecification={id:'cities',type:'symbol',source:'openmaptiles','source-layer':'place',filter:['==',['get','class'],'city']};
 const style:StyleSpecification={version:8,sources:{openmaptiles:{type:'vector',tiles:['https://example.com/{z}/{x}/{y}.pbf']}},layers:[layer,{...layer,id:'other-source',source:'unrelated'},{...layer,id:'poi','source-layer':'poi'}]};
 const updated=replaceBasemapLabels(style);
 const accepts=featureFilter((updated.layers[0] as SymbolLayerSpecification).filter,'test').filter;
 const id=anchors.find(a=>a.place_id==='nanjing-cn')!.feature_id;
 assert.equal(accepts({zoom:10},{id,type:'Point',properties:{class:'city',name:'南京市'}}),false);
 assert.equal(accepts({zoom:10},{id:42,type:'Point',properties:{class:'city',name:'南京市'}}),true);
 assert.equal(accepts({zoom:10},{id:42,type:'Point',properties:{class:'town',name:'南京市'}}),false);
 assert.equal(updated.layers[1],style.layers[1]);assert.equal(updated.layers[2],style.layers[2]);
 assert.deepEqual(layer.filter,['==',['get','class'],'city']);
});

test('selection and grouping restyle symbols without moving their geometry or losing click identities',()=>{
 const origin=records.find(r=>r.place.id==='nanjing-cn')!;
 const initial=placeFeatures(records,[],null),selected=placeFeatures(records,[origin],origin.id);
 assert.equal(new Set(selected.features.map(f=>f.id)).size,records.length);
 assert.deepEqual(initial.features.map(f=>f.geometry),selected.features.map(f=>f.geometry));
 const feature=selected.features.find(f=>f.id===origin.id)!;
 assert.equal(feature.properties?.analysis_id,origin.id);
 assert.equal(feature.properties?.icon,'atlas-selected');
 assert.equal(feature.properties?.label,'南京\nNanjing');
});

test('native zoom expressions hide both text and icon at the same levels',()=>{
 const text=createPropertyExpression(placeLabelText,'text-field',v8.layout_symbol['text-field'] as unknown as Parameters<typeof createPropertyExpression>[2]);
 const icon=createPropertyExpression(placeIconImage,'icon-image',v8.layout_symbol['icon-image'] as unknown as Parameters<typeof createPropertyExpression>[2]);
 const iconOpacity=createPropertyExpression(placeSymbolOpacity,'icon-opacity',v8.paint_symbol['icon-opacity'] as unknown as Parameters<typeof createPropertyExpression>[2]);
 const opacity=createPropertyExpression(placeSymbolOpacity,'text-opacity',v8.paint_symbol['text-opacity'] as unknown as Parameters<typeof createPropertyExpression>[2]);
 assert.equal(icon.result,'success');assert.equal(iconOpacity.result,'success');
 assert.equal(text.result,'success');assert.equal(opacity.result,'success');
 if(text.result!=='success'||opacity.result!=='success'||icon.result!=='success'||iconOpacity.result!=='success')return;
 const label=(zoom:number,active=false,country=false)=>{
  const feature={type:'Point' as const,properties:{active,country,icon:'atlas-active',label:'南京\nNanjing'}};
  const labelText=String(text.value.evaluate({zoom},feature));
  const image=icon.value.evaluate({zoom},feature);
  assert.equal(image?.name || '',labelText ? 'atlas-active' : '');
  assert.equal(iconOpacity.value.evaluate({zoom},feature),opacity.value.evaluate({zoom},feature));
  return {text:labelText,opacity:opacity.value.evaluate({zoom},feature)};
 };
 assert.deepEqual(label(1),{text:'',opacity:0});
 assert.equal(label(1,true).opacity,1);
 assert.equal(label(2.5).opacity,0.5);
 assert.equal(label(6.5,false,true).opacity,0.5);
 assert.deepEqual(label(7,false,true),{text:'',opacity:0});
 assert.equal(label(8).text,'南京\nNanjing');
 assert.equal(label(13,true).opacity,0.5);
 assert.deepEqual(label(14,true),{text:'',opacity:0});
 assert.deepEqual(label(20,true),{text:'',opacity:0});
 const nanjing=records.find(r=>r.place.id==='nanjing-cn')!;
 assert.equal(placeFeatures(records,[nanjing],nanjing.id).features.find(f=>f.id===nanjing.id)?.properties?.icon,'atlas-selected');
});
