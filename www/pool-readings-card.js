// Local, dependency-free Home Assistant card. Read-only: no service calls.
export function numeric(value) {
  if (value === null || value === undefined || typeof value === 'boolean' || String(value).trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
export function historyPath(rows, start, end) {
  const points = rows.map(r => ({ t: Date.parse(r.last_changed || r.last_updated), v: numeric(r.state) }))
    .filter(p => Number.isFinite(p.t) && p.t <= end).sort((a,b) => a.t-b.t);
  // Preserve unknown/unavailable transitions as gaps, and never invent prehistory.
  const before = points.filter(p => p.t < start).slice(-1);
  const visible = [...before.map(p => ({...p,t:start})), ...points.filter(p => p.t >= start)];
  const values = visible.filter(p => p.v !== null).map(p => p.v);
  if (!values.length || end <= start) return null;
  let low = Math.min(...values), high = Math.max(...values);
  const pad = Math.max((high-low)*.15, Math.abs(high)*.005, .05);
  low -= pad; high += pad;
  const x = t => 3 + Math.max(0,Math.min(1,(t-start)/(end-start)))*194;
  const y = v => 33 - (v-low)/(high-low)*28;
  let path='', active=false;
  for (const p of visible) {
    if (p.v === null) {
      if (active) path += ` H${x(p.t).toFixed(2)}`;
      active=false;
    } else {
      path += active ? ` H${x(p.t).toFixed(2)} V${y(p.v).toFixed(2)}` : ` M${x(p.t).toFixed(2)},${y(p.v).toFixed(2)}`;
      active=true;
    }
  }
  // A horizontal tail represents the last recorded state, not new measurements.
  if (active) path += ` H${x(end).toFixed(2)}`;
  return {path, low:Math.min(...values), high:Math.max(...values)};
}

const CSS = `
:host{display:block;--pool-green:#2da995;--pool-yellow:#e6ac38;--pool-red:#dc5b5b}
*{box-sizing:border-box}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
button{display:block;text-align:left;width:100%;min-width:0;background:var(--ha-card-background,var(--card-background-color));color:var(--primary-text-color);border:1px solid var(--divider-color);border-radius:16px;padding:12px 13px 8px;font:inherit;cursor:pointer;overflow:hidden}
button:focus-visible{outline:3px solid var(--primary-color);outline-offset:2px}.name{font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.value{font-size:30px;line-height:1.2;font-weight:500;letter-spacing:-.8px;margin-top:4px;font-variant-numeric:tabular-nums}.unit{font-size:12px;color:var(--secondary-text-color);margin-left:4px;letter-spacing:0;font-weight:400}
.bar{height:6px;position:relative;display:flex;border-radius:4px;margin:12px 2px 7px;background:var(--divider-color)}.band{height:6px}.band:first-child{border-radius:4px 0 0 4px}.band:last-child{border-radius:0 4px 4px 0}.marker{position:absolute;width:3px;height:14px;border-radius:2px;background:var(--primary-text-color);top:-4px;transform:translateX(-50%);box-shadow:0 0 0 1px var(--card-background-color)}
.hint{font-size:11px;color:var(--secondary-text-color);min-height:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.stale .hint{color:var(--warning-color,#a47715)}.trend{border-top:1px solid var(--divider-color);margin-top:7px;padding-top:4px;height:44px}.trend svg{display:block;width:100%;height:38px}.empty{font-size:11px;color:var(--secondary-text-color);display:flex;align-items:center;height:38px}.times{display:flex;justify-content:space-between;color:var(--secondary-text-color);font-size:10px}.foot{font-size:11px;color:var(--secondary-text-color);padding:8px 3px 0}
@media(max-width:600px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}button{padding:11px 12px 8px}.value{font-size:29px}}
`;

export class PoolReadingsCard extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode:'open'}); this._history={}; this._historyAt=0;
    this.shadowRoot.innerHTML=`<style>${CSS}</style><div class="grid"></div><div class="foot">24-hour recorded history · Tap a reading for details</div>`;
    this.shadowRoot.addEventListener('click', event => {
      const button=event.target.closest('button[data-entity]');
      if (button) this.dispatchEvent(new CustomEvent('hass-more-info',{detail:{entityId:button.dataset.entity},bubbles:true,composed:true}));
    });
  }
  setConfig(config) {
    if (!Array.isArray(config.readings) || !config.readings.length) throw new Error('Pool readings are required');
    for (const c of config.readings) {
      if (!c.entity || !Number.isFinite(c.min) || !Number.isFinite(c.max) || c.min>=c.max) throw new Error('Invalid pool reading range');
    }
    this._config=config; this._historyAt=0; this._render();
  }
  set hass(hass) {
    const changed=!this._hass || this._config?.readings.some(c=>this._hass.states[c.entity]!==hass.states[c.entity]);
    this._hass=hass;
    if(changed) this._render();
    if(this.isConnected) this._loadHistory();
  }
  connectedCallback() {
    this._loadHistory();
    clearInterval(this._timer);
    this._timer=setInterval(()=>{this._loadHistory();this._render();},60000);
  }
  disconnectedCallback(){clearInterval(this._timer);}
  getCardSize(){return 7;}
  getGridOptions(){return {columns:'full',min_columns:12};}
  async _loadHistory() {
    if(!this._hass || !this._config || this._loading || Date.now()-this._historyAt<300000) return;
    this._loading=true; const requestedConfig=this._config;
    const end=Date.now(), start=end-86400000;
    const query=new URLSearchParams({filter_entity_id:this._config.readings.map(c=>c.entity).join(','),end_time:new Date(end).toISOString(),minimal_response:'',no_attributes:''});
    try {
      const data=await this._hass.callApi('GET',`history/period/${encodeURIComponent(new Date(start).toISOString())}?${query}`);
      if(this._config!==requestedConfig)return;
      const histories={};
      for(const rows of data) if(rows.length && rows[0].entity_id) histories[rows[0].entity_id]=rows;
      this._history=histories;this._historyAt=end;this._start=start;this._end=end;this._historyError=false;
    } catch (_) {this._historyError=true;this._historyAt=Date.now()-240000;}
    finally {this._loading=false;this._render();}
  }
  _render() {
    if(!this._config || !this._hass)return;
    const html=this._config.readings.map(c=>{
      const entity=this._hass.states[c.entity], value=numeric(entity?.state), stale=entity?.attributes.stale===true;
      const unit=c.unit ?? entity?.attributes.unit_of_measurement ?? '';
      const display=value===null?'—':new Intl.NumberFormat(this._hass.locale?.language||'en',{maximumFractionDigits:c.precision??1}).format(value);
      const fraction=Math.max(0,Math.min(1,(value-c.min)/(c.max-c.min)));
      const segments=c.segments||[{from:c.min,color:'#2596be'}];
      const bands=segments.map((s,i)=>`<span class="band" style="width:${100*((segments[i+1]?.from??c.max)-s.from)/(c.max-c.min)}%;background:${/^#[0-9a-f]{6}$/i.test(s.color)?s.color:'#2596be'}"></span>`).join('');
      const time=entity?.attributes.last_successful_reading;
      let hint=c.target||'Current reading';
      if(value===null)hint='Reading unavailable';
      else if(stale)hint='Last known · cannot update';
      else if(c.good_min!==undefined)hint=value<c.good_min?'Below range':value>c.good_max?'Above range':'In range';
      const history=historyPath(this._history[c.entity]||[],this._start,this._end);
      const lineColor=stale?'var(--secondary-text-color)':c.neutral?'#2596be':'#2da995';
      const caption=this._historyError?'History unavailable':history?`${history.low}–${history.high} ${unit}`:'No recorded history yet';
      const graph=history?`<svg viewBox="0 0 200 38" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(c.name+' recorded 24-hour history; '+caption+(stale?'; includes retained readings':''))}"><path d="${history.path}" fill="none" stroke="${lineColor}" stroke-width="1.7" vector-effect="non-scaling-stroke" ${stale?'stroke-dasharray="4 3"':''}/></svg>`:`<span class="empty">${caption}</span>`;
      return `<button type="button" class="${stale?'stale':''}" data-entity="${escapeHtml(c.entity)}" aria-label="${escapeHtml(c.name+': '+display+' '+unit+'. '+hint)}" title="${escapeHtml(c.target+(stale&&time?' · Last confirmed '+new Date(time).toLocaleString():''))}"><div class="name">${escapeHtml(c.name)}</div><div class="value">${display}<span class="unit">${value===null?'':escapeHtml(unit)}</span></div><div class="bar">${value===null?'':bands+`<span class="marker" style="left:${fraction*100}%"></span>`}</div><div class="hint">${escapeHtml(hint)}</div><div class="trend">${graph}</div><div class="times"><span>−24h${stale?' · retained':''}</span><span>${this._historyError?'update failed':'now'}</span></div></button>`;
    }).join('');
    if(html!==this._lastHTML){this.shadowRoot.querySelector('.grid').innerHTML=html;this._lastHTML=html;}
  }
}
if(!customElements.get('pool-readings-card'))customElements.define('pool-readings-card',PoolReadingsCard);
window.customCards=window.customCards||[];
window.customCards.push({type:'pool-readings-card',name:'Pool compact readings',description:'Compact range bars with actual 24-hour history.'});
