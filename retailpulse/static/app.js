"use strict";
const $ = id => document.getElementById(id);
let state = null, token = sessionStorage.getItem("retailpulse_token") || "", inFlight = false;
let initialized = false;
let productEditing = null, countReference = null, loadedBill = null;
let managedBusy = false, managedPending = null;
let shopNameDraft = false, shopNameReference = null;
try { managedPending = JSON.parse(sessionStorage.getItem("retailpulse_action") || "null"); } catch (_) {}
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const number = value => value === null || value === undefined ? "—" : Number(value).toLocaleString(undefined, {maximumFractionDigits: 1});
const currency = (value,code=state?.metadata.currency || "INR") => new Intl.NumberFormat("en-IN", {style:"currency", currency:code, maximumFractionDigits: 2}).format(value / 100);
function whatsappNumber(value) {
  const raw=String(value).trim();
  if(!raw)return "";
  if(raw.length>40 || !/^\+?[0-9 ()-]+$/.test(raw))throw new Error("Enter a WhatsApp number using digits and a country code for numbers outside India.");
  let digits=raw.replace(/[ ()-]/g,"");
  const international=digits.startsWith("+") || digits.startsWith("00");
  if(digits.startsWith("+"))digits=digits.slice(1);else if(digits.startsWith("00"))digits=digits.slice(2);
  if(!international && digits.length===10){
    if(!/^[6-9]/.test(digits))throw new Error("For an Indian mobile, enter 10 digits. For another number, include + and its country code.");
    digits="91"+digits;
  }else if(!international && digits.length<11)throw new Error("Enter a 10-digit Indian mobile number, or include + and the country code.");
  if(!/^[1-9][0-9]{7,14}$/.test(digits) || digits.startsWith("91") && digits.length!==12)throw new Error("Check the WhatsApp number and country code. Indian numbers need 10 digits after +91.");
  return digits;
}

const viewDetails = {
  overview: ["YOUR DAY, AT A GLANCE", "Today at the shop.", "A little order for every sale, shelf and customer."],
  checkout: ["AT THE COUNTER", "Checkout & bills", "Build a basket, record the sale and give your customer a digital bill."],
  products: ["YOUR CATALOGUE", "Products", "Find an item, update its price or add something new."],
  stock: ["ON YOUR SHELVES", "Stock", "Receive deliveries, check quantities and plan your next order."],
  forecast: ["LOOKING AHEAD", "Forecast", "See your sales history and what may sell over the next 14 days."],
  returns: ["CUSTOMER RETURNS", "Returns", "Record returned items and refunds against the original bill."],
  activity: ["YOUR SHOP RECORDS", "Activity", "Follow recent sales and deliveries as they happen."],
  backups: ["KEEP A COPY", "Backups & exports", "Save a backup of your shop and download your records."]
};
let activeView = "overview";
const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const quiet = (title, detail) => `<div class="quiet-state"><strong>${esc(title)}</strong><p>${esc(detail)}</p></div>`;
const lastMarkup = new WeakMap();
function updateHTML(id, markup) {
  const element=$(id);
  if(lastMarkup.get(element)!==markup){element.innerHTML=markup;lastMarkup.set(element,markup);}
}
function localTime(timestamp, full=false) {
  return new Date(timestamp).toLocaleString("en-GB", {timeZone:state?.metadata.timezone || "Asia/Kolkata", ...(full ? {day:"numeric",month:"short"} : {}),hour:"2-digit",minute:"2-digit"});
}
function showView(name, focus=false) {
  activeView = Object.hasOwn(viewDetails,name) ? name : "overview";
  for(const panel of document.querySelectorAll("[data-view]")) panel.hidden=panel.dataset.view!==activeView;
  for(const link of document.querySelectorAll("nav a")) {
    const selected=link.getAttribute("href")==="#"+activeView;
    link.classList.toggle("active",selected);
    if(selected) link.setAttribute("aria-current","page"); else link.removeAttribute("aria-current");
  }
  const [eyebrow,title,intro]=viewDetails[activeView];
  $("page-eyebrow").textContent=eyebrow;$("page-title").textContent=title;$("page-intro").textContent=intro;
  document.title=title+" · "+(state?.metadata.shop_name || "Satya Shop");
  if(focus) {window.scrollTo({top:0,behavior:"instant"});$("page-title").focus({preventScroll:true});}
}
function navigate(name) {
  if(window.location.hash!=="#"+name) window.history.pushState(null,"","#"+name);
  showView(name,true);
}
function showStockTab(name, focus=false) {
  for(const panel of document.querySelectorAll("[data-stock-panel]")) panel.hidden=panel.dataset.stockPanel!==name;
  for(const button of document.querySelectorAll("[data-stock-tab]")) {
    const selected=button.dataset.stockTab===name;
    button.setAttribute("aria-selected",String(selected));button.tabIndex=selected ? 0 : -1;
    if(selected && focus) button.focus();
  }
}
document.addEventListener("click",event=>{
  const link=event.target.closest('a[href^="#"]');
  if(!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)return;
  const name=link.getAttribute("href").slice(1);
  if(!Object.hasOwn(viewDetails,name))return;
  event.preventDefault();navigate(name);
  if(link.dataset.stockTarget)showStockTab(link.dataset.stockTarget);
});
function restoreView() {
  const name=window.location.hash.slice(1)||"overview";
  if(Object.hasOwn(viewDetails,name) && name!==activeView)showView(name,true);
}
window.addEventListener("hashchange",restoreView);
window.addEventListener("popstate",restoreView);
for(const button of document.querySelectorAll("[data-stock-tab]")) {
  button.addEventListener("click",()=>showStockTab(button.dataset.stockTab));
  button.addEventListener("keydown",event=>{
    if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;
    event.preventDefault();const tabs=[...document.querySelectorAll("[data-stock-tab]")];let index=tabs.indexOf(button);
    index=event.key==="Home" ? 0 : event.key==="End" ? tabs.length-1 : (index+(event.key==="ArrowRight" ? 1 : tabs.length-1))%tabs.length;
    showStockTab(tabs[index].dataset.stockTab,true);
  });
}

// Calendar coverage is declared by the shop/import. Today is never a complete day.
function historyDays(item, snapshot=state) {
  const meta=snapshot?.metadata || {};
  const end=meta.continuous_recording ? Date.parse(snapshot.business_date+"T00:00:00Z")-86400000 : Date.parse((meta.coverage_end||"")+"T00:00:00Z");
  const start=Math.max(Date.parse((meta.coverage_start||"")+"T00:00:00Z"),item?.introduced_on ? Date.parse(item.introduced_on+"T00:00:00Z") : -Infinity);
  return Number.isFinite(start) && Number.isFinite(end) ? Math.max(0,Math.floor((end-start)/86400000)+1) : 0;
}
function renderForecastStatus() {
  if(!state)return;
  const item=product("chart-product"),days=historyDays(item),required=3;
  const included=(state.forecast?.rows||[]).some(row=>row.sku===item?.sku);
  const ownSales=item?.has_completed_sales ?? state.history.some(row=>row.sku===item?.sku && row.units>0);
  const ready=days>=required && item?.active && ownSales;
  const detail=state.forecast?.product_methods?.[item?.sku];
  $("forecast-status-title").textContent=state.training ? "Preparing forecast…" : item && !item.active ? "This item is archived" : included ? "Forecast available" : ready ? "Ready for an early estimate" : "Building history";
  $("forecast-status-detail").textContent=included ? (detail?.early_estimate ? "Early estimate from limited history. Use it cautiously for stock decisions." : "Forecast from your recorded history.") : `This item has ${days} complete days. It needs 3 complete days and a saved sale for an early estimate.`;
  $("forecast-days").textContent=number(Math.min(required,days))+" / 3 days";
  $("forecast-progress").max=required;$("forecast-progress").value=Math.min(required,days);
  $("forecast-progress").setAttribute("aria-valuetext",`${days} complete days; 3 required for an early estimate`);
  $("forecast-readiness-note").textContent=`${days} complete days recorded. Today counts tomorrow. Compare smoothing and Holt-Winters after 28 days; Random Forest joins after 90 days.`;
  $("overview-forecast-title").textContent=state.forecast_current ? "Forecast available" : "Early forecasts after 3 days";
  $("overview-forecast-detail").textContent="Early estimates use a daily average or exponential smoothing. Longer history allows model comparison.";
  const canTrain=state.products.some(p=>p.active && historyDays(p)>=3 && (p.has_completed_sales ?? state.history.some(r=>r.sku===p.sku && r.units>0)));
  $("train-button").disabled=state.training || !canTrain;
  $("train-button").textContent=state.training ? "Preparing…" : canTrain ? "Refresh forecast ↻" : "Waiting for 3 days";
  $("train-button").title="An active item needs 3 complete days and a saved sale";
}

function renderProductList() {
  if(!state)return;
  const search=$("product-search").value.trim().toLocaleLowerCase(),filter=$("product-filter").value;
  const items=state.products.filter(p=>(p.name+" "+p.sku).toLocaleLowerCase().includes(search) && (filter==="all" || filter==="active" && p.active || filter==="archived" && !p.active || filter==="empty" && p.active && p.stock_initialized && p.stock===0));
  $("product-list-count").textContent=`${items.length} of ${state.products.length}`;
  updateHTML("product-body",items.map(p=>`<tr><td>${esc(p.name)}<small>${esc(p.sku)}</small></td><td>${currency(p.price_minor)}</td><td>${p.stock_initialized ? number(p.stock) : "Not set"}</td><td><span class="pill ${p.active ? p.stock===0 ? "warn" : "" : "neutral"}">${p.active ? p.stock_initialized && p.stock===0 ? "Out of stock" : "Available" : "Archived"}</span></td><td><button class="secondary-button" type="button" data-edit-product="${esc(p.sku)}" aria-label="Edit ${esc(p.name)}">Edit</button></td></tr>`).join("") || `<tr><td colspan="5" class="table-empty">${state.products.length ? "No matching products. Try another search or filter." : "Add your first item using the product form."}</td></tr>`);
}
$("product-search").addEventListener("input",renderProductList);
$("product-filter").addEventListener("change",renderProductList);

async function api(path, body) {
  if (body !== undefined && state?.metadata.store_id) {
    if (body.store_id && body.store_id !== state.metadata.store_id) throw new Error("This saved request belongs to a different shop. Open the original data folder to confirm it.");
    body = {...body,store_id:body.store_id || state.metadata.store_id};
  }
  const response = await fetch(path, {method: body === undefined ? "GET" : "POST", headers: {
    ...(token ? {Authorization: "Bearer " + token} : {}), ...(body === undefined ? {} : {"Content-Type": "application/json"})},
    ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  if (response.status === 401) {
    $("login-panel").classList.remove("hidden");
    throw new Error("Enter the project access token to continue.");
  }
  const result = await response.json();
  if (!response.ok) {const error=new Error(result.error || "Request failed.");error.httpStatus=response.status;error.code=result.code;throw error;}
  return result;
}

function showMessage(id, message, error=false) {
  $(id).textContent = message;
  $(id).classList.toggle("error", error);
}

function product(id) { return state?.products.find(item => item.sku === $(id).value); }
function updatePrice() { const item = product("sale-product"); if (item) $("sale-price").value = (item.price_minor/100).toFixed(2); }
function updatePolicy() { const item = product("policy-product"); if (item) { $("lead-days").value = item.lead_days; $("buffer-units").value = item.buffer_units; } }

function populateSelects() {
  for (const id of ["sale-product", "chart-product", "receipt-product", "policy-product", "cart-product", "count-product"]) {
    const oldValue = $(id).value;
    const choices = ["sale-product","cart-product"].includes(id) ? state.products.filter(item=>item.active) : state.products;
    updateHTML(id, choices.map(item => `<option value="${esc(item.sku)}">${esc(item.name)}${item.active ? "" : " (archived)"}</option>`).join(""));
    if (choices.some(item => item.sku === oldValue)) $(id).value = oldValue;
    if (!initialized || oldValue !== $(id).value) {
      if(id === "sale-product") updatePrice();
      if(id === "cart-product") updateCartPrice();
      if(id === "policy-product") updatePolicy();
      if(id === "count-product") loadCount();
    }
  }
  initialized = true;
}

function renderChart() {
  if (!state) return;
  renderForecastStatus();
  const sku = $("chart-product").value, artifact = state.forecast;
  const series = state.history.filter(row => row.sku === sku);
  const future = (artifact?.rows || []).filter(row => row.sku === sku);
  $("forecast-context").textContent="";
  if (!series.length && !future.length) {
    updateHTML("chart",`<div class="chart-empty">${icon("chart")}<strong>${state.products.length ? "Your sales story starts here" : "Add a product to begin"}</strong><p>${state.products.length ? "Saved sales from completed days will appear here. Today’s sales appear after the day ends. Early estimates need 3 complete days and saved sales." : "Set up your products and record customer purchases. This chart uses your saved sales."}</p></div>`);
    return;
  }
  const end = future.length ? artifact.train_through : state.forecast_readiness.complete_through;
  const endDate = new Date(end+"T12:00:00Z");
  const lookup = Object.fromEntries(series.map(row => [row.day, row.units]));
  const points = [];
  const historyLength=Math.max(1,Math.min(28,historyDays(product("chart-product"))));
  for (let i=historyLength-1; i>=0; i--) {
    const day = new Date(endDate); day.setUTCDate(day.getUTCDate()-i);
    const date = day.toISOString().slice(0,10);
    points.push({date, value: lookup[date] || 0, forecast:false});
  }
  points.push(...future.map(row => ({date:row.date, value:row.predicted_units, forecast:true})));
  const width=690, height=260, left=35, right=20, top=25, bottom=34, pw=width-left-right, ph=height-top-bottom;
  const maximum = Math.max(1, ...points.map(point => point.value));
  const step = Math.max(1, Math.ceil(maximum/4));
  const ymax = step*4;
  const x = index => left+index*pw/Math.max(1,points.length-1);
  const y = value => top+ph-value/ymax*ph;
  let content = "";
  if (future.length) {
    const split=x(historyLength-1)+pw/(points.length-1)/2;
    content+=`<rect x="${split}" y="${top-8}" width="${width-right-split}" height="${ph+8}" fill="#fff0df"/><text x="${split+12}" y="16" fill="#9d4f2b" font-family="Arial" font-size="10" letter-spacing="1">FORECAST</text>`;
  }
  for (let i=0;i<=4;i++) {
    const value = step*i;
    content += `<line x1="${left}" y1="${y(value)}" x2="${width-right}" y2="${y(value)}" stroke="#e5eadc" stroke-width="1"/><text x="${left-8}" y="${y(value)+3}" text-anchor="end" fill="#819177" font-family="Arial" font-size="10">${value}</text>`;
  }
  const line = values => values.map(({value,index}) => `${x(index)},${y(value)}`).join(" ");
  const actual = points.map((point,index) => ({...point,index})).filter(point => !point.forecast);
  const forecast = points.map((point,index) => ({...point,index})).filter(point => point.forecast || point.index === actual.length-1);
  content += `<polygon points="${x(0)},${y(0)} ${line(actual)} ${x(actual.length-1)},${y(0)}" fill="#e8eedb"/><polyline points="${line(actual)}" fill="none" stroke="#163438" stroke-width="2.7" stroke-linejoin="round"/>`;
  if (actual.length===1) content+=`<circle cx="${x(0)}" cy="${y(actual[0].value)}" r="3.5" fill="#163438"/>`;
  if (future.length) content += `<polyline points="${line(forecast)}" fill="none" stroke="#cf7447" stroke-width="2.6" stroke-dasharray="6 5" stroke-linejoin="round"/>`;
  const labelIndexes=[...new Set([0,...Array.from({length:4},(_,i)=>Math.round((i+1)*(points.length-1)/5)),points.length-1])];
  for (const index of labelIndexes) {
    const date = new Date(points[index].date+"T12:00:00Z").toLocaleDateString("en-GB", {day:"numeric",month:"short",timeZone:"UTC"});
    content += `<text x="${x(index)}" y="${height-8}" text-anchor="middle" fill="#819177" font-family="Arial" font-size="10">${esc(date)}</text>`;
  }
  updateHTML("chart",`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${future.length ? "Recorded daily sales and a 14-day forecast" : "Recorded daily sales; forecast is not available for this product"}">${content}</svg>`);
  $("forecast-context").textContent = "Through " + end;
}

function render() {
  const meta = state.metadata;
  updateHTML("stream-list",(state.stream_events || []).slice(0,6).map(e => `<div class="transaction-row"><span class="event-icon">${icon(e.kind==="receipt" ? "stock" : "bill")}</span><span class="event-info"><strong>${esc(e.name)}</strong><small>${e.source==="simulated" ? "SIMULATED" : (e.source==="demo" || meta.mode==="demo") ? "DEMO" : e.kind==="receipt" ? "Stock received" : "Sale"} · ${esc(localTime(e.occurred_at,true))}${e.flagged ? " · ⚠ Check sale" : ""}</small></span><span class="event-qty">${e.kind==="receipt" ? "+" : ""}${number(e.quantity)} units</span></div>`).join("") || quiet("Ready for your first sale", "Saved sales and stock deliveries will appear here."));
  updateHTML("anomaly-list",(state.anomaly_alerts || []).slice(0,3).map(e => `<div class="review-row"><strong>${esc(e.name)} · ${number(e.quantity)} units</strong><small>${e.source==="simulated" ? "SIMULATED · " : ""}${esc(localTime(e.occurred_at,true))} · Unusual sale, check the quantity and price</small></div>`).join("") || quiet("No unusual sales flagged", "Alerts appear when the app flags a sale for review."));
  $("source-label").textContent = !meta.mode ? "NEW SHOP" : meta.mode === "demo" ? "DEMO DATA" : meta.mode === "live" ? "YOUR SHOP" : "HISTORICAL DATA";
  $("source-detail").textContent = !meta.mode ? "Start with your own shop details" : meta.mode === "demo" ? "Generated sample sales · Updated live" : meta.mode === "live" ? "Saved sales and live stock" : "Original transaction dates preserved";
  document.querySelector(".source-bar").classList.toggle("demo",meta.mode==="demo");
  $("date-label").textContent = new Date(state.business_date+"T12:00:00Z").toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"}) + " · " + (meta.timezone || "India time");
  const shopName=meta.shop_name || "Satya Shop";
  $("brand-name").textContent=shopName;
  $("shop-home").setAttribute("aria-label",shopName+" overview");
  document.title=viewDetails[activeView][1]+" · "+shopName;
  $("shop-avatar").textContent=(shopName.match(/\S+/g)||["RP"]).slice(0,2).map(word=>word[0]).join("").toUpperCase();
  $("shop-mode").textContent=(meta.mode==="demo" ? "Sample records" : state.desktop_mode ? "Desktop shop" : "Local shop")+" · v0.8.1";
  if(state.desktop_mode)$("install-app").classList.add("hidden");
  $("revenue").textContent = currency(state.summary.revenue_today_minor);
  $("revenue-note").textContent = "Sales " + currency(state.summary.gross_revenue_today_minor) + " · Refunds " + currency(state.summary.refund_today_minor);
  $("units").textContent = number(state.summary.units_today);
  $("units-note").textContent = number(state.summary.returned_units_today) + " units returned today";
  $("restock").textContent = state.forecast_current ? number(state.summary.restock_products) : "—";
  $("product-count").textContent = number(state.summary.products);
  $("footer-source").textContent = meta.source || "Your shop details come first.";
  const alerts = [];
  if (state.shop_setup_required) alerts.push("Set up your shop below to begin.");
  else if (state.setup_required) alerts.push("Your shop is ready. Open Products to add your first item and its counted stock.");
  if (state.training_error) alerts.push("Forecast update: " + state.training_error);
  $("alert").textContent = alerts.join(" ");
  $("alert").classList.toggle("hidden", !alerts.length);
  updateHTML("inventory-body",state.products.map(item => `<tr><td>${esc(item.name)}<small>${esc(item.sku)}</small></td><td>${item.stock_initialized ? number(item.stock) : "Not set"}</td><td>${number(item.next_7_days)}</td><td>${item.lead_days} days</td><td>${number(item.reorder_point)}</td><td>${number(item.suggested_order)}</td><td><span class="pill ${item.stock_status === "Restock" ? "warn" : item.stock_status === "Covered" ? "" : "neutral"}">${esc(item.stock_status)}</span></td></tr>`).join("") || '<tr><td colspan="7" class="table-empty">Add a product to begin tracking stock.</td></tr>');
  const evaluation = state.forecast?.evaluation;
  const methodDetail=state.forecast?.product_methods?.[$("chart-product").value];
  $("model-label").textContent = methodDetail ? methodDetail.method+(methodDetail.validated_comparison ? " · validated comparison" : methodDetail.early_estimate ? " · early estimate" : " · fast estimate") : state.forecast?.method || "Waiting for history";
  if (evaluation?.holdout_period) {
    const test = evaluation.holdout_period;
    $("evaluation-detail").textContent = `Separate 14-day test: ${test.from} to ${test.through}. These test scores did not choose the model.`;
    updateHTML("evaluation-body",Object.entries(evaluation.holdout_comparison).map(([method,score]) => `<tr><td>${esc(method)}${method === evaluation.selected_method ? '<span class="selected-method">selected</span>' : ""}</td><td>${number(score.mae)}</td><td>${score.wape_percent === null ? "Undefined" : number(score.wape_percent)+"%"}</td></tr>`).join(""));
  } else {
    $("evaluation-detail").textContent="At 28 days, comparison uses 7 validation days then 7 separate test days. Fast mode has a 7-day test from 14 days. Shorter histories have no measured accuracy yet.";
    const scores=Object.entries(state.forecast?.product_methods||{}).flatMap(([sku,detail])=>detail.comparison ? Object.entries(detail.comparison.holdout_comparison).map(([method,score])=>({sku,method,score,selected:method===detail.method})) : detail.holdout_score ? [{sku,method:detail.method,score:detail.holdout_score,selected:true}] : []);
    updateHTML("evaluation-body",scores.map(({sku,method,score,selected})=>`<tr><td>${esc(sku)} · ${esc(method)} (7-day test)${selected ? '<span class="selected-method">selected</span>' : ''}</td><td>${number(score.mae)}</td><td>${score.wape_percent===null ? "Undefined" : number(score.wape_percent)+"%"}</td></tr>`).join("") || '<tr><td colspan="3" class="table-empty">More recorded days are needed to measure forecast accuracy.</td></tr>');
  }
  updateHTML("activity-list",state.recent_events.slice(0,15).map(event => {
    const time = localTime(event.occurred_at,true);
    const label = event.kind === "receipt" ? "Stock receipt" : "Sale";
    const source = event.source === "live" ? "app event" : event.source;
    return `<div class="activity-row"><span class="event-icon">${event.kind === "receipt" ? "+" : "↗"}</span><span class="event-info"><strong>${esc(event.name)}</strong><small>${label} · ${esc(time)} · ${esc(source)}</small></span><span class="event-qty">${event.kind === "receipt" ? "+" : ""}${event.quantity} units</span></div>`;
  }).join("") || quiet("Nothing recorded yet", "Your saved sales and deliveries appear here."));
  populateSelects();
  renderChart();
  renderBills();
  renderCart();
  renderShop();
}

async function refresh() {
  if (inFlight) return;
  inFlight = true;
  try {
    state = await api("/api/state");
    render();
    if(!$("connection").classList.contains("connected")) $("connection").innerHTML='<span class="live-dot"></span> Connected';
    $("connection").classList.add("connected");
    $("login-panel").classList.add("hidden");
  } catch (error) {
    $("connection").textContent = "Connection interrupted";
    $("connection").classList.remove("connected");
    if (!$("login-panel").classList.contains("hidden")) $("login-message").textContent = error.message;
    else { $("alert").textContent = error.message; $("alert").classList.remove("hidden"); }
  } finally { inFlight = false; }
}

async function eventSubmit(name, route, payload, messageId) {
  return managedAction(route,{...payload,event_id:crypto.randomUUID()},messageId,name==="sale" ? "Sale" : "Stock delivery");
}

$("sale-form").addEventListener("submit", event => { event.preventDefault(); eventSubmit("sale", "/api/sales", {sku:$("sale-product").value,quantity:Number($("sale-quantity").value),unit_price:$("sale-price").value}, "sale-message"); });
$("receipt-form").addEventListener("submit", event => { event.preventDefault(); eventSubmit("receipt", "/api/receipts", {sku:$("receipt-product").value,quantity:Number($("receipt-quantity").value)}, "stock-message"); });
$("policy-form").addEventListener("submit", async event => {
  event.preventDefault();
  managedAction("/api/policy",{request_id:crypto.randomUUID(),sku:$("policy-product").value,lead_days:Number($("lead-days").value),buffer_units:Number($("buffer-units").value)},"stock-message","Restock policy");
});
$("sale-product").addEventListener("change", updatePrice);
$("policy-product").addEventListener("change", updatePolicy);
$("chart-product").addEventListener("change", renderChart);
$("train-button").addEventListener("click", async () => {
  $("train-button").disabled = true;
  try { await api("/api/train", {compare_models:$("forecast-method").value==="compare"}); await refresh(); } catch (error) { $("alert").textContent=error.message; $("alert").classList.remove("hidden"); $("train-button").disabled = false; }
});
$("login-form").addEventListener("submit", async event => {
  event.preventDefault(); token = $("access-token").value;
  sessionStorage.setItem("retailpulse_token", token);
  await refresh();
});
async function download(table) {
  try {
    const response = await fetch("/api/export?table="+table, {headers:token ? {Authorization:"Bearer "+token} : {}});
    if (!response.ok) throw new Error("Export failed. Check the project connection and access token.");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href=url; link.download=table+".csv"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  } catch (error) { $("alert").textContent=error.message; $("alert").classList.remove("hidden"); }
}
for (const [id,table] of [["export-inventory","inventory"],["export-daily","daily_sales"],["export-forecast","forecast"],["export-holdout","holdout"]]) $(id).addEventListener("click", () => download(table));



// Installable app shell. Live data and bills always come from the server.
if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});
let installPrompt = null;
window.addEventListener("beforeinstallprompt", event => {event.preventDefault();installPrompt=event;if(!state?.desktop_mode)$("install-app").classList.remove("hidden");});
$("install-app").addEventListener("click",async () => {if (!installPrompt) return;await installPrompt.prompt();const choice=await installPrompt.userChoice;$("install-message").textContent=choice.outcome === "accepted" ? "App installed. Keep your store server running." : "You can install later from your browser menu.";installPrompt=null;$("install-app").classList.add("hidden");});
window.addEventListener("appinstalled",()=>{$("install-app").classList.add("hidden");});

let cart = [], savedBill = null, checkoutBusy = false, checkoutPending = null;
try { checkoutPending = JSON.parse(sessionStorage.getItem("retailpulse_checkout") || "null"); } catch (_) {}
if (checkoutPending) {
  cart = checkoutPending.items.map(item => ({...item,name:item.sku}));
  $("bill-shop").value=checkoutPending.shop_name;
  $("bill-customer").value=checkoutPending.customer_name;
  $("bill-customer-phone").value=checkoutPending.customer_phone || "";
  showMessage("checkout-message","An earlier bill request needs confirmation. Click Create bill to retry the same request.");
}
function updateCartPrice() {const item=product("cart-product");if(item) $("cart-price").value=(item.price_minor/100).toFixed(2);}
function renderCart() {
  updateHTML("cart-body",cart.map((line,index)=>`<tr><td>${esc(line.name)}</td><td>${line.quantity}</td><td>${currency(Math.round(Number(line.unit_price)*100))}</td><td>${currency(Math.round(Number(line.unit_price)*100)*line.quantity)}</td><td><button class="secondary-button" type="button" data-remove="${index}" aria-label="Remove ${esc(line.name)} from bill" ${checkoutPending || checkoutBusy ? "disabled" : ""}>Remove</button></td></tr>`).join("") || '<tr><td colspan="5" class="table-empty">Your basket is empty. Choose a product and add it above.</td></tr>');
  const units=cart.reduce((total,line)=>total+line.quantity,0);
  $("cart-count").textContent=`${cart.length} ${cart.length===1 ? "product" : "products"}`;
  $("cart-summary-count").textContent=number(units);
  $("nav-cart-count").textContent=number(units);$("nav-cart-count").classList.toggle("hidden",!units);
  $("cart-total").textContent=currency(paymentQuote ? paymentQuote.pricing.total_minor : cart.reduce((total,line)=>total+Math.round(Number(line.unit_price)*100)*line.quantity,0));
  $("checkout-button").textContent=checkoutBusy ? "Saving bill…" : checkoutPending ? "Recover payment request" : "Prepare payment →";
  $("checkout-button").disabled=checkoutBusy || !cart.length || !state;
  for(const input of $("cart-form").elements) input.disabled=checkoutBusy || !!checkoutPending || !state;
  for(const id of ["bill-shop","bill-customer","bill-customer-phone","discount-type","discount-value","supply-type","payment-method"])$(id).disabled=checkoutBusy || !!checkoutPending || managedBusy || !!managedPending || !state || state.shop_setup_required;
}
$("cart-product").addEventListener("change",updateCartPrice);
$("cart-form").addEventListener("submit",event=>{
  event.preventDefault();if(checkoutBusy || checkoutPending)return;
  const item=product("cart-product");if(!item)return;
  const quantity=Number($("cart-quantity").value),unit_price=$("cart-price").value;
  const existing=cart.find(line=>line.sku===item.sku);
  if(existing && Number(existing.unit_price)!==Number(unit_price)){showMessage("checkout-message","Remove that product before adding it at a different price.",true);return;}
  if(existing)existing.quantity+=quantity;else cart.push({sku:item.sku,name:item.name,quantity,unit_price});
  renderCart();
});
$("cart-body").addEventListener("click",event=>{const button=event.target.closest("button[data-remove]");if(button && !checkoutPending && !checkoutBusy){cart.splice(Number(button.dataset.remove),1);renderCart();}});
let paymentQuote=null, paymentQrUrl=null;
function billingOptions(){return {discount_type:$("discount-type").value,discount_value:$("discount-value").value,supply_type:$("supply-type").value};}
function displaySavedBill(bill){
  savedBill=bill;checkoutPending=null;paymentQuote=null;sessionStorage.removeItem("retailpulse_checkout");cart=[];
  $("payment-panel").classList.add("hidden");$("bill-customer").value="";$("bill-customer-phone").value="";$("discount-value").value="0";
  $("bill-number").textContent="Bill "+bill.bill_id;$("bill-result").classList.remove("hidden");closeBillSharing();
  showMessage("checkout-message","Payment confirmed by you. Bill saved and stock updated.");
}
async function displayPayment(quote){
  paymentQuote=quote;$("payment-panel").classList.remove("hidden");$("bill-result").classList.add("hidden");$("payment-received").checked=false;
  const p=quote.pricing;
  $("payment-breakdown").textContent=`Subtotal ${currency(p.subtotal_minor,quote.currency)} · Discount ${currency(p.discount_minor,quote.currency)} · GST ${currency(p.tax_minor,quote.currency)}${p.gst_mode==="inclusive" ? " (included)" : ""}`;
  $("payment-amount").textContent="Pay "+currency(p.total_minor,quote.currency);
  $("cart-total").textContent=currency(p.total_minor,quote.currency);
  $("payment-payee").textContent=quote.payment_method==="upi" ? "UPI ID: "+new URL(quote.upi_uri).searchParams.get("pa") : "Collect cash from the customer.";
  $("payment-qr").classList.add("hidden");
  if(paymentQrUrl){URL.revokeObjectURL(paymentQrUrl);paymentQrUrl=null;}
  if(quote.payment_method==="upi"){
    const response=await fetch("/api/payment/qr",{method:"POST",headers:{"Content-Type":"application/json",...(token?{Authorization:"Bearer "+token}:{})},body:JSON.stringify({store_id:state.metadata.store_id,order_id:quote.order_id})});
    if(!response.ok)throw new Error("Cannot display the QR. Retry the same payment request.");
    paymentQrUrl=URL.createObjectURL(await response.blob());$("payment-qr").src=paymentQrUrl;$("payment-qr").classList.remove("hidden");
  }
  $("payment-panel").scrollIntoView({block:"nearest"});
}
$("checkout-button").addEventListener("click",async()=>{
  if(checkoutBusy || !cart.length || !state || managedPending || managedBusy)return;
  if(!checkoutPending){
    let phone;try{phone=whatsappNumber($("bill-customer-phone").value);}catch(error){showMessage("checkout-message",error.message,true);return;}
    checkoutPending={store_id:state.metadata.store_id,bill_id:crypto.randomUUID(),shop_name:$("bill-shop").value.trim(),customer_name:$("bill-customer").value.trim(),customer_phone:phone,items:cart.map(({sku,quantity,unit_price})=>({sku,quantity,unit_price})),billing_options:billingOptions(),payment_method:$("payment-method").value};
    sessionStorage.setItem("retailpulse_checkout",JSON.stringify(checkoutPending));
  }
  checkoutBusy=true;renderCart();
  try{
    if(!checkoutPending.payment_method){displaySavedBill(await api("/api/checkout",checkoutPending));await refresh();}
    else {
      // Recover a confirmation whose response was lost before displaying another QR.
      try{const bill=await api("/api/bills/"+encodeURIComponent(checkoutPending.bill_id));displaySavedBill(bill);await refresh();return;}catch(error){if(error.httpStatus!==404)throw error;}
      await displayPayment(await api("/api/payment/quote",checkoutPending));
      showMessage("checkout-message","Amount prepared. Check payment receipt before giving the bill.");
    }
  }catch(error){
    if(!paymentQuote && [400,409].includes(error.httpStatus) && error.code!=="STORE_MISMATCH"){checkoutPending=null;sessionStorage.removeItem("retailpulse_checkout");}
    showMessage("checkout-message",error.message,true);
  }finally{checkoutBusy=false;renderCart();}
});
$("payment-confirm").addEventListener("click",async()=>{
  if(checkoutBusy || !paymentQuote)return;
  if(!$("payment-received").checked){showMessage("payment-message","Check the payment arrived, then tick the confirmation box.",true);return;}
  checkoutBusy=true;$("payment-confirm").disabled=true;$("payment-cancel").disabled=true;renderCart();
  try{displaySavedBill(await api("/api/payment/confirm",{store_id:state.metadata.store_id,order_id:paymentQuote.order_id,received:true}));await refresh();}
  catch(error){showMessage("payment-message",error.message+" Do not collect payment again. Retry confirmation after resolving the issue.",true);}
  finally{checkoutBusy=false;$("payment-confirm").disabled=false;$("payment-cancel").disabled=false;renderCart();}
});
$("payment-cancel").addEventListener("click",async()=>{
  if(checkoutBusy || !paymentQuote)return;
  checkoutBusy=true;renderCart();
  try{await api("/api/payment/cancel",{store_id:state.metadata.store_id,order_id:paymentQuote.order_id});checkoutPending=null;paymentQuote=null;sessionStorage.removeItem("retailpulse_checkout");$("payment-panel").classList.add("hidden");showMessage("checkout-message","Payment request cancelled. No bill or sale was recorded.");}
  catch(error){showMessage("payment-message",error.message,true);}
  finally{checkoutBusy=false;renderCart();}
});
let billingSettingsKey="";
function renderBillingSettings(){
  if(!state)return;
  const config=state.metadata.billing||{}, key=JSON.stringify([config,state.products.map(p=>[p.sku,p.name])]);
  if(key===billingSettingsKey)return;billingSettingsKey=key;
  $("settings-upi").value=config.upi_id||"";$("settings-gst-mode").value=config.gst_mode||"off";$("settings-gstin").value=config.gstin||"";
  updateHTML("settings-rates",state.products.filter(p=>p.active).map(p=>`<label>${esc(p.name)} GST %<input data-gst-sku="${esc(p.sku)}" type="number" min="0" max="100" step="0.01" value="${esc(config.rates?.[p.sku]||"0")}"></label>`).join(""));
}
$("billing-settings-form").addEventListener("submit",async event=>{
  event.preventDefault();
  const rates={};for(const input of document.querySelectorAll("[data-gst-sku]"))rates[input.dataset.gstSku]=input.value;
  try{await api("/api/billing/settings",{store_id:state.metadata.store_id,upi_id:$("settings-upi").value,gstin:$("settings-gstin").value,gst_mode:$("settings-gst-mode").value,rates});showMessage("settings-message","Settings saved for future payments and bills.");await refresh();}
  catch(error){showMessage("settings-message",error.message,true);}
});

function renderBills(){
  renderBillingSettings();
  updateHTML("bill-history",(state?.recent_bills||[]).map(bill=>`<div class="bill-row"><span><strong>${esc(bill.customer_name||"Walk-in customer")}</strong><small>${bill.source==="demo" ? "DEMO · " : ""}${esc(bill.status.replaceAll("_"," "))} · ${esc(localTime(bill.created_at,true))}<br>Bill ${esc(bill.bill_id)}</small></span><span class="bill-amount">${currency(bill.net_total_minor,bill.currency)}</span><div class="bill-actions"><button class="secondary-button" type="button" data-manage-bill="${esc(bill.bill_id)}">View / return</button><button class="secondary-button" type="button" data-bill="${esc(bill.bill_id)}">PDF ↓</button><button class="whatsapp-button" type="button" data-share-bill="${esc(bill.bill_id)}">WhatsApp</button></div></div>`).join("") || quiet("Your first bill will appear here", "Create a bill above to save the purchase and its PDF."));
}
async function billPDF(billId,open=false,messageId="checkout-message"){
  const viewer=open ? window.open("", "_blank") : null;
  try{
    const response=await fetch("/api/bills/"+encodeURIComponent(billId)+".pdf",{headers:token?{Authorization:"Bearer "+token}:{}});
    if(!response.ok)throw new Error("Cannot download the bill. Check the connection and access token.");
    const url=URL.createObjectURL(await response.blob());
    if(viewer){viewer.location.href=url;setTimeout(()=>URL.revokeObjectURL(url),120000);}
    else{const link=document.createElement("a");link.href=url;link.download="Satya-Shop-"+billId+".pdf";link.click();setTimeout(()=>URL.revokeObjectURL(url),2000);if(open)showMessage("checkout-message","PDF downloaded. Open it and use Print.");}
  }catch(error){if(viewer)viewer.close();showMessage(messageId,error.message,true);}
}
$("bill-download").addEventListener("click",()=>{if(savedBill)billPDF(savedBill.bill_id);});
$("bill-print").addEventListener("click",()=>{if(savedBill)billPDF(savedBill.bill_id,true);});
$("bill-whatsapp").addEventListener("click",()=>{if(savedBill)beginBillSharing(savedBill.bill_id);});
$("bill-history").addEventListener("click",event=>{const button=event.target.closest("button[data-bill]");if(button)billPDF(button.dataset.bill);const share=event.target.closest("button[data-share-bill]");if(share)beginBillSharing(share.dataset.shareBill);const manage=event.target.closest("button[data-manage-bill]");if(manage){$("find-bill-id").value=manage.dataset.manageBill;navigate("returns");loadBill(manage.dataset.manageBill);}});

let sharingBill = null, shareGeneration = 0;
function billMessage(bill) {
  const amount=minor=>bill.currency+" "+(minor/100).toFixed(2);
  const lines=[...(bill.source==="demo" ? ["DEMO BILL — SAMPLE PURCHASE",""] : []),bill.shop_name,"Digital bill: "+bill.bill_id,"Date: "+bill.business_date,"Customer: "+(bill.customer_name || "Walk-in customer"),""];
  for(const item of bill.items){
    lines.push(item.product_name+" — "+item.quantity+" × "+amount(item.unit_price_minor)+" = "+amount(item.line_total_minor));
    if(item.returned_quantity)lines.push("  Returned: "+item.returned_quantity+" of "+item.quantity);
  }
  if(bill.pricing?.discount_minor)lines.push("Discount: "+amount(bill.pricing.discount_minor));
  if(bill.pricing?.gst_mode && bill.pricing.gst_mode!=="off")lines.push("GSTIN: "+bill.pricing.gstin,"GST: "+amount(bill.pricing.tax_minor));
  if(bill.payment)lines.push("Payment: "+bill.payment.method+" · receipt confirmed by shop");
  lines.push("","Original bill total: "+amount(bill.total_minor));
  if(bill.status!=="active")lines.push("Status: "+bill.status.replaceAll("_"," "),"Recorded refunds: "+amount(bill.refund_minor),"Total after refunds: "+amount(bill.net_total_minor));
  lines.push("","Thank you for shopping at "+bill.shop_name+".");
  return lines.join("\n");
}
function sharingBusy(busy) {
  for(const field of $("whatsapp-form").elements)field.disabled=busy || !sharingBill;
}
function closeBillSharing() {
  shareGeneration++;sharingBill=null;$("bill-share").classList.add("hidden");
}
async function beginBillSharing(id) {
  const generation=++shareGeneration, storeId=state.metadata.store_id;
  sharingBill=null;navigate("checkout");$("bill-share").classList.remove("hidden");
  $("whatsapp-bill").textContent="Loading bill "+id+"…";$("whatsapp-preview").textContent="";$("whatsapp-number").value="";
  showMessage("whatsapp-message","");sharingBusy(true);
  $("bill-share").scrollIntoView({block:"nearest"});
  try{
    const bill=await api("/api/bills/"+encodeURIComponent(id));
    if(generation!==shareGeneration || state.metadata.store_id!==storeId)return;
    sharingBill={bill,storeId};
    $("whatsapp-bill").textContent=bill.shop_name+" · Bill "+bill.bill_id;
    $("whatsapp-preview").textContent=billMessage(bill);
    $("whatsapp-number").value=bill.customer_phone ? "+"+bill.customer_phone : "";
    sharingBusy(false);$("whatsapp-number").focus({preventScroll:true});
  }catch(error){if(generation===shareGeneration)showMessage("whatsapp-message",error.message+" Close this panel and open sharing again to retry.",true);}
}
$("whatsapp-close").addEventListener("click",()=>{closeBillSharing();$("bill-whatsapp").focus({preventScroll:true});});
$("whatsapp-pdf").addEventListener("click",()=>{if(sharingBill)billPDF(sharingBill.bill.bill_id,false,"whatsapp-message");});
$("whatsapp-form").addEventListener("submit",async event=>{
  event.preventDefault();if(!sharingBill)return;
  let phone;
  try{phone=whatsappNumber($("whatsapp-number").value);if(!phone)throw new Error("Enter the customer’s WhatsApp number.");}
  catch(error){showMessage("whatsapp-message",error.message,true);$("whatsapp-number").focus();return;}
  const target=sharingBill, generation=shareGeneration;
  if(target.storeId!==state.metadata.store_id){closeBillSharing();return;}
  // Open during the click, then fetch the latest bill before leaving our app.
  const chat=window.open("","_blank");
  if(!chat){showMessage("whatsapp-message","Your browser blocked the new tab. Allow pop-ups for this shop and try again.",true);return;}
  chat.opener=null;
  sharingBusy(true);showMessage("whatsapp-message","Preparing your bill message…");
  try{
    const bill=await api("/api/bills/"+encodeURIComponent(target.bill.bill_id));
    if(generation!==shareGeneration || target.storeId!==state.metadata.store_id){chat.close();return;}
    sharingBill={bill,storeId:target.storeId};
    const message=billMessage(bill);$("whatsapp-preview").textContent=message;
    const url="https://wa.me/"+phone+"?text="+encodeURIComponent(message);
    chat.location.href=url;
    showMessage("whatsapp-message","Bill message prepared. Check the number and message in WhatsApp, then tap Send. To send the PDF too, download it and attach it in the chat.");
  }catch(error){chat.close();if(generation===shareGeneration)showMessage("whatsapp-message",error.message+" Try again when the shop is connected.",true);}
  finally{if(generation===shareGeneration)sharingBusy(false);}
});

function loadCount() {
  const item=product("count-product");
  countReference=item ? {sku:item.sku,stock:item.stock} : null;
  $("count-value").value=item ? item.stock : "";
  $("count-reference").textContent=item ? `Loaded stock: ${item.stock} units. A change made after this count was loaded will require you to check again.` : "Add a product to count its stock.";
}

function newProduct() {
  if(managedPending || managedBusy)return;
  productEditing=null;$("product-form").reset();$("product-sku").readOnly=false;
  $("opening-label").classList.remove("hidden");$("product-save").textContent="Add item";
  showMessage("product-message","");renderShop();$("product-editor").scrollIntoView({block:"nearest"});$("product-sku").focus({preventScroll:true});
}

function editProduct(sku) {
  if(managedPending || managedBusy)return;
  const item=state.products.find(p=>p.sku===sku);if(!item)return;
  productEditing={sku:item.sku,revision:item.revision};
  $("product-sku").value=item.sku;$("product-sku").readOnly=true;
  $("product-name").value=item.name;$("product-price").value=(item.price_minor/100).toFixed(2);
  $("product-lead").value=item.lead_days;$("product-buffer").value=item.buffer_units;
  $("product-active").checked=!!item.active;$("opening-label").classList.add("hidden");
  $("product-save").textContent="Save item changes";
  showMessage("product-message","Editing "+item.name+". Use Count and correct stock for a stock correction.");
  renderShop();$("product-editor").scrollIntoView({block:"nearest"});$("product-name").focus({preventScroll:true});
}

function renderShop() {
  if(!state)return;
  $("shop-setup").classList.toggle("hidden",!state.shop_setup_required);
  const name=state.metadata.shop_name || "Satya Shop", storedName=state.metadata.shop_name || "";
  if(!checkoutPending)$("bill-shop").value=name;
  if(shopNameReference?.storeId!==state.metadata.store_id || !shopNameDraft){
    $("shop-name").value=name;shopNameReference={storeId:state.metadata.store_id,name:storedName};shopNameDraft=false;
  }
  if(sharingBill && sharingBill.storeId!==state.metadata.store_id)closeBillSharing();
  renderProductList();
  $("product-editor-title").textContent=productEditing ? "Edit item details" : "Add a new item";
  $("product-editor-note").textContent=productEditing ? "Save a new name, price or availability. Item codes stay fixed." : "Give each item a unique code, such as SOAP01.";
  const blocked=!!managedPending || managedBusy || !!checkoutPending || checkoutBusy;
  for(const id of ["setup-form","shop-name-form","product-form","count-form","return-form"]){
    for(const field of $(id).elements)field.disabled=blocked || (id!=="setup-form" && state.shop_setup_required);
  }
  for(const id of ["sale-form","receipt-form","policy-form","cart-form"]){
    const noItems=["sale-form","cart-form"].includes(id) ? !state.products.some(p=>p.active) : !state.products.length;
    for(const field of $(id).elements)field.disabled=blocked || state.shop_setup_required || noItems;
  }
  $("checkout-button").disabled=blocked || !cart.length || state.shop_setup_required;
  $("product-opening").disabled=blocked || !!productEditing || state.shop_setup_required;
  $("new-product").disabled=blocked || state.shop_setup_required;
  $("return-save").disabled=blocked || !loadedBill || ["cancelled","returned"].includes(loadedBill.status);
  $("cancel-bill").disabled=$("return-save").disabled;
  for(const input of document.querySelectorAll("[data-return-line]")) input.disabled=blocked || Number(input.max)===0;
  $("pending-action").classList.toggle("hidden",!managedPending);
  $("retry-action").disabled=managedBusy;
  if(managedPending)$("pending-description").textContent=managedPending.label+". Request: "+(managedPending.payload.request_id || managedPending.payload.return_id || managedPending.payload.event_id)+ (managedPending.payload.store_id!==state.metadata.store_id ? ". Open the original shop database to retry." : ". Retry this same action to confirm its result.");
  updateHTML("return-history",(state.recent_returns||[]).map(r=>`<div class="bill-row"><span><strong>${r.kind==="cancellation" ? "Bill cancellation" : "Item return"}</strong><small>${esc(r.reason)} · ${r.restock ? "Added back to stock" : "Stock unchanged"}<br>Bill ${esc(r.bill_id)}</small></span><span class="bill-amount">${currency(r.refund_minor,r.currency)}</span><button class="secondary-button" type="button" data-return-pdf="${esc(r.return_id)}">Return PDF ↓</button></div>`).join("") || quiet("No returns recorded", "Saved returns and bill cancellations will appear here."));
  updateHTML("movement-history",(state.stock_movements||[]).map(m=>`<div class="activity-row movement-row"><strong>${esc(m.name)}</strong><span>${esc(m.kind)} · ${m.quantity_delta>=0 ? "+" : ""}${m.quantity_delta} units · Now: ${m.stock_after}</span><small>${esc(m.reason)} · ${esc(localTime(m.created_at,true))}</small></div>`).join("") || quiet("Your stock changes will appear here", "Opening stock, returns and counted corrections are saved with a reason."));
  const backup=state.backup_status || {};
  updateHTML("backup-history",(backup.files||[]).map(b=>`<div class="bill-row"><span><strong>${b.kind==="auto" ? "Automatic backup" : "Manual backup"}</strong><small>${esc(localTime(b.created_at,true))} · ${number(b.size_bytes/1024)} KB</small></span><button class="secondary-button" type="button" data-backup="${esc(b.filename)}">Download ZIP ↓</button></div>`).join("") || quiet("No backup available yet", "The first automatic copy is being prepared. You can also make one now."));
  if(backup.error)showMessage("backup-message","Backup failed: "+backup.error,true);
}

async function managedAction(route,payload,messageId,label) {
  if(managedPending || managedBusy || checkoutPending || checkoutBusy){showMessage(messageId,"Confirm the pending request before starting another action.",true);return;}
  managedPending={route,payload:{...payload,store_id:state.metadata.store_id},messageId,label};
  sessionStorage.setItem("retailpulse_action",JSON.stringify(managedPending));
  await retryManagedAction();
}

async function retryManagedAction() {
  if(!managedPending || managedBusy)return;
  managedBusy=true;renderShop();
  const action=managedPending;
  try {
    const result=await api(action.route,action.payload);
    managedPending=null;sessionStorage.removeItem("retailpulse_action");
    let message=result.duplicate ? "Your earlier action was already saved." : action.label+" saved.";
    if(result.stock!==undefined)message+=" Stock now: "+number(result.stock)+" units.";
    if(result.refund_minor!==undefined)message+=" Recorded refund: "+currency(result.refund_minor)+". Handle the actual payment separately.";
    showMessage(action.messageId,message);
    if(action.route.startsWith("/api/products")){productEditing=null;$("product-form").reset();$("product-sku").readOnly=false;$("opening-label").classList.remove("hidden");$("product-save").textContent="Add item";}
    if(action.route==="/api/shop/name"){shopNameDraft=false;shopNameReference=null;}
    await refresh();
    if(action.route==="/api/setup")navigate("products");
    if(action.route.startsWith("/api/products")){updatePrice();updateCartPrice();updatePolicy();}
    if(action.route==="/api/stock/adjust")loadCount();
    if(action.payload.bill_id)await loadBill(action.payload.bill_id);
  }catch(error){
    if((error.httpStatus===400 || error.httpStatus===409) && error.code!=="STORE_MISMATCH"){managedPending=null;sessionStorage.removeItem("retailpulse_action");}
    showMessage(action.messageId,error.message+(managedPending ? " Retry the saved request above to confirm it." : ""),true);
  }finally{managedBusy=false;renderShop();}
}

async function loadBill(id) {
  try {
    loadedBill=await api("/api/bills/"+encodeURIComponent(id));
    $("return-details").classList.remove("hidden");
    $("return-summary").textContent=`${loadedBill.customer_name||"Walk-in customer"} · ${loadedBill.status.replaceAll("_"," ")} · Original total ${currency(loadedBill.total_minor)} · Recorded refunds ${currency(loadedBill.refund_minor)} · Remaining ${currency(loadedBill.net_total_minor)}`;
    $("return-body").innerHTML=loadedBill.items.map(l=>`<tr><td>${esc(l.product_name)}<small>${esc(l.sku)}</small></td><td>${l.quantity}</td><td>${l.returned_quantity}</td><td><input aria-label="Return quantity for ${esc(l.product_name)}" data-return-line="${l.line_no}" type="number" min="0" max="${l.remaining_quantity}" step="1" value="0" required ${!l.remaining_quantity ? "disabled" : ""}></td></tr>`).join("");
    renderShop();
  }catch(error){loadedBill=null;$("return-details").classList.add("hidden");showMessage("return-message",error.message,true);}
}

$("setup-form").addEventListener("submit",event=>{event.preventDefault();managedAction("/api/setup",{request_id:crypto.randomUUID(),shop_name:$("setup-name").value,currency:$("setup-currency").value,timezone:$("setup-timezone").value},"setup-message","Shop setup");});
$("shop-name").addEventListener("input",()=>{shopNameDraft=true;});
$("shop-name-form").addEventListener("submit",event=>{
  event.preventDefault();if(!shopNameReference || !state)return;
  managedAction("/api/shop/name",{request_id:crypto.randomUUID(),shop_name:$("shop-name").value,expected_shop_name:shopNameReference.name},"shop-name-message","Shop name");
});
$("product-form").addEventListener("submit",event=>{
  event.preventDefault();
  const payload={request_id:crypto.randomUUID(),sku:$("product-sku").value,name:$("product-name").value,unit_price:$("product-price").value,lead_days:Number($("product-lead").value),buffer_units:Number($("product-buffer").value),active:$("product-active").checked};
  if(productEditing)payload.expected_revision=productEditing.revision;else payload.opening_stock=Number($("product-opening").value);
  managedAction(productEditing ? "/api/products/edit" : "/api/products",payload,"product-message",productEditing ? "Product changes" : "New product");
});
$("new-product").addEventListener("click",newProduct);
$("product-body").addEventListener("click",event=>{const button=event.target.closest("button[data-edit-product]");if(button)editProduct(button.dataset.editProduct);});
$("count-product").addEventListener("change",loadCount);
$("reload-count").addEventListener("click",async()=>{await refresh();loadCount();});
$("count-form").addEventListener("submit",event=>{
  event.preventDefault();if(!countReference)return;
  managedAction("/api/stock/adjust",{request_id:crypto.randomUUID(),sku:countReference.sku,counted_stock:Number($("count-value").value),expected_stock:countReference.stock,reason:$("count-reason").value},"count-message","Stock correction");
});
$("find-bill-form").addEventListener("submit",event=>{event.preventDefault();loadBill($("find-bill-id").value.trim());});
$("return-form").addEventListener("submit",event=>{
  event.preventDefault();if(!loadedBill)return;
  const items=[...document.querySelectorAll("[data-return-line]")].filter(input=>Number(input.value)>0).map(input=>({line_no:Number(input.dataset.returnLine),quantity:Number(input.value)}));
  if(!items.length){showMessage("return-message","Enter at least one return quantity.",true);return;}
  managedAction("/api/returns",{return_id:crypto.randomUUID(),bill_id:loadedBill.bill_id,reason:$("return-reason").value,restock:$("return-restock").checked,items},"return-message","Item return");
});
$("cancel-bill").addEventListener("click",()=>{
  if(!loadedBill)return;
  if(!$("return-reason").value.trim()){showMessage("return-message","Enter a reason before cancelling this bill.",true);$("return-reason").focus();return;}
  if(!window.confirm("Cancel the remaining bill for "+currency(loadedBill.net_total_minor)+"? "+($("return-restock").checked ? "The remaining items will be added back to stock." : "Stock will stay unchanged.")))return;
  managedAction("/api/bills/cancel",{return_id:crypto.randomUUID(),bill_id:loadedBill.bill_id,reason:$("return-reason").value,restock:$("return-restock").checked},"return-message","Bill cancellation");
});
$("retry-action").addEventListener("click",retryManagedAction);

async function downloadFile(path,filename,messageId) {
  try {
    const response=await fetch(path,{headers:token ? {Authorization:"Bearer "+token} : {}});
    if(!response.ok)throw new Error("Download failed. Check the connection and access token.");
    const url=URL.createObjectURL(await response.blob());const link=document.createElement("a");link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),5000);
  }catch(error){showMessage(messageId,error.message,true);}
}
$("return-history").addEventListener("click",event=>{const b=event.target.closest("button[data-return-pdf]");if(b)downloadFile("/api/returns/"+encodeURIComponent(b.dataset.returnPdf)+".pdf","RetailPulse-return-"+b.dataset.returnPdf+".pdf","return-message");});
$("backup-now").addEventListener("click",async()=>{
  $("backup-now").disabled=true;
  try {await api("/api/backups",{});showMessage("backup-message","Backup saved. Download a copy below.");await refresh();}
  catch(error){showMessage("backup-message",error.message,true);}
  finally{$("backup-now").disabled=false;}
});
$("backup-history").addEventListener("click",event=>{const b=event.target.closest("button[data-backup]");if(b)downloadFile("/api/backups/"+encodeURIComponent(b.dataset.backup),b.dataset.backup,"backup-message");});
for(const [id,table] of [["export-net","net_daily_sales"],["export-returns","returns"],["export-movements","stock_movements"]])$(id).addEventListener("click",()=>download(table));

for(const id of ["setup-form","shop-name-form","whatsapp-form","product-form","sale-form","receipt-form","policy-form","count-form","cart-form","return-form"]) {
  for(const field of $(id).elements)field.disabled=true;
}
$("new-product").disabled=true;$("train-button").disabled=true;
showView(window.location.hash.slice(1));
renderCart();
refresh();
setInterval(refresh,1000);
