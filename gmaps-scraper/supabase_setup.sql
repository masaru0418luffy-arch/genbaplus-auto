-- ============================================================
-- Google マップ営業リスト抽出システム - Supabase テーブル定義
-- ============================================================
-- Supabase ダッシュボード → SQL Editor に貼り付けて実行してください

-- 営業リスト本体
CREATE TABLE IF NOT EXISTS stores (
  id                        UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  company_name              TEXT,
  industry                  TEXT,
  instagram_url             TEXT,
  website_url               TEXT,
  review_count              INTEGER DEFAULT 0,
  last_photo_posted_date    TEXT,
  website_domain_creation_date TEXT,
  google_maps_url           TEXT UNIQUE NOT NULL,
  scraped_at                TIMESTAMPTZ DEFAULT NOW(),
  created_at                TIMESTAMPTZ DEFAULT NOW()
);

-- 取得済みURL管理（重複スキップ・再開用）
CREATE TABLE IF NOT EXISTS completed_urls (
  url          TEXT PRIMARY KEY,
  completed_at TIMESTAMPTZ DEFAULT NOW()
);

-- 検索クエリごとの進捗状態
CREATE TABLE IF NOT EXISTS search_progress (
  query_key       TEXT PRIMARY KEY,
  keyword         TEXT NOT NULL,
  area            TEXT NOT NULL,
  status          TEXT DEFAULT 'pending',  -- pending / in_progress / completed
  processed_count INTEGER DEFAULT 0,
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 実行ステータス（CAPTCHA中断・正常終了の管理）
CREATE TABLE IF NOT EXISTS run_status (
  id               INTEGER PRIMARY KEY DEFAULT 1,  -- 常に1行だけ
  interrupted      BOOLEAN DEFAULT FALSE,
  interrupt_reason TEXT,
  last_run_at      TIMESTAMPTZ
);
INSERT INTO run_status (id) VALUES (1) ON CONFLICT DO NOTHING;

-- ============================================================
-- インデックス（検索パフォーマンス向上）
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_stores_industry  ON stores (industry);
CREATE INDEX IF NOT EXISTS idx_stores_scraped_at ON stores (scraped_at DESC);

-- ============================================================
-- Row Level Security（RLS）— 社内利用のため anon キーで読み書き可
-- 本番運用では認証ユーザーのみに絞ることを推奨
-- ============================================================
ALTER TABLE stores           ENABLE ROW LEVEL SECURITY;
ALTER TABLE completed_urls   ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_progress  ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_status       ENABLE ROW LEVEL SECURITY;

-- anon ロールに全操作を許可（社内ツール前提）
CREATE POLICY "anon full access" ON stores           FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "anon full access" ON completed_urls   FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "anon full access" ON search_progress  FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "anon full access" ON run_status       FOR ALL TO anon USING (true) WITH CHECK (true);
