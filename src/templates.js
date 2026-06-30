/**
 * メッセージテンプレート
 * 季節の挨拶は月に応じて自動生成
 */

const SEASONAL_GREETINGS = {
  1:  '寒い中での作業、ありがとうございます。',
  2:  '寒い中での作業、ありがとうございます。',
  3:  '春めいてきた中、作業ありがとうございます。',
  4:  '春の陽気の中、作業ありがとうございます。',
  5:  '初夏の陽気の中、作業ありがとうございます。',
  6:  '梅雨の時期の作業、ありがとうございます。',
  7:  '暑い中での作業、ありがとうございます。',
  8:  '猛暑の中での作業、ありがとうございます。',
  9:  '残暑の中での作業、ありがとうございます。',
  10: '秋の涼しさの中、作業ありがとうございます。',
  11: '寒くなってきた中、作業ありがとうございます。',
  12: '寒い中での作業、ありがとうございます。'
};

function getSeasonalGreeting() {
  const month = new Date().getMonth() + 1;
  return SEASONAL_GREETINGS[month];
}

async function generateWeeklyMessage() {
  const greeting = getSeasonalGreeting();
  return `いつもお世話になっております。
（${greeting}）

作業入られました皆様、各種工事完了時（3日以内）に写真の格納お願いいたします。
大工さんは毎週土曜日終日までの工事進捗報告を兼ねた写真（3枚程度）の格納お願いいたします。

よろしくお願いいたします。`;
}

async function generateMonthlyMessage() {
  const greeting = getSeasonalGreeting();
  const now = new Date();
  const yearMonth = `${now.getFullYear()}年${now.getMonth() + 1}月`;

  return `いつもお世話になっております。
（${greeting}）

【出荷証明書の格納はお忘れなく】

下記項目に関しましては、出荷完了後7日以内に「14.出荷証明書」へ格納お願いいたします。
確認申請格化に伴いお手数お掛けいたしますが全現場共通になります。
よろしくお願いいたします。
格納が遅れる場合は日程含め事務担当までコメントお願いいたします。

「構造材、サッシ、玄関ドア、換気設備、照明器具、断熱材」
（${yearMonth}現在）`;
}

module.exports = { generateWeeklyMessage, generateMonthlyMessage };
