# QRコード設計（ブランド検索誘導）
生成日: 2026-03-18

## 目的
紙媒体からの流入を「ブランド検索」として計測可能にする。
UTMパラメータ付きURLでQRコードを生成し、GA4で効果測定。

### tokaiair_card
- URL: `https://www.tokaiair.com/?utm_source=card&utm_medium=qr&utm_campaign=brand`
- テキスト: ドローン測量のご相談は
「東海エアサービス」で検索
- 配置: 名刺裏面 右下
- QR生成: https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://www.tokaiair.com/?utm_source=card&utm_medium=qr&utm_campaign=brand

### tokaiair_quote
- URL: `https://www.tokaiair.com/drone-survey-market-report/?utm_source=quote&utm_medium=qr`
- テキスト: 費用目安は市場レポートでご確認いただけます
- 配置: 見積書フッター
- QR生成: https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://www.tokaiair.com/drone-survey-market-report/?utm_source=quote&utm_medium=qr

### tokaiair_pamphlet
- URL: `https://www.tokaiair.com/earthwork-calculator/?utm_source=pamphlet&utm_medium=qr`
- テキスト: 無料 土量計算ツール
- 配置: パンフレット最終ページ
- QR生成: https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://www.tokaiair.com/earthwork-calculator/?utm_source=pamphlet&utm_medium=qr

### tomoshi_card
- URL: `https://tomoshi.jp/?utm_source=card&utm_medium=qr&utm_campaign=brand`
- テキスト: 「TOMOSHI 事業承継」で検索
- 配置: 名刺裏面
- QR生成: https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://tomoshi.jp/?utm_source=card&utm_medium=qr&utm_campaign=brand
