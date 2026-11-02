import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
globalThis.HTMLElement=class {};
globalThis.customElements={get:()=>true};
globalThis.window={};
const source=await readFile(new URL('../www/pool-readings-card.js',import.meta.url),'utf8');
const {numeric,escapeHtml,historyPath,PoolReadingsCard}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
function renderSalt(attributes) {
  const grid={innerHTML:''};
  const card=Object.create(PoolReadingsCard.prototype);
  card.shadowRoot={querySelector:()=>grid};
  card._config={readings:[{entity:'sensor.salt',name:'Salt',min:0,max:6000,target:'Salt target'}]};
  card._history={};
  card._hass={locale:{language:'en-US'},states:{'sensor.salt':{state:'2800',attributes}}};
  card._render();
  return grid.innerHTML;
}
test('retained salt shows ongoing checks separately from its old confirmation',()=>{
  const html=renderSalt({stale:true,last_attempt:'2026-11-02T13:42:31+00:00',
    last_successful_reading:'2026-10-18T14:23:15+00:00',update_status:'controller offline'});
  assert.match(html,/Checked Nov 2/);
  assert.match(html,/Display connection offline/);
  assert.match(html,/Last known · awaiting fresh reading/);
  assert.match(html,/Last confirmed/);
  assert.match(html,/class="stale"/);
  assert.doesNotMatch(html,/cannot update/);
});
test('connected display without numeric salt is distinguished from an offline display',()=>{
  const html=renderSalt({stale:true,last_attempt:'2026-11-02T13:42:31+00:00',
    update_status:'connected; salt not rendered'});
  assert.match(html,/Connected · no numeric salt reading/);
  assert.doesNotMatch(html,/Display connection offline/);
});
test('bad or missing check timestamps do not fabricate a check',()=>{
  for(const last_attempt of [undefined,null,'bad']) {
    const html=renderSalt({stale:true,last_attempt});
    assert.doesNotMatch(html,/Checked |Invalid Date/);
  }
});
test('poll results are escaped when rendered',()=>{
  const html=renderSalt({last_attempt:'2026-11-02T13:42:31+00:00',update_status:'<img onerror="bad">'});
  assert.doesNotMatch(html,/<img/);
  assert.match(html,/&lt;img onerror=&quot;bad&quot;&gt;/);
});
test('missing, blank and nonfinite values never become zero',()=>{
  for(const v of [undefined,null,'',' ','unknown','unavailable','NaN','Infinity',Infinity,true])assert.equal(numeric(v),null);
  assert.equal(numeric('0'),0);assert.equal(numeric('3200'),3200);assert.equal(numeric('7.8'),7.8);
});
test('entity labels cannot inject HTML',()=>assert.equal(escapeHtml('<script>"&'), '&lt;script&gt;&quot;&amp;'));
const start=Date.parse('2026-10-03T00:00:00Z'),end=start+86400000;
const row=(hour,state)=>({last_changed:new Date(start+hour*3600000).toISOString(),state});
test('empty or unavailable history does not invent observations',()=>{
  assert.equal(historyPath([],start,end),null);
  assert.equal(historyPath([row(2,'unknown')],start,end),null);
});
test('history uses steps and preserves missing-data gaps',()=>{
  const result=historyPath([row(0,'5'),row(6,'unknown'),row(12,'6')],start,end);
  assert.equal((result.path.match(/M/g)||[]).length,2);
  assert.equal(result.low,5);assert.equal(result.high,6);
  assert.match(result.path,/H197\.00$/);
});
test('new sensors do not get fabricated full-day history',()=>{
  const result=historyPath([row(12,'3200')],start,end);
  assert.match(result.path,/M100\.00,/);assert.ok(!result.path.includes('NaN'));
});
test('state before window is clamped to start and future data excluded',()=>{
  const result=historyPath([row(-2,'5'),row(25,'100')],start,end);
  assert.match(result.path,/M3\.00,/);assert.equal(result.high,5);
});
test('history fetched once per five minutes for all readings, GET only',async()=>{
  let calls=0;
  const card=Object.create(PoolReadingsCard.prototype);
  card._config={readings:[{entity:'sensor.a'},{entity:'sensor.b'}]};
  card._historyAt=0;card._render=()=>{};
  card._hass={callApi:async(method,url)=>{calls++;assert.equal(method,'GET');assert.ok(url.includes('sensor.a%2Csensor.b'));return [[{entity_id:'sensor.a',...row(1,'7')}]];}};
  await card._loadHistory();await card._loadHistory();
  assert.equal(calls,1);assert.equal(card._history['sensor.a'][0].state,'7');
});
test('history failure retains previous data and reports unavailable',async()=>{
  const card=Object.create(PoolReadingsCard.prototype);
  card._config={readings:[{entity:'sensor.a'}]};card._historyAt=0;
  card._history={'sensor.a':[row(1,'7')]};card._render=()=>{};
  card._hass={callApi:async()=>{throw new Error('offline');}};
  await card._loadHistory();
  assert.equal(card._historyError,true);assert.equal(card._history['sensor.a'][0].state,'7');
});
