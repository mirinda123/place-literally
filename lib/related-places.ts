import type {SimilarResponse} from './atlas-api';
import {localizedText, type Locale} from './i18n';

export type RelatedHit=SimilarResponse['results'][number];

/** Show every available interpretation in its original order, without ranking it. */
export function relatedMeanings(hit:RelatedHit, locale:Locale){
 return hit.feature.literal_meanings.flatMap(meaning=>{
   const translation=localizedText(meaning.translations,locale);
   return translation?[translation]:[];
 });
}
