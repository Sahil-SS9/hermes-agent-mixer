import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

const source = fs.readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
let durable = 'stored-A'
let fail = false
let flip = false
const calls = []
const host = { state: { focusedStoredSessionId: {get:()=>durable}, focusedSessionId:{get:()=> 'runtime-not-durable'} } }
const context = vm.createContext({console})
const sdk = new vm.SyntheticModule(['host'], function(){this.setExport('host',host)}, {context})
const jsx = new vm.SyntheticModule(['jsx','jsxs','Fragment'], function(){for(const name of ['jsx','jsxs','Fragment']) this.setExport(name, ()=>null)}, {context})
const module = new vm.SourceTextModule(source+'\nexport { makeApi };', {context})
await module.link(name => name==='@hermes/plugin-sdk' ? sdk : jsx)
await module.evaluate()
const api = module.namespace.makeApi({rest:async (path, opts)=>{
 calls.push({path,opts})
 if(fail) throw new Error('backend unavailable')
 const session=durable
 if(flip) durable='stored-B'
 return path==='/command' ? {ok:true,state:{session,dials:{}},reply:'applied'} : {session,dials:{}}
}})
assert.equal(api.sessionOf(),'stored-A')
await api.send('edits plan')
assert.equal(calls[0].opts.body.session,'stored-A')
assert.equal(calls[0].opts.body.command,'edits plan')
await api.get()
assert.match(calls[1].path,/session=stored-A/)
durable=null
const before=calls.length
assert.equal((await api.send('edits plan')).ok,false)
assert.ok((await api.get()).error)
assert.equal(calls.length,before)
durable='stored-A'; fail=true
assert.ok((await api.get()).error)
fail=false; flip=true
assert.ok((await api.get()).error)
console.log('Desktop durable-id routing, missing-id refusal, failure and stale-focus guards PASS')
