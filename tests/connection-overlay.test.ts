import {test} from 'node:test';
import assert from 'node:assert/strict';
import {connectionOverlay} from '../lib/connection-overlay';
import type {AtlasRecord} from '../lib/feature-model';

const base={kind:'city',literal_name:null,literal_meanings:[],meaning_id:null};
const jinan:AtlasRecord={...base,feature_id:'jinan',names:{zh:'济南市',en:'Jinan'},location:{lon:117.1138479,lat:36.6519754}};
const jining:AtlasRecord={...base,feature_id:'jining',names:{zh:'济宁市',en:'Jining'},location:{lon:116.5849266,lat:35.4125047}};
const henan:AtlasRecord={...base,feature_id:'henan',kind:'province',names:{zh:'河南省',en:'Henan Province'},location:{lon:114,lat:34}};

test('each connection retains its target name and actual destination, including province representative points',()=>{
 const overlay=connectionOverlay(jinan,[jinan,jining,henan],'zh');
 assert.equal(overlay.arcs.features.length,2);
 assert.deepEqual(overlay.arcs.features.map(feature=>feature.properties?.label),['济宁市','河南省']);
 const targets=[jining,henan];
 for(let i=0;i<2;i++){
  const arc=overlay.arcs.features[i];
  assert.equal(arc.properties?.feature_id,targets[i].feature_id);
  const lines=arc.geometry.type==='LineString'?[arc.geometry.coordinates]:arc.geometry.coordinates;
  const last=lines[lines.length-1][lines[lines.length-1].length-1];
  assert.ok(Math.abs(last[0]-targets[i].location.lon)<1e-8);
  assert.ok(Math.abs(last[1]-targets[i].location.lat)<1e-8);
 }
});
