import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/certifications.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {isCertification,certificationRows,certificationPayload,certificationDetails}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('legacy imported credentials open as separate certificates without levels',()=>{
 const data={category:'skills',title:'Certifications',skill_items:[{name:'Example Cloud',level:'advanced'},{name:'Example Analytics',level:'unknown'}]};
 assert.ok(isCertification(data));const rows=certificationRows(data);assert.equal(rows.length,2);assert.equal(rows[0].name,'Example Cloud');assert.equal(rows[0].earned_date,'');assert.ok(!('level' in rows[0]));
 assert.deepEqual(certificationPayload(data).skill_items,[]);assert.equal(certificationPayload(data).tools,'');
 assert.equal(isCertification({category:'project',title:'Certificate app'}),false);
});
test('legacy text names and dates remain unguessed',()=>{
 const rows=certificationRows({title:'Certifications',description:'Example A; Example B (in progress)'});
 assert.equal(rows.length,2);assert.equal(rows[1].name,'Example B (in progress)');assert.ok(rows.every(r=>!r.does_not_expire&&!r.earned_date));
});
test('structured fields survive edits and nonexpiring choice clears expiration',()=>{
 const data={category:'skills',title:'Credentials',certification_items:[{name:' Example ',issuer:'Issuer',earned_date:'2024-01-01',expiration_date:'2027-01-01',does_not_expire:true,document_id:'private-id'}]};
 assert.ok(isCertification(data));const row=certificationPayload(data).certification_items[0];
 assert.equal(row.name,'Example');assert.equal(row.expiration_date,'');assert.equal(row.document_id,'private-id');
 const text=certificationDetails(row);assert.ok(text.includes('Earned 2024-01-01'));assert.ok(text.includes('Does not expire'));assert.ok(!text.includes('private-id'));
});
const {fillCertificate}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('PDF suggestions fill blanks, preserve entered values and cannot change attachment',()=>{
 const row={...certificationRows({description:'Existing name'})[0],document_id:'doc',issuer:'Typed issuer'};
 const source={document_id:'doc',fields:{name:{value:'PDF name'},issuer:{value:'PDF issuer'},earned_date:{value:'2024-05-15'},credential_id:{value:'EXAMPLE'},document_id:{value:'other'}}};
 const result=fillCertificate(row,source);
 assert.equal(result.row.name,'Existing name');assert.equal(result.row.issuer,'Typed issuer');assert.equal(result.row.earned_date,'2024-05-15');assert.equal(result.row.document_id,'doc');assert.deepEqual(result.conflicts,['name','issuer']);assert.equal(row.earned_date,'');
 assert.deepEqual(fillCertificate(row,{...source,document_id:'different'}).row,row);
});
test('PDF expiration respects nonexpiration and existing date bounds',()=>{
 const base={...certificationRows({description:'Example'})[0],document_id:'doc'};
 const source={document_id:'doc',fields:{expiration_date:{value:'2023-01-01'}}};
 assert.deepEqual(fillCertificate({...base,does_not_expire:true},source).conflicts,['expiration_date']);
 assert.deepEqual(fillCertificate({...base,earned_date:'2024-01-01'},source).conflicts,['expiration_date']);
 assert.deepEqual(fillCertificate({...base,expiration_date:'2023-01-01'},{document_id:'doc',fields:{earned_date:{value:'2024-01-01'}}}).conflicts,['earned_date']);
});

const {certificateDraftPatch,supportsCertificateExtraction}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('async certificate fill uses the current attachment and preserves concurrent draft fields',()=>{
 let data={category:'skills',title:'Certifications',certification_items:[{name:'My chosen name'}],confirmed:true};
 const attach=current=>certificateDraftPatch(current,rows=>rows.map(r=>({...r,document_id:'new-doc'})));
 const fill=current=>certificateDraftPatch(current,rows=>rows.map(r=>fillCertificate(r,{document_id:'new-doc',fields:{name:{value:'Extracted name'},issuer:{value:'Example Institute'},earned_date:{value:'2024-05-15'}}}).row));
 data={...data,...attach(data)};data={...data,...fill(data)};
 assert.equal(data.certification_items[0].document_id,'new-doc');assert.equal(data.certification_items[0].issuer,'Example Institute');assert.equal(data.certification_items[0].name,'My chosen name');assert.equal(data.certification_items[0].earned_date,'2024-05-15');assert.equal(data.confirmed,false);
 const switched={...data,certification_items:data.certification_items.map(r=>({...r,document_id:'replacement',issuer:'Typed issuer'}))};assert.deepEqual(fill(switched).certification_items,switched.certification_items);
 for(const mime of ['application/pdf','image/png','image/jpeg'])assert(supportsCertificateExtraction(mime));assert(!supportsCertificateExtraction('text/html'));
});
