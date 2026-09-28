import {test} from 'node:test';
import assert from 'node:assert/strict';
import {decodeOsmId,encodeOsmId,basemapTarget} from '../lib/map-identity';

test('OpenFreeMap OSM identities preserve object type and reject synthetic or unsafe IDs',()=>{
 assert.equal(decodeOsmId(2440813811),'node/244081381');
 assert.equal(decodeOsmId(4243135821),'node/424313582');
 assert.equal(decodeOsmId(1232),'way/123');
 assert.equal(decodeOsmId(1233),'relation/123');
 for(const id of [0,1,-1231,1230,1234,12.5,'1231',undefined,Number.MAX_SAFE_INTEGER+1])assert.equal(decodeOsmId(id),undefined);
 assert.equal(encodeOsmId('node/244081381'),2440813811);
 assert.equal(encodeOsmId('relation/123'),1233);
 assert.equal(encodeOsmId('node/9999999999999999999'),undefined);
});
test('decode only the configured provider place layer, including non-OSM names with no matching key',()=>{
 const f={source:'openmaptiles',sourceLayer:'place',id:2440813811,properties:{name:'南京市','name:en':'Nanjing'}};
 assert.deepEqual(basemapTarget(f),{name:'Nanjing',osm:'node/244081381'});
 assert.equal(basemapTarget({...f,source:'other-provider'}),undefined);
 assert.equal(basemapTarget({...f,sourceLayer:'poi'}),undefined);
 assert.equal(basemapTarget({...f,properties:{}}),undefined);
 assert.equal(basemapTarget({...f,id:1230})?.osm,undefined);
});
