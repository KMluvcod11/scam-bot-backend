require('dotenv').config();
const express = require('express');
const line = require('@line/bot-sdk');

const app = express();

// ตั้งค่า LINE Config
const lineConfig = {
  channelSecret: process.env.CHANNEL_SECRET
};

const client = new line.messagingApi.MessagingApiClient({
  channelAccessToken: process.env.CHANNEL_ACCESS_TOKEN,
});

// สร้าง Endpoint สำหรับรับ Webhook จาก LINE
app.post('/webhook', line.middleware(lineConfig), (req, res) => {
  Promise
    .all(req.body.events.map(handleEvent))
    .then((result) => res.json(result))
    .catch((err) => {
      console.error('Webhook Error:', err);
      res.status(500).end();
    });
});

// ฟังก์ชันประมวลผลเมื่อมีคนพิมพ์แชท
async function handleEvent(event) {
  // กรองให้บอทอ่านเฉพาะข้อความประเภท Text
  if (event.type !== 'message' || event.message.type !== 'text') {
    return Promise.resolve(null);
  }

  const userMessage = event.message.text;
  console.log(`[LOG] ข้อความเข้า: ${userMessage}`);

  // TODO: จุดนี้คือที่ที่เราจะเอาข้อความไปเช็คกับ Dataset หรือส่งให้ LLM วิเคราะห์
  // สมมติว่าเจอคำว่า "คลิกเลย" ให้ลองแจ้งเตือนดูก่อน
  if (userMessage.includes('คลิกเลย')) {
    return client.replyMessage({
      replyToken: event.replyToken,
      messages: [
        {
          type: 'text',
          text: '⚠️ [ระบบเตือนภัย] ระวัง! ข้อความนี้อาจเป็นลิงก์อันตราย'
        }
      ]
    });
  }

  return Promise.resolve(null); // ถ้าเป็นข้อความปกติ ให้บอทเงียบไว้
}

// TODO: อนาคตสามารถเพิ่ม API เส้นอื่นๆ ให้นนท์และหยกเรียกใช้ที่นี่ได้ เช่น app.get('/api/stats', ...)

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Webhook Server รันแล้วที่พอร์ต ${PORT}`);
});
