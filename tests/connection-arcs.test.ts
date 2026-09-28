import {test} from 'node:test';
import assert from 'node:assert/strict';
import {connectionArc} from '../lib/connection-arcs';

test('Korea–Japan connection is visibly curved instead of a straight chord',()=>{
 const curve=connectionArc([127,37],[135,35]);
 assert.equal(curve.geometry.type,'LineString');
 const positions=curve.geometry.coordinates as number[][];
 const middle=positions[Math.floor(positions.length/2)];
 const straightLatitude=37+(middle[0]-127)*(35-37)/(135-127);
 assert.ok(Math.abs(middle[1]-straightLatitude)>0.4);
 assert.ok(positions.length>10);
});

test('arc crossing the antimeridian is split without a world-spanning jump',()=>{
 const curve=connectionArc([179,35],[-178,37]);
 assert.equal(curve.geometry.type,'MultiLineString');
 const segments=curve.geometry.coordinates as number[][][];
 for(const segment of segments){
  for(let i=1;i<segment.length;i++)assert.ok(Math.abs(segment[i][0]-segment[i-1][0])<180);
 }
});
