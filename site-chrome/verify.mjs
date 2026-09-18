// Verify built sites through a real HTTP server and Chromium.
// Build each site first; see README.md. Set CHROME_EVIDENCE to save screenshots.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir, stat } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const family = path.dirname(workspace);
const { chromium, expect } = await import(path.join(family, 'archivebox-browser-extension/node_modules/@playwright/test/index.mjs'));
const mounts = {
  archivebox: path.join(workspace, 'archivebox/publicsite'),
  plugins: path.join(workspace, 'abx-plugins/docs'),
  packages: path.join(workspace, 'abxpkg/docs'),
  downloader: path.join(workspace, 'abx-dl/dist/site'),
  'archivebox-browser-extension': path.join(family, 'archivebox-browser-extension/docs/site/_site'),
  'ios-archivebox': path.join(family, 'ios-archivebox/docs/site/_site'),
  observatory: path.join(workspace, 'evals/site'),
  digest: path.join(family, 'DigestBox'),
  community: '/tmp/archivebox-chrome-preview/community',
  'good-karma-kit': '/tmp/archivebox-chrome-preview/good-karma-kit',
  debian: path.join(workspace, 'debian-archivebox/website'),
};
const types = {'.html':'text/html','.css':'text/css','.js':'text/javascript','.json':'application/json','.png':'image/png','.svg':'image/svg+xml'};
const server = createServer(async (req, res) => {
  try {
    const parts = decodeURIComponent(new URL(req.url,'http://localhost').pathname).split('/').filter(Boolean);
    const key=parts.shift(); let root=mounts[key];
    if(key==='archivebox' && parts[0]==='screenshots' && process.env.ARCHIVEBOX_GALLERY) {root=process.env.ARCHIVEBOX_GALLERY;parts.shift();}
    if(!root) throw Error('Unknown site');
    let file=path.resolve(root,parts.join('/'));
    if(!file.startsWith(root+path.sep) && file!==root) throw Error('Invalid path');
    if((await stat(file)).isDirectory()) file=path.join(file,'index.html');
    res.writeHead(200,{'content-type':types[path.extname(file)]||'application/octet-stream'});
    res.end(await readFile(file));
  } catch {res.writeHead(404);res.end('Not found');}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const evidence=process.env.CHROME_EVIDENCE||'/tmp/archivebox-chrome-preview/evidence';
await mkdir(evidence,{recursive:true});
const browser=await chromium.launch();
const report=[];
try {
  for(const key of Object.keys(mounts)) {
    const page=await browser.newPage();
    const errors=[];page.on('pageerror',err=>errors.push(err.message));
    for(const width of [1440,390]) {
      await page.setViewportSize({width,height:1000});
      await page.goto(`${origin}/${key}/`,{waitUntil:'domcontentloaded'});
      await expect(page.locator('.abx-header')).toHaveCount(1);
      await expect(page.locator('.abx-header')).toHaveCSS('display','flex');
      await expect(page.locator('.abx-footer')).toHaveCount(1);
      await expect(page.locator('.abx-footer-column')).toHaveCount(3);
      await expect(page.locator('.abx-header .abx-cta')).toBeVisible();
      await expect(page.locator('.abx-footer-column a.abx-source')).toHaveCount(20);
      const shared=await page.locator('.abx-footer-column a').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')));
      assert(shared.includes('https://swag.archivebox.io/'));
      assert(shared.includes('https://www.linkedin.com/company/archivebox/'));
      const menu=page.locator('.abx-apps');
      await menu.locator('summary').focus();await page.keyboard.press('Enter');
      await expect(menu).toHaveAttribute('open','');
      await expect(menu.locator('a').first()).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(menu).not.toHaveAttribute('open','');
      await menu.locator('summary').click();await page.locator('.abx-header .abx-brand').click({position:{x:8,y:8},trial:true});
      const headerBox=await page.locator('.abx-header').boundingBox();
      await page.mouse.click(headerBox.x+2,headerBox.y+5);
      await expect(menu).not.toHaveAttribute('open','');
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${key} overflows at ${width}px`);
      const footer=page.locator('.abx-footer');await footer.scrollIntoViewIfNeeded();
      await footer.screenshot({path:path.join(evidence,`${key}-footer-${width}.png`)});
      await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
      await page.screenshot({path:path.join(evidence,`${key}-header-${width}.png`)});
      if(['plugins','packages'].includes(key)) {
        await page.goto(`${origin}/${key}/#resources`);
        await expect(page.locator('#resources')).toBeVisible();
        assert(await page.locator('#resources').evaluate(el=>!!el.closest('details')?.open));
      }
    }
    assert.deepEqual(errors,[],`${key} JavaScript errors`);
    await page.close();
    const nojs=await browser.newContext({javaScriptEnabled:false,viewport:{width:390,height:900}});
    const plain=await nojs.newPage();await plain.goto(`${origin}/${key}/`,{waitUntil:'domcontentloaded'});
    await plain.locator('.abx-apps summary').click();
    await expect(plain.locator('.abx-app-links a').first()).toBeVisible();
    await expect(plain.locator('.abx-footer-column a').first()).toBeVisible();
    await nojs.close();report.push(key);
    console.log(`PASS ${key}: desktop/mobile, keyboard/dropdown, no-JS links, three columns`);
  }
  for(const [route,buttonKey,figureSelector,desktop,mobile] of [
    ...(process.env.ARCHIVEBOX_GALLERY ? [['archivebox/screenshots/','viewport','.shot','desktop','mobile']] : []),
    ['archivebox-browser-extension/screenshots/','profile','article.capture figure','desktop','mobile'],
    ['ios-archivebox/screenshots/','platform','.native-gallery figure','macos','all'],
  ]) {
    const page=await browser.newPage({viewport:{width:390,height:900}});
    await page.goto(`${origin}/${route}`,{waitUntil:'domcontentloaded'});
    await expect(page.locator('.abx-header')).toHaveCSS('display','flex');
    await expect(page.locator('.abx-footer-column')).toHaveCount(3);
    await expect(page.locator(`button[data-${buttonKey}="${desktop}"]`)).toHaveAttribute('aria-pressed','true');
    const before=await page.locator(figureSelector).evaluateAll(nodes=>nodes.map(n=>({id:n.id,text:n.textContent,link:n.querySelector('a').getAttribute('href')})));
    await page.locator(`button[data-${buttonKey}="${mobile}"]`).click();
    await expect(page.locator(`button[data-${buttonKey}="${mobile}"]`)).toHaveAttribute('aria-pressed','true');
    const after=await page.locator(figureSelector).evaluateAll(nodes=>nodes.map(n=>({id:n.id,text:n.textContent,link:n.querySelector('a').getAttribute('href')})));
    assert.deepEqual(after,before,`${route} lost screenshot details`);
    if(buttonKey==='platform') {
      const id=before[0].id;await page.goto(`${origin}/${route}#${id}`);
      await expect(page.locator(`[id="${id}"]`)).toBeVisible();
      await expect(page.locator(`button[data-platform="${desktop}"]`)).toHaveAttribute('aria-pressed','true');
    }
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${route} overflow`);
    await page.close();console.log(`PASS ${route}: shared chrome, device switching, screenshot details`);
  }
  // No existing static anchor disappears from edited source templates.
  for(const [repo,file] of [
    ['archivebox','publicsite/index.html'],['abx-plugins','docs/index.html.j2'],['abxpkg','docs/index.html.j2'],
    ['abx-dl','website/index.html'],['.','evals/site/index.html'],
    ['../ios-archivebox','docs/site/_layouts/default.html'],['../DigestBox','index.html'],
  ]) {
    const root=path.resolve(workspace,repo);
    const before=execFileSync('git',['show',`HEAD:${file}`],{cwd:root,encoding:'utf8'});
    const after=await readFile(path.join(root,file),'utf8');
    for(const [,id] of before.matchAll(/\bid="([^"]+)"/g)) assert(after.includes(`id="${id}"`),`${repo}: lost anchor ${id}`);
  }
  console.log(`Verified ${report.length} sites and preserved existing source anchors. Evidence: ${evidence}`);
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
