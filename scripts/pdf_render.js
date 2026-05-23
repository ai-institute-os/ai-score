#!/usr/bin/env node
/**
 * Renders HTML to PDF using Puppeteer.
 * Reads HTML from stdin, writes PDF bytes to stdout.
 * Usage: echo "<html>..." | node scripts/pdf_render.js
 */
const puppeteer = require("puppeteer");

async function main() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const html = Buffer.concat(chunks).toString("utf8");

  const browser = await puppeteer.launch({
    headless: true,
    // Use system Chromium if configured (avoids bundled-Chromium download in Docker)
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--no-first-run",
      "--no-zygote",
      "--single-process",
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setContent(html, { waitUntil: "domcontentloaded" });

    const pdfBuffer = await page.pdf({
      format: "A4",
      printBackground: true,
      margin: { top: "0", right: "0", bottom: "0", left: "0" },
    });

    process.stdout.write(pdfBuffer);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  process.stderr.write(`pdf_render error: ${err.message}\n`);
  process.exit(1);
});
