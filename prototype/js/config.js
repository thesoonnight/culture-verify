/* 全局配置：维度默认值、存储键、版本。 */
window.CV = window.CV || {};
(function (CV) {
  'use strict';

  const DEFAULT_DIMENSIONS = [
    {
      id: 'd1',
      label: '文化元素准确性',
      question: '图中服饰、器物、纹样等文化元素的形制与符号是否符合该文化？',
    },
    {
      id: 'd2',
      label: '无西方化错配',
      question: '是否存在西方中心化的错配、替换或刻板化简化？',
    },
    {
      id: 'd3',
      label: '图内文字可读性',
      question: '图内文字是否字形正确、笔画完整、可读？',
    },
  ];

  const DEFAULT_CRITERIA = [
    { id: 'q1', label: '画面质感', question: '材质、光影、颗粒与整体画面完成度' },
    { id: 'q2', label: '细节真实度', question: '局部结构、边缘与纹理的精细程度' },
  ];

  function defaultConfig() {
    const labels = {};
    const questions = {};
    [...DEFAULT_DIMENSIONS, ...DEFAULT_CRITERIA].forEach((d) => {
      labels[d.id] = d.label;
      questions[d.id] = d.question;
    });
    return {
      labels,
      questions,
      showRationale: true,
      autoNext: false,
      requireCorrection: false,
    };
  }

  CV.config = {
    VERSION: '0.2.0',
    LS_KEY: 'culture-verify-v02',
    LS_ANNOTATOR: 'culture-verify-annotator',
    DEFAULT_ANNOTATOR: 'local',
    DEFAULT_DIMENSIONS,
    DEFAULT_CRITERIA,
    defaultConfig,
  };
})(window.CV);
