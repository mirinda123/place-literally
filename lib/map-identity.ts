// This adapter is specific to OpenFreeMap's Planetiler-generated OSM features.
// Do not apply it to another provider, synthetic IDs, or our own GeoJSON layer.
export type MapPlaceTarget={name:string;osm?:string;featureId?:string};
export function decodeOsmId(id:unknown):string|undefined{
 if(typeof id!=='number'||!Number.isSafeInteger(id)||id<=10)return;
 const type=({1:'node',2:'way',3:'relation'} as Record<number,string>)[id%10];
 return type?`${type}/${Math.floor(id/10)}`:undefined;
}
export function encodeOsmId(osm:string):number|undefined{
 const match=/^(node|way|relation)\/([1-9][0-9]*)$/.exec(osm);
 if(!match)return;
 const id=Number(match[2])*10+({node:1,way:2,relation:3} as Record<string,number>)[match[1]];
 return Number.isSafeInteger(id)?id:undefined;
}
export function basemapTarget(feature:{id?:unknown;source?:string;sourceLayer?:string;properties?:Record<string,unknown>|null}):MapPlaceTarget|undefined{
 if(feature.source!=='openmaptiles'||feature.sourceLayer!=='place')return;
 const props=feature.properties;
 const name=props?.['name:zh']||props?.['name:en']||props?.name;
 if(typeof name!=='string'||!name.trim())return;
 return {name,osm:decodeOsmId(feature.id)};
}
