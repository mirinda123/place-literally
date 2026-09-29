import {copyFileSync,mkdirSync} from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';

const packageDir=path.dirname(createRequire(import.meta.url).resolve('maplibre-gl/package.json'));
const destination=path.join(process.cwd(),'public','maplibre');
mkdirSync(destination,{recursive:true});

for(const name of ['maplibre-gl-worker.mjs','maplibre-gl-shared.mjs']){
 copyFileSync(path.join(packageDir,'dist',name),path.join(destination,name));
}
