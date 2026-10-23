// Logic smoke checks with a minimal DOM fixture. This does not verify browser layout.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'retailpulse/static/index.html'),'utf8'),source=fs.readFileSync(path.join(root,'retailpulse/static/app.js'),'utf8');
let document;
class Element {
  constructor(tag,attrs,pos=0){this.tag=tag;this.attrs=attrs;this.pos=pos;this.dataset={};this.events={};this.value=attrs.value||'';this.hidden=Object.hasOwn(attrs,'hidden');this.checked=Object.hasOwn(attrs,'checked');this.disabled=Object.hasOwn(attrs,'disabled');this.elements=[];this.htmlWrites=0;this._html='';this.textContent='';this.tabIndex=Number(attrs.tabindex||0);const classes=new Set((attrs.class||'').split(/\s+/));this.classList={contains:c=>classes.has(c),add:c=>classes.add(c),remove:c=>classes.delete(c),toggle:(c,value)=>{value=value===undefined ? !classes.has(c) : value;value ? classes.add(c) : classes.delete(c);return value;}};for(const [k,v]of Object.entries(attrs))if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,s)=>s.toUpperCase())]=v;}
  set innerHTML(value){this._html=value;this.htmlWrites++;if(this.tag==='select')this.value=value.match(/<option value="([^"]*)"/)?.[1]||'';}
  get innerHTML(){return this._html;}
  addEventListener(name,fn){(this.events[name]||=[]).push(fn);}
  setAttribute(name,value){this.attrs[name]=String(value);}
  getAttribute(name){return this.attrs[name]??null;}
  removeAttribute(name){delete this.attrs[name];}
  focus(){document.activeElement=this;}
  scrollIntoView(){}
  closest(selector){if(selector.startsWith('a'))return this.tag==='a' ? this : null;const attr=selector.match(/^button\[([^\]=]+)/)?.[1];return this.tag==='button' && (!attr || Object.hasOwn(this.attrs,attr)) ? this : null;}
  querySelectorAll(selector){return elements.filter(e=>e.pos>this.pos && e.pos<html.indexOf('</aside>',this.pos) && (selector==='a,button' ? ['a','button'].includes(e.tag) : false));}
  reset(){for(const e of this.elements){e.value=e.attrs.value||'';e.checked=Object.hasOwn(e.attrs,'checked');}}
  async fire(name,extra={}){for(const fn of this.events[name]||[])await fn({preventDefault(){},target:this,...extra});}
}
const attrPattern=/([\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'))?/g;
const elements=[...html.matchAll(/<([a-z][\w-]*)\b([^>]*)>/gi)].map(m=>{const attrs={};for(const a of m[2].matchAll(attrPattern))attrs[a[1]]=a[2]??a[3]??'';return new Element(m[1],attrs,m.index);});
const ids=new Map(elements.filter(e=>e.attrs.id).map(e=>[e.attrs.id,e]));
for(const e of elements){if(e.tag==='form')e.elements=elements.filter(c=>c.pos>e.pos && c.pos<html.indexOf('</form>',e.pos) && ['input','select','button'].includes(c.tag));if(e.tag==='select')e.value=html.slice(e.pos,html.indexOf('</select>',e.pos)).match(/<option value="([^"]*)"/)?.[1]||'';}
const navStart=html.indexOf('<nav '),navEnd=html.indexOf('</nav>');
const nav=elements.filter(e=>e.tag==='a' && e.pos>navStart && e.pos<navEnd);
const selectAll=s=>s==='[data-view]' ? elements.filter(e=>e.dataset.view) : s==='nav a' ? nav : s==='[data-stock-panel]' ? elements.filter(e=>e.dataset.stockPanel) : s==='[data-stock-tab]' ? elements.filter(e=>e.dataset.stockTab) : s==='[data-return-line]' ? [] : [];
document={body:new Element('body',{}),events:{},title:'',getElementById:id=>ids.get(id),querySelectorAll:selectAll,querySelector:s=>s==='.source-bar' ? elements.find(e=>e.classList.contains('source-bar')) : s==='nav a[aria-current="page"]' ? nav.find(e=>e.attrs['aria-current']==='page') : null,addEventListener(name,fn){(this.events[name]||=[]).push(fn);}};
const stored=new Map(),sessionStorage={getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
const window={events:{},location:{hash:'#overview'},history:{pushState(a,b,hash){window.location.hash=hash;}},scrollTo(){},addEventListener(name,fn){(this.events[name]||=[]).push(fn);},matchMedia(){return {addEventListener(){},matches:false};}};
let snapshot={metadata:{mode:'live',currency:'INR',timezone:'Asia/Kolkata',shop_name:'Test shop',store_id:'shop-ui',coverage_start:'2026-07-01',continuous_recording:true},business_date:'2026-10-05',forecast_readiness:{required_days:90,complete_through:'2026-10-04',has_completed_sales:true},summary:{revenue_today_minor:7000,gross_revenue_today_minor:7000,refund_today_minor:0,units_today:2,returned_units_today:0,restock_products:0,products:2},products:[{sku:'A',name:'<Soap & bar>',price_minor:3500,stock:20,stock_initialized:1,active:1,revision:1,introduced_on:'2026-07-01',lead_days:3,buffer_units:10,stock_status:'Forecast unavailable'},{sku:'B',name:'Archived tea',price_minor:2000,stock:0,stock_initialized:1,active:0,revision:1,introduced_on:'2026-07-01',lead_days:3,buffer_units:10,stock_status:'Archived'},{sku:'C',name:'Milk',price_minor:5000,stock:0,stock_initialized:1,active:1,revision:1,introduced_on:'2026-10-05',lead_days:3,buffer_units:10,stock_status:'Forecast unavailable'}],history:[{day:'2026-10-04',sku:'A',units:2}],forecast:null,recent_events:[],recent_bills:[],recent_returns:[],stream_events:[],anomaly_alerts:[],stock_movements:[],backup_status:{files:[]},setup_required:false,shop_setup_required:false,training:false};
let offline=false,popupBlocked=false;const requests=[],chats=[];
window.open=()=>{if(popupBlocked)return null;const chat={opener:window,closed:false,location:{href:''},close(){this.closed=true;}};chats.push(chat);return chat;};
let billFixture={bill_id:'saved-bill',shop_name:'Satya Shop',customer_name:'Customer <name>',customer_phone:'919000000000',source:'live',business_date:'2026-10-05',currency:'INR',status:'active',total_minor:7000,refund_minor:0,net_total_minor:7000,items:[{line_no:0,sku:'A',product_name:'Soap & bar',quantity:2,unit_price_minor:3500,line_total_minor:7000,returned_quantity:0,remaining_quantity:2}]};
const fetch=async(url,options)=>{
  requests.push({path:url,options});if(offline)throw new Error('Test connection unavailable');
  let result;
  if(url==='/api/shop/name' && options.method==='POST'){
    const payload=JSON.parse(options.body);snapshot.metadata.shop_name=payload.shop_name;
    result={shop_name:payload.shop_name,duplicate:false};
  }else if(url==='/api/payment/quote' && options.method==='POST'){
    const payload=JSON.parse(options.body);context.quotePayload=payload;
    result={order_id:payload.bill_id,payment_method:'cash',currency:'INR',pricing:{subtotal_minor:7000,discount_minor:0,tax_minor:0,total_minor:7000,gst_mode:'off'}};
  }else if(url==='/api/payment/confirm' && options.method==='POST'){
    const payload=context.quotePayload;billFixture={...billFixture,bill_id:payload.bill_id,shop_name:payload.shop_name,customer_name:payload.customer_name,customer_phone:payload.customer_phone};result=billFixture;
  }else if(url==='/api/checkout' && options.method==='POST'){
    const payload=JSON.parse(options.body);billFixture={...billFixture,bill_id:payload.bill_id,shop_name:payload.shop_name,customer_name:payload.customer_name,customer_phone:payload.customer_phone};result=billFixture;
  }else if(url.startsWith('/api/bills/') && context.quotePayload===undefined)return {ok:false,status:404,json:async()=>({error:'Bill not found'})};
  else if(url.startsWith('/api/bills/'))result={...billFixture,bill_id:decodeURIComponent(url.slice('/api/bills/'.length))};
  else result=snapshot;
  return {ok:true,status:200,json:async()=>structuredClone(result)};
};
const context=vm.createContext({document,window,sessionStorage,navigator:{},fetch,console,Intl,Date,Number,String,Object,Array,JSON,WeakMap,Math,Set,crypto,URL,setInterval(){},setTimeout,structuredClone});
vm.runInContext(source,context);
const run=s=>vm.runInContext(s,context),get=id=>ids.get(id);
(async()=>{
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(get('connection').textContent,'');assert(get('connection').innerHTML.includes('Connected'));
  for(const name of ['overview','checkout','products','stock','forecast','returns','activity','backups']){run(`navigate('${name}')`);assert.deepEqual(selectAll('[data-view]').filter(e=>!e.hidden).map(e=>e.dataset.view),[name]);assert.equal(nav.find(e=>e.attrs['aria-current']==='page').attrs.href,'#'+name);}
  get('cart-product').value='A';get('cart-quantity').value='2';get('cart-price').value='35.00';await get('cart-form').fire('submit');
  assert.equal(get('cart-summary-count').textContent,'2');assert(get('cart-total').textContent.includes('70.00'));
  run("navigate('products')");get('product-name').value='Unfinished new item';const cartWrites=get('cart-body').htmlWrites,selectWrites=get('cart-product').htmlWrites;run('render()');assert.equal(get('product-name').value,'Unfinished new item');assert.equal(get('cart-summary-count').textContent,'2');assert.equal(get('cart-body').htmlWrites,cartWrites);assert.equal(get('cart-product').htmlWrites,selectWrites);
  get('shop-name').value='Satya Shop';await get('shop-name').fire('input');run('render()');
  assert.equal(get('shop-name').value,'Satya Shop');assert.equal(get('bill-shop').value,'Test shop');
  await get('shop-name-form').fire('submit');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(get('brand-name').textContent,'Satya Shop');assert.equal(get('bill-shop').value,'Satya Shop');assert(document.title.endsWith('Satya Shop'));
  const rename=JSON.parse(requests.find(r=>r.path==='/api/shop/name').options.body);
  assert.equal(rename.expected_shop_name,'Test shop');assert.equal(rename.store_id,'shop-ui');assert.equal(stored.has('retailpulse_action'),false);
  get('bill-customer-phone').value='bad number';const beforeBad=requests.length;await get('checkout-button').fire('click');
  assert.equal(requests.length,beforeBad);assert.equal(stored.has('retailpulse_checkout'),false);
  get('bill-customer').value='Customer <name>';get('bill-customer-phone').value='9000000000';await get('checkout-button').fire('click');
  assert(!requests.some(r=>r.path==='/api/payment/confirm'));
  await get('payment-confirm').fire('click');assert(get('payment-message').textContent.includes('tick'));
  get('payment-received').checked=true;await get('payment-confirm').fire('click');
  const purchase=JSON.parse(requests.find(r=>r.path==='/api/payment/quote').options.body);
  assert.equal(purchase.shop_name,'Satya Shop');assert.equal(purchase.customer_phone,'919000000000');assert.equal(get('bill-customer-phone').value,'');assert.equal(get('bill-customer').value,'');
  assert.equal(get('cart-summary-count').textContent,'0');
  const postCount=()=>requests.filter(r=>r.options.method==='POST').length;const writesBeforeShare=postCount();
  await run("beginBillSharing('saved-bill')");assert.equal(get('bill-share').classList.contains('hidden'),false);assert.equal(get('whatsapp-number').value,'+919000000000');
  assert(get('whatsapp-preview').textContent.includes('Soap & bar'));assert(!get('whatsapp-preview').textContent.includes('127.0.0.1'));
  get('whatsapp-number').value='900';const beforeNumber=chats.length;await get('whatsapp-form').fire('submit');assert.equal(chats.length,beforeNumber);
  get('whatsapp-number').value='+1 (202) 555-0100';
  billFixture={...billFixture,status:'partially_returned',refund_minor:3500,net_total_minor:3500,items:billFixture.items.map(i=>({...i,returned_quantity:1,remaining_quantity:1}))};
  await get('whatsapp-form').fire('submit');const chat=chats.at(-1),chatUrl=new URL(chat.location.href),message=chatUrl.searchParams.get('text');
  assert.equal(chat.opener,null);assert.equal(chatUrl.origin,'https://wa.me');assert.equal(chatUrl.pathname,'/12025550100');
  for(const phrase of ['Satya Shop','Customer <name>','Soap & bar','Returned: 1 of 2','Recorded refunds: INR 35.00','Total after refunds: INR 35.00'])assert(message.includes(phrase));
  assert.equal(billFixture.customer_phone,'919000000000');assert.equal(postCount(),writesBeforeShare);assert(get('whatsapp-message').textContent.includes('tap Send'));
  offline=true;await get('whatsapp-form').fire('submit');assert(chats.at(-1).closed);assert.equal(chats.at(-1).location.href,'');offline=false;
  popupBlocked=true;const requestsBeforePopup=requests.length;await get('whatsapp-form').fire('submit');assert.equal(requests.length,requestsBeforePopup);assert(get('whatsapp-message').textContent.includes('blocked'));popupBlocked=false;
  await get('whatsapp-close').fire('click');assert(get('bill-share').classList.contains('hidden'));
  const historyShare=new Element('button',{'data-share-bill':'older-bill'});await get('bill-history').fire('click',{target:historyShare});await new Promise(resolve=>setImmediate(resolve));assert(get('whatsapp-bill').textContent.includes('older-bill'));
  await get('whatsapp-close').fire('click');
  for(const raw of ['9000000000','+91 90000-00000','0091 (90000) 00000','919000000000']){context.phoneTest=raw;assert.equal(run('whatsappNumber(phoneTest)'),'919000000000');}
  for(const raw of ['12345','1234567890','+91 90000','9'.repeat(16),'+9000000','9000000000 ext 2','https://wa.me/9000000000','++919000000000','٩'.repeat(10)]){context.phoneTest=raw;assert.throws(()=>run('whatsappNumber(phoneTest)'));}
  const sampleMessage=run("billMessage({...sharingBill?.bill,...{shop_name:'Satya Shop',bill_id:'demo',business_date:'2026-10-05',source:'demo',currency:'INR',status:'active',total_minor:7000,items:[]}})");assert(sampleMessage.startsWith('DEMO BILL'));
  get('product-search').value='soap';await get('product-search').fire('input');assert(get('product-body').innerHTML.includes('&lt;Soap &amp; bar&gt;'));assert(!get('product-body').innerHTML.includes('Milk'));
  get('product-search').value='';get('product-filter').value='archived';await get('product-filter').fire('change');assert(get('product-body').innerHTML.includes('Archived tea'));assert(!get('product-body').innerHTML.includes('Milk'));
  get('product-filter').value='empty';await get('product-filter').fire('change');assert(get('product-body').innerHTML.includes('Milk'));assert(!get('product-body').innerHTML.includes('Archived tea'));
  await get('tab-receive').fire('keydown',{key:'ArrowRight'});assert.equal(get('stock-count').hidden,false);assert.equal(get('stock-receive').hidden,true);assert.equal(get('tab-count').attrs['aria-selected'],'true');
  get('chart-product').value='A';run('renderChart()');assert.equal(get('forecast-status-title').textContent,'Ready for an early estimate');assert.equal(get('forecast-progress').value,3);
  get('chart-product').value='C';run('renderChart()');assert.equal(get('forecast-progress').value,0);assert(get('forecast-status-detail').textContent.includes('0 complete days'));assert(!get('train-button').disabled);
  get('chart-product').value='B';run('renderChart()');assert.equal(get('forecast-status-title').textContent,'This item is archived');
  const manage=new Element('button',{'data-manage-bill':'saved-bill'});await get('bill-history').fire('click',{target:manage});await new Promise(resolve=>setImmediate(resolve));assert.equal(get('returns').hidden,false);assert.equal(get('find-bill-id').value,'saved-bill');assert.equal(get('return-details').classList.contains('hidden'),false);
  assert(!ids.has('sidebar'));assert(!ids.has('menu-toggle'));assert(!ids.has('nav-backdrop'));assert(get('top-nav').classList.contains('top-nav'));assert.equal(nav.length,8);
  snapshot.desktop_mode=true;await run('refresh()');assert.equal(get('shop-mode').textContent,'Desktop shop · v0.8.1');assert(get('install-app').classList.contains('hidden'));
  offline=true;await run('refresh()');assert.equal(get('connection').textContent,'Connection interrupted');offline=false;await run('refresh()');assert(get('connection').innerHTML.includes('Connected'));assert(get('connection').classList.contains('connected'));
  const daySnapshot={metadata:{coverage_start:'2026-01-01',continuous_recording:true},business_date:'2026-04-01'};context.daySnapshot=daySnapshot;assert.equal(run("historyDays({introduced_on:'2026-01-01'},daySnapshot)"),90);assert.equal(run("historyDays({introduced_on:'2026-04-01'},daySnapshot)"),0);

  console.log('JavaScript logic checks passed: navigation and shop-name drafts; checkout contact validation; number normalization; WhatsApp draft URLs, fresh return totals, demo labels, read-only sharing, popup/network failures; existing dashboard controls. No actual browser or WhatsApp message was used.');
})().catch(error=>{console.error(error);process.exitCode=1;});
