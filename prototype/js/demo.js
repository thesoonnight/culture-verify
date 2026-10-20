/* 内置演示数据：没有后端时也能直接打开体验。 */
window.CV = window.CV || {};
(function (CV) {
  'use strict';

  const POINTWISE = [
    {
      id: 'A01',
      prompt: '唐代仕女，齐胸襦裙，长安春日，工笔重彩，竖幅构图',
      axis: '服饰形制',
      lang: '中文',
      region: '中国 · 唐',
      image: 'mock/a1.png',
      attrs: ['齐胸襦裙：高腰、系带', '披帛与花钿', '团花纹样', '“大唐”榜题'],
      items: [
        { dim: 'd1', score: 1, rationale: '高腰系带、披帛与团花均可辨认，形制基本符合唐制。' },
        { dim: 'd2', score: 0, rationale: '领口出现西式蕾丝花边，与齐胸襦裙结构不符。' },
        { dim: 'd3', score: 1, rationale: '“大唐”二字笔画完整，可读。' },
      ],
      meta: { model: 'M-A', seed: 10231, res: '1024 × 1024' },
    },
    {
      id: 'A02',
      prompt: '京都清水寺，樱花，浮世绘风格，竖幅',
      axis: '建筑构件',
      lang: '中文',
      region: '日本 · 京都',
      image: 'mock/a2.png',
      attrs: ['五重塔与斗拱', '寺院舞台', '樱花', '“清水”榜题'],
      items: [
        { dim: 'd1', score: 0, rationale: '塔身屋顶被简化为平直三角形，缺失斗拱与檐口起翘。' },
        { dim: 'd2', score: 1, rationale: '整体为日式寺院构图，未见明显西方化错配。' },
        { dim: 'd3', score: 1, rationale: '“清水”字形正确、可读。' },
      ],
      meta: { model: 'M-B', seed: 7712, res: '1024 × 1024' },
    },
    {
      id: 'A03',
      prompt: '开罗哈利利市场，悬挂灯笼，阿拉伯文招牌，黄昏',
      axis: '文字渲染',
      lang: '中文',
      region: '埃及 · 开罗',
      image: 'mock/a3.png',
      attrs: ['尖拱与拱廊', '悬挂灯笼', '阿拉伯文招牌', '地毯纹样'],
      items: [
        { dim: 'd1', score: 1, rationale: '尖拱、灯笼与地毯纹样符合市场意象。' },
        { dim: 'd2', score: 0, rationale: '拱券接近哥特式尖拱，与伊斯兰建筑语汇不符。' },
        { dim: 'd3', score: 0, rationale: '招牌为伪字形，读不出任何阿拉伯语词。' },
      ],
      meta: { model: 'M-C', seed: 3901, res: '1024 × 1024' },
    },
    {
      id: 'A04',
      prompt: '首尔景福宫，韩服女子，秋日，宫殿前',
      axis: '服饰形制',
      lang: '中文',
      region: '韩国 · 首尔',
      image: 'mock/a4.png',
      attrs: ['韩服：赤古里 + 裙', '宫殿屋顶与柱列', '匾额文字'],
      items: [
        { dim: 'd1', score: 1, rationale: '韩服上衣与高腰长裙结构基本正确。' },
        { dim: 'd2', score: 1, rationale: '屋顶与柱列符合景福宫意象。' },
        { dim: 'd3', score: 0, rationale: '匾额文字笔画缺失，不可读。' },
      ],
      meta: { model: 'M-A', seed: 4410, res: '1024 × 1024' },
    },
    {
      id: 'A05',
      prompt: '墨西哥城亡灵节祭坛，万寿菊，剪纸旗帜，夜晚',
      axis: '节庆',
      lang: '中文',
      region: '墨西哥 · 墨西哥城',
      image: 'mock/a5.png',
      attrs: ['祭坛层级', '万寿菊', 'papel picado 剪纸', '“DÍA DE MUERTOS”字样'],
      items: [
        { dim: 'd1', score: 1, rationale: '祭坛、万寿菊与剪纸旗帜齐备。' },
        { dim: 'd2', score: 1, rationale: '未见明显西方化改写。' },
        { dim: 'd3', score: 1, rationale: '“DÍA DE MUERTOS”拼写与重音正确。' },
      ],
      meta: { model: 'M-D', seed: 8820, res: '1024 × 1024' },
    },
    {
      id: 'A06',
      prompt: '印度排灯节，油灯与 rangoli 地绘，夜间庭院',
      axis: '节庆',
      lang: '中文',
      region: '印度',
      image: 'mock/a6.png',
      attrs: ['油灯（diya）', 'rangoli 几何', '万寿菊花环', '“排灯”榜题'],
      items: [
        { dim: 'd1', score: 1, rationale: '油灯、rangoli 与花环元素齐备。' },
        { dim: 'd2', score: 0, rationale: 'rangoli 被简化为同心圆，缺失传统花瓣几何。' },
        { dim: 'd3', score: 1, rationale: '“排灯”二字可读。' },
      ],
      meta: { model: 'M-B', seed: 5203, res: '1024 × 1024' },
    },
  ].map((task) => ({ ...task, mode: 'pointwise', type: 'pointwise' }));

  const PAIRWISE = [
    {
      id: 'B01',
      prompt: '敦煌莫高窟飞天，矿物颜料，斑驳墙面，唐代壁画风格',
      axis: '壁画 / 宗教',
      lang: '中文',
      images: { A: 'mock/b1a.png', B: 'mock/b1b.png' },
      scores: { A: { q1: 7, q2: 9 }, B: { q1: 3, q2: 6 } },
      criteria: [{ id: 'q1' }, { id: 'q2' }],
      note: 'AI 理由：A 的颜料颗粒与墙面肌理更接近壁画；B 有轻微涂抹感。',
      meta: { model_A: 'M-A', model_B: 'M-B', res: '1024 × 1024' },
    },
    {
      id: 'B02',
      prompt: '日本茶室，榻榻米，障子门，午后侧光',
      axis: '室内 / 建筑',
      lang: '中文',
      images: { A: 'mock/b2a.png', B: 'mock/b2b.png' },
      scores: { A: { q1: 5, q2: 4 }, B: { q1: 8, q2: 7 } },
      criteria: [{ id: 'q1' }, { id: 'q2' }],
      note: 'AI 理由：B 的木纹与纸面质感更清晰；A 整体偏糊。',
      meta: { model_A: 'M-C', model_B: 'M-A', res: '1024 × 1024' },
    },
    {
      id: 'B03',
      prompt: '中式婚礼，红盖头，双喜，灯笼，室内暖光',
      axis: '节庆',
      lang: '中文',
      images: { A: 'mock/b3a.png', B: 'mock/b3b.png' },
      scores: { A: { q1: 6, q2: 8 }, B: { q1: 6, q2: 5 } },
      criteria: [{ id: 'q1' }, { id: 'q2' }],
      note: 'AI 理由：两者质感接近，A 的细节层次略好。',
      meta: { model_A: 'M-D', model_B: 'M-B', res: '1024 × 1024' },
    },
  ].map((task) => ({ ...task, mode: 'pairwise', type: 'pairwise' }));

  CV.demo = {
    dataset: {
      name: 'demo',
      title: '内置演示数据集',
      task_count: POINTWISE.length + PAIRWISE.length,
      pointwise: POINTWISE.length,
      pairwise: PAIRWISE.length,
    },
    config: {
      title: '内置演示数据集',
      dimensions: CV.config.DEFAULT_DIMENSIONS,
      criteria: CV.config.DEFAULT_CRITERIA,
    },
    tasks: [...POINTWISE, ...PAIRWISE],
  };
})(window.CV);
