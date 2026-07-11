-- stores テーブルに address カラムを追加するマイグレーション
-- Supabase ダッシュボード → SQL Editor に貼り付けて実行してください

ALTER TABLE stores ADD COLUMN IF NOT EXISTS address TEXT;
