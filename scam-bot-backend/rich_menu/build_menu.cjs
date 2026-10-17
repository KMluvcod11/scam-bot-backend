// เครื่องมือส่งออกภาพเท่านั้น; บอตใช้งาน menu.png โดยไม่ต้องติดตั้ง Sharp
const fs = require('node:fs');
const path = require('node:path');
const sharp = require('sharp');

async function main() {
  const assetDirectory = process.argv[2];
  if (!assetDirectory) throw new Error('Usage: node build_menu.cjs <mascot asset directory>');
  const mascot = (name) => `data:image/png;base64,${fs.readFileSync(path.join(assetDirectory, `${name}.png`)).toString('base64')}`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="2500" height="843" viewBox="0 0 2500 843">
  <defs>
    <linearGradient id="pink" x2="1" y2="1"><stop stop-color="#fff4f9"/><stop offset="1" stop-color="#ffdfed"/></linearGradient>
    <linearGradient id="mint" x2="1" y2="1"><stop stop-color="#f0fff9"/><stop offset="1" stop-color="#cef7e9"/></linearGradient>
    <linearGradient id="cream" x2="1" y2="1"><stop stop-color="#fffdf5"/><stop offset="1" stop-color="#fff0d8"/></linearGradient>
  </defs>
  <rect width="2500" height="843" fill="#fff9fc"/>
  <g stroke-width="4">
    <rect x="24" y="24" width="960" height="795" rx="55" fill="url(#pink)" stroke="#f9c7db"/>
    <rect x="1012" y="24" width="712" height="795" rx="55" fill="url(#mint)" stroke="#bcebdd"/>
    <rect x="1752" y="24" width="724" height="795" rx="55" fill="url(#cream)" stroke="#f1dfbe"/>
  </g>
  <g font-family="Tahoma, sans-serif" text-anchor="middle" fill="#371735">
    <text x="504" y="122" font-size="55" font-weight="bold"><tspan fill="#f72b80">Eh?</tspan>Bot</text>
    <circle cx="504" cy="322" r="166" fill="#fffdf3"/>
    <image href="${mascot('inspect')}" x="350" y="167" width="308" height="308"/>
    <text x="504" y="607" font-size="112" font-weight="bold">ตรวจข้อความ</text>
    <text x="504" y="707" font-size="53" fill="#79566d">เริ่มเช็กข้อความที่สงสัย</text>
    <circle cx="1368" cy="304" r="167" fill="#ffffff" fill-opacity=".8"/>
    <image href="${mascot('book')}" x="1215" y="153" width="306" height="306"/>
    <text x="1368" y="607" font-size="96" font-weight="bold">เรียนรู้กลโกง</text>
    <text x="1368" y="707" font-size="49" fill="#40756b">เอ๊ะให้ทัน ก่อนเชื่อ</text>
    <circle cx="2114" cy="304" r="167" fill="#ffffff" fill-opacity=".8"/>
    <image href="${mascot('guide')}" x="1961" y="153" width="306" height="306"/>
    <text x="2114" y="607" font-size="104" font-weight="bold">วิธีใช้งาน</text>
    <text x="2114" y="707" font-size="49" fill="#8b6c47">เช็กง่ายใน 3 ขั้น</text>
  </g>
  </svg>`;
  fs.writeFileSync(path.join(__dirname, 'menu.svg'), svg);
  await sharp(Buffer.from(svg)).png({ compressionLevel: 9 }).toFile(path.join(__dirname, 'menu.png'));
  const preview = await sharp(path.join(__dirname, 'menu.png')).resize(1000).toBuffer();
  fs.writeFileSync(path.join(__dirname, 'preview.png'), preview);
  console.log('Created menu.svg, menu.png (2500x843), preview.png (1000px wide)');
}

main().catch(() => { console.error('Unable to build image; check mascot directory and Sharp installation.'); process.exitCode = 1; });
