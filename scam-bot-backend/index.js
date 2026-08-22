require('dotenv').config();
const express = require('express');
const line = require('@line/bot-sdk');
const axios = require('axios');

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

try {
    // ยิง API ไปหา Python AI Engine
    const response = await axios.post('http://127.0.0.1:8000/api/analyze', {
      message: userMessage
    });
    
    const analysisResult = response.data;
    console.log(`[AI Result]`, analysisResult);

    // เช็คผลลัพธ์จาก Python ว่าเป็นสแกมหรือไม่
    if (analysisResult.is_scam) {
      return client.replyMessage({
        replyToken: event.replyToken,
        messages: [
          {
            type: 'text',
            text: `⚠️ [ระบบเตือนภัย]\nระดับความเสี่ยง: ${analysisResult.risk_level}\nเหตุผล: ${analysisResult.reason}`
          }
        ]
      });
    }
    
    return Promise.resolve(null);

  } catch (error) {
    console.error('Error connecting to Python AI:', error.message);
    return Promise.resolve(null);
  }
}

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Webhook Server รันแล้วที่พอร์ต ${PORT}`);
});
