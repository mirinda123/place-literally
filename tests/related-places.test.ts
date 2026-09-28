import {test} from 'node:test';
import assert from 'node:assert/strict';
import {relatedMeanings,type RelatedHit} from '../lib/related-places';

const feature={feature_id:'country',kind:'country',names:{zh:'某国'},location:{lon:0,lat:0},literal_name:null,meaning_id:null,
 literal_meanings:[{translations:{zh:'第一种含义',en:'First meaning'}},{translations:{zh:'实际命中的含义',en:'Matched meaning'}}]};
const country:RelatedHit={feature,score:3,source_meaning_index:0,matched_meaning_index:1};

test('related preview keeps interpretations parallel in their original order',()=>{
 assert.deepEqual(relatedMeanings(country,'zh'),[
  {text:'第一种含义',lang:'zh'},
  {text:'实际命中的含义',lang:'zh'},
 ]);
 assert.deepEqual(relatedMeanings({...country,matched_meaning_index:9},'zh'),relatedMeanings(country,'zh'));
});
