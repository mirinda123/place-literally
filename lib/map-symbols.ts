import type {FeatureCollection, Point} from 'geojson';
import type {StyleSpecification, FilterSpecification} from 'maplibre-gl';
import anchors from '../data/map-anchors.json';
import {relationLabel, type AtlasRecord} from './atlas';

export const PLACE_SOURCE = 'atlas-places';
export const PLACE_LAYER = 'atlas-place-symbols';

// Feature IDs identify the verified objects, not every place sharing their names.
export function replaceBasemapLabels(style: StyleSpecification): StyleSpecification {
 const ids = anchors.map(anchor => anchor.feature_id);
 return {...style, layers: style.layers.map(layer => {
  if(layer.type !== 'symbol' || layer.source !== 'openmaptiles' || layer['source-layer'] !== 'place') return layer;
  return {...layer, filter: ['all', ...(layer.filter ? [layer.filter] : []), ['!', ['in', ['id'], ['literal', ids]]]] as FilterSpecification};
 })};
}

export function placeFeatures(all: AtlasRecord[], visible: AtlasRecord[], selected: string | null): FeatureCollection<Point> {
 const ids = new Set(visible.map(record => record.id));
 const origin = all.find(record => record.id === selected);
 return {type: 'FeatureCollection', features: all.map(record => {
  const active = ids.has(record.id), chosen = record.id === selected;
  const near = active && origin && !chosen && relationLabel(origin, record) !== '同义归一';
  return {type: 'Feature', id: record.id, geometry: {type: 'Point', coordinates: record.place.geometry.coordinates}, properties: {
   analysis_id: record.id, label: `${record.place.display_name.zh}\n${record.place.display_name.en}`,
   active, country: record.place.kind === 'country', priority: chosen ? 0 : active ? 1 : 2,
   icon: chosen ? 'atlas-selected' : near ? 'atlas-near' : active ? 'atlas-active' : 'atlas-other',
   color: chosen || active ? '#315bc9' : '#667c8a',
  }};
 })};
}

// Small icon assets only; MapLibre places both icon and text in the same symbol.
export function pinImage(color: string, radius: number, halo = false) {
 const canvas = document.createElement('canvas'); canvas.width = canvas.height = 64;
 const ctx = canvas.getContext('2d')!; ctx.scale(2, 2);
 if(halo) {ctx.beginPath(); ctx.arc(16,16,14,0,Math.PI*2); ctx.fillStyle='#e8bb5780'; ctx.fill();}
 ctx.beginPath(); ctx.arc(16,16,radius,0,Math.PI*2); ctx.fillStyle=color; ctx.fill();
 ctx.lineWidth=2; ctx.strokeStyle='#fff'; ctx.stroke();
 return ctx.getImageData(0,0,64,64);
}
