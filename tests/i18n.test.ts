import {test} from 'node:test';
import assert from 'node:assert/strict';
import {isLocale,localizedText,messages,translate,languages} from '../lib/i18n';

test('requested language wins; missing translation carries its actual fallback language',()=>{
 const meanings={zh:'中央之国',en:'central country',ja:'中央の国'};
 assert.deepEqual(localizedText(meanings,'ja'),{text:'中央の国',lang:'ja'});
 assert.deepEqual(localizedText(meanings,'fr'),{text:'central country',lang:'en'});
 assert.equal(localizedText({},'ko'),null);
 assert.deepEqual(localizedText({'zh-Hans':'中国',en:'China'},'zh'),{text:'中国',lang:'zh'});
});
test('five selectable languages have complete UI copy; Korean copy stays available for later',()=>{
 const keys=Object.keys(messages.en);
 assert.deepEqual(languages.map(language=>language.code),['en','zh','es','fr','ja']);
 for(const code of [...languages.map(language=>language.code),'ko'] as const){
  assert.deepEqual(Object.keys(messages[code]).sort(),[...keys].sort());
  for(const key of keys as (keyof typeof messages.en)[]){
   assert.ok(messages[code][key].trim());
   assert.deepEqual((messages[code][key].match(/\{\w+\}/g)||[]).sort(),(messages.en[key].match(/\{\w+\}/g)||[]).sort());
  }
 }
 assert.equal(translate('fr','places',{count:5}),'5 lieux');
 assert.equal(translate('fr','places',{count:1}),'1 lieu');
 assert.equal(isLocale('ja'),true);assert.equal(isLocale('ko'),false);assert.equal(isLocale('unknown'),false);
});
