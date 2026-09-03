const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const base = 'http://127.0.0.1:5011';
const out = path.resolve('docs/screenshots');
fs.mkdirSync(out, { recursive: true });
async function shot(page, name) { await page.setViewportSize({ width: 1280, height: 720 }); await page.waitForTimeout(700); await page.screenshot({ path: path.join(out, name), fullPage: false }); }
async function main() {
 const browser = await chromium.launch({ headless: true });
 const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, acceptDownloads: true });
 page.setDefaultTimeout(10000);
 await page.goto(base + '/auth/login', { waitUntil: 'networkidle' }); await shot(page, '01-login-page.png');
 await page.fill('input[name="work_id"]', '03107').catch(()=>{}); await page.fill('input[name="password"]', '********').catch(()=>{}); await shot(page, '02-login-filled.png');
 await page.goto(base + '/', { waitUntil: 'networkidle' }); await shot(page, '03-home-function-entry.png');
 await page.goto(base + '/workspace/pdf-overlay', { waitUntil: 'networkidle' }); await shot(page, '04-pdf-overlay-upload.png');
 await page.setInputFiles('input[type="file"]', path.resolve('docs/manual_samples/internal_regulation_sample.pdf')); await shot(page, '05-pdf-overlay-file-selected.png');
 await page.goto(base + '/workspace/pdf-doc', { waitUntil: 'networkidle' }); await shot(page, '06-pdf-rebuild-upload.png');
 await page.setInputFiles('input[type="file"]', path.resolve('docs/manual_samples/internal_regulation_sample.pdf')); await shot(page, '07-pdf-rebuild-file-selected.png');
 await page.goto(base + '/workspace/word', { waitUntil: 'networkidle' }); await shot(page, '08-word-upload-with-job.png');
 await page.setInputFiles('input[type="file"]', path.resolve('docs/manual_samples/internal_notice_sample.docx')); await shot(page, '09-word-file-selected.png');
 await page.locator('#wordJobsSearch').fill('內部通知'); await shot(page, '10-word-job-filtered.png');
 await page.goto(base + '/job/11111111111111111111111111111111', { waitUntil: 'networkidle' }); await shot(page, '11-editor-review-results.png');
 await page.locator('[data-sidebar-target="sidebarToolsSection"]').click(); await shot(page, '12-editor-tools.png');
 await page.locator('#addBox').click(); await shot(page, '13-editor-add-textbox.png');
 await page.locator('#saveBtn').click(); await page.waitForTimeout(1200); await shot(page, '14-editor-save-result.png');
 await page.locator('#menuBtn').click(); await shot(page, '15-editor-more-menu.png');
 await page.locator('#batchRestoreBtn').click(); await page.waitForTimeout(500); await shot(page, '16-editor-restore-confirm.png');
 await page.keyboard.press('Escape').catch(()=>{});
 await page.goto(base + '/workspace/pdf-overlay', { waitUntil: 'networkidle' }); await page.locator('#jobsSearch').fill('內部法規').catch(()=>{}); await shot(page, '17-pdf-job-list-completed.png');
 await browser.close();
}
main().catch(e => { console.error(e); process.exit(1); });
