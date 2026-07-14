#!/bin/bash
# スクレイピング進捗マップ - デスクトップアイコンインストーラー
# 使い方: bash <(curl -s https://industrious-prosperity-production-8d90.up.railway.app/install.sh)

set -e

APP_URL="https://industrious-prosperity-production-8d90.up.railway.app/scrape-map.html"
APP_NAME="スクレイピングマップ"
APP_PATH="$HOME/Desktop/${APP_NAME}.app"

echo "================================================"
echo " スクレイピング進捗マップ インストーラー"
echo "================================================"
echo ""

# macOS チェック
if [[ "$OSTYPE" != "darwin"* ]]; then
  echo "❌ このスクリプトは macOS 専用です"
  exit 1
fi

# 既存アプリを削除
if [ -d "$APP_PATH" ]; then
  rm -rf "$APP_PATH"
  echo "🗑  既存アプリを削除しました"
fi

echo "📦 アプリを作成中..."

# AppleScript 作成 & コンパイル
cat > /tmp/_install_map.applescript << ASCRIPT
set appURL to "$APP_URL"
open location appURL
ASCRIPT

osacompile -o "$APP_PATH" /tmp/_install_map.applescript
rm /tmp/_install_map.applescript

# カスタムアイコンを Python で生成 & 設定
python3 - << 'PYEOF'
import struct, zlib, math, subprocess, os, tempfile, shutil

W = H = 512
bg = (30, 41, 59, 255)
circles = [
    (140,190,75,(74,144,217,255)),
    (240,120,58,(226,125,96,255)),
    (340,210,62,(130,224,170,255)),
    (200,320,55,(245,166,35,255)),
    (370,320,50,(189,16,224,255)),
    (110,360,45,(73,190,180,255)),
]
def get_pixel(x,y):
    pad,r=60,90
    if x<pad+r and y<pad+r and (x-pad-r)**2+(y-pad-r)**2>r**2: return (0,0,0,0)
    if x>W-pad-r and y<pad+r and (x-(W-pad-r))**2+(y-pad-r)**2>r**2: return (0,0,0,0)
    if x<pad+r and y>H-pad-r and (x-pad-r)**2+(y-(H-pad-r))**2>r**2: return (0,0,0,0)
    if x>W-pad-r and y>H-pad-r and (x-(W-pad-r))**2+(y-(H-pad-r))**2>r**2: return (0,0,0,0)
    if x<pad or x>W-pad or y<pad or y>H-pad: return (0,0,0,0)
    for cx,cy,rad,col in circles:
        d=math.sqrt((x-cx)**2+(y-cy)**2)
        if d<=rad: return col
        if d<=rad+4: return (255,255,255,180)
    if (x-60)%80<1 or (y-60)%80<1: return (50,70,100,255)
    return bg

raw=b''
for y in range(H):
    raw+=b'\x00'
    for x in range(W): raw+=bytes(get_pixel(x,y))
compressed=zlib.compress(raw,9)
def chunk(n,d):
    c=n+d; return struct.pack('>I',len(d))+c+struct.pack('>I',zlib.crc32(c)&0xffffffff)
ihdr=struct.pack('>IIBBBBB',W,H,8,6,0,0,0)
png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',ihdr)+chunk(b'IDAT',compressed)+chunk(b'IEND',b'')

# iconset 作成
iconset=tempfile.mkdtemp(suffix='.iconset')
src=os.path.join(tempfile.gettempdir(),'_map_icon.png')
with open(src,'wb') as f: f.write(png)
for sz in [16,32,64,128,256,512]:
    subprocess.run(['sips','-z',str(sz),str(sz),src,'--out',f'{iconset}/icon_{sz}x{sz}.png'],capture_output=True)
for sz in [16,32,128,256,512]:
    subprocess.run(['sips','-z',str(sz*2),str(sz*2),src,'--out',f'{iconset}/icon_{sz}x{sz}@2x.png'],capture_output=True)
icns=os.path.join(tempfile.gettempdir(),'_MapIcon.icns')
subprocess.run(['iconutil','-c','icns',iconset,'-o',icns],capture_output=True)
shutil.rmtree(iconset)

app_resources=os.path.expanduser('~/Desktop/スクレイピングマップ.app/Contents/Resources')
shutil.copy(icns,os.path.join(app_resources,'droplet.icns'))
print("icon_ok")
PYEOF

# Gatekeeper 隔離属性を削除
xattr -r -d com.apple.quarantine "$APP_PATH" 2>/dev/null || true

# Finder リフレッシュ
touch "$APP_PATH"

echo ""
echo "================================================"
echo " ✅ インストール完了！"
echo ""
echo " デスクトップに「${APP_NAME}」が追加されました"
echo " ダブルクリックで進捗マップを開けます"
echo ""
echo " ⚠ 初回起動時: 右クリック → 開く → 開く"
echo "   (セキュリティ確認は初回のみです)"
echo "================================================"
