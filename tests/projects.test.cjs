const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'../static/board/projects.js'),'utf8');
const run = (document) => { const context = {document, module:{exports:{}}}; vm.runInNewContext(source,context); return context.module.exports; };
const api = run({querySelectorAll:()=>[],getElementById:()=>null});
const input = (name,size,maxBytes) => ({name,files:[{name:'demo',size}],dataset:{maxBytes}});
test('exact 25 MiB video allowed; oversized rejected',()=>{
  assert.equal(typeof api.validateProjectUploads,'function');
  assert.equal(api.validateProjectUploads([input('projects-0-video',25*1024*1024,25*1024*1024)]),'');
  assert.match(api.validateProjectUploads([input('projects-0-video',25*1024*1024+1,25*1024*1024)]),/大小/);
});
test('combined request includes parent files with exact 64 MiB boundary',()=>{
  const files=[input('projects-0-video',25*1024*1024,25*1024*1024),input('audio',25*1024*1024),input('images',7*1024*1024),input('images',7*1024*1024)];
  assert.equal(api.validateProjectUploads(files),''); files[3].files[0].size++;
  assert.match(api.validateProjectUploads(files),/64 MB/);
});
test('legacy images-only request is unaffected by project combined budget',()=>{
  assert.equal(api.validateProjectUploads(Array.from({length:9},()=>input('images',8*1024*1024))),'');
});
test('playing pauses siblings and error displays fallback',()=>{
  const error={hidden:true}; const events=()=>({handlers:{},paused:0,addEventListener(name,callback){this.handlers[name]=callback},pause(){this.paused++},closest(){return {querySelector:()=>error}}});
  const first=events(),second=events(); run({querySelectorAll:()=>[first,second],getElementById:()=>null});
  first.handlers.play(); assert.equal(first.paused,0); assert.equal(second.paused,1);
  first.handlers.error(); assert.equal(error.hidden,false);
});
test('add project expands rows through nine then stops at ten; deletion reopens capacity',()=>{
  const handlers={}; const total={value:'1'}; const add={addEventListener:(name,fn)=>handlers.add=fn};
  const makeRow=()=>({deleted:false,position:{value:''},attributes:[{name:'name',value:'projects-__prefix__-position'}],setAttribute(name,value){this.attributes[0].value=value},querySelector(selector){return selector.includes('DELETE')?{checked:this.deleted}:this.position}});
  const allRows=[makeRow()]; const rows={querySelectorAll:()=>allRows,addEventListener:(name,fn)=>handlers.change=fn,append(fragment){allRows.push(fragment.row)}};
  const template={content:{cloneNode(){const row=makeRow();return {row,querySelectorAll:()=>[row],querySelector:(selector)=>row.querySelector(selector)}}}};
  const form={addEventListener:(name,fn)=>handlers.submit=fn}; const editor={closest:()=>form};
  const elements={'project-editor':editor,'id_projects-TOTAL_FORMS':total,'project-add':add,'project-rows':rows,'project-empty-form':template};
  run({querySelectorAll:()=>[],getElementById:id=>elements[id]});
  for(let i=0;i<8;i++) handlers.add();
  assert.equal(allRows.length,9);assert.equal(total.value,9); assert.equal(allRows[8].attributes[0].value,'projects-8-position');
  handlers.add();assert.equal(add.disabled,true);handlers.add();assert.equal(allRows.length,10);
  allRows[0].deleted=true;handlers.change();assert.equal(add.disabled,false);
});
