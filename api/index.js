const https = require('https');
const http = require('http');

// TV Knowledge Base
const TV_KNOWLEDGE = {
  sizes: [
    { size: 55, distance: '1.5-2.0m', room: '卧室/小客厅' },
    { size: 65, distance: '2.0-2.5m', room: '客厅' },
    { size: 75, distance: '2.5-3.0m', room: '大客厅' },
    { size: 85, distance: '3.0-3.5m', room: '大客厅/影音室' },
    { size: 98, distance: '3.5m+', room: '别墅/影音室' }
  ],
  panels: {
    'LCD': { pros: ['价格实惠', '亮度高', '寿命长'], cons: ['对比度一般', '可视角度有限'], best: '预算有限、明亮客厅' },
    'OLED': { pros: ['无限对比度', '响应极快', '可视角度广'], cons: ['价格高', '亮度较低', '烧屏风险'], best: '影音发烧友、暗室观影' },
    'MiniLED': { pros: ['高亮度', '高对比度', '无烧屏风险'], cons: ['价格较高', '光晕现象'], best: '追求画质的主流用户' },
    'QLED': { pros: ['色彩鲜艳', '亮度高', '寿命长'], cons: ['对比度不如OLED'], best: '明亮环境、体育赛事' }
  },
  budgets: [
    { range: '2000-4000', tier: '入门', sizes: [55, 65], features: ['4K', 'HDR10', '60Hz'] },
    { range: '4000-8000', tier: '中端', sizes: [65, 75], features: ['4K', '杜比视界', '120Hz', 'MEMC'] },
    { range: '8000-15000', tier: '中高端', sizes: [75, 85], features: ['MiniLED/OLED', '144Hz', 'HDMI2.1', '全阵列背光'] },
    { range: '15000+', tier: '旗舰', sizes: [85, 98], features: ['OLED/MicroLED', '144Hz+', 'AI画质芯片', '杜比全景声'] }
  ],
  useCases: {
    '观影': { priority: ['画质', '对比度', 'HDR', '音效'], rec: 'OLED或MiniLED，支持杜比视界' },
    '游戏': { priority: ['低延迟', '高刷', 'HDMI2.1', 'VRR'], rec: '120Hz以上，HDMI2.1接口，输入延迟<20ms' },
    '体育': { priority: ['MEMC', '亮度', '可视角度'], rec: 'MiniLED/QLED，MEMC运动补偿' },
    '儿童': { priority: ['护眼', '低蓝光', '内容管控'], rec: '低蓝光认证，家长控制功能' },
    '老人': { priority: ['操作简单', '大字体', '远场语音'], rec: '简洁系统，远场语音控制' }
  }
};

function callLLM(messages) {
  return new Promise((resolve) => {
    const apiKey = process.env.AI_API_KEY;
    if (!apiKey) { resolve(null); return; }
    const baseUrl = process.env.AI_BASE_URL || 'https://api.openai.com/v1';
    const model = process.env.AI_MODEL || 'gpt-4o-mini';
    const url = new URL(baseUrl.replace(/\/$/, '') + '/chat/completions');
    const data = JSON.stringify({ model, messages, temperature: 0.7, max_tokens: 1000 });
    const req = https.request({
      hostname: url.hostname, port: 443, path: url.pathname, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` }
    }, (res) => {
      let body = '';
      res.on('data', (c) => body += c);
      res.on('end', () => {
        try { const j = JSON.parse(body); resolve(j.choices?.[0]?.message?.content || null); }
        catch { resolve(null); }
      });
    });
    req.on('error', () => resolve(null));
    req.write(data); req.end();
  });
}

function analyzeRequirement(text) {
  const sizeMatch = text.match(/(\d{2})\s*[寸吋英寸]/);
  const budgetMatch = text.match(/(\d{3,5})\s*(?:块|元|预算|以内|以下)/);
  const useCases = [];
  if (/电影|观影|追剧|Netflix|奈飞/.test(text)) useCases.push('观影');
  if (/游戏|PS|Xbox|Switch|主机/.test(text)) useCases.push('游戏');
  if (/体育|球赛|足球|篮球|运动/.test(text)) useCases.push('体育');
  if (/孩子|儿童|小孩/.test(text)) useCases.push('儿童');
  if (/老人|父母|爸妈/.test(text)) useCases.push('老人');
  const panels = [];
  if (/OLED/.test(text)) panels.push('OLED');
  if (/Mini\s*LED|MiniLED/.test(text)) panels.push('MiniLED');
  if (/QLED/.test(text)) panels.push('QLED');
  return {
    size: sizeMatch ? parseInt(sizeMatch[1]) : null,
    budget: budgetMatch ? parseInt(budgetMatch[1]) : null,
    useCases,
    panels,
    rawText: text
  };
}

function matchBudget(budget) {
  if (!budget) return TV_KNOWLEDGE.budgets[1];
  for (const b of TV_KNOWLEDGE.budgets) {
    const [min, max] = b.range.split('-').map(x => parseInt(x) || 999999);
    if (budget >= min && budget <= max) return b;
  }
  return TV_KNOWLEDGE.budgets[TV_KNOWLEDGE.budgets.length - 1];
}

function recommendProducts(req, budgetTier) {
  const products = [];
  const size = req.size || 65;
  if (budgetTier.tier === '入门') {
    products.push({ name: 'Redmi A Pro 65', price: '2999', panel: 'LCD', size: 65, features: ['4K 60Hz', 'HDR10', '远场语音'] });
    products.push({ name: '海信 E3K 65', price: '3299', panel: 'LCD', size: 65, features: ['4K 60Hz', 'MEMC', 'DTS音效'] });
  } else if (budgetTier.tier === '中端') {
    products.push({ name: 'TCL T7K 65', price: '4999', panel: 'MiniLED', size: 65, features: ['4K 144Hz', '杜比视界', 'HDMI2.1'] });
    products.push({ name: '海信 E5N Pro 65', price: '4599', panel: 'QLED', size: 65, features: ['4K 144Hz', 'MEMC', 'AI画质'] });
    products.push({ name: '小米 S Pro 75', price: '6999', panel: 'MiniLED', size: 75, features: ['4K 144Hz', '杜比视界', 'HDMI2.1'] });
  } else if (budgetTier.tier === '中高端') {
    products.push({ name: 'TCL Q10K 75', price: '9999', panel: 'MiniLED', size: 75, features: ['4K 144Hz', '2000nits', '杜比视界IQ'] });
    products.push({ name: '索尼 X90L 75', price: '12999', panel: 'LCD', size: 75, features: ['4K 120Hz', 'XR认知芯片', 'HDMI2.1'] });
    products.push({ name: 'LG C3 77', price: '14999', panel: 'OLED', size: 77, features: ['4K 120Hz', 'evo面板', 'G-SYNC'] });
  } else {
    products.push({ name: '三星 S95D 77', price: '19999', panel: 'QD-OLED', size: 77, features: ['4K 144Hz', 'AI画质', '杜比视界'] });
    products.push({ name: '索尼 A95L 77', price: '24999', panel: 'QD-OLED', size: 77, features: ['4K 120Hz', 'XR芯片', '杜比视界'] });
  }
  if (size >= 75 && budgetTier.tier !== '旗舰') {
    products.push({ name: `Redmi MAX ${size}`, price: size === 75 ? '5999' : '8999', panel: 'LCD', size, features: ['4K 120Hz', 'HDR10+', '远场语音'] });
  }
  return products.slice(0, 4);
}

function generateDeterministicReply(req) {
  const budgetTier = matchBudget(req.budget);
  const products = recommendProducts(req, budgetTier);
  const size = req.size || 65;
  const sizeInfo = TV_KNOWLEDGE.sizes.find(s => s.size === size) || TV_KNOWLEDGE.sizes[1];

  let reply = `## 需求分析\n\n`;
  reply += `- **观看尺寸**：${size}寸（建议观看距离 ${sizeInfo.distance}，适合${sizeInfo.room}）\n`;
  if (req.budget) reply += `- **预算范围**：${req.budget}元（${budgetTier.tier}级别）\n`;
  else reply += `- **预算范围**：未指定，默认推荐${budgetTier.tier}级别\n`;
  if (req.useCases.length) reply += `- **使用场景**：${req.useCases.join('、')}\n`;
  if (req.panels.length) reply += `- **面板偏好**：${req.panels.join('、')}\n`;

  reply += `\n## 推荐产品\n\n`;
  products.forEach((p, i) => {
    reply += `### ${i + 1}. ${p.name} — ¥${p.price}\n`;
    reply += `- 面板：${p.panel} | 尺寸：${p.size}寸\n`;
    reply += `- 亮点：${p.features.join('、')}\n\n`;
  });

  if (req.useCases.includes('游戏')) {
    reply += `## 游戏专项建议\n\n`;
    reply += `- 优先选择 **120Hz以上刷新率** + **HDMI2.1** 接口\n`;
    reply += `- 输入延迟建议 <20ms，支持 VRR 和 ALLM\n`;
    reply += `- OLED 响应时间最快，但注意烧屏风险；MiniLED 是更均衡的选择\n\n`;
  }
  if (req.useCases.includes('观影')) {
    reply += `## 观影专项建议\n\n`;
    reply += `- 杜比视界 > HDR10+ > HDR10\n`;
    reply += `- 暗室选 OLED，亮室选 MiniLED/QLED\n`;
    reply += `- 建议搭配回音壁提升音效\n\n`;
  }

  reply += `## 选购建议\n\n`;
  reply += `1. **到店实测**：参数仅供参考，建议到实体店实际观看画质\n`;
  reply += `2. **关注接口**：确认 HDMI2.1 接口数量，至少需要 2 个（游戏机+回音壁）\n`;
  reply += `3. **系统体验**：优先选择开机无广告、操作流畅的品牌\n`;
  reply += `4. **安装售后**：大屏建议选择含安装服务的渠道\n`;

  return reply;
}

async function handle(message, sessionId) {
  const req = analyzeRequirement(message);
  const apiKey = process.env.AI_API_KEY;
  if (apiKey) {
    const sysPrompt = `你是一个专业的电视选购顾问，基于以下知识库回答用户问题：\n${JSON.stringify(TV_KNOWLEDGE, null, 2)}\n\n请用中文回答，使用Markdown格式，给出具体产品推荐和选购建议。`;
    const llmReply = await callLLM([
      { role: 'system', content: sysPrompt },
      { role: 'user', content: message }
    ]);
    if (llmReply) return { success: true, reply: llmReply, mode: 'llm', analysis: req };
  }
  return { success: true, reply: generateDeterministicReply(req), mode: 'deterministic', analysis: req };
}

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') { res.status(204).end(); return; }

  if (req.method === 'GET' && req.url === '/health') {
    res.status(200).json({ status: 'ok', llm_available: !!process.env.AI_API_KEY });
    return;
  }

  if (req.method === 'POST' && req.url === '/chat') {
    let body = '';
    req.on('data', c => body += c);
    req.on('end', async () => {
      try {
        const data = JSON.parse(body || '{}');
        const message = (data.message || '').trim();
        if (!message) { res.status(400).json({ error: 'message is required' }); return; }
        const result = await handle(message, data.session_id);
        res.status(200).json(result);
      } catch (e) {
        res.status(500).json({ error: e.message });
      }
    });
    return;
  }

  res.status(404).json({ error: 'not found' });
};
