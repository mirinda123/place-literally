import type {FeatureCollection, LineString, MultiLineString} from 'geojson';
import {connectionArc} from './connection-arcs';
import {coordinates, displayName, type AtlasRecord} from './feature-model';
import {localizedText, type Locale} from './i18n';

/** Attach the target name to each drawn arc for hover identification. */
export function connectionOverlay(origin:AtlasRecord, visible:AtlasRecord[], locale:Locale):{
 arcs:FeatureCollection<LineString|MultiLineString>;
}{
 const targets=visible.filter(record=>record.feature_id!==origin.feature_id);
 return {
  arcs:{type:'FeatureCollection',features:targets.map(record=>{
   const properties={feature_id:record.feature_id,
    label:localizedText(record.names,locale)?.text||displayName(record)};
   return {...connectionArc(coordinates(origin),coordinates(record)),properties};
  })},
 };
}
