import {test} from 'node:test';
import assert from 'node:assert/strict';
import {featureFilter} from '@maplibre/maplibre-gl-style-spec';
import type {StyleSpecification, SymbolLayerSpecification} from 'maplibre-gl';
import anchors from '../data/map-anchors.json';
import {records} from '../lib/atlas';
import {placeFeatures, replaceBasemapLabels} from '../lib/map-symbols';

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
