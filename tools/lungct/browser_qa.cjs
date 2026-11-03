// Run with the bundled Node runtime. Synthetic engineering QA only, never A04.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/STN/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs');const path=require('path');const assert=require('assert/strict');
(async()=>{
 const out=path.resolve('docs/lungct/evidence');const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:900}});const page=await context.newPage();
 const errors=[],external=[],steps=[],rejections=[];page.on('pageerror',e=>errors.push(e.message));
 page.on('response',async r=>{if(r.status()>=400)rejections.push({url:r.url(),status:r.status(),body:await r.text()});});
 page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 await page.route('**/*',route=>{if(new URL(route.request().url()).hostname!=='127.0.0.1'){external.push(route.request().url());return route.abort();}return route.continue();});
 try{
  await page.goto('http://127.0.0.1:8766');await page.waitForSelector('#projects');
  assert.match(await page.title(),/肺结节/);
  const project='QA-'+Date.now();await page.locator('#projectForm input[name=name]').fill(project);await page.locator('#projectForm input[name=operator]').fill('READER-01');await page.locator('#projectForm button').click();
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('项目已创建'));
  await page.locator('input[name=directory]').fill('D:\\STN02\\DMT\\data\\lungct-demo');await page.locator('input[name=source_code]').fill('SYNTHETIC');await page.locator('input[name=consent]').check();await page.locator('#importForm button').click();
  await page.getByRole('button',{name:'选择此序列'}).filter({visible:true}).first().waitFor();
  assert.equal(await page.locator('.seriesRow button:disabled').count(),1);
  await page.locator('.seriesRow button:enabled').first().click();await page.locator('#manualDraft:enabled').waitFor();await page.locator('#manualDraft').click();await page.locator('#addFinding:enabled').waitFor();steps.push('创建项目、导入薄层+定位像、确认有效序列、建立人工草稿');
  async function pixel(x,y){const p=await page.evaluate(async({x,y})=>{const {transform}=await import('/static/app.js');const t=transform(),r=document.querySelector('#axial').getBoundingClientRect();return {x:r.left+t.ox+x*t.sx,y:r.top+t.oy+y*t.sy};},{x,y});await page.mouse.click(p.x,p.y);}
  async function add(x,y){const count=await page.locator('.finding').count();await page.locator('#addFinding').click();await pixel(x,y);await page.waitForFunction(n=>document.querySelectorAll('.finding').length===n,count+1);}
  await add(20,28);await page.locator('#longAxis').click();await pixel(10,28);await pixel(30,28);await page.waitForFunction(()=>document.querySelector('.measurements')?.textContent.includes('10.0'));
  await page.locator('#shortAxis').click();await pixel(20,24);await pixel(20,32);await page.waitForFunction(()=>document.querySelector('.measurements')?.textContent.includes('6.0'));
  await page.locator('#side').selectOption('right');await page.getByRole('button',{name:'确认',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.finding.selected').textContent.includes('已确认'));steps.push('原片绘制10.0/6.0 mm径线、人工侧别和确认保存');
  await page.locator('#addFinding').click();
  await page.route('**/api/image?**',async route=>{await new Promise(r=>setTimeout(r,1000));await route.continue();});
  await page.locator('#nextSlice').click();await pixel(40,40);await page.waitForTimeout(1200);
  assert.equal(await page.locator('.finding').count(),1,'Never save against a new index while its image is loading');
  await page.unroute('**/api/image?**');await page.locator('#returnFinding').click();
  await page.waitForFunction(async()=>{const {state}=await import('/static/app.js');return !state.loading;});
  steps.push('慢速切片加载期间禁止在旧画面落点');
  const sourceIndex=await page.locator('#slice').inputValue();await page.locator('#nextSlice').click();await page.waitForFunction(i=>document.querySelector('#slice').value!==i,sourceIndex);await page.locator('#returnFinding').click();await page.waitForFunction(i=>document.querySelector('#slice').value===i,sourceIndex);
  await page.locator('#axial').hover();await page.keyboard.down('Control');await page.mouse.wheel(0,-120);await page.keyboard.up('Control');assert.match(await page.locator('.measurements').textContent(),/10.0.*6.0/);await page.locator('#resetView').click();
  await add(44,30);await page.locator('#browsed').check();await page.getByRole('button',{name:'完成复核',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('待复核'));
  await page.locator('#reason').selectOption('artifact');await page.getByRole('button',{name:'排除',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.finding.selected').textContent.includes('已排除'));
  await add(40,36);await page.locator('#reason').selectOption('insufficient_evidence');await page.getByRole('button',{name:'存疑',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.finding.selected').textContent.includes('存疑'));
  await add(24,36);await page.locator('#missingReason').selectOption('not_measured');await page.getByRole('button',{name:'确认',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.finding.selected').textContent.includes('已确认'));
  await page.locator('.finding').first().click();await page.waitForFunction(()=>document.querySelector('.finding.selected').textContent.includes('N-001'));
  await page.locator('#center').focus();await page.keyboard.press('ArrowDown');assert.match(await page.locator('.finding.selected').textContent(),/N-001/);await page.locator('#caseLabel').click();await page.keyboard.press('ArrowDown');await page.waitForFunction(()=>document.querySelector('.finding.selected').textContent.includes('N-002'));await page.locator('.finding').first().click();
  await page.waitForFunction(async()=>{const {state}=await import('/static/app.js');return state.image&&state.locator&&!state.loading&&state.imageIndex===state.index;});
  await page.locator('aside').evaluate(el=>el.scrollTop=0);await page.screenshot({path:path.join(out,'T06-synthetic-1440x900.png')});
  await page.setViewportSize({width:1280,height:800});await page.waitForFunction(()=>document.querySelector('#axial').width===document.querySelector('#axial').clientWidth);await page.screenshot({path:path.join(out,'T06-synthetic-1280x800.png')});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);steps.push('翻层/返回、缩放测量不变、待复核阻断、确认2/排除1/存疑1、键盘输入焦点保护、两尺寸截图');
  await page.locator('#startRun').click();await page.waitForFunction(()=>document.querySelector('#runStatus').textContent.includes('未配置检测模型'));steps.push('无模型提示与人工路径共存');
  await page.locator('#browsed').check();await page.getByRole('button',{name:'完成复核',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#completion').textContent.includes('快照已冻结'));
  await page.locator('#exportButton').click();await page.waitForFunction(()=>document.querySelector('#exportPanel').textContent.includes('纳入 1 次检查 / 2 个确认结节'));
  await page.getByRole('button',{name:'导出研究包到本机',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('导出成功'));
  await page.screenshot({path:path.join(out,'T06-synthetic-export.png')});const exported=await page.locator('#status').textContent();
  await page.locator('#lookupFinding').fill('N-001');await page.getByRole('button',{name:'回到原始切片',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('已定位至导出快照'));assert.match(await page.locator('.measurements').textContent(),/10.0.*6.0/);steps.push('完成快照、导出1检查2结节、按N-001回查原片及测量');
  await page.reload();await page.locator('#workstation:visible').waitFor();await page.waitForFunction(()=>document.querySelector('#completion').textContent.includes('快照已冻结'));steps.push('浏览器重开恢复项目及已完成复核记录');
  assert.equal(rejections.length,1);assert.equal(rejections[0].status,400);assert.match(JSON.parse(rejections[0].body).error,/待复核/);
  assert.equal(errors.length,1);assert.match(errors[0],/400/);assert.deepEqual(external,[]);
  fs.writeFileSync(path.join(out,'T06-browser.json'),JSON.stringify({status:'PASS',data:'SYNTHETIC ONLY; NOT A04',url:page.url(),viewports:[[1440,900],[1280,800]],egress:'non-loopback blocked',unexpected_errors:[],expected_negative_test:rejections,external,steps,exported},null,2));
  console.log(JSON.stringify({status:'PASS',steps,errors,external,exported}));
 }catch(e){await page.screenshot({path:path.join(out,'T06-browser-failure.png')});console.error(e);console.error({errors,steps});process.exitCode=1;}finally{await browser.close();}
})();
