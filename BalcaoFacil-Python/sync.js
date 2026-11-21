/* Balcão Fácil – camada de sincronização: troca o LocalStorage por banco no servidor, sem alterar o app */
(function(){"use strict";
var S=Storage.prototype,raw=S.setItem,mute=false,snap={},sent={},Q,tm,CID=Math.random().toString(36).slice(2),ME={};
function rst(){Q={up:{},ds:{},del:[],h:{},c:null,s:null,e:null}}rst();
function note(m,t){if(window.showToast)window.showToast(m,t);else console.log(m)}
function mk(p){var r={},k;for(k in p)if(k!="stockPhysical"&&k!="stockReserved")r[k]=p[k];return{j:JSON.stringify(r),s:[+p.stockPhysical||0,+p.stockReserved||0]}}
function adopt(st){mute=true;try{
  ["products","clients","sellers","history","empresa"].forEach(function(k){if(st[k])raw.call(localStorage,"sgmei_"+k,JSON.stringify(st[k]))});
  snap={};(st.products||[]).forEach(function(p){snap[p.id]=mk(p)});
  sent={};(st.history||[]).forEach(function(h){sent[h.id]=JSON.stringify(h)});
  sent.c=st.clients?JSON.stringify(st.clients):null;sent.s=st.sellers?JSON.stringify(st.sellers):null;sent.e=st.empresa?JSON.stringify(st.empresa):null}finally{mute=false}}
/* carga inicial síncrona: o app já nasce com os dados do servidor */
var x=new XMLHttpRequest();x.open("GET","/api/state",false);x.send();
if(x.status==401){location.href="/login";throw new Error("auth")}
var st0=JSON.parse(x.responseText);ME=st0.user;window.SGMEI_USER=ME;adopt(st0);

function dp(l){var ids={};l.forEach(function(p){ids[p.id]=1;var n=mk(p),o=snap[p.id];
  if(!o)Q.up[p.id]=p;
  else{if(o.j!=n.j||Q.up[p.id])Q.up[p.id]=p;var a=n.s[0]-o.s[0],b=n.s[1]-o.s[1];if(a||b){var d=Q.ds[p.id]||[0,0];Q.ds[p.id]=[d[0]+a,d[1]+b]}}
  snap[p.id]=n});
  Object.keys(snap).forEach(function(id){if(!ids[id]){Q.del.push(id);delete snap[id];delete Q.up[id];delete Q.ds[id]}})}
S.setItem=function(k,v){raw.call(this,k,v);if(mute||this!==localStorage)return;
  try{
    if(k=="sgmei_products")dp(JSON.parse(v));
    else if(k=="sgmei_history")JSON.parse(v).forEach(function(h){var j=JSON.stringify(h);if(sent[h.id]!==j){sent[h.id]=j;Q.h[h.id]=h}});
    else if(k=="sgmei_clients"){if(sent.c!==v){sent.c=v;Q.c=JSON.parse(v)}}
    else if(k=="sgmei_sellers"){if(sent.s!==v){sent.s=v;Q.s=JSON.parse(v)}}
    else if(k=="sgmei_empresa"){if(sent.e!==v){sent.e=v;Q.e=JSON.parse(v)}}
    else return;
    clearTimeout(tm);tm=setTimeout(flush,60)}catch(e){console.log(e)}};
function flush(){var b=Q;rst();
  var body={upsert:Object.keys(b.up).map(function(k){return b.up[k]}),dstock:b.ds,del:b.del,history:Object.keys(b.h).map(function(k){return b.h[k]})};
  if(b.c)body.clients=b.c;if(b.s)body.sellers=b.s;if(b.e)body.empresa=b.e;
  fetch("/api/sync",{method:"POST",headers:{"Content-Type":"application/json","X-CID":CID},body:JSON.stringify(body)})
   .then(function(r){if(r.status==401){location.href="/login";return}if(!r.ok)return r.json().then(function(e){note(e.error||"Alteração não permitida.","error");refresh()},function(){throw 0})})
   .catch(function(){note("Falha ao gravar no servidor. Verifique a rede e o servidor.","error")})}

/* tempo real: outro caixa alterou algo -> recarrega o estado */
function val(id){var e=document.getElementById(id);return e?e.value:""}
function reload(){try{var c=val("pdv-cliente"),v=val("pdv-vendedor");loadStorage();renderSelectOptions();
  document.getElementById("pdv-cliente").value=c;document.getElementById("pdv-vendedor").value=v;
  renderCart();renderProductsTable();renderClientsTable();renderSellersTable();renderHistoryTable();if(window.syncEmpresaUI)syncEmpresaUI();if(window.sgmeiAfterReload)sgmeiAfterReload()}catch(e){console.log(e)}}
function refresh(){fetch("/api/state").then(function(r){if(r.status==401){location.href="/login";throw 0}return r.json()}).then(function(s){adopt(s);reload()}).catch(function(){})}
window.sgmeiRefresh=refresh;window.SGMEI_CID=CID;
var es=new EventSource("/api/events"),first=true;
es.onmessage=function(e){var m=JSON.parse(e.data);if(m.cid===CID)return;if(m.docs){if(window.sgmeiDocs)window.sgmeiDocs(m.docs);return}refresh();note("Atualizado por "+m.by,"info")};
es.onopen=function(){if(!first)refresh();first=false};

document.addEventListener("DOMContentLoaded",function(){
  window.resetSystemData=function(){alert("No modo servidor, o reset é feito pelo administrador: pare o servidor e apague a pasta data/.")};
  if(!(ME.caps||{}).admin)document.querySelectorAll(".emp-field").forEach(function(e){e.disabled=true;e.title="Apenas o administrador altera os dados da empresa"});
  var c=ME.caps||{},css=[];
  if(!c.stock)css.push('button[onclick^="openProductModal"],button[onclick^="editProduct"],button[onclick^="deleteProduct"],button[onclick^="openSellerModal"],button[onclick^="editSeller"],button[onclick^="deleteSeller"],[data-nfe]');
  if(!c.sell)css.push('button[onclick="processTransaction(\'VENDA\')"]');
  if(!c.quote)css.push('button[onclick="processTransaction(\'ORCAMENTO\')"]');
  if(css.length){var st=document.createElement("style");st.textContent=css.join(",")+"{display:none!important}";document.head.appendChild(st)}
  var d=document.createElement("div");d.className="print:hidden";
  d.style.cssText="position:fixed;left:8px;bottom:8px;z-index:60;background:#0f172a;color:#e2e8f0;font:12px system-ui;padding:6px 10px;border-radius:8px;opacity:.92";
  d.appendChild(document.createTextNode(ME.name+" ("+(ME.roles||[]).join(", ")+") · "));
  var o=document.createElement("a");o.href="#";o.textContent="Sair";o.style.color="#fca5a5";
  o.onclick=function(e){e.preventDefault();fetch("/api/logout",{method:"POST"}).then(function(){location.href="/login"})};
  d.appendChild(o);document.body.appendChild(d)});
})();
