import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=ts.transpileModule(readFileSync(new URL('../src/coachPanelSize.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {coachPanelLimits,clampCoachWidth}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('docked assistant leaves the task room and expanded assistant preserves navigation',()=>{
 for(const viewport of [1280,1600,1920]){const {maximum,expanded}=coachPanelLimits(viewport,244);assert(maximum<=800);assert(viewport-244-maximum>=480);assert(expanded<=1100);assert(viewport-expanded>=268);}
});
test('temporary viewport clamping does not destroy the preferred width',()=>{
 const preference=760;
 assert.equal(clampCoachWidth(preference,coachPanelLimits(1280,244).maximum),556);
 assert.equal(clampCoachWidth(preference,coachPanelLimits(1920,244).maximum),760);
 assert.equal(preference,760);
});
test('invalid and extreme geometry cannot move the panel offscreen on desktop',()=>{
 assert.equal(clampCoachWidth(NaN,800),480);assert.equal(clampCoachWidth(-10,800),360);assert.equal(clampCoachWidth(5000,800),800);
});
