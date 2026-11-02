// 기관 홈페이지에서 공지·공모 게시판 후보를 찾는 브라우저용 도우미 (설정 작업용)
(async()=>{const W=/(공지|공모|모집|공고|새소식|알림|지원사업)/,X=/결과|채용|입찰|FAQ|자주|정보공개|감사|계약/;
const cand=new Map();
const grab=(doc,base)=>{for(const a of doc.querySelectorAll('a')){const t=a.textContent.replace(/\s+/g,' ').trim();if(!t||t.length>16||!W.test(t)||X.test(t))continue;let u=a.getAttribute('href')||'';const oc=(a.getAttribute('onclick')||'')+' '+u;const m=oc.match(/['"](\/[^'"]+|https?:[^'"]+|[\w./-]+\.(?:php|do|jsp|asp|aspx|html)[^'"]*)['"]/);if((!u||u.startsWith('#')||/^javascript/i.test(u))&&m)u=m[1];if(!u||u.startsWith('#')||/^javascript/i.test(u)||/\.(pdf|hwp|jpg|png)/i.test(u))continue;try{u=new URL(u,base).href}catch(e){continue}if(new URL(u).hostname.replace(/^www\./,'')!==location.hostname.replace(/^www\./,''))continue;if(!cand.has(u))cand.set(u,t)}};
grab(document,location.href);
const res=[];for(const [u,t] of [...cand].slice(0,6)){try{const h=await (await fetch(u,{credentials:'omit'})).text();const d=new DOMParser().parseFromString(h,'text/html');
 const posts=[...d.querySelectorAll('a')].map(a=>({t:a.textContent.replace(/\s+/g,' ').trim(),h:a.getAttribute('href')||'',o:a.getAttribute('onclick')||''})).filter(x=>x.t.length>=8&&x.t.length<120&&/\d{3,}|[?&](idx|seq|no|id|num|nttId|wr_id|uid|bbsIdx|idx_no)=/i.test(x.h+' '+x.o));
 res.push({t,u,n:posts.length,ex:posts.slice(0,2).map(p=>p.t.slice(0,30)+' => '+(p.h.startsWith('javascript')||!p.h?p.o.slice(0,60):p.h.slice(0,90)))})}catch(e){res.push({t,u,err:String(e).slice(0,40)})}}
return JSON.stringify([location.href,res.sort((a,b)=>(b.n||0)-(a.n||0)).slice(0,3)]).replace(/\?/g,' QQ ').replace(/&/g,' AA ').replace(/=/g,' EQ ');})()
